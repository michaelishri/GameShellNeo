#!/usr/bin/env python3
"""Collect one documented, read-only AXP223 gauge/charger inventory over USB."""
import fcntl
import hashlib
import json
import os

from private_config import load_env
from remote import ROOT, LOCAL, device, evidence_directory, run, python_command


def main():
    os.umask(0o077)
    lock_path = ROOT / 'build/sources.lock.json'
    lock = json.loads(lock_path.read_text())
    if lock['linux']['tag'] != 'v6.18.54':
        raise ValueError('Re-audit the regmap inspection before changing Linux version')
    helper = ROOT / 'tools/charge_inventory.py'
    source = helper.read_bytes()
    LOCAL.mkdir(exist_ok=True)
    with (LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        capture = evidence_directory()
        print('Private charge inventory:', capture, flush=True)
        (capture / 'provenance.json').write_text(json.dumps(dict(
            helper_sha256=hashlib.sha256(source).hexdigest(),
            sources_lock_sha256=hashlib.sha256(lock_path.read_bytes()).hexdigest(),
            route='usb', linux=lock['linux']['tag']), indent=2) + '\n')
        with device(load_env(), 'usb') as client, (capture / 'inventory.json').open('wb') as output:
            data = run(client, **python_command(source.decode(), '--kernel',
                lock['linux']['tag'][1:] + lock['linux']['localversion'],
                '--image', lock['image_version']), output=output, display=False, timeout=40)
        result = json.loads(data)
        if result.get('completed') is not True or result.get('kind') != 'axp223-charge-inventory':
            raise ValueError('Incomplete charge inventory; original output retained')
        print(json.dumps(dict(boot_id=result['before']['boot_id'],
                              assessment=result['assessment'], limits=result['limits']), indent=2))


if __name__ == '__main__':
    main()
