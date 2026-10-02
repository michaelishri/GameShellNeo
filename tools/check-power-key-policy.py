#!/usr/bin/env python3
"""Inspect or qualify boot-local power-key suppression awake; no PM or key input."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import uuid

from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run, upload


def validate_result(value, token, boot):
    if (value.get('run_id') != token or value.get('passed') is not True or
            value.get('restored') is not True or value.get('worker_returncode') != -9 or
            value.get('policy_owner_retained') is not False or value.get('dropin_retained') is not False):
        raise ValueError('Awake policy-worker death/restoration check failed')
    if value['before']['boot_id'] != boot or value['before'] != value['after']:
        raise ValueError('Policy test changed boot or baseline state')
    held = value['survived_worker_death']
    if (not held['owned'] or not held['dropin'] or
            held['logind'] != value['before']['logind'] or
            held['config'] != value['before']['config'] or
            held['policy'] != value['before']['policy'] |
                {'HandlePowerKey': 'ignore', 'HandlePowerKeyLongPress': 'ignore'}):
        raise ValueError('Ignore policy did not survive worker death')
    key = value['power_key']
    if key.get('events') or not all(key.get(k) is True for k in
            ('handed_back', 'logical_release_verified', 'descriptor_closed')):
        raise ValueError('Untouched power-key ownership/handoff failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--collect', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    config, capture = load_env(), evidence_directory()
    print('Private power-policy evidence:', capture, flush=True)
    with (LOCAL/'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with device(config, 'usb') as client:
            if args.collect:
                token = os.environ.get('NEO_POLICY_RUN', '')
                if not re.fullmatch('[a-f0-9]{32}', token):
                    raise ValueError('Supply the original 32-character RUN ID')
                data = run(client, shlex.join(['sudo', '-n', 'cat',
                    '/var/lib/gameshellneo/power-policy-tests/'+token+'/result.json']), display=False)
                (capture/'result.json').write_bytes(data)
                if json.loads(data).get('run_id') != token:
                    raise ValueError('Collected result belongs to another diagnostic run')
                print('Collected original result; inspect any retained owner before further tests.')
                return
            directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-power-policy.XXXXXXXX', display=False).decode().strip()
            if not re.fullmatch(r'/tmp/gameshellneo-power-policy\.[A-Za-z0-9]+', directory):
                raise ValueError('Unexpected helper directory')
            hashes = {}
            with client.open_sftp() as sftp:
                for name in ('power_key_policy', 'power_key', 'keypad_pm'):
                    path = ROOT/'tools'/(name+'.py')
                    hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
                    upload(sftp, path, directory+'/'+name+'.py')
            (capture/'source.json').write_text(json.dumps(hashes, indent=2)+'\n')
            script = directory+'/power_key_policy.py'
            before = json.loads(run(client, shlex.join(['sudo', '-n', 'python3', '-B', script, '--inspect']), display=False))
            (capture/'before.json').write_text(json.dumps(before, indent=2)+'\n')
            if not args.smoke:
                print('Read-only effective logind policy and ownership saved.')
                return
            lock = json.loads((ROOT/'build/sources.lock.json').read_text())
            if before['kernel'] != lock['linux']['tag'][1:]+lock['linux']['localversion']:
                raise ValueError('Running kernel differs from the current diagnostic source lock')
            token = uuid.uuid4().hex
            (capture/'run.json').write_text(json.dumps(dict(run_id=token, helper=directory))+'\n')
            print('Power-policy run:', token, flush=True)
            command = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                '--unit=gameshellneo-power-policy-smoke', '--property=RuntimeMaxSec=75',
                '--property=TimeoutStopSec=10', '--property=UMask=0077',
                '/usr/bin/systemd-inhibit', '--what=handle-power-key:sleep:idle', '--mode=block',
                '--who=GameShellNeo PM diagnostic', '--why=Awake policy ownership qualification',
                '/usr/bin/python3', '-B', script, '--smoke', '--run-id', token]
            # No ExecStopPost restores poweroff after uncertain ownership. The
            # boot-local ignore policy intentionally survives cgroup destruction.
            try:
                with (capture/'transcript.log').open('wb') as output:
                    run(client, shlex.join(command), output=output, display=False, timeout=90)
            except BaseException as error:
                (capture/'submission-error.txt').write_text(type(error).__name__+': '+str(error)+'\n')
                raise
            finally:
                data = run(client, shlex.join(['sudo', '-n', 'cat',
                    '/var/lib/gameshellneo/power-policy-tests/'+token+'/result.json']), display=False)
                (capture/'result.json').write_bytes(data)
            validate_result(json.loads(data), token, before['boot_id'])
            print('Awake policy survived worker SIGKILL; untouched key and original policy restored.')


if __name__ == '__main__':
    main()
