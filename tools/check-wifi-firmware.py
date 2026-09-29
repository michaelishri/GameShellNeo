#!/usr/bin/env python3
"""Fetch the pinned A0 candidate and run a bounded USB-only trial with rollback."""
import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time
import urllib.request

import paramiko
from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run, upload

PHASES = ['original_before', 'candidate_initial',
          *['candidate_reconnect_' + str(index) for index in range(1, 5)], 'original_restored']


def verify_wifi(config, boot, address):
    """Use the independently pinned Wi-Fi route, never the USB control socket."""
    with device(dict(config, GAMESHELL_IP=address), 'wifi') as wifi:
        output = run(wifi, 'cat /proc/sys/kernel/random/boot_id; printf "%s\\n" "$SSH_CONNECTION"',
                     display=False, timeout=10).decode().splitlines()
    if (len(output) != 2 or output[0] != boot or len(output[1].split()) != 4 or
            output[1].split()[2] != address):
        raise ValueError('Wi-Fi SSH reached an unexpected boot or endpoint')


class ConnectedCapture:
    """Handle split JSON lines while the device waits for independent Wi-Fi proof."""
    def __init__(self, output, evidence, client, config, boot, script):
        self.output, self.evidence, self.client = output, evidence, client
        self.config, self.boot, self.script = config, boot, script
        self.pending = b''
        self.phases = []

    def flush(self):
        self.output.flush()

    def write(self, data):
        self.output.write(data)
        self.output.flush()
        self.pending += data
        while b'\n' in self.pending:
            line, self.pending = self.pending.split(b'\n', 1)
            if not line.startswith(b'{'):
                continue  # Preserve tracebacks in the capture without treating them as events.
            record = json.loads(line)
            if record.get('event') != 'wifi_ready':
                continue
            phase, token = record['phase'], record['token']
            address = str(ipaddress.IPv4Address(record['address']))
            if (len(self.phases) >= len(PHASES) or phase != PHASES[len(self.phases)] or
                    record['boot_id'] != self.boot or not re.fullmatch('[0-9a-f]{32}', token) or
                    address == self.config.get('GAMESHELL_USB_IP', '192.168.10.1')):
                raise ValueError('Invalid or out-of-order Wi-Fi checkpoint')
            started = time.monotonic()
            for attempt in range(3):
                try:
                    verify_wifi(self.config, self.boot, address)
                    break
                except (OSError, paramiko.SSHException):
                    if attempt == 2 or time.monotonic() - started > 45:
                        raise
                    time.sleep(1)
            run(self.client, shlex.join(['sudo', '-n', '/usr/bin/python3', '-B', self.script,
                                        '--ack', token]), display=False, timeout=10)
            self.phases.append(phase)
            self.evidence.write(json.dumps(dict(phase=phase, boot_id=self.boot, address=address,
                                                passed=True, duration_seconds=time.monotonic() - started)) + '\n')
            self.evidence.flush()
            print('Independent Wi-Fi SSH verified:', phase, flush=True)


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connected', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    config = load_env()
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
        with device(config, 'usb') as client:
            if run(client, 'systemctl show gameshellneo-firmware-trial -p LoadState --value',
                   display=False).decode().strip() != 'not-found':
                raise ValueError('An earlier firmware-trial unit still exists; verify its recovery first')
            boot = run(client, 'cat /proc/sys/kernel/random/boot_id', display=False).decode().strip()
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
                       '--property=RuntimeMaxSec=' + str(seconds + (1500 if args.connected else 210)),
                       '--property=TimeoutStopSec=180',
                       '--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore',
                       '/usr/bin/python3', '-B', '-u', script,
                       '--candidate', remote_dir + '/candidate.bin',
                       '--metadata', remote_dir + '/candidate.json', '--seconds', str(seconds)]
            if args.connected:
                command.append('--connected')
            print('Retain helper on failure:', remote_dir, flush=True)
            path = capture / 'firmware-trial.jsonl'
            sink = None
            try:
                with path.open('wb') as output, (capture / 'wifi-ssh.jsonl').open('w') as evidence:
                    if args.connected:
                        sink = ConnectedCapture(output, evidence, client, config, boot, script)
                    run(client, shlex.join(command), output=sink or output, timeout=240)
            except BaseException:
                # Do not leave a live firmware trial waiting for a failed host acknowledgement.
                try:
                    loaded = run(client, 'systemctl show gameshellneo-firmware-trial -p LoadState --value',
                                 display=False).decode().strip()
                    if loaded != 'not-found':
                        run(client, 'sudo -n systemctl stop gameshellneo-firmware-trial',
                            display=False, timeout=210)
                    run(client, shlex.join(['sudo', '-n', '/usr/bin/python3', '-B', script, '--restore']),
                        display=False, timeout=210)
                    print('Independent original-firmware recovery hook completed.', flush=True)
                except (OSError, RuntimeError, paramiko.SSHException):
                    print('Recovery could not be verified; retain the helper and recovery record.', flush=True)
                raise
            records = [json.loads(line) for line in path.read_text().splitlines()]
            if not records or records[-1].get('event') != 'complete' or not records[-1].get('passed'):
                raise ValueError('Incomplete firmware trial; verify original-firmware restoration')
            if args.connected and (sink.phases != PHASES or not records[-1].get('connected')):
                raise ValueError('Incomplete independent Wi-Fi checkpoint evidence')
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
