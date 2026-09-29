#!/usr/bin/env python3
"""Run saved USB count/error diagnostics under a device-side recovery service."""
import argparse
import json
import os
import re
import shlex

from private_config import load_env
from remote import ROOT, device, evidence_directory, run, upload


def service_command(script, mode, seconds, errors):
    if not re.fullmatch(r'/tmp/gameshellneo-usb-diag\.[A-Za-z0-9]+/test-usb-diagnostics.py', script):
        raise ValueError('Unexpected device helper path')
    if mode not in ('count', 'errors') or not 30 <= seconds <= 300 or not 1 <= errors <= 4:
        raise ValueError('Expected count/errors mode, SECONDS=30..300 and ERRORS=1..4')
    return ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
            '--unit=gameshellneo-usb-diagnostics', '--property=RuntimeMaxSec=' + str(seconds + 30),
            '--property=TimeoutStopSec=5',
            '--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore',
            '/usr/bin/python3', '-B', '-u', script, '--mode', mode,
            '--seconds', str(seconds), '--errors', str(errors)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('count', 'errors'), default='count')
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    if not args.restore:
        seconds = int(os.environ.get('NEO_USB_DIAG_SECONDS', '60'))
        errors = int(os.environ.get('NEO_USB_DIAG_ERRORS', '1'))
        service_command('/tmp/gameshellneo-usb-diag.validation/test-usb-diagnostics.py', args.mode, seconds, errors)
    route = os.environ.get('NEO_ROUTE', 'usb')
    capture = evidence_directory()
    with device(load_env(), route) as client:
        if args.restore:
            loaded = run(client, 'systemctl show gameshellneo-usb-diagnostics -p LoadState --value',
                         display=False, timeout=10).decode().strip()
            if loaded != 'not-found':
                run(client, 'sudo -n systemctl stop gameshellneo-usb-diagnostics', timeout=15)
            command = ['sudo', '-n', '/usr/bin/python3', '-B', '-c',
                       (ROOT / 'tools/test-usb-diagnostics.py').read_text(), '--restore']
            with (capture / 'restore.txt').open('wb') as output:
                run(client, shlex.join(command), output=output, timeout=15)
            print('USB diagnostic test stopped; any owned controls restored.')
            return
        directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-usb-diag.XXXXXXXX',
                        display=False).decode().strip()
        script = directory + '/test-usb-diagnostics.py'
        command = service_command(script, args.mode, seconds, errors)
        with client.open_sftp() as sftp:
            upload(sftp, ROOT / 'tools/test-usb-diagnostics.py', script)
        print('Private USB diagnostic evidence:', capture, flush=True)
        print('Helper retained on failure for recovery:', directory, flush=True)
        with (capture / 'usb-diagnostics.jsonl').open('wb') as output:
            run(client, shlex.join(command), output=output, timeout=seconds + 45)
        records = [json.loads(line) for line in (capture / 'usb-diagnostics.jsonl').read_text().splitlines()]
        if (not records or records[-1].get('event') != 'complete' or
                records[-1].get('passed') is not True or records[-1].get('controls_restored') is not True):
            raise ValueError('Incomplete diagnostic test; inspect the private capture and device recovery service')
        with client.open_sftp() as sftp:
            sftp.remove(script)
            sftp.rmdir(directory)


if __name__ == '__main__':
    main()
