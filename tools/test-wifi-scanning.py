#!/usr/bin/env python3
"""Compare normal/offload-disabled/normal scanning, restoring the runtime flag."""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import time

STATE = Path('/run/gameshellneo-scan-test.json')


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=15).stdout.strip()


def wpa(*args):
    return command('/usr/sbin/wpa_cli', '-i', 'wlan0', *args)


def setting():
    value = wpa('get', 'disable_scan_offload')
    if value not in ('0', '1'):
        raise ValueError('Unable to read scan-offload setting')
    return int(value)


def set_value(value):
    if value not in (0, 1) or wpa('set', 'disable_scan_offload', str(value)) != 'OK':
        raise ValueError('Could not set scan-offload flag')
    if setting() != value:
        raise ValueError('Scan-offload flag readback failed')
    # Firmware recovery may temporarily disable the interface. The saved
    # userspace setting can still be verified independently of reassociation.
    return wpa('reassociate') == 'OK'


def restore():
    if STATE.exists():
        original = json.loads(STATE.read_text())['original']
        set_value(original)
        STATE.unlink()


def snapshot():
    fields = dict(line.split('=', 1) for line in wpa('status').splitlines() if '=' in line)
    ifindex_error = None
    try:
        ifindex = Path('/sys/class/net/wlan0/ifindex').read_text().strip()
    except OSError as error:
        ifindex = None  # Firmware recovery can remove/recreate the interface.
        ifindex_error = error.errno
    return dict(monotonic_seconds=time.monotonic(),
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                wpa_state=fields.get('wpa_state', 'unavailable'),
                disable_scan_offload=setting(),
                ifindex=ifindex, ifindex_error=ifindex_error)


def kernel_counts():
    log = command('journalctl', '-b', '-k', '--no-pager', '-o', 'cat')
    return dict(firmware_crashes=log.count('brcmf_fw_crashed: Firmware has halted or crashed'),
                sdio_removals=log.count('mmc1: card 0001 removed'))


def emit(event, **values):
    print(json.dumps(dict(event=event, **values)), flush=True)


def interrupted(number, _frame):
    raise InterruptedError('Scan comparison interrupted by signal ' + str(number))


def measure(seconds):
    original = setting()
    if original != 0:
        raise ValueError('This comparison requires the original offload-enabled setting (0)')
    if STATE.exists():
        raise ValueError('An earlier scan-test restoration record still exists')
    with STATE.open('x') as stream:
        stream.write(json.dumps({'original': original}))
    STATE.chmod(0o600)
    initial_boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    phases = []
    try:
        for name, value in [('original', original), ('host_scanning', 1), ('original_repeat', original)]:
            requested = set_value(value)
            emit('settling', phase=name, disable_scan_offload=value, seconds=10,
                 reassociate_accepted=requested)
            time.sleep(10)
            before = kernel_counts()
            samples = []
            started = time.monotonic()
            for index in range(seconds // 10 + 1):
                time.sleep(max(0, started + index * 10 - time.monotonic()))
                sample = snapshot()
                if sample['boot_id'] != initial_boot or sample['disable_scan_offload'] != value:
                    raise ValueError('Boot or scan-offload flag changed during comparison')
                samples.append(sample)
                emit('sample', phase=name, **sample)
            after = kernel_counts()
            if any(after[key] < before[key] for key in before):
                raise ValueError('Kernel log count decreased; cannot compare')
            result = dict(phase=name, disable_scan_offload=value,
                          reassociate_accepted=requested,
                          duration_seconds=time.monotonic() - started,
                          counts={key: after[key] - before[key] for key in before},
                          states=sorted({sample['wpa_state'] for sample in samples}),
                          interface_indices=sorted({sample['ifindex'] for sample in samples
                                                    if sample['ifindex'] is not None}))
            phases.append(result)
            emit('phase_complete', **result)
    finally:
        restore()
        emit('restored', disable_scan_offload=original)
    emit('complete', passed=True, phases=phases,
         limits='Runtime flag isolation; not firmware repair, calibrated power or absent-AP proof.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    if args.restore:
        restore()
        return
    if not 60 <= args.seconds <= 180 or args.seconds % 10:
        parser.error('seconds must be a multiple of ten in 60..180')
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    measure(args.seconds)


if __name__ == '__main__':
    main()
