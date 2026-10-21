#!/usr/bin/env python3
"""Collect a bounded awake charging baseline through USB, with a remote deadline."""
import fcntl
import hashlib
import json
import os
import shlex

from private_config import load_env
from remote import ROOT, LOCAL, device, evidence_directory, run


def payload():
    dependency = (ROOT/'tools/charge_inventory.py').read_text()
    main = (ROOT/'tools/sample-charge.py').read_text()
    source = ('import sys, types\n'
              'helper = types.ModuleType("charge_inventory")\n'
              'exec(' + repr(dependency) + ', helper.__dict__)\n'
              'sys.modules["charge_inventory"] = helper\n' + main)
    return source.encode(), dict(charge_inventory=hashlib.sha256(dependency.encode()).hexdigest(),
                                 sample_charge=hashlib.sha256(main.encode()).hexdigest())


def main():
    os.umask(0o077)
    seconds = int(os.environ.get('NEO_CHARGE_SECONDS', '120'))
    if not 60 <= seconds <= 600 or seconds % 10:
        raise ValueError('SECONDS must be a multiple of ten in 60..600')
    lock_bytes = (ROOT/'build/sources.lock.json').read_bytes()
    lock = json.loads(lock_bytes)
    if lock['linux']['tag'] != 'v6.18.54':
        raise ValueError('Re-audit charge inventory before changing Linux version')
    source, sources = payload()
    arguments = ['sudo', '-n', '/usr/bin/timeout', '--signal=TERM', '--kill-after=5', str(seconds+20),
                 '/usr/bin/python3', '-B', '-', '--kernel',
                 lock['linux']['tag'][1:]+lock['linux']['localversion'],
                 '--image', lock['image_version'], '--seconds', str(seconds)]
    LOCAL.mkdir(exist_ok=True)
    with (LOCAL/'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        capture = evidence_directory()
        print('Private charging baseline:', capture, flush=True)
        (capture/'provenance.json').write_text(json.dumps(dict(sources=sources, seconds=seconds,
            payload_sha256=hashlib.sha256(source).hexdigest(), route='usb',
            sources_lock_sha256=hashlib.sha256(lock_bytes).hexdigest()), indent=2)+'\n')
        with device(load_env(), 'usb') as client, (capture/'charge-baseline.jsonl').open('wb') as output:
            data = run(client, shlex.join(arguments), input_data=source,
                       output=output, display=False, timeout=40)
        events = [json.loads(line) for line in data.splitlines()]
        result = events[-1]
        if result.get('event') != 'completed' or result.get('passed') is not True:
            raise ValueError('Charging baseline did not finish; original output retained')
        print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
