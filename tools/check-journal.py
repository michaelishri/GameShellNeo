#!/usr/bin/env python3
"""Capture journal storage; explicitly apply policy or check ordinary log rotation."""
import argparse
import fcntl
import hashlib
import json
import os

from journal_policy import FILES, validate_continuity, validate_policy, validate_rotation
from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run, python_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--verify-rotation', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    capture = evidence_directory()
    print('Private journal evidence:', capture, flush=True)
    policy = {name: (ROOT / 'runtime' / name).read_text() for name in FILES}
    code = (ROOT / 'tools/journal_policy.py').read_text()
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    (capture / 'source.json').write_text(json.dumps(dict(policy=policy,
        helper_sha256=hashlib.sha256(code.encode()).hexdigest()), indent=2) + '\n')
    with (LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with device(load_env(), 'usb') as client:
            def collect(name, extra=()):
                data = run(client, **python_command(code, *extra),
                           display=False, timeout=180)
                (capture / name).write_bytes(data)
                return json.loads(data)
            before = collect('before.json')
            if not (args.apply or args.verify_rotation):
                print('Read-only capture saved; open journal files:', len(before['open_journals']))
                return
            if before['kernel'] != lock['linux']['tag'][1:] + lock['linux']['localversion']:
                raise ValueError('Device kernel does not match the current source lock')
            if args.apply:
                after = collect('after.json', ('--apply', json.dumps(policy), before['boot_id']))
            else:
                validate_policy(before, policy)
                if before['units']['logrotate.service']['ActiveState'] != 'inactive':
                    raise ValueError('Log rotation is not idle')
                # No --force: this runs the ordinary configured text-log rotation.
                # Never retry an uncertain service submission automatically.
                try:
                    run(client, 'sudo -n systemctl start logrotate.service', display=False, timeout=60)
                finally:
                    after = collect('after.json')
            validate_policy(after, policy)
            validate_continuity(before, after)
            if args.verify_rotation:
                validate_rotation(before, after)
            (capture / 'summary.json').write_text(json.dumps(dict(passed=True,
                mode='apply' if args.apply else 'verify-rotation', boot_id=after['boot_id'],
                journald_unchanged=True, kernel_journal_retained=True,
                displaced_journals_unchanged=True), indent=2) + '\n')
            print('Journal policy and continuity passed; no journal restart, move or repair performed.')


if __name__ == '__main__':
    main()
