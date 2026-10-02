#!/usr/bin/env python3
"""Inspect PEK or verify exclusive ownership while awake; no PM or key injection."""
import argparse
import json
import shlex
from private_config import load_env
from remote import ROOT, device, evidence_directory, run, upload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    capture = evidence_directory()
    print('Private power-key evidence:', capture, flush=True)
    with device(load_env(), 'usb') as client:
        directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-power-key.XXXXXXXX', display=False).decode().strip()
        import re
        if not re.fullmatch(r'/tmp/gameshellneo-power-key\.[A-Za-z0-9]+', directory):
            raise ValueError('Unexpected helper path')
        with client.open_sftp() as sftp:
            for name in ('power_key', 'keypad_pm'):
                upload(sftp, ROOT / 'tools' / (name + '.py'), directory + '/' + name + '.py')
        command = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                   '--unit=gameshellneo-power-key-smoke', '--property=RuntimeMaxSec=25',
                   '--property=TimeoutStopSec=10', '--property=UMask=0077']
        if args.smoke:
            command += ['/usr/bin/systemd-inhibit', '--what=handle-power-key:sleep:idle', '--mode=block',
                        '--who=GameShellNeo PM diagnostic', '--why=Awake power-key ownership check']
        command += ['/usr/bin/python3', '-B', directory + '/power_key.py', '--smoke' if args.smoke else '--inspect']
        with (capture/'result.jsonl').open('wb') as output:
            data = run(client, shlex.join(command), output=output, display=False, timeout=40)
        result = json.loads(data.splitlines()[-1])
        if args.smoke and (result.get('passed') is not True or result.get('handed_back') is not True):
            raise ValueError('Awake ownership check failed')
        print('Awake power-key ownership passed.' if args.smoke else 'Power-key identity inspected.')


if __name__ == '__main__':
    main()
