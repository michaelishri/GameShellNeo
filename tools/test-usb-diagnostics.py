#!/usr/bin/env python3
"""On-device, bounded USB callback counts or isolated status-read fault test."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time

DEBUG = Path('/sys/kernel/debug/gameshellneo-usb')
STATE = Path('/run/gameshellneo/usb-diagnostic-test.json')
LOCK = Path('/run/lock/gameshellneo-usb-diagnostics.lock')
BOOT = Path('/proc/sys/kernel/random/boot_id')
OBSERVERS = ('idle-sample', 'power-profile', 'governor-profile', 'governor-comparison',
             'usb-detection', 'usb-reconnects', 'scan-test', 'firmware-trial',
             'stability-test', 'backlight-test')


def check_observers():
    units = subprocess.check_output(['systemctl', 'list-units', '--all', '--plain', '--no-legend',
                                     '--state=active,activating,deactivating',
                                     *['gameshellneo-' + name + '.service' for name in OBSERVERS]], text=True)
    if units.strip():
        raise ValueError('Stop other diagnostic observers before measuring USB callbacks')


def command(value):
    with (DEBUG / 'control').open('w') as stream:
        stream.write(value + '\n')


def snapshot():
    with (DEBUG / 'status').open('rb', buffering=0) as stream:
        value = json.loads(stream.read(4096))
    validate(value)
    return value


def validate(value):
    if (value['version'] != 1 or value['entries'] != value['completed'] + value['inflight'] or
            value['completed'] != value['success'] + value['real_errors'] + value['injected_errors'] or
            not 0 <= value['budget'] <= 4):
        raise ValueError('Incoherent USB diagnostic counters')


def quiet_snapshot():
    deadline = time.monotonic() + 1
    while True:
        value = snapshot()
        if not value['inflight']:
            return value
        if time.monotonic() >= deadline:
            raise ValueError('USB callback did not complete within one second')
        time.sleep(0.001)


def count_result(before, after):
    for value in (before, after):
        validate(value)
        if not value['enabled'] or value['inflight'] or value['synthetic_requests']:
            raise ValueError('Natural count window crossed a control action or callback boundary')
    if (before['generation'] != after['generation'] or before['experimental'] != after['experimental'] or
            after['monotonic_ns'] <= before['monotonic_ns']):
        raise ValueError('USB count identity or time changed')
    delta = {key: after[key] - before[key] for key in
             ('entries', 'completed', 'success', 'real_errors', 'injected_errors')}
    if any(number < 0 for number in delta.values()) or delta['real_errors'] or delta['injected_errors']:
        raise ValueError('Count window contained an error or reset')
    seconds = (after['monotonic_ns'] - before['monotonic_ns']) / 1e9
    return dict(delta=delta, seconds=seconds, callbacks_per_second=delta['entries'] / seconds)


def error_result(before, after, errors, status):
    validate(before)
    validate(after)
    if (not before['enabled'] or not after['enabled'] or before['inflight'] or before['budget'] or
            before['generation'] != after['generation'] or after['inflight'] or after['budget'] or
            before['experimental'] != after['experimental'] or
            after['synthetic_requests'] != before['synthetic_requests'] + 1 or
            after['real_errors'] != before['real_errors']):
        raise ValueError('Error test identity, expiry or real-read health failed')
    retry = bool(after['experimental'] or not (status & 16))
    expected = errors if retry else 1
    events = after['events']
    injected = [event for event in events if event['injected']]
    if after['injected_errors'] - before['injected_errors'] != expected or len(injected) != expected:
        raise ValueError('Unexpected injected error count')
    if any(event['result'] != -5 or event['status'] != status or
           event['retry_ms'] != (50 if retry else 0) for event in injected):
        raise ValueError('Failed read changed retained status or retry selection')
    recovered = any(not event['injected'] and event['result'] == 0 for event in events)
    if retry and not recovered:
        raise ValueError('Automatic real-read recovery was not observed')
    if after['status'] != status:
        raise ValueError('USB state changed during the isolated test')
    return dict(expected_injected=expected, automatic_retry_expected=retry,
                successful_real_read_observed=recovered,
                physical_irq_recovery_tested=False)


def restore():
    if not STATE.exists():
        return
    saved = json.loads(STATE.read_text())
    if saved['boot_id'] != BOOT.read_text().strip():
        raise ValueError('Saved diagnostic ownership belongs to another boot')
    command('disable')
    value = quiet_snapshot()
    if value['enabled'] or value['budget']:
        raise ValueError('USB diagnostic restoration failed')
    STATE.unlink()


def emit(event, **values):
    print(json.dumps(dict(event=event, **values)), flush=True)


def execute(mode, seconds, errors):
    check_observers()
    identity = json.loads(Path('/etc/gameshellneo/image.json').read_text())
    if (identity['board'] != 'gameshellneo-cpi31' or identity['kernel'] != os.uname().release or
            identity['sources'].get('experiments', {}).get('usb_diagnostics') is not True):
        raise ValueError('Expected a running diagnostic image with USB diagnostics opted in')
    if Path('/proc/sys/kernel/tainted').read_text().strip() != '0':
        raise ValueError('Kernel is tainted')
    if STATE.exists():
        raise ValueError('Earlier test ownership exists; restore it before starting')
    initial = snapshot()
    if initial['enabled'] or initial['budget'] or initial['inflight']:
        raise ValueError('Diagnostics are already in use')
    boot = BOOT.read_text().strip()
    with STATE.open('x') as stream:
        json.dump(dict(boot_id=boot, original=initial), stream)
    started = time.process_time()
    emit('ready', boot_id=boot, kernel=os.uname().release, image=identity['version'],
         mode=mode, seconds=seconds, requested_errors=errors if mode == 'errors' else 0, initial=initial,
         limits='Direct callbacks, not unique CPU wakeups or energy. Error injection affects only '
                'one poll call site; it does not reproduce electrical bus failures or cable IRQs.')
    try:
        command('enable')
        before = quiet_snapshot()
        emit('started', snapshot=before)
        if mode == 'count':
            time.sleep(seconds)
            after = quiet_snapshot()
            emit('observed', snapshot=after)
            result = count_result(before, after)
        else:
            supply = Path('/sys/class/power_supply/axp20x-usb')
            status = (int((supply / 'present').read_text()) << 5 |
                      int((supply / 'online').read_text()) << 4)
            command('inject ' + str(errors))
            # Includes the kernel's one-second budget expiry and recovery time.
            time.sleep(1.5)
            after = quiet_snapshot()
            emit('observed', snapshot=after, expected_retained_status=status)
            result = error_result(before, after, errors, status)
        if BOOT.read_text().strip() != boot:
            raise ValueError('Boot changed during the test')
        check_observers()
        emit('measurement', before=before, after=after, result=result,
             observer_cpu_seconds=time.process_time() - started)
    finally:
        restore()
    emit('complete', passed=True, controls_restored=True, final=snapshot())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('count', 'errors'), default='count')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--errors', type=int, default=1)
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    if not 30 <= args.seconds <= 300 or not 1 <= args.errors <= 4:
        parser.error('SECONDS must be 30..300 and ERRORS must be 1..4')
    os.umask(0o077)
    def stop(number, _frame):
        raise SystemExit('Interrupted by signal ' + str(number))
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, stop)
    with LOCK.open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.restore:
            restore()
        else:
            execute(args.mode, args.seconds, args.errors)


if __name__ == '__main__':
    main()
