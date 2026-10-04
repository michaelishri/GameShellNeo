#!/usr/bin/env python3
"""Run the saved RSB delay comparison over USB under independent device recovery."""
import argparse
import fcntl
import json
import os
import re
import shlex

from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run, upload, python_command


def service_command(directory, seconds, delay):
    if (not re.fullmatch(r'/tmp/gameshellneo-rsb\.[A-Za-z0-9]+', directory) or
            not 60 <= seconds <= 300 or seconds % 30 or not 10 <= delay <= 500):
        raise ValueError('Invalid RSB comparison path, duration or delay')
    script = directory + '/compare-rsb.py'
    return ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
            '--unit=gameshellneo-rsb-comparison', '--property=RuntimeMaxSec=' + str(3 * (seconds + 15) + 90),
            '--property=TimeoutStopSec=10',
            '--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore',
            '/usr/bin/python3', '-B', '-u', script, '--lock', directory + '/sources.lock.json',
            '--seconds', str(seconds), '--delay-ms', str(delay)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    seconds = int(os.environ.get('NEO_RSB_SECONDS', '120'))
    delay = int(os.environ.get('NEO_RSB_DELAY_MS', '100'))
    service_command('/tmp/gameshellneo-rsb.validation', seconds, delay)
    capture = evidence_directory()
    print('Private RSB evidence:', capture, flush=True)
    with (LOCAL / 'rsb-comparison.lock').open('a') as lock:
        if not args.restore:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with device(load_env(), 'usb') as client:
            loaded = run(client, 'systemctl show gameshellneo-rsb-comparison -p LoadState --value',
                         display=False).decode().strip()
            if args.restore:
                if loaded != 'not-found':
                    run(client, 'sudo -n systemctl stop gameshellneo-rsb-comparison', timeout=30)
                with (capture / 'restore.txt').open('wb') as output:
                    run(client, **python_command((ROOT / 'tools/compare-rsb.py').read_text(), '--restore'),
                        output=output, timeout=30)
                print('RSB comparison stopped and owned delay restored.')
                return
            if loaded != 'not-found':
                raise ValueError('Earlier RSB comparison unit exists; verify recovery first')
            directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-rsb.XXXXXXXX',
                            display=False).decode().strip()
            command = service_command(directory, seconds, delay)
            files = [(ROOT / 'tools/compare-rsb.py', 'compare-rsb.py'),
                     (ROOT / 'tools/profile-power.py', 'profile-power.py'),
                     (ROOT / 'build/sources.lock.json', 'sources.lock.json')]
            with client.open_sftp() as sftp:
                for source, name in files:
                    upload(sftp, source, directory + '/' + name)
            (capture / 'sources.lock.json').write_bytes((ROOT / 'build/sources.lock.json').read_bytes())
            print('Helper retained on failure:', directory, flush=True)
            with (capture / 'rsb-comparison.jsonl').open('wb') as output:
                run(client, shlex.join(command), output=output, timeout=seconds + 90)
            records = [json.loads(line) for line in (capture / 'rsb-comparison.jsonl').read_text().splitlines()]
            if not records or records[-1].get('event') != 'complete' or records[-1].get('passed') is not True:
                raise ValueError('Incomplete RSB comparison; use device:rsb-restore before another test')
            with client.open_sftp() as sftp:
                for _, name in files:
                    sftp.remove(directory + '/' + name)
                sftp.rmdir(directory)


if __name__ == '__main__':
    main()
