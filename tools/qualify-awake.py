#!/usr/bin/env python3
"""Run a fixed, bounded awake qualification; preserve evidence and never retry a failed step."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time

from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run, python_command

LIMITS = ('Awake software qualification only. No sleep/wake, physical controls, cable, '
          'visual/audio quality, battery endurance or energy qualification. '
          'Software battery readings do not resolve NEO-10.')
RECOVERY = ('Do not repeat an interrupted run blindly. Inspect step logs and retained evidence; '
            'verify USB access and the device service/recovery state first. The installed-firmware '
            'trial has its own bounded service and ExecStopPost restoration. See README for '
            'device:wifi-recovery recovery instructions. This runner never resets another test’s state.')
# Exact argv, never a task-name interpolation or an inherited physical-cycle count.
PLAN = (
    ('guard-before', ('qualify-awake.py', '--guard'), 120),
    ('boot-before', ('check-boot-cycles.py', '--cycles', '0'), 180),
    ('pm-before', ('check-pm-stages.py', '--inspect'), 120),
    ('keypad-before', ('check-keypad.py',), 120),
    ('audio-before', ('check-audio.py', '--inspect'), 120),
    ('wifi', ('check-wifi-firmware.py', '--installed'), 2100),
    ('pm-after-wifi', ('check-pm-stages.py', '--inspect'), 120),
    ('stability', ('remote.py', 'device', 'stability', '--route', 'usb'), 510),
    ('battery', ('remote.py', 'device', 'battery-check', '--route', 'usb'), 150),
    ('integration', ('remote.py', 'device', 'check', '--route', 'usb'), 240),
    ('boot-after', ('check-boot-cycles.py', '--cycles', '0'), 180),
    ('pm-after', ('check-pm-stages.py', '--inspect'), 120),
    ('keypad-after', ('check-keypad.py',), 120),
    ('audio-after', ('check-audio.py', '--inspect'), 120),
    ('guard-after', ('qualify-awake.py', '--guard'), 120),
)
# Read-only preflight. Existing recovery files are evidence, never deleted here.
GUARD = r'''
import json, pathlib, subprocess
units = subprocess.check_output(['systemctl', 'list-units', '--all', '--plain',
    '--no-legend', '--state=active,activating,deactivating', 'gameshellneo-*.service'],
    text=True, stderr=subprocess.PIPE, timeout=20).splitlines()
ordinary = {'gameshellneo-usb.service', 'gameshellneo-battery.service', 'gameshellneo-ready.service'}
active = [line.split()[0] for line in units if line.split()[0] not in ordinary]
owned = [str(p) for p in pathlib.Path('/run').glob('gameshellneo-*')]
usb_record = pathlib.Path('/run/gameshellneo/usb-diagnostic-test.json')
if usb_record.exists():
    owned.append(str(usb_record))
for unit in ('gameshellneo-firmware-trial', 'gameshellneo-stability-test'):
    state = subprocess.check_output(['systemctl', 'show', unit, '-p', 'LoadState', '--value'],
        text=True, stderr=subprocess.PIPE, timeout=20).strip()
    if state != 'not-found' and unit + '.service' not in active:
        active.append(unit + '.service:' + state)
print(json.dumps({'boot_id': pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    'active_diagnostics': active, 'recovery_records': sorted(owned)}))
'''


def now():
    return datetime.now(timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, value):
    """Atomic durable progress: a host crash cannot turn a partial step into a pass."""
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(json.dumps(value, indent=2) + '\n')
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def module(filename):
    spec = importlib.util.spec_from_file_location('awake_' + filename.replace('-', '_'), ROOT / 'tools' / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def sources():
    paths = [ROOT / 'build/sources.lock.json', *sorted((ROOT / 'tools').glob('*.py')),
             ROOT / 'runtime/tests/test_battery.py',
             ROOT / 'runtime/usr/local/lib/gameshellneo/battery_guard.py']
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def child_environment(directory):
    env = os.environ.copy()
    # Force only the options used by this fixed sequence. Credentials still come from .env.
    env.update(NEO_EVIDENCE_ROOT=str(directory), NEO_ROUTE='usb', NEO_BOOT_CYCLES='0',
               NEO_PROFILE_SECONDS='120', PYTHONUNBUFFERED='1')
    return env


def stop_child(process, grace):
    if process.poll() is not None:
        return
    # Python controllers handle SIGINT with their existing finally/recovery hooks.
    # SIGTERM would bypass those hooks in several legacy host controllers.
    os.killpg(process.pid, signal.SIGINT)
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def execute(argv, directory, timeout, grace):
    with (directory / 'controller.log').open('xb') as output:
        process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'tools' / argv[0]), *argv[1:]],
            cwd=ROOT, env=child_environment(directory), stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return process.wait(timeout=timeout)
        finally:
            stop_child(process, grace)


def capture(directory):
    # One newly created step directory owns exactly one child capture. Never glob
    # the global diagnostics tree or adopt another run's earlier success.
    matches = [p for p in directory.iterdir() if p.is_dir()]
    require(len(matches) == 1 and not matches[0].is_symlink(), 'Expected one fresh child capture')
    return matches[0]


def json_file(directory, name):
    return json.loads((directory / name).read_text())


def json_lines(directory, name):
    return [json.loads(line) for line in (directory / name).read_text().splitlines() if line.strip()]


def same_boot(value, context):
    boot = value['boot_id']
    require(re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot), 'Invalid boot identity')
    if 'boot_id' in context:
        require(boot == context['boot_id'], 'Device rebooted during awake qualification')
    else:
        context['boot_id'] = boot


def validate_step(name, directory, context, lock):
    """Require semantic evidence in addition to a successful controller exit."""
    if name.startswith('guard-'):
        value = json_file(directory, 'guard.json')
        same_boot(value, context)
        require(not value['active_diagnostics'] and not value['recovery_records'],
                'Concurrent diagnostic or unresolved recovery record; inspect guard.json')
        return {'diagnostics_idle': True, 'recovery_records_absent': True}
    if name.startswith('boot-'):
        summary = json_file(directory, 'summary.json')
        require(summary['passed'] is True and summary['requested_cycles'] == 0 and
                summary['verified_cycles'] == 0, 'Current-boot check did not pass')
        value = json_file(directory, context['boot_id'] + '.json')
        same_boot(value, context)
        require(value.get('wifi_ssh_verified') is True and not value['failed_checks'], 'Both SSH routes must pass')
        require(not module('check-boot-cycles.py').validate(value, lock), 'Boot snapshot failed validation')
        return {'boot_id': context['boot_id'], 'usb_and_wifi_ssh': True}
    if name.startswith('pm-'):
        value = json_file(directory, 'inspection.json')
        same_boot(value, context)
        module('test-pm-stages.py').validate(value, lock)
        if name == 'pm-before':
            context['pm'] = value
        else:
            before = context['pm']
            for field in ('pm', 'pm_test_delay', 'stats', 'masks', 'sleep_config', 'usb_experiments',
                          'wifi_config_sha256', 'wifi_power_save', 'charger', 'cpu_policy', 'backlight',
                          'firmware_sha256', 'nvram_sha256', 'sdio_retains_power', 'keypad_retains_supply'):
                require(value[field] == before[field], 'Changed awake state: ' + field)
            require(value['journal'].startswith(before['journal']), 'Kernel journal was lost or rotated')
        return {'healthy_usb_powered': True, 'battery_percent': value['battery']['capacity_percent'],
                'state_unchanged': name != 'pm-before', 'suspend_count': int(value['stats']['success'])}
    if name.startswith('keypad-'):
        value = json_file(directory, 'keypad.json')
        identity = {k: value[k] for k in ('usb', 'inputs', 'regulators', 'port_quirks')}
        require(value['inputs'] and value['usb']['power']['control'] == 'on' and
                value['usb']['power']['persist'] == '1' and value['port_quirks']['value'] == 0,
                'Keypad is missing or has unexpected policy')
        if name == 'keypad-before':
            context['keypad'] = identity
        else:
            require(identity == context['keypad'], 'Keypad identity or policy changed')
        return {'devnum': value['usb']['attributes']['devnum'], 'identity_unchanged': name != 'keypad-before'}
    if name.startswith('audio-'):
        value = json_file(directory, 'audio.json')
        same_boot(value, context)
        require(value['pcm_status'] and all(v.strip() == 'closed' for v in value['pcm_status'].values()) and
                value['amplifiers'] and all(v == 'Off' for v in value['amplifiers'].values()),
                'Audio is not idle')
        if name == 'audio-before':
            context['audio'] = value['controls']
        else:
            require(value['controls'] == context['audio'], 'Mixer controls changed')
        return {'pcm_closed': True, 'amplifiers_off': True, 'tones_played': False}
    if name == 'wifi':
        events = json_lines(directory, 'firmware-trial.jsonl')
        final = events[-1]
        require(final.get('event') == 'complete' and all(final.get(k) is True for k in
                ('passed', 'installed', 'connected', 'configuration_restored')), 'Missing Wi-Fi completion/restoration')
        phases = module('check-wifi-firmware.py').INSTALLED_PHASES
        checkpoints = json_lines(directory, 'wifi-ssh.jsonl')
        require([v['phase'] for v in checkpoints] == phases, 'Incomplete independent Wi-Fi checkpoints')
        for value in checkpoints:
            same_boot(value, context)
            require(value['passed'] is True, 'Wi-Fi SSH checkpoint failed')
        windows = [e for e in events if e['event'] == 'installed_window_complete']
        require([e['phase'] for e in windows] == ['unavailable_network', 'connected'] and
                all(e['duration_seconds'] >= 120 for e in windows), 'Incomplete Wi-Fi observation windows')
        require(final['health']['identities'] == [lock['radio']['firmware']['runtime_identity']] and
                not any(final['health']['faults'].values()), 'Wi-Fi firmware reloaded or faulted')
        return {'wifi_ssh_checkpoints': len(checkpoints), 'configuration_restored': True,
                'window_seconds': [e['duration_seconds'] for e in windows]}
    if name == 'stability':
        events = json_lines(directory, 'stability.jsonl')
        require(events[-1]['event'] == 'passed' and events[-1].get('temporary_files_removed') is True,
                'Missing storage/load completion or cleanup')
        for value in (events[0], events[-1]):
            same_boot(value, context)
        storage = [e for e in events if e['event'] == 'storage_passed']
        stress = [e for e in events if e['event'] == 'stress_result']
        require(len(storage) == 1 and storage[0]['bytes'] == 128 * 1024 * 1024 and
                storage[0]['direct_read'] is True and len(stress) == 1 and stress[0]['exit_code'] == 0,
                'Missing storage or load verification')
        samples = [e for e in events if e['event'] == 'sample']
        require(samples and all(e['temperature_mc'] < 80000 and e['kernel_taint'] == 0 for e in samples),
                'Temperature or taint limit failed')
        return {'storage_bytes': storage[0]['bytes'], 'storage_sha256': storage[0]['sha256'],
                'maximum_temperature_c': max(e['temperature_mc'] for e in samples) / 1000,
                'temporary_files_removed': True}
    if name == 'battery':
        output = (directory / 'battery-policy.txt').read_text()
        match = re.search(r'Ran ([1-9][0-9]*) tests? in ', output)
        require(match and output.rstrip().endswith('\nOK'), 'Installed battery-policy simulation did not pass')
        return {'simulated_tests_passed': int(match[1]), 'real_shutdown_tested': False}
    if name == 'integration':
        value = json_file(directory, 'integration.json')
        require(set(value) == {'image_identity', 'service_state', 'database_and_policy', 'journal_acl',
                              'bpf_enforcement', 'country'} and all(v['passed'] is True for v in value.values()),
                'Incomplete or failed integration checks')
        return {'check_groups_passed': len(value)}
    raise ValueError('Unknown qualification step')


def report_text(record):
    lines = ['# Awake qualification', '', 'Status: **' + record['status'] + '**', '',
             'Started: ' + record['started'], 'Image: ' + record['image'], 'Kernel: ' + record['kernel'],
             'Boot: ' + record.get('boot_id', 'not verified'), '',
             '| Step | Status | Evidence |', '| --- | --- | --- |']
    for step in record['steps']:
        evidence = step.get('evidence', step['directory'] + '/controller.log')
        lines.append(f"| {step['name']} | {step['status']} | [{evidence}]({evidence}) |")
    results = {s['name']: s['result'] for s in record['steps'] if s['status'] == 'passed' and 'result' in s}
    lines += ['', 'Observed results:', '']
    if 'wifi' in results:
        result = results['wifi']
        lines.append(f"- Wi-Fi: {result['wifi_ssh_checkpoints']} independent SSH checkpoints; configuration restored.")
    if 'stability' in results:
        result = results['stability']
        lines.append(f"- Storage/load: {result['storage_bytes']} bytes verified by direct read; "
                     f"maximum sampled temperature {result['maximum_temperature_c']:.3f} C; temporary files removed.")
    if 'battery' in results:
        lines.append(f"- Battery policy: {results['battery']['simulated_tests_passed']} simulated tests passed.")
    if 'integration' in results:
        lines.append(f"- Integration: {results['integration']['check_groups_passed']} groups passed.")
    if 'pm-after' in results:
        lines.append(f"- Final awake state matched baseline; battery estimate {results['pm-after']['battery_percent']}%. "
                     'Suspend counters unchanged.')
    lines += ['', 'Restoration: ' + record['restoration'] + '.', '', LIMITS, '',
              'Full results, source hashes and timings: [progress.json](progress.json). '
              'Each step has private controller logs and raw evidence. No credentials are copied into this report.']
    if record['status'] != 'passed':
        lines += ['', RECOVERY, '', 'A running record is incomplete until this process writes a final result; '
                  'it may also mean the host stopped unexpectedly. Reporting never resumes tests.']
    return '\n'.join(lines) + '\n'


def persist(directory, record):
    save(directory / 'progress.json', record)
    temporary = directory / 'report.md.tmp'
    temporary.write_text(report_text(record))
    temporary.replace(directory / 'report.md')


def qualify(directory, execute_step=execute, validate=validate_step):
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    fingerprints = sources()
    record = {'schema': 1, 'started': now(), 'status': 'running', 'host_pid': os.getpid(),
              'image': lock['image_version'], 'kernel': lock['linux']['tag'][1:] + lock['linux']['localversion'],
              'restoration': 'not yet verified', 'source_sha256': fingerprints, 'limits': LIMITS,
              'steps': [{'name': n, 'argv': list(a), 'timeout_seconds': t, 'status': 'pending',
                         'directory': f'{i:02d}-{n}'} for i, (n, a, t) in enumerate(PLAN)]}
    save(directory / 'sources.lock.json', lock)
    persist(directory, record)
    context = {}
    current = None
    try:
        for current in record['steps']:
            require(sources() == fingerprints, 'Qualification sources changed during this run')
            step_dir = directory / current['directory']
            step_dir.mkdir(mode=0o700)  # Refuse stale evidence, including an interrupted run.
            current.update(status='running', started=now())
            persist(directory, record)
            print('Awake qualification:', current['name'], flush=True)
            start = time.monotonic()
            code = execute_step(current['argv'], step_dir, current['timeout_seconds'],
                                450 if current['name'] == 'wifi' else 30)
            current['exit_code'] = code
            require(code == 0, 'Controller failed; see private step log')
            child = capture(step_dir)
            current['evidence'] = str(child.relative_to(directory))
            current['result'] = validate(current['name'], child, context, lock)
            current.update(status='passed', completed=now(), duration_seconds=round(time.monotonic() - start, 3))
            record['boot_id'] = context.get('boot_id', 'not verified')
            persist(directory, record)
        require(sources() == fingerprints, 'Qualification sources changed during this run')
        record.update(status='passed', restoration='verified against the original awake state')
    except (Exception, KeyboardInterrupt) as error:
        if current:
            current.update(status='interrupted' if isinstance(error, KeyboardInterrupt) else 'failed',
                           error_type=type(error).__name__, completed=now())
        # Exception messages and controller output stay private; never print the environment.
        (directory / 'failure.txt').write_text(type(error).__name__ + ': ' + str(error) + '\n')
        record.update(status='interrupted' if isinstance(error, KeyboardInterrupt) else 'failed',
                      restoration='unverified; inspect retained evidence before another test')
        for step in record['steps']:
            if step['status'] == 'pending':
                step['status'] = 'skipped'
    record['completed'] = now()
    persist(directory, record)
    return record


def interrupted(_signum, _frame):
    raise KeyboardInterrupt('Qualification interrupted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true', help='Print the fixed sequence without connecting')
    mode.add_argument('--report', type=Path, help='Read saved progress without connecting or resuming')
    mode.add_argument('--guard', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.umask(0o077)
    if args.plan:
        for name, argv, timeout in PLAN:
            print(f'{name}: {shlex.join(argv)} (host limit {timeout}s)')
        print(LIMITS)
        return 0
    if args.report:
        print(report_text(json_file(args.report, 'progress.json')), end='')
        return 0
    if args.guard:
        directory = evidence_directory()
        with device(load_env(), 'usb') as client:
            data = run(client, **python_command(GUARD), display=False, timeout=75)
        (directory / 'guard.json').write_bytes(data)
        return 0
    config = load_env()
    country = os.environ.get('NEO_ACTIVE_COUNTRY') or config.get('GAMESHELL_WIFI_COUNTRY', '')
    require(re.fullmatch('[A-Z]{2}', country), 'Set GAMESHELL_WIFI_COUNTRY; ACTIVE_COUNTRY may override observation')
    os.environ['NEO_ACTIVE_COUNTRY'] = country
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    with (LOCAL / 'awake-qualification.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Ignore an inherited evidence override for the top-level run.
        directory = LOCAL / 'diagnostics' / ('awake-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
        directory.mkdir(mode=0o700, parents=True)
        print('Private awake qualification:', directory, flush=True)
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(signum, interrupted)
        result = qualify(directory)
        print('Awake qualification ' + result['status'] + '. Report: ' + str(directory / 'report.md'), flush=True)
        return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
