#!/usr/bin/env python3
"""Observe owner-operated power cycles; never issue reboot or poweroff commands."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
import shlex
import sys
import time

import paramiko
from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run


PROBE = r'''
import json, os, subprocess
from pathlib import Path

def command(*args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=20).strip()
    except subprocess.CalledProcessError as error:
        raise RuntimeError(error.stderr.strip()) from error

def read(path):
    return Path(path).read_text().strip()

units = ['gameshellneo-usb', 'gameshellneo-battery', 'gameshellneo-ready',
         'ssh', 'systemd-networkd', 'wpa_supplicant@wlan0', 'getty@tty1']
services = {}
for unit in units:
    values = command('systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'NRestarts')
    services[unit] = dict(line.split('=', 1) for line in values.splitlines())
boots = command('journalctl', '--list-boots', '--no-pager')
previous = next((line.split()[1] for line in boots.splitlines() if line.split()[0] == '-1'), None)
result = {
    'boot_id': read('/proc/sys/kernel/random/boot_id'), 'previous_boot_id': previous,
    'kernel': os.uname().release, 'image': json.loads(read('/etc/gameshellneo/image.json')),
    'cpus': os.cpu_count(), 'memory_kib': int(read('/proc/meminfo').splitlines()[0].split()[1]),
    'taint': int(read('/proc/sys/kernel/tainted')), 'services': services,
    'failed_units': command('systemctl', '--failed', '--no-legend', '--plain', '--no-pager'),
    'ready': json.loads(read('/run/gameshellneo/ready.json')),
    'battery': json.loads(read('/run/gameshellneo/battery.json')),
    'usb_states': [read(p) for p in Path('/sys/class/udc').glob('*/state')],
    'backlight': {p: int(read('/sys/class/backlight/ocp8178/' + p))
                  for p in ('brightness', 'bl_power')},
    'inputs': [read(p) for p in Path('/sys/class/input').glob('event*/device/name')],
    'startup': command('systemd-analyze'),
    'kernel_journal': command('journalctl', '-b', '0', '-k', '--no-pager', '-o', 'short-monotonic'),
    'previous_shutdown': command('journalctl', '-b', previous, '-n', '300', '--no-pager',
                                 '-o', 'short-monotonic') if previous else '',
}
print(json.dumps(result))
'''


def firmware_check(journal, firmware):
    """Preserve loaded identities/fault counts; only enforce a pinned expectation."""
    required = 'runtime_identity' in firmware
    expected = firmware.get('runtime_identity')
    prefix = 'brcmf_c_preinit_dcmds: '
    identities = [line.split(prefix, 1)[1].strip() for line in journal.splitlines()
                  if prefix + 'Firmware: ' in line]
    faults = {name: journal.count(marker) for name, marker in {
        'firmware_crashes': 'brcmf_fw_crashed: Firmware has halted or crashed',
        'sdio_removals': 'mmc1: card 0001 removed',
        'pm_usage_underflows': 'Runtime PM usage count underflow',
    }.items()}
    passed = (isinstance(expected, str) and expected.startswith('Firmware: ') and
              identities == [expected] and not any(faults.values())) if required else None
    return {'required': required, 'expected': expected, 'identities': identities,
            'faults': faults, 'passed': passed}


def validate(snapshot, lock):
    expected_kernel = lock['linux']['tag'][1:] + lock['linux']['localversion']
    snapshot['firmware_check'] = firmware_check(
        snapshot.get('kernel_journal', ''), lock.get('radio', {}).get('firmware', {}))
    checks = {
        'image': snapshot['image']['version'] == lock['image_version'],
        'kernel': snapshot['kernel'] == expected_kernel,
        'cpus': snapshot['cpus'] == 4,
        'memory': 900 * 1024 <= snapshot['memory_kib'] <= 1100 * 1024,
        'kernel_taint': snapshot['taint'] == 0,
        'firmware': snapshot['firmware_check']['passed'] is not False,
        'services': all(s['ActiveState'] == 'active' and s['NRestarts'] == '0'
                        for s in snapshot['services'].values()),
        'failed_units': not snapshot['failed_units'],
        'ready': snapshot['ready'].get('local_userspace_ready') is True,
        'battery_monitor': snapshot['battery'].get('monitoring') == 'valid',
        'usb': snapshot['usb_states'] == ['configured'],
        'backlight': snapshot['backlight']['brightness'] > 0 and
                     snapshot['backlight']['bl_power'] == 0,
        'inputs': all(name in snapshot['inputs'] for name in
                      ('axp20x-pek', 'rancidbacon.com UsbKeyboard')),
    }
    return [name for name, passed in checks.items() if not passed]


def capture(config, directory, lock):
    with device(config, 'usb') as client, (directory / 'latest-probe.txt').open('wb') as output:
        snapshot = json.loads(run(client, shlex.join(['sudo', '-n', 'python3', '-c', PROBE]),
                                  output=output, display=False, timeout=30))
    path = directory / (snapshot['boot_id'] + '.json')
    snapshot['checked_at'] = datetime.now(timezone.utc).isoformat()
    snapshot['failed_checks'] = validate(snapshot, lock)
    path.write_text(json.dumps(snapshot, indent=2) + '\n')
    if snapshot['failed_checks']:
        raise ValueError('Boot checks failed: ' + ', '.join(snapshot['failed_checks']))
    # Each captured boot needs a separate direct Wi-Fi SSH check as well.
    with device(config, 'wifi') as client:
        wifi_boot = run(client, 'cat /proc/sys/kernel/random/boot_id',
                        display=False, timeout=10).decode().strip()
    if wifi_boot != snapshot['boot_id']:
        raise ValueError('Wi-Fi SSH reached a different boot')
    snapshot['wifi_ssh_verified'] = True
    path.write_text(json.dumps(snapshot, indent=2) + '\n')
    return snapshot


def observe(config, args, directory, record, summary):
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    baseline = capture(config, directory, lock)
    previous = baseline['boot_id']
    seen = {previous}
    record('ready', boot_id=previous, requested_cycles=args.cycles,
           message=('Baseline captured. Ready for owner-operated power cycles.' if args.cycles
                    else 'Current boot checked; no power cycles requested.'))
    deadline = time.monotonic() + args.timeout
    while summary['verified_cycles'] < args.cycles and time.monotonic() < deadline:
        try:
            with device(config, 'usb') as client:
                current = run(client, 'cat /proc/sys/kernel/random/boot_id',
                              display=False, timeout=10).decode().strip()
        except (OSError, RuntimeError, paramiko.SSHException) as error:
            record('usb_not_ready', error=str(error))
            time.sleep(2)
            continue
        if current != previous:
            if current in seen:
                raise ValueError('Previously recorded boot reappeared')
            try:
                snapshot = capture(config, directory, lock)
            except (OSError, RuntimeError, paramiko.SSHException) as error:
                record('capture_retry', boot_id=current, error=str(error))
                time.sleep(2)
                continue
            if snapshot['boot_id'] != current:
                raise ValueError('Boot changed during collection; allow more time between cycles')
            if snapshot['previous_boot_id'] != previous.replace('-', ''):
                raise ValueError('A boot was missed; no consecutive-cycle credit')
            log = snapshot['previous_shutdown']
            if not all(marker in log for marker in ('Power key pressed short.',
                                                     'Reached target poweroff.target',
                                                     'Syncing filesystems and block devices.')):
                raise ValueError('Previous boot lacks the required button/shutdown evidence')
            summary['verified_cycles'] += 1
            record('verified', cycle=summary['verified_cycles'], boot_id=current,
                   ready_seconds=snapshot['ready']['monotonic_seconds'])
            previous = current
            seen.add(current)
        time.sleep(2)
    if summary['verified_cycles'] != args.cycles:
        raise RuntimeError('Timed out waiting for all requested power cycles')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=os.environ.get('NEO_BOOT_CYCLES', '4'))
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    if not 0 <= args.cycles <= 10 or not 30 <= args.timeout <= 3600:
        parser.error('cycles must be 0..10 and timeout must be 30..3600 seconds')
    os.umask(0o077)
    directory = evidence_directory()
    print('Private boot-cycle evidence:', directory, flush=True)
    summary = {'requested_cycles': args.cycles, 'verified_cycles': 0, 'passed': False,
               'physical_off_and_console_confirmation_required': True}
    with (LOCAL / 'boot-cycles.lock').open('a') as lock, \
            (directory / 'boot-cycles.jsonl').open('w') as output:
        def record(event, **fields):
            entry = {'time': datetime.now(timezone.utc).isoformat(), 'event': event, **fields}
            line = json.dumps(entry)
            output.write(line + '\n')
            output.flush()
            print(line, flush=True)

        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            observe(load_env(), args, directory, record, summary)
            summary['passed'] = True
        except (OSError, ValueError, RuntimeError, KeyError, paramiko.SSHException,
                KeyboardInterrupt) as error:
            summary['error'] = str(error) or type(error).__name__
            record('failed', error=summary['error'])
        finally:
            (directory / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
