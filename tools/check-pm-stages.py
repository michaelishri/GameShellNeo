#!/usr/bin/env python3
"""Run opt-in PM debug stages with device-owned evidence across SSH disconnects."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shlex
import statistics
import time
import uuid

import paramiko
from private_config import load_env
from host_timing import phase, timed_capture, collection_state
from remote import LOCAL, ROOT, device, evidence_directory, run, upload, python_command


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def service_command(directory, stage, run_id, keypad_trace=False, keypad_persist=None, keypad_input=False, keypad_audio=False,
                    keypad_quirk=None, wifi_trace=False, power_key=False, power_key_input=False):
    if (not re.fullmatch(r'/tmp/gameshellneo-pm\.[A-Za-z0-9]+', directory) or
            stage not in ('freezer', 'devices', 'platform') or not re.fullmatch(r'[0-9a-f]{32}', run_id) or
            type(keypad_trace) is not bool or (keypad_trace and stage not in ('devices', 'platform')) or
            (keypad_persist is not None and (keypad_persist not in ('0', '1') or
                                            stage != 'devices' or not keypad_trace)) or
            type(keypad_input) is not bool or (keypad_input and
                (stage != 'devices' or not keypad_trace or keypad_persist is not None)) or
            type(keypad_audio) is not bool or (keypad_audio and not keypad_input) or
            (keypad_quirk is not None and (keypad_quirk not in ('baseline', 'old-scheme', 'fast-recovery') or
                stage != 'devices' or not keypad_trace or keypad_persist is not None)) or
            type(wifi_trace) is not bool or (wifi_trace and (stage not in ('devices', 'platform') or keypad_input or
                keypad_persist is not None or keypad_quirk is not None))):
        raise ValueError('Invalid PM stage, path or run ID')
    if stage == 'platform' and (power_key is not True or keypad_trace is not True):
        raise ValueError('Platform debug requires key ownership and trace')
    if type(power_key) is not bool:
        raise ValueError('Invalid power-key ownership option')
    if (type(power_key_input) is not bool or (power_key_input and
            (stage != 'devices' or not power_key or not keypad_trace or keypad_input or keypad_audio or
             keypad_persist is not None or keypad_quirk is not None or wifi_trace))):
        raise ValueError('Invalid isolated physical power-key test')
    script = directory + '/test-pm-stages.py'
    # No SSH-owned pipe: USB may disconnect during the devices test.
    return ['sudo', '-n', 'systemd-run', '--quiet', '--collect', '--unit=gameshellneo-pm-test',
            '--property=RuntimeMaxSec=' + ('420' if keypad_input or power_key_input else '120'), '--property=TimeoutStopSec=15',
            '--property=UMask=0077', '--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore' +
            (' --power-key-input --run-id '+run_id if power_key_input else ''),
            '/usr/bin/systemd-inhibit', '--what=handle-power-key:sleep:idle', '--mode=block',
            '--who=GameShellNeo PM diagnostic', '--why=Bounded PM debug test',
            '/usr/bin/python3', '-B', script, '--lock', directory + '/sources.lock.json',
            '--stage', stage, '--run-id', run_id] + (['--keypad-trace'] if keypad_trace else []) + (
                ['--keypad-persist', keypad_persist] if keypad_persist is not None else []) + (
                ['--keypad-input'] if keypad_input else []) + (['--keypad-audio'] if keypad_audio else []) + (
                ['--keypad-quirk', keypad_quirk] if keypad_quirk is not None else []) + (
                ['--wifi-trace'] if wifi_trace else []) + (['--power-key'] if power_key else []) + (
                ['--power-key-input'] if power_key_input else [])


def inline(client, *args):
    # Inline inspection/recovery also needs the same saved keypad helper.
    program = 'import sys, types\n'
    for name in ('battery_sample', 'cpi_idle', 'keypad_pm', 'keypad_input', 'speaker_audio', 'wifi_trace', 'power_key', 'rtc_alarm', 'pm_platform'):
        program += ('keypad_helper = types.ModuleType(' + repr(name) + ')\n'
                    'exec(' + repr((ROOT / 'tools' / (name + '.py')).read_text()) + ', keypad_helper.__dict__)\n'
                    'sys.modules[' + repr(name) + '] = keypad_helper\n')
    program += (ROOT / 'tools/test-pm-stages.py').read_text()
    return run(client, **python_command(program, *args), display=False, timeout=40)


def wifi_proof(config, snapshot):
    addresses = re.findall(r'^ip_address=(.+)$', snapshot['wifi'], re.M)
    if len(addresses) != 1 or addresses[0] == config.get('GAMESHELL_USB_IP', '192.168.10.1'):
        raise ValueError('A distinct connected Wi-Fi address is required')
    module('pm_wifi_proof', 'check-wifi-firmware.py').verify_wifi(config, snapshot['boot_id'], addresses[0])


def collect(config, run_id):
    with device(config, 'usb') as client:
        return json.loads(inline(client, '--collect', run_id))


@timed_capture('pm.cycle')
def cycle(config, capture, lock, stage, keypad_trace=False, keypad_persist=None, keypad_input=False, keypad_audio=False,
          keypad_quirk=None, wifi_trace=False, power_key=False, power_key_input=False):
    with device(config, 'usb') as client:
        before = json.loads(inline(client, '--inspect'))
        (capture / 'before.json').write_text(json.dumps(before, indent=2) + '\n')
        module('pm_device', 'test-pm-stages.py').validate(before, lock)
        wifi_proof(config, before)
        if run(client, 'systemctl show gameshellneo-pm-test -p LoadState --value',
               display=False).decode().strip() != 'not-found':
            raise ValueError('Previous PM unit exists; collect/recover it before another test')
        directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-pm.XXXXXXXX',
                        display=False).decode().strip()
        run_id = uuid.uuid4().hex
        command = service_command(directory, stage, run_id, keypad_trace, keypad_persist, keypad_input, keypad_audio,
                                  keypad_quirk, wifi_trace, power_key, power_key_input)
        with client.open_sftp() as sftp:
            upload(sftp, ROOT / 'tools/test-pm-stages.py', directory + '/test-pm-stages.py')
            upload(sftp, ROOT / 'tools/battery_sample.py', directory + '/battery_sample.py')
            upload(sftp, ROOT / 'tools/cpi_idle.py', directory + '/cpi_idle.py')
            upload(sftp, ROOT / 'tools/keypad_pm.py', directory + '/keypad_pm.py')
            upload(sftp, ROOT / 'tools/keypad_input.py', directory + '/keypad_input.py')
            upload(sftp, ROOT / 'tools/speaker_audio.py', directory + '/speaker_audio.py')
            upload(sftp, ROOT / 'tools/wifi_trace.py', directory + '/wifi_trace.py')
            upload(sftp, ROOT / 'tools/power_key.py', directory + '/power_key.py')
            upload(sftp, ROOT / 'tools/rtc_alarm.py', directory + '/rtc_alarm.py')
            upload(sftp, ROOT / 'tools/pm_platform.py', directory + '/pm_platform.py')
            if power_key_input:
                for name in ('power_key_policy', 'power_key_input', 'power_key_pm'):
                    upload(sftp, ROOT/'tools'/(name+'.py'), directory+'/'+name+'.py')
                names = ('test-pm-stages', 'battery_sample', 'cpi_idle', 'keypad_pm', 'keypad_input', 'speaker_audio',
                         'power_key', 'power_key_policy', 'power_key_input', 'power_key_pm')
                (capture/'source.json').write_text(json.dumps({name: hashlib.sha256(
                    (ROOT/'tools'/(name+'.py')).read_bytes()).hexdigest() for name in names}, indent=2)+'\n')
            upload(sftp, ROOT / 'build/sources.lock.json', directory + '/sources.lock.json')
        (capture / 'run.json').write_text(json.dumps(dict(run_id=run_id, stage=stage, helper=directory)) + '\n')
        print('PM run:', run_id, 'helper:', directory, flush=True)
        # Submission may itself lose SSH after systemd accepted it. Never retry
        # submission: recover this exact ID and fail incomplete evidence.
        try:
            with phase('pm.submit'):
                run(client, shlex.join(command), display=False, timeout=20)
        except (OSError, RuntimeError, paramiko.SSHException) as error:
            (capture / 'submission-error.txt').write_text(type(error).__name__ + '\n')
    deadline = time.monotonic() + (480 if keypad_input or power_key_input else 180)
    while time.monotonic() < deadline:
        with phase('collection.wait'):
            time.sleep(5)
        try:
            with phase('collection.attempt'):
                result = collect(config, run_id)
                collection_state(result)
        except (OSError, RuntimeError, paramiko.SSHException) as error:
            with (capture / 'collection-errors.txt').open('a') as output:
                output.write(type(error).__name__ + ': ' + str(error) + '\n')
            continue
        (capture / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        if result.get('event') not in ('complete', 'failed'):
            continue
        if not result.get('passed') or result.get('run_id') != run_id:
            raise ValueError('PM stage failed; private evidence retained')
        if result['before']['boot_id'] != before['boot_id']:
            raise ValueError('Boot changed between preflight and test')
        if keypad_persist is not None:
            policy = result.get('persistence', {})
            if (policy.get('requested') != keypad_persist or policy.get('applied') != keypad_persist or
                    policy.get('original') != '1' or policy.get('restored') is not True):
                raise ValueError('Keypad persistence application/restoration was not verified')
        if keypad_quirk is not None:
            validate_quirk_result(result, keypad_quirk)
        if wifi_trace:
            trace = result.get('wifi_trace', {})
            if trace.get('restored') is not True or trace.get('trace_lost') is not False:
                raise ValueError('Wi-Fi trace completeness/restoration failed')
        if power_key and result.get('power_key', {}).get('handed_back') is not True:
            raise ValueError('Power-key ownership was not handed back cleanly')
        if power_key_input:
            from power_key_pm import validate_result
            validate_result(result)
        with phase('proof.wifi'):
            wifi_proof(config, result['after'])
        # A fresh USB SSH collection above and independent Wi-Fi proof below
        # are required; kernel return alone is insufficient.
        with phase('proof.final'):
            with device(config, 'usb') as client:
                boot = run(client, 'cat /proc/sys/kernel/random/boot_id', display=False).decode().strip()
            if boot != before['boot_id']:
                raise ValueError('USB SSH reached a different boot after the PM test')
        result.update(usb_ssh_verified=True, wifi_ssh_verified=True)
        (capture / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(stage, 'debug stage passed; both SSH routes verified.', flush=True)
        return result
    raise TimeoutError('No complete PM result. Do not retry; inspect device and use device:pm-collect RUN=' + run_id)


def compare_keypad(config, capture, lock):
    if lock.get('experiments', {}).get('keypad_supply_retention'):
        raise ValueError('Persistence comparison requires the power-off baseline image')
    results = []
    baseline = None
    for name, value in (('before', '1'), ('off', '0'), ('after', '1')):
        directory = capture / name
        directory.mkdir(mode=0o700)
        result = cycle(config, directory, lock, 'devices', True, value)
        context = {key: result['before'][key] for key in
                   ('boot_id', 'kernel', 'wifi_config_sha256', 'cpu_policy', 'charger', 'backlight')}
        context['keypad_identity'] = result['persistence']['identity']
        if baseline is not None and context != baseline:
            raise ValueError('Boot, configuration or keypad changed during comparison')
        baseline = context
        results.append(dict(phase=name, persist=value, run_id=result['run_id'],
                            boot_id=result['before']['boot_id'], stage_seconds=result['stage_seconds'],
                            ready_after_stage_seconds=result['keypad_ready_after_stage']['seconds'],
                            old_handle_disconnected=result['keypad']['old_handle_after']['disconnected'],
                            restored=result['persistence']['restored']))
        (capture / 'comparison.json').write_text(json.dumps(dict(passed=False, phases=results), indent=2) + '\n')
        if name != 'after':
            time.sleep(20)
    (capture / 'comparison.json').write_text(json.dumps(dict(passed=True, phases=results,
        limits='Debug stages and healthy input-handle availability, not real sleep or first key delivery.'),
        indent=2) + '\n')
    print('Keypad persistence on/off/on comparison passed; original policy restored.', flush=True)


def retention_result(result):
    keypad = result['keypad']
    if (not result['before']['keypad_retains_supply'] or
            not result['after']['keypad_retains_supply'] or
            keypad.get('trace_overrun') is not False or
            keypad.get('trace_restored') is not True or
            re.search(r'regulator_disable(?:_complete)?:.*keypad-vbus', keypad['trace'])):
        raise ValueError('Supply retention or complete restored tracing was not demonstrated')
    before, after = keypad['before'], keypad['after']
    if any(before['usb']['power'][key] != after['usb']['power'][key]
           for key in ('persist', 'control', 'wakeup')):
        raise ValueError('Keypad persistence/runtime/wake policy changed')
    old = keypad['old_handle_after']
    return dict(run_id=result['run_id'], stage_seconds=result['stage_seconds'],
                ready_after_stage_seconds=result['keypad_ready_after_stage']['seconds'],
                original_handle_healthy=old['ioctl_errno'] is None and not old['disconnected'],
                usb_device_number_unchanged=before['usb']['attributes']['devnum'] == after['usb']['attributes']['devnum'],
                input_sysfs_unchanged=before['inputs'][0]['sysfs'] == after['inputs'][0]['sysfs'],
                keypad_disconnects=len(re.findall(r'usb \d+-1: USB disconnect', result['journal_delta'])),
                supply_disable_events=0,
                limits='Software supply evidence and input-handle health; physical input, voltage and energy unmeasured.')


def validate_physical_result(result, retention):
    from keypad_input import BUTTONS
    physical = result.get('physical_input', {})
    if (physical.get('passed') is not True or physical.get('grab_released') is not True or
            physical.get('console_restored') is not True or physical.get('reader_error') or
            not all(retention[k] for k in ('original_handle_healthy', 'usb_device_number_unchanged',
                                           'input_sysfs_unchanged')) or retention['keypad_disconnects'] or
            result['keypad']['old_handle_after'].get('hung_up') or
            result['keypad']['old_handle_after'].get('poll_error')):
        raise ValueError('Physical input, original-handle continuity or cleanup failed')
    taps = [(code, value) for _, code in BUTTONS for value in (1, 0)]
    edges = [(e['code'], e['value']) for e in physical['events'] if e['type'] == 1 and e['value'] != 2]
    mode = physical.get('hold_resume_mode')
    hold_edges = [(36, 1), (36, 0)] * (2 if mode == 'reasserted' else 1)
    if mode not in ('continuous', 'cleared', 'reasserted') or edges != taps + hold_edges + taps:
        raise ValueError('Physical input did not deliver the complete ordered sequence')
    if (physical.get('continuous_hold') is not (mode == 'continuous') or
            physical.get('physical_release_event_observed') is not (mode != 'cleared')):
        raise ValueError('Physical held-key classification is inconsistent')
    checks = {c['name']: c['handle'] for c in physical['checkpoints']}
    for name, expected in (('immediately-before-entry', [36]), ('after-stage', [] if mode == 'cleared' else [36]),
                           ('released-after-stage', []), ('final', [])):
        state = checks.get(name, {})
        if (state.get('held_key_codes') != expected or state.get('ioctl_errno') is not None or
                state.get('hung_up') is not False or state.get('poll_error') is not False):
            raise ValueError('Missing healthy physical-input checkpoint: ' + name)
    if mode != 'continuous':
        # Accept a cleared/reasserted observation only when its release falls
        # inside the known input device's actual suspend callback. An early
        # physical release before PM is not equivalent evidence.
        input_name = result['keypad']['before']['inputs'][0]['sysfs'].split('/')[-2]
        if not re.fullmatch(r'input[0-9]+', input_name):
            raise ValueError('Unexpected input sysfs identity for release correlation')
        start, intervals = None, []
        for line in result['keypad']['trace'].splitlines():
            match = re.search(r'\s([0-9]+\.[0-9]+): device_pm_callback_(start|end): input ' +
                              input_name + r', (.*)', line)
            if not match:
                continue
            if match[2] == 'start' and 'type [suspend]' in match[3]:
                start = float(match[1])
            elif match[2] == 'end' and start is not None:
                if match[3] == 'err=0':
                    intervals.append((start, float(match[1])))
                start = None
        key_events = [e for e in physical['events'] if e['type'] == 1 and e['value'] != 2]
        release = key_events[len(taps) + 1]['seconds']
        matched = [(start, end) for start, end in intervals if start <= release <= end]
        if len(matched) != 1:
            raise ValueError('Held-key release is not correlated with input suspend')
        physical['suspend_release_correlation'] = dict(event_seconds=release,
            callback_start_seconds=matched[0][0], callback_end_seconds=matched[0][1])


def validate_audio_result(record):
    expected = ['before-' + button for button in ('A', 'B', 'X', 'Y')] + ['hold-A', 'screen-blank'] + [
        'after-' + button for button in ('A', 'B', 'X', 'Y')]
    off = {'Speaker Amp DRV': 'Off', 'Headphone Amp': 'Off'}
    if (record.get('restored') is not True or record.get('idle_before_pm') != off or
            [c['label'] for c in record.get('cues', [])] != expected or
            any(c['amplifiers_after'] != off for c in record['cues'])):
        raise ValueError('Speaker confirmation sequence or idle/restoration checks failed')


def validate_quirk_result(result, mode):
    from keypad_pm import QUIRK_MODES, keypad_identity
    policy = result.get('port_quirks', {})
    original = policy.get('original')
    if (type(original) is not int or original & 3 or policy.get('mode') != mode or
            policy.get('restored') is not True or policy.get('requested') != original | QUIRK_MODES[mode] or
            policy.get('before') != policy.get('after_restore') or
            policy.get('applied') != policy.get('after_stage') or
            policy.get('applied', {}).get('value') != policy['requested'] or
            policy.get('before', {}).get('value') != original or
            policy['applied']['path'] != policy['before']['path'] or
            policy['applied']['globals'] != policy['before']['globals'] or
            policy['before']['globals'] != {'old_scheme_first': 'N', 'use_both_schemes': 'Y'}):
        raise ValueError('Keypad port quirks application/restoration was not verified')
    keypad = result['keypad']
    if any(keypad_identity(keypad[phase]) != policy['identity'] for phase in ('before', 'after')):
        raise ValueError('Keypad identity changed during port trial')
    summary = retention_result(result)
    if (not all(summary[key] for key in ('original_handle_healthy', 'usb_device_number_unchanged',
                                       'input_sysfs_unchanged')) or summary['keypad_disconnects'] or
            keypad['old_handle_after'].get('hung_up') or keypad['old_handle_after'].get('poll_error')):
        raise ValueError('Keypad port trial lost input continuity')
    for phase in ('before', 'after'):
        power = keypad[phase]['usb']['power']
        if power['persist'] != '1' or power['control'] != 'on' or power['wakeup'] is not None:
            raise ValueError('Keypad port trial changed input power policy')
    name = policy['identity']['path'].rsplit('/', 1)[1]
    pattern = r'\s([0-9]+\.[0-9]+): device_pm_callback_(start|end): usb ' + re.escape(name) + r', (.*)'
    start, intervals = None, []
    for line in keypad['trace'].splitlines():
        match = re.search(pattern, line)
        if not match:
            continue
        if match[2] == 'start' and 'type [resume]' in match[3]:
            if start is not None:
                raise ValueError('Overlapping keypad resume callbacks')
            start = float(match[1])
        elif match[2] == 'end' and start is not None:
            if match[3] != 'err=0' or float(match[1]) < start:
                raise ValueError('Failed or invalid keypad resume callback')
            intervals.append(float(match[1]) - start)
            start = None
    if start is not None or len(intervals) != 1:
        raise ValueError('Expected exactly one complete keypad USB resume callback')
    return summary | dict(mode=mode, usb_resume_seconds=intervals[0],
                          port_quirks_restored=True)


def compare_quirks(config, capture, lock, candidate, cycles):
    if (candidate not in ('old-scheme', 'fast-recovery') or not 1 <= cycles <= 4 or
            lock.get('experiments', {}).get('keypad_supply_retention') is not True):
        raise ValueError('Select one port candidate and CYCLES=1..4 on the retention image')
    report = dict(passed=False, candidate=candidate, cycles_per_phase=cycles, phases=[],
                  limits='Instrumented driver debug recovery, not real wake latency or energy.')
    context = None
    try:
        for phase, mode in (('before', 'baseline'), ('candidate', candidate), ('after', 'baseline')):
            for index in range(cycles):
                directory = capture / f'{phase}-{index + 1}'
                directory.mkdir(mode=0o700)
                print(f'Port comparison: {phase} {index + 1}/{cycles}, {mode}', flush=True)
                result = cycle(config, directory, lock, 'devices', True, keypad_quirk=mode)
                summary = validate_quirk_result(result, mode)
                current = {key: result['before'][key] for key in
                           ('boot_id', 'kernel', 'wifi_config_sha256', 'cpu_policy', 'charger', 'backlight')}
                current.update(identity=result['port_quirks']['identity'], port=result['port_quirks']['before'])
                if context is not None and context != current:
                    raise ValueError('Boot, configuration or keypad changed during port comparison')
                context = current
                report['phases'].append(summary | dict(phase=phase))
                (directory / 'quirks.json').write_text(json.dumps(summary, indent=2) + '\n')
                print('Keypad USB resume:', round(summary['usb_resume_seconds'], 6), 's; policy restored.', flush=True)
                (capture / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
                if phase != 'after' or index + 1 < cycles:
                    time.sleep(20)
        report['mean_usb_resume_seconds'] = {phase: statistics.mean(
            r['usb_resume_seconds'] for r in report['phases'] if r['phase'] == phase)
            for phase in ('before', 'candidate', 'after')}
        report['passed'] = True
    finally:
        (capture / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Port comparison passed:', json.dumps(report['mean_usb_resume_seconds']), flush=True)


def wifi_smoke(config, capture, lock):
    with device(config, 'usb') as client:
        before = json.loads(inline(client, '--inspect'))
        module('pm_wifi_smoke', 'test-pm-stages.py').validate(before, lock)
        wifi_proof(config, before)
        active = run(client, 'systemctl list-units --all --plain --no-legend --state=active,activating,deactivating '
                     'gameshellneo-pm-test.service gameshellneo-firmware-trial.service '
                     'gameshellneo-scan-test.service gameshellneo-wifi-trace-smoke.service', display=False)
        if active.strip():
            raise ValueError('Stop concurrent radio/PM diagnostics before the awake capture')
        directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-wifi-trace.XXXXXXXX',
                        display=False).decode().strip()
        if not re.fullmatch(r'/tmp/gameshellneo-wifi-trace\.[A-Za-z0-9]+', directory):
            raise ValueError('Unexpected Wi-Fi trace helper directory')
        script = directory + '/wifi_trace.py'
        with client.open_sftp() as sftp:
            upload(sftp, ROOT / 'tools/wifi_trace.py', script)
        command = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                   '--unit=gameshellneo-wifi-trace-smoke', '--property=RuntimeMaxSec=90',
                   '--property=TimeoutStopSec=15', '--property=UMask=0077',
                   '--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore',
                   '/usr/bin/python3', '-B', script, '--smoke']
        # Preserve failed device output and its helper for independent recovery.
        with (capture / 'wifi-smoke.json').open('wb') as output:
            data = run(client, shlex.join(command), output=output, display=False, timeout=120)
        result = json.loads(data)
        after = json.loads(inline(client, '--inspect'))
        (capture / 'before.json').write_text(json.dumps(before, indent=2) + '\n')
        (capture / 'after.json').write_text(json.dumps(after, indent=2) + '\n')
        module('pm_wifi_smoke_after', 'test-pm-stages.py').validate(after, lock)
        for name in ('boot_id', 'pm', 'stats', 'wifi_config_sha256', 'firmware_sha256', 'nvram_sha256'):
            if before[name] != after[name]:
                raise ValueError('Awake Wi-Fi test changed ' + name)
        wifi_proof(config, after)
        if result.get('passed') is not True or result.get('restored') is not True:
            raise ValueError('Incomplete awake Wi-Fi metadata capture')
        with client.open_sftp() as sftp:
            sftp.remove(script)
            sftp.rmdir(directory)
        print('Awake capture passed; EAPOL tx/rx:', result['eapol_tx'], result['eapol_rx'],
              '; logging/tracing restored and both SSH routes verified.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--test', action='store_true')
    mode.add_argument('--collect', action='store_true')
    mode.add_argument('--restore', action='store_true')
    mode.add_argument('--keypad-compare', action='store_true')
    mode.add_argument('--keypad-retention', action='store_true')
    mode.add_argument('--keypad-input', action='store_true')
    mode.add_argument('--keypad-quirks', action='store_true')
    mode.add_argument('--wifi-smoke', action='store_true')
    mode.add_argument('--platform', action='store_true')
    parser.add_argument('--power-key', action='store_true')
    parser.add_argument('--power-key-input', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    config = load_env()
    capture = evidence_directory()
    print('Private PM evidence:', capture, flush=True)
    if args.collect:
        run_id = os.environ.get('NEO_PM_RUN', '')
        if not re.fullmatch(r'[0-9a-f]{32}', run_id):
            raise ValueError('Supply the 32-character RUN ID')
        result = collect(config, run_id)
        (capture / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print('Saved device result:', result.get('event'), '(collection alone does not requalify SSH recovery)')
        return
    if args.restore:
        with device(config, 'usb') as client:
            if run(client, 'systemctl show gameshellneo-pm-test -p LoadState --value',
                   display=False).decode().strip() != 'not-found':
                run(client, 'sudo -n systemctl stop gameshellneo-pm-test', display=False, timeout=30)
            inline(client, '--restore')
        print('PM unit stopped and owned debug controls restored.')
        return
    if args.inspect:
        with device(config, 'usb') as client:
            data = inline(client, '--inspect')
        (capture / 'inspection.json').write_bytes(data)
        value = json.loads(data)
        print(json.dumps({key: value[key] for key in ('kernel', 'boot_id', 'pm', 'pm_test_delay', 'rsb')}, indent=2))
        return
    stage = os.environ.get('NEO_PM_STAGE', '')
    cycles = int(os.environ.get('NEO_PM_CYCLES', '1'))
    trace_option = os.environ.get('NEO_KEYPAD_TRACE', '0')
    if args.platform:
        stage, trace_option, cycles = 'platform', '1', 1
        args.power_key = True
    if args.power_key_input:
        if not args.test or cycles != 1:
            raise ValueError('Physical power-key input requires one explicitly attended test')
        stage, trace_option, args.power_key = 'devices', '1', True
    if args.keypad_retention or args.keypad_input or args.keypad_quirks:
        stage, trace_option = 'devices', '1'
    if stage == 'platform' and not args.platform:
        raise ValueError('Use device:pm-platform for one guarded late/noirq cycle')
    if trace_option not in ('0', '1') or (trace_option == '1' and stage not in ('devices', 'platform')):
        raise ValueError('KEYPAD_TRACE=0/1; tracing requires STAGE=devices')
    if not (args.keypad_compare or args.wifi_smoke) and (stage not in ('freezer', 'devices', 'platform') or not 1 <= cycles <= 4):
        raise ValueError('Explicit STAGE=freezer/devices and CYCLES=1..4 required')
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    if (args.keypad_retention or args.keypad_input or args.keypad_quirks) and lock.get('experiments', {}).get('keypad_supply_retention') is not True:
        raise ValueError('Keypad retention requires its separately identified image')
    if args.keypad_input and cycles != 1:
        raise ValueError('Physical keypad task runs one owner-assisted cycle at a time')
    audio_option = os.environ.get('NEO_KEYPAD_AUDIO', '0')
    if audio_option not in ('0', '1') or (audio_option == '1' and
            (not args.keypad_input or lock.get('features', {}).get('speaker_audio') is not True)):
        raise ValueError('AUDIO=1 requires physical input on the speaker-enabled image')
    quirk = os.environ.get('NEO_KEYPAD_QUIRK', '')
    if quirk and (quirk not in ('baseline', 'old-scheme', 'fast-recovery') or
                  not (args.keypad_input or args.keypad_quirks)):
        raise ValueError('QUIRK requires the port comparison or physical keypad task')
    wifi_option = '1' if args.platform else os.environ.get('NEO_WIFI_TRACE', '0')
    if wifi_option not in ('0', '1') or (wifi_option == '1' and
            (not (args.test or args.platform) or stage not in ('devices', 'platform') or quirk)):
        raise ValueError('WIFI_TRACE=1 requires the ordinary devices test task')
    (capture / 'sources.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    with (LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.wifi_smoke:
            wifi_smoke(config, capture, lock)
            return
        if args.keypad_compare:
            compare_keypad(config, capture, lock)
            return
        if args.keypad_quirks:
            compare_quirks(config, capture, lock, quirk, cycles)
            return
        for index in range(cycles):
            directory = capture / ('cycle-' + str(index + 1))
            directory.mkdir(mode=0o700)
            result = cycle(config, directory, lock, stage, trace_option == '1', keypad_input=args.keypad_input,
                           keypad_audio=audio_option == '1', keypad_quirk=quirk or None, wifi_trace=wifi_option == '1',
                           power_key=args.power_key, power_key_input=args.power_key_input)
            if args.keypad_retention or args.keypad_input:
                summary = retention_result(result)
                (directory / 'retention.json').write_text(json.dumps(summary, indent=2) + '\n')
                print('Retention observation:', json.dumps(summary), flush=True)
            if args.keypad_input:
                validate_physical_result(result, summary)
                if audio_option == '1':
                    validate_audio_result(result['speaker_audio'])
                (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
                (directory / 'physical-input.json').write_text(json.dumps(result['physical_input'], indent=2) + '\n')
                print('Physical taps passed on the original input handle; held-key resume mode:',
                      result['physical_input']['hold_resume_mode'], flush=True)
            if index + 1 < cycles:
                time.sleep(20)


if __name__ == '__main__':
    main()
