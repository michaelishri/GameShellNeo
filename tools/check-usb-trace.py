#!/usr/bin/env python3
"""Passive ten-second USB metadata sample, or read-only collection of its exact run."""
import argparse
import json
import os
import re
import shlex
import uuid

from private_config import load_env
from remote import ROOT, device, evidence_directory, run, upload
from usb_trace import run_id


def collect(config, token, route):
    token = run_id(token)
    with device(config, route) as client:
        result = json.loads(run(client, 'sudo -n cat /var/lib/gameshellneo/usb-traces/'+token+'/result.json',
                                display=False, timeout=20))
    if result.get('run_id') != token:
        raise ValueError('USB trace result belongs to another run')
    return result


def service(directory, token):
    run_id(token)
    if not re.fullmatch(r'/tmp/gameshellneo-usb-trace\.[A-Za-z0-9]+', directory):
        raise ValueError('Unexpected USB trace helper path')
    script = directory+'/usb_trace.py'
    return ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--collect',
            '--unit=gameshellneo-usb-trace-sample', '--property=RuntimeMaxSec=60',
            '--property=TimeoutStopSec=20', '--property=UMask=0077',
            '--property=ExecStopPost=/usr/bin/python3 -B '+script+' --restore --run-id '+token,
            '/usr/bin/python3', '-B', script, '--sample', '--run-id', token]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect', action='store_true')
    args = parser.parse_args()
    token = run_id(os.environ.get('NEO_PM_RUN', '')) if args.collect else uuid.uuid4().hex
    route = os.environ.get('NEO_SLEEP_COLLECT_ROUTE', 'usb') if args.collect else 'usb'
    if route not in ('usb', 'wifi'):
        raise ValueError('Use ROUTE=usb or wifi')
    config = load_env()
    capture = evidence_directory()
    receipt = dict(run_id=token, route=route)
    (capture/'run.json').write_text(json.dumps(receipt)+'\n')
    print('Private USB trace evidence:', capture, '; run:', token, flush=True)
    if not args.collect:
        with device(config, 'usb') as client:
            directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-usb-trace.XXXXXXXX',
                            display=False).decode().strip()
            command = service(directory, token)
            receipt['helper'] = directory
            (capture/'run.json').write_text(json.dumps(receipt)+'\n')
            with client.open_sftp() as sftp:
                for name in ('usb_trace', 'wifi_trace', 'keypad_pm'):
                    upload(sftp, ROOT/'tools'/(name+'.py'), directory+'/'+name+'.py')
            try:
                run(client, shlex.join(command), display=False, timeout=90)
            except Exception as error:
                (capture/'submission-error.txt').write_text(type(error).__name__+': '+str(error)+'\n')
                print('Submission/worker failed; collecting the original result, without resubmitting.', flush=True)
    result = collect(config, token, route)
    (capture/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    if args.collect:
        print('Original USB result collected; no trace or recovery was started.')
        return
    if result.get('passed') is not True or result.get('restored') is not True or result.get('trace_lost') is not False:
        raise ValueError('Passive sample failed; preserve the saved result and ownership')
    for path in ('usb', 'wifi'):
        with device(config, path) as client:
            boot = run(client, 'cat /proc/sys/kernel/random/boot_id', display=False).decode().strip()
        if boot != result['before']['boot_id']:
            raise ValueError('Boot changed while proving SSH routes')
        receipt[path+'_ssh_verified'] = True
        (capture/'run.json').write_text(json.dumps(receipt)+'\n')
    print('Passive sample passed; trace/logging restored, PM state unchanged, both SSH routes verified.')
    print('This checks the recorder while awake; it does not qualify notification delivery or USB resume.')


if __name__ == '__main__':
    main()
