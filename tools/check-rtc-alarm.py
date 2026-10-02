#!/usr/bin/env python3
"""Inspect or test an owned RTC deadline while awake; no sleep or RTC time changes."""
import argparse
import json
import shlex
import uuid
from private_config import load_env
from remote import ROOT, device, evidence_directory, run, upload


def result_for(data, run_id):
    # ExecStopPost can emit its own restoration JSON after the test's result.
    rows = [json.loads(line) for line in data.splitlines() if line.startswith(b'{')]
    matching = [row for row in rows if row.get('run_id') == run_id]
    if len(matching) != 1:
        raise ValueError('Missing or ambiguous exact-run RTC result')
    return matching[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    capture = evidence_directory()
    print('Private rtc-alarm evidence:', capture, flush=True)
    with device(load_env(), 'usb') as client:
        directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-rtc-alarm.XXXXXXXX', display=False).decode().strip()
        import re
        if not re.fullmatch(r'/tmp/gameshellneo-rtc-alarm\.[A-Za-z0-9]+', directory):
            raise ValueError('Unexpected helper path')
        with client.open_sftp() as sftp:
            for name in ('rtc_alarm', 'keypad_pm'):
                upload(sftp, ROOT / 'tools' / (name + '.py'), directory + '/' + name + '.py')
        command = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                   '--unit=gameshellneo-rtc-alarm-smoke', '--property=RuntimeMaxSec=25',
                   '--property=TimeoutStopSec=10', '--property=UMask=0077']
        if args.smoke:
            command += ['--property=ExecStopPost=/usr/bin/python3 -B ' + directory + '/rtc_alarm.py --restore']
        command += ['/usr/bin/python3', '-B', directory + '/rtc_alarm.py', '--smoke' if args.smoke else '--restore' if args.restore else '--inspect']
        if args.smoke:
            run_id = uuid.uuid4().hex
            command += ['--run-id', run_id]
            (capture/'run.json').write_text(json.dumps(dict(run_id=run_id, helper=directory))+'\n')
        with (capture/'result.jsonl').open('wb') as output:
            data = run(client, shlex.join(command), output=output, display=False, timeout=40)
        result = result_for(data, run_id) if args.smoke else json.loads(data.splitlines()[-1])
        if args.smoke and (result.get('passed') is not True or result.get('restored') is not True):
            raise ValueError('Awake ownership check failed')
        print('Awake RTC alarm delivery and restoration passed.' if args.smoke else
              'RTC alarm restored.' if args.restore else 'RTC identity and alarm inspected.')


if __name__ == '__main__':
    main()
