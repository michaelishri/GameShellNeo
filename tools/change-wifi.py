#!/usr/bin/env python3
"""Apply .env Wi-Fi credentials through USB, verify Wi-Fi SSH, then commit."""
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import time

import paramiko
from private_config import load_env
from provision import wifi_config_from_key
from remote import LOCAL, ROOT, device, evidence_directory, run, upload

UNIT = 'gameshellneo-wifi-change'


def stage(sftp, directory, candidate):
    upload(sftp, ROOT / 'tools/apply-wifi.py', directory + '/apply-wifi.py')
    for name, content in [('candidate.conf', candidate),
                          ('status.json', b'{"phase":"queued","passed":false}\n')]:
        path = directory + '/' + name
        # Paramiko needs 'w' as well as 'x' to open an exclusive writable file.
        with sftp.open(path, 'wx') as output:
            output.write(content)
        sftp.chmod(path, 0o600)
        with sftp.open(path, 'rb') as source:
            if source.read() != content:
                raise ValueError('Private Wi-Fi staging readback failed')


def update_address(path, original, address):
    address = str(ipaddress.IPv4Address(address))
    # Worktrees share the owner's .env through a symlink. Replace its target,
    # not the link, so subsequent credential edits remain visible everywhere.
    path = path.resolve(strict=True)
    if path.read_bytes() != original:
        raise ValueError('.env changed during verification; device Wi-Fi is committed, update GAMESHELL_IP manually')
    lines = original.decode().splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if re.match(r'^\s*(?:export\s+)?GAMESHELL_IP\s*=', line)]
    if len(matches) > 1:
        raise ValueError('Duplicate GAMESHELL_IP assignments; update the address manually')
    if matches:
        lines[matches[0]] = 'GAMESHELL_IP=' + address + '\n'
    else:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.append('GAMESHELL_IP=' + address + '\n')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(''.join(lines).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def verify(client, boot, address):
    result = run(client, 'cat /proc/sys/kernel/random/boot_id; printf "%s\\n" "$SSH_CONNECTION"',
                 display=False, timeout=10).decode().splitlines()
    return (len(result) == 2 and result[0] == boot and len(result[1].split()) == 4 and
            result[1].split()[2] == address)


def main():
    os.umask(0o077)
    config = load_env()
    source_env = (ROOT / '.env').resolve(strict=True)
    original_env = source_env.read_bytes()
    candidate = wifi_config_from_key(config['GAMESHELL_WIFI_SSID'], config['GAMESHELL_WIFI_PSK'],
                                    config['GAMESHELL_WIFI_COUNTRY']).encode()
    LOCAL.mkdir(exist_ok=True)
    with (LOCAL / 'wifi-change.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        capture = evidence_directory()
        result = {'passed': False, 'committed': False}
        print('Private Wi-Fi transaction evidence:', capture, flush=True)
        with device(config, 'usb') as client:
            boot = run(client, 'cat /proc/sys/kernel/random/boot_id', display=False).decode().strip()
            if not verify(client, boot, config.get('GAMESHELL_USB_IP', '192.168.10.1')):
                raise ValueError('USB access verification failed')
            directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-wifi.XXXXXXXX',
                            display=False).decode().strip()
            if not re.fullmatch(r'/tmp/gameshellneo-wifi\.[A-Za-z0-9]+', directory):
                raise ValueError('Unexpected transaction directory')
            result.update(boot_id=boot, device_directory=directory)
            (capture / 'wifi-change.json').write_text(json.dumps(result, indent=2) + '\n')
            try:
                with client.open_sftp() as sftp:
                    stage(sftp, directory, candidate)
            except BaseException:
                run(client, shlex.join(['rm', '-r', '--', directory]), display=False)
                raise
            run(client, shlex.join(['sudo', '-n', 'chown', '-R', 'root:root', directory]), display=False)
            script = directory + '/apply-wifi.py'
            arguments = ['sudo', '-n', 'systemd-run', '--quiet', '--collect', '--unit=' + UNIT,
                         '--property=RuntimeMaxSec=160', '--property=TimeoutStopSec=30',
                         '--property=RemainAfterExit=yes',
                         '--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore --directory ' + directory,
                         '/usr/bin/python3', '-B', script, '--directory', directory]
            started = False
            try:
                run(client, shlex.join(arguments), display=False)
                started = True
                print('Applying Wi-Fi; previous configuration will return unless verification succeeds.', flush=True)
                deadline = time.monotonic() + 150
                accepted = None
                while time.monotonic() < deadline:
                    data = run(client, shlex.join(['sudo', '-n', 'cat', directory + '/status.json']),
                               display=False, timeout=10)
                    status = json.loads(data)
                    result['device_status'] = status
                    if status['phase'] == 'restored':
                        raise RuntimeError('New Wi-Fi was not verified; previous configuration restored')
                    if status['phase'] == 'committed':
                        if accepted != status['address']:
                            raise ValueError('Committed address differs from verified Wi-Fi address')
                        result.update(committed=True, address=accepted)
                        update_address(source_env, original_env, accepted)
                        result['passed'] = True
                        break
                    if status['phase'] == 'ready':
                        address = str(ipaddress.IPv4Address(status['address']))
                        if address == config.get('GAMESHELL_USB_IP', '192.168.10.1'):
                            raise ValueError('Wi-Fi address overlaps USB')
                        if accepted != address:
                            try:
                                with device(dict(config, GAMESHELL_IP=address), 'wifi') as wifi:
                                    if not verify(wifi, boot, address):
                                        raise ValueError('Wi-Fi reached a different boot or address')
                                accepted = address
                                run(client, shlex.join(['sudo', '-n', '/usr/bin/python3', '-B', script,
                                                       '--directory', directory, '--commit', address]), display=False)
                            except (OSError, paramiko.SSHException):
                                result['wifi_verification_retries'] = result.get('wifi_verification_retries', 0) + 1
                    time.sleep(3)
                else:
                    raise TimeoutError('Wi-Fi transaction deadline expired')
            finally:
                if started:
                    # Stop waits for ExecStopPost rollback on uncommitted changes.
                    try:
                        loaded = run(client, shlex.join(['systemctl', 'show', UNIT, '-p', 'LoadState', '--value']),
                                     display=False, timeout=10).decode().strip()
                        if loaded != 'not-found':
                            run(client, shlex.join(['sudo', '-n', 'systemctl', 'stop', UNIT]), display=False, timeout=45)
                        run(client, shlex.join(['sudo', '-n', '/usr/bin/python3', '-B', script,
                                               '--restore', '--directory', directory]), display=False, timeout=45)
                        result['cleanup_verified'] = True
                        run(client, shlex.join(['sudo', '-n', 'rm', '-r', '--', directory]), display=False)
                    except (OSError, RuntimeError, paramiko.SSHException):
                        result['cleanup_verified'] = False
                        result['passed'] = False
                        print('Device transaction is bounded; retain its directory for recovery.', flush=True)
                (capture / 'wifi-change.json').write_text(json.dumps(result, indent=2) + '\n')
            if not result.get('cleanup_verified'):
                raise RuntimeError('Wi-Fi applied but transaction cleanup needs verification')
            print('Wi-Fi SSH verified; GAMESHELL_IP updated privately in .env. No reboot was needed.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, paramiko.SSHException) as error:
        print('Wi-Fi change failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
