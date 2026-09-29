#!/usr/bin/env python3
"""Record cable events on the board and verify USB SSH after each return."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
import re
import shlex
import sys
import time

import paramiko
from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run

UNIT = 'gameshellneo-usb-reconnects'


def stamp():
    return datetime.now(timezone.utc).isoformat()


def packet(client, config, remote_dir, directory):
    command = ('printf "%s\\n" "$SSH_CONNECTION"; '
               'cat /proc/sys/kernel/random/boot_id /sys/class/udc/*/state; '
               'systemctl is-active ' + UNIT + '; sudo -n cat ' +
               shlex.quote(remote_dir + '/states.jsonl'))
    lines = run(client, command, display=False, timeout=10).decode().splitlines()
    if len(lines) < 5:
        raise ValueError('Incomplete device capture')
    connection = lines[0].split()
    if len(connection) != 4 or connection[2] != config.get('GAMESHELL_USB_IP', '192.168.10.1'):
        raise ValueError('SSH did not terminate at the expected USB address')
    if lines[3] != 'active':
        raise ValueError('Device recorder is no longer active')
    trace = [json.loads(line) for line in lines[4:]]
    if any(event['boot_id'] != lines[1] for event in trace):
        raise ValueError('USB recorder belongs to a different boot')
    if [event['sequence'] for event in trace] != list(range(len(trace))):
        raise ValueError('USB state record is incomplete or out of order')
    (directory / 'device-states.jsonl').write_text('\n'.join(lines[4:]) + '\n')
    return lines[1], lines[2], trace


def cycle_complete(events, state):
    """Count only one observed removal followed by the current configuration."""
    removals = [event for event in events if event['state'] == 'not attached']
    if len(removals) > 1:
        raise RuntimeError('Multiple removals occurred before USB SSH could be verified; '
                           'leave more time between cycles')
    if removals and state == 'configured' and events[-1]['state'] == 'configured':
        if events[-1]['sequence'] <= removals[0]['sequence']:
            raise ValueError('No configured state after removal')
        return True
    return False


def observe(config, cycles, timeout, record, directory, sample_ms=250):
    started = False
    with device(config, 'usb') as client:
        remote_dir = run(client, 'sudo -n mktemp -d /run/gameshellneo-usb-reconnects.XXXXXXXX',
                         display=False, timeout=10).decode().strip()
        if not re.fullmatch(r'/run/gameshellneo-usb-reconnects\.[A-Za-z0-9]+', remote_dir):
            raise ValueError('Unexpected device capture directory')
        record('device_capture', directory=remote_dir)
        arguments = ['sudo', '-n', 'systemd-run', '--quiet', '--collect', '--unit=' + UNIT,
                     '--property=RuntimeMaxSec=' + str(timeout + 60), '--property=UMask=0077',
                     '--property=StandardOutput=file:' + remote_dir + '/states.jsonl',
                     '--property=StandardError=journal', '/usr/bin/python3', '-u', '-c',
                     (ROOT / 'tools/record-usb-states.py').read_text(),
                     '--sample-ms', str(sample_ms)]
        run(client, shlex.join(arguments), display=False, timeout=10)
        started = True
    try:
        time.sleep(0.5)
        with device(config, 'usb') as client:
            boot_id, state, trace = packet(client, config, remote_dir, directory)
        if state != 'configured' or trace[-1]['state'] != 'configured':
            raise ValueError('Start with USB connected and configured')
        identity = {'boot_id': boot_id,
                    'server_address': config.get('GAMESHELL_USB_IP', '192.168.10.1')}
        record('ready', requested_cycles=cycles, baseline=identity,
               sample_interval_ms=sample_ms,
               message='Baseline verified. Ready for physical USB cable cycles.')
        deadline = time.monotonic() + timeout
        completed = 0
        verified_sequence = trace[-1]['sequence']
        heartbeat = time.monotonic()
        while time.monotonic() < deadline:
            try:
                with device(config, 'usb') as client:
                    current_boot, state, trace = packet(client, config, remote_dir, directory)
            except (OSError, RuntimeError, paramiko.SSHException) as error:
                record('ssh_not_ready', error=str(error))
                time.sleep(1)
                continue
            if current_boot != boot_id:
                raise RuntimeError('Board rebooted during cable testing')
            events = [event for event in trace if event['sequence'] > verified_sequence]
            if cycle_complete(events, state):
                completed += 1
                record('verified', cycle=completed, identity=identity, device_events=events)
                verified_sequence = events[-1]['sequence']
                if completed == cycles:
                    return completed
            now = time.monotonic()
            if now - heartbeat >= 20:
                record('waiting', verified_cycles=completed, state=state)
                heartbeat = now
            time.sleep(1)
        raise RuntimeError('Timed out waiting for all requested physical reconnections')
    finally:
        if started:
            try:
                with device(config, 'usb') as client:
                    run(client, 'sudo -n systemctl stop ' + UNIT, display=False, timeout=10)
                    trace_bytes = run(client, 'sudo -n cat ' +
                                      shlex.quote(remote_dir + '/states.jsonl'),
                                      display=False, timeout=10)
                    (directory / 'device-states.jsonl').write_bytes(trace_bytes)
                    run(client, shlex.join(['sudo', '-n', 'rm', '--', remote_dir + '/states.jsonl']),
                        display=False, timeout=10)
                    run(client, shlex.join(['sudo', '-n', 'rmdir', '--', remote_dir]),
                        display=False, timeout=10)
                record('recorder_stopped')
            except (OSError, ValueError, RuntimeError, paramiko.SSHException) as error:
                record('cleanup_pending', error=str(error), directory=remote_dir,
                       message='Recorder has a bounded runtime; reconnect USB to retrieve/clean it.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cycles', type=int, default=os.environ.get('NEO_USB_CYCLES', '4'))
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--rapid', action='store_true',
                        help='Use nominal 20 ms state samples for immediate unplug/replug checks')
    args = parser.parse_args()
    if not 1 <= args.cycles <= 10 or not 30 <= args.timeout <= 3600:
        parser.error('cycles must be 1..10 and timeout must be 30..3600 seconds')
    os.umask(0o077)
    config = load_env()
    directory = evidence_directory()
    print('Private USB reconnection evidence:', directory, flush=True)
    summary = {'started_at': stamp(), 'requested_cycles': args.cycles,
               'verified_cycles': 0, 'passed': False,
               'mode': 'rapid' if args.rapid else 'standard',
               'sample_interval_ms': 20 if args.rapid else 250,
               'physical_timing_qualified': False}
    with (LOCAL / 'usb-reconnects.lock').open('a') as lock, \
            (directory / 'usb-reconnects.jsonl').open('w') as output:
        def record(event, **fields):
            entry = {'time': stamp(), 'event': event, **fields}
            line = json.dumps(entry)
            output.write(line + '\n')
            output.flush()
            print(line, flush=True)
            if event == 'verified':
                summary['verified_cycles'] = fields['cycle']

        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            observe(config, args.cycles, args.timeout, record, directory,
                    summary['sample_interval_ms'])
            summary['passed'] = True
        except (OSError, ValueError, RuntimeError, paramiko.SSHException, KeyboardInterrupt) as error:
            summary['error'] = str(error) or type(error).__name__
            record('failed', error=summary['error'])
        finally:
            summary['finished_at'] = stamp()
            (directory / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
