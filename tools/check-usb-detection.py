#!/usr/bin/env python3
"""Capture four plug/unplug cycles over Wi-Fi, checking USB SSH independently."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import json
import os
import re
import shlex
import time

import paramiko
from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run, upload

UNIT = 'gameshellneo-usb-detection'


class WifiObserver:
    """Reconnect once for read-only/idempotent operations on a stale transport."""
    def __init__(self, config, emit):
        self.config, self.emit = config, emit
        self.stack = ExitStack()
        self.client = None

    def __enter__(self):
        self.client = self.stack.enter_context(device(self.config, 'wifi'))
        return self

    def __exit__(self, *_args):
        self.stack.close()

    def query(self, command):
        return self.retry(lambda: run(self.client, command, display=False, timeout=10))

    def trace_since(self, path, offset):
        def fetch():
            with self.client.open_sftp() as sftp:
                sftp.get_channel().settimeout(10)
                if sftp.stat(path).st_size < offset:
                    raise ValueError('Remote trace was truncated')
                with sftp.open(path, 'rb') as source:
                    source.seek(offset)
                    return source.read(32768)
        return self.retry(fetch)

    def retry(self, operation):
        try:
            return operation()
        except (OSError, paramiko.SSHException) as error:
            self.emit('wifi_reconnecting', error=str(error))
            self.stack.close()
            self.stack = ExitStack()
            self.client = self.stack.enter_context(device(self.config, 'wifi'))
            result = operation()
            self.emit('wifi_reconnected')
            return result


def trace_records(data, final=False):
    # A concurrent append may leave the final JSON line incomplete. Ignore only
    # that tail during observation, never after the recorder has stopped.
    if final and data and not data.endswith(b'\n'):
        raise ValueError('Truncated final trace')
    lines = data.split(b'\n')[:-1]
    records = [json.loads(line) for line in lines]
    boot = None
    previous_time = -1
    previous_irqs = None
    for sequence, event in enumerate(records):
        if event['sequence'] != sequence:
            raise ValueError('Incomplete or out-of-order trace')
        boot = boot or event['boot_id']
        if event['boot_id'] != boot or event['monotonic'] < previous_time:
            raise ValueError('Boot or monotonic trace identity changed')
        previous_time = event['monotonic']
        if event['event'] == 'failed':
            raise ValueError('Recorder failed: ' + event['error'])
        if event['event'] == 'snapshot':
            irqs = event['irqs']
            if previous_irqs is not None:
                if (irqs['cpus'] != previous_irqs['cpus'] or
                        irqs['counts'].keys() != previous_irqs['counts'].keys() or
                        any(irqs['counts'][key] < value for key, value in previous_irqs['counts'].items())):
                    raise ValueError('IRQ layout or counters changed')
            previous_irqs = irqs
    if records and records[0]['event'] != 'ready':
        raise ValueError('Missing recorder metadata')
    if final and (not records or records[-1]['event'] != 'complete'):
        raise ValueError('Recorder did not complete cleanly')
    return records


class Cycles:
    """Require a disconnected baseline and authenticated USB access per cycle."""
    def __init__(self):
        self.baseline = None
        self.pending = None
        self.completed = []

    def consume(self, event):
        if event['event'] != 'snapshot':
            return
        state = event['state']
        if self.baseline is None:
            supply = event['power']['supplies']['axp20x-usb']
            if state != 'not attached' or supply['present'] or supply['online']:
                raise ValueError('Start this task with USB unplugged')
            self.baseline = event
        elif state == 'configured' and self.pending is None:
            self.pending = dict(attachment=event, usb_ssh=None, first_removal=None)
        elif state == 'not attached' and self.pending is not None:
            if self.pending['usb_ssh'] is None:
                raise ValueError('USB removed before SSH was verified; increase connected time')
            if self.pending['first_removal'] is None:
                self.pending['first_removal'] = event
            # Allow PMIC and controller observations to settle independently.
            # Include late removal IRQs in this cycle rather than the next one.
            if event['start'] - self.pending['first_removal']['start'] < 1:
                return
            supply = event['power']['supplies']['axp20x-usb']
            if supply['present'] or supply['online']:
                return
            counts = event['irqs']['counts']
            baseline = self.baseline['irqs']['counts']
            self.completed.append(dict(cycle=len(self.completed) + 1,
                                       baseline=self.baseline, **self.pending, removal=event,
                                       irq_delta={key: counts[key] - baseline[key] for key in counts}))
            self.pending = None
            self.baseline = event
        elif state == 'configured' and self.pending and self.pending['first_removal']:
            raise ValueError('Reconnected before the removal observation settled')


def usb_check(config, boot):
    started = time.monotonic()
    with device(config, 'usb') as client:
        lines = run(client, 'printf "%s\\n" "$SSH_CONNECTION"; '
                    'cat /proc/sys/kernel/random/boot_id /sys/class/udc/*/state',
                    display=False, timeout=10).decode().splitlines()
    if (len(lines) != 3 or len(lines[0].split()) != 4 or
            lines[0].split()[2] != config.get('GAMESHELL_USB_IP', '192.168.10.1') or
            lines[1] != boot or lines[2] != 'configured'):
        raise ValueError('USB SSH endpoint/boot/state verification failed')
    return dict(host_start=started, host_end=time.monotonic(),
                note='Includes Mac SSH, forwarding, routing and device SSH; not detection latency.')


def observe(config, cycles, seconds, directory, emit):
    tracker = Cycles()
    observed = 0
    ready = False
    stopped = False
    trace = []
    data = b''
    with WifiObserver(config, emit) as observer:
        client = observer.client
        # Refuse collision before creating private files or owning a unit.
        state = run(client, 'systemctl show ' + UNIT + ' -p LoadState --value', display=False).decode().strip()
        if state != 'not-found':
            raise ValueError('USB detection unit already exists; inspect before starting another test')
        remote_dir = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-usb-detection.XXXXXXXX',
                         display=False).decode().strip()
        if not re.fullmatch(r'/tmp/gameshellneo-usb-detection\.[A-Za-z0-9]+', remote_dir):
            raise ValueError('Invalid temporary capture path')
        script = remote_dir + '/recorder.py'
        capture = remote_dir + '/trace.jsonl'
        emit('device_capture', directory=remote_dir)
        with client.open_sftp() as sftp:
            upload(sftp, ROOT / 'tools/record-usb-detection.py', script)
            # Preserve SSH-account ownership when systemd opens the existing
            # file, allowing bounded incremental SFTP reads without sudo cat.
            with sftp.open(capture, 'wx'):
                pass
            sftp.chmod(capture, 0o600)
        started = False
        try:
            command = ['sudo', '-n', 'systemd-run', '--quiet', '--collect', '--unit=' + UNIT,
                       '--property=RuntimeMaxSec=' + str(seconds + 15), '--property=TimeoutStopSec=5',
                       '--property=UMask=0077', '--property=StandardOutput=file:' + capture,
                       '--property=StandardError=journal', '/usr/bin/python3', '-B', '-u', script,
                       '--seconds', str(seconds)]
            run(client, shlex.join(command), display=False)
            started = True
            deadline = time.monotonic() + seconds + 10
            last_heartbeat = time.monotonic()
            last_progress = time.monotonic()
            while time.monotonic() < deadline:
                chunk = observer.trace_since(capture, len(data))
                if chunk:
                    data += chunk
                    last_progress = time.monotonic()
                (directory / 'device-trace.jsonl').write_bytes(data)
                trace = trace_records(data)
                for event in trace[observed:]:
                    tracker.consume(event)
                observed = len(trace)
                if (not trace or trace[-1]['event'] != 'complete') and time.monotonic() - last_progress > 3:
                    active = observer.query('systemctl show ' + UNIT + ' -p ActiveState --value').decode().strip()
                    if active not in ('active', 'activating'):
                        # It may have completed between the read and unit query.
                        while chunk := observer.trace_since(capture, len(data)):
                            data += chunk
                        (directory / 'device-trace.jsonl').write_bytes(data)
                        trace = trace_records(data, final=True)
                        for event in trace[observed:]:
                            tracker.consume(event)
                        observed = len(trace)
                if tracker.baseline and not ready:
                    ready = True
                    emit('ready', cycles=cycles, boot_id=tracker.baseline['boot_id'],
                         instructions=('Plug in for 20 seconds, unplug for 10 seconds; repeat, ending unplugged.'
                                       if cycles else 'Smoke capture; leave USB unplugged.'))
                if tracker.pending and tracker.pending['usb_ssh'] is None:
                    try:
                        result = usb_check(config, tracker.baseline['boot_id'])
                    except (OSError, RuntimeError, paramiko.SSHException) as error:
                        emit('usb_ssh_not_ready', error=str(error))
                    else:
                        tracker.pending['usb_ssh'] = result
                        emit('usb_verified', cycle=len(tracker.completed) + 1, **result)
                if cycles and len(tracker.completed) >= cycles:
                    break
                if trace and trace[-1]['event'] == 'complete':
                    if cycles:
                        raise ValueError('Recorder ended before all requested cycles')
                    break
                if time.monotonic() - last_heartbeat >= 20:
                    emit('waiting', verified_cycles=len(tracker.completed))
                    last_heartbeat = time.monotonic()
                time.sleep(0.5)
            else:
                raise ValueError('USB capture timed out')
        finally:
            if started:
                # Retry a stale Wi-Fi transport; if recovery also fails, leave
                # the bounded unit and printed directory intact.
                try:
                    loaded = observer.query('systemctl show ' + UNIT + ' -p LoadState --value').decode().strip()
                    if loaded != 'not-found':
                        observer.query('sudo -n systemctl stop ' + UNIT)
                    while chunk := observer.trace_since(capture, len(data)):
                        data += chunk
                    (directory / 'device-trace.jsonl').write_bytes(data)
                    trace = trace_records(data, final=True)
                    stopped = True
                    emit('recorder_stopped', metrics=trace[-1])
                except (OSError, RuntimeError, ValueError, paramiko.SSHException) as error:
                    emit('cleanup_pending', directory=remote_dir, error=str(error))
                    try:
                        journal = observer.query('sudo -n journalctl -u ' + UNIT + ' -n 60 --no-pager')
                        (directory / 'recorder-journal.txt').write_bytes(journal)
                    except (OSError, RuntimeError, paramiko.SSHException):
                        pass
            if stopped:
                run(observer.client, shlex.join(['sudo', '-n', 'rm', '--', capture, script]), display=False)
                run(observer.client, shlex.join(['rmdir', '--', remote_dir]), display=False)
        if not stopped or not ready or (cycles and len(tracker.completed) != cycles):
            raise ValueError('Incomplete capture, cycles or cleanup')
        return dict(cycles=tracker.completed, recorder=trace[-1],
                    timing_qualified=False, power_measurement=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=os.environ.get('NEO_USB_CYCLES', '4'))
    parser.add_argument('--seconds', type=int, default=os.environ.get('NEO_USB_DETECT_SECONDS', '600'))
    args = parser.parse_args()
    if not 0 <= args.cycles <= 4 or not 5 <= args.seconds <= 900:
        parser.error('cycles must be 0..4 and seconds 5..900; cycles=0 is an unplugged smoke capture')
    os.umask(0o077)
    config = load_env()
    directory = evidence_directory()
    print('Private USB detection evidence:', directory, flush=True)
    summary = dict(passed=False, requested_cycles=args.cycles)
    with ExitStack() as stack:
        lock = stack.enter_context((LOCAL / 'usb-reconnects.lock').open('a'))
        output = stack.enter_context((directory / 'usb-detection.jsonl').open('w'))

        def emit(event, **values):
            line = json.dumps(dict(event=event, utc=datetime.now(timezone.utc).isoformat(), **values))
            output.write(line + '\n')
            output.flush()
            print(line, flush=True)

        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            summary.update(observe(config, args.cycles, args.seconds, directory, emit), passed=True)
        except (OSError, RuntimeError, ValueError, KeyError, paramiko.SSHException, KeyboardInterrupt) as error:
            summary['error'] = str(error) or type(error).__name__
            emit('failed', error=summary['error'])
        finally:
            (directory / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
