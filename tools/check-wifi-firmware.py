#!/usr/bin/env python3
"""Fetch the pinned A0 candidate and run a bounded USB-only trial with rollback."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import urllib.request

import paramiko
from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run, upload


def fetch(path, url, expected):
    if not path.exists():
        with urllib.request.urlopen(url, timeout=45) as response:
            data = response.read(1024 * 1024)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Downloaded firmware candidate/license hash mismatch')
        path.write_bytes(data)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('Cached firmware candidate/license hash mismatch')


def main():
    os.umask(0o077)
    seconds = int(os.environ.get('NEO_PROFILE_SECONDS', '120'))
    if not 60 <= seconds <= 300 or seconds % 10:
        raise ValueError('SECONDS must be a multiple of ten in 60..300')
    metadata_path = ROOT / 'build/wifi-firmware-candidate.json'
    metadata = json.loads(metadata_path.read_text())
    directory = LOCAL / 'firmware-candidate'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        candidate = directory / 'brcmfmac43430a0-sdio.bin'
        license_path = directory / 'LICENCE.broadcom_bcm43xx'
        fetch(candidate, metadata['url'], metadata['sha256'])
        fetch(license_path, metadata['license_url'], metadata['license_sha256'])
        capture = evidence_directory()
        (capture / 'candidate.json').write_text(json.dumps(metadata, indent=2) + '\n')
        print('Private firmware trial:', capture, flush=True)
        with device(load_env(), 'usb') as client:
            remote_dir = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-firmware.XXXXXXXX',
                             display=False).decode().strip()
            if not re.fullmatch(r'/tmp/gameshellneo-firmware\.[A-Za-z0-9]+', remote_dir):
                raise ValueError('Unexpected firmware trial directory')
            files = [(ROOT / 'tools/test-wifi-firmware.py', 'test-wifi-firmware.py'),
                     (candidate, 'candidate.bin'), (metadata_path, 'candidate.json'),
                     (license_path, license_path.name)]
            with client.open_sftp() as sftp:
                for source, name in files:
                    upload(sftp, source, remote_dir + '/' + name)
            script = remote_dir + '/test-wifi-firmware.py'
            command = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                       '--unit=gameshellneo-firmware-trial',
                       '--property=RuntimeMaxSec=' + str(seconds + 210),
                       '--property=TimeoutStopSec=180',
                       '--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore',
                       '/usr/bin/python3', '-B', '-u', script,
                       '--candidate', remote_dir + '/candidate.bin',
                       '--metadata', remote_dir + '/candidate.json', '--seconds', str(seconds)]
            print('Retain helper on failure:', remote_dir, flush=True)
            path = capture / 'firmware-trial.jsonl'
            with path.open('wb') as output:
                run(client, shlex.join(command), output=output, timeout=240)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            if not records or records[-1].get('event') != 'complete' or not records[-1].get('passed'):
                raise ValueError('Incomplete firmware trial; verify original-firmware restoration')
            with client.open_sftp() as sftp:
                for _, name in files:
                    sftp.remove(remote_dir + '/' + name)
                sftp.rmdir(remote_dir)
            print('Original firmware restored; candidate remains unqualified for production.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, paramiko.SSHException) as error:
        print('Firmware trial failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
