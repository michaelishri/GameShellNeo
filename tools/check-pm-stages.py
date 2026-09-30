#!/usr/bin/env python3
"""Run opt-in PM debug stages with device-owned evidence across SSH disconnects."""
import argparse
import fcntl
import importlib.util
import json
import os
import re
import shlex
import time
import uuid

import paramiko
from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run, upload


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def service_command(directory, stage, run_id, keypad_trace=False, keypad_persist=None):
    if (not re.fullmatch(r'/tmp/gameshellneo-pm\.[A-Za-z0-9]+', directory) or
            stage not in ('freezer', 'devices') or not re.fullmatch(r'[0-9a-f]{32}', run_id) or
            type(keypad_trace) is not bool or (keypad_trace and stage != 'devices') or
            (keypad_persist is not None and (keypad_persist not in ('0', '1') or
                                            stage != 'devices' or not keypad_trace))):
        raise ValueError('Invalid PM stage, path or run ID')
    script = directory + '/test-pm-stages.py'
    # No SSH-owned pipe: USB may disconnect during the devices test.
    return ['sudo', '-n', 'systemd-run', '--quiet', '--collect', '--unit=gameshellneo-pm-test',
            '--property=RuntimeMaxSec=120', '--property=TimeoutStopSec=15',
            '--property=UMask=0077', '--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore',
            '/usr/bin/systemd-inhibit', '--what=handle-power-key:sleep:idle', '--mode=block',
            '--who=GameShellNeo PM diagnostic', '--why=Bounded freezer/devices debug test',
            '/usr/bin/python3', '-B', script, '--lock', directory + '/sources.lock.json',
            '--stage', stage, '--run-id', run_id] + (['--keypad-trace'] if keypad_trace else []) + (
                ['--keypad-persist', keypad_persist] if keypad_persist is not None else [])


def inline(client, *args):
    # Inline inspection/recovery also needs the same saved keypad helper.
    program = ('import sys, types\n'
               'keypad_helper = types.ModuleType("keypad_pm")\n'
               'exec(' + repr((ROOT / 'tools/keypad_pm.py').read_text()) + ', keypad_helper.__dict__)\n'
               'sys.modules["keypad_pm"] = keypad_helper\n' +
               (ROOT / 'tools/test-pm-stages.py').read_text())
    return run(client, shlex.join(['sudo', '-n', 'python3', '-B', '-c',
               program, *args]), display=False, timeout=40)


def wifi_proof(config, snapshot):
    addresses = re.findall(r'^ip_address=(.+)$', snapshot['wifi'], re.M)
    if len(addresses) != 1 or addresses[0] == config.get('GAMESHELL_USB_IP', '192.168.10.1'):
        raise ValueError('A distinct connected Wi-Fi address is required')
    module('pm_wifi_proof', 'check-wifi-firmware.py').verify_wifi(config, snapshot['boot_id'], addresses[0])


def collect(config, run_id):
    with device(config, 'usb') as client:
        return json.loads(inline(client, '--collect', run_id))


def cycle(config, capture, lock, stage, keypad_trace=False, keypad_persist=None):
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
        command = service_command(directory, stage, run_id, keypad_trace, keypad_persist)
        with client.open_sftp() as sftp:
            upload(sftp, ROOT / 'tools/test-pm-stages.py', directory + '/test-pm-stages.py')
            upload(sftp, ROOT / 'tools/keypad_pm.py', directory + '/keypad_pm.py')
            upload(sftp, ROOT / 'build/sources.lock.json', directory + '/sources.lock.json')
        (capture / 'run.json').write_text(json.dumps(dict(run_id=run_id, stage=stage, helper=directory)) + '\n')
        print('PM run:', run_id, 'helper:', directory, flush=True)
        # Submission may itself lose SSH after systemd accepted it. Never retry
        # submission: recover this exact ID and fail incomplete evidence.
        try:
            run(client, shlex.join(command), display=False, timeout=20)
        except (OSError, RuntimeError, paramiko.SSHException) as error:
            (capture / 'submission-error.txt').write_text(type(error).__name__ + '\n')
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        time.sleep(5)
        try:
            result = collect(config, run_id)
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
        wifi_proof(config, result['after'])
        # A fresh USB SSH collection above and independent Wi-Fi proof below
        # are required; kernel return alone is insufficient.
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--test', action='store_true')
    mode.add_argument('--collect', action='store_true')
    mode.add_argument('--restore', action='store_true')
    mode.add_argument('--keypad-compare', action='store_true')
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
    if trace_option not in ('0', '1') or (trace_option == '1' and stage != 'devices'):
        raise ValueError('KEYPAD_TRACE=0/1; tracing requires STAGE=devices')
    if not args.keypad_compare and (stage not in ('freezer', 'devices') or not 1 <= cycles <= 4):
        raise ValueError('Explicit STAGE=freezer/devices and CYCLES=1..4 required')
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    (capture / 'sources.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    with (LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.keypad_compare:
            compare_keypad(config, capture, lock)
            return
        for index in range(cycles):
            directory = capture / ('cycle-' + str(index + 1))
            directory.mkdir(mode=0o700)
            cycle(config, directory, lock, stage, trace_option == '1')
            if index + 1 < cycles:
                time.sleep(20)


if __name__ == '__main__':
    main()
