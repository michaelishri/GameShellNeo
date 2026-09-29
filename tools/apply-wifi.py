#!/usr/bin/env python3
"""Device-side Wi-Fi transaction; systemd also runs restoration on forced exit."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

TARGET = Path('/etc/wpa_supplicant/wpa_supplicant-wlan0.conf')
UNIT = 'wpa_supplicant@wlan0.service'


def atomic_write(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=20).stdout


def restart():
    command('systemctl', 'restart', UNIT)


def state(directory, **values):
    atomic_write(directory / 'status.json', (json.dumps(values) + '\n').encode())


def restore(directory):
    previous = directory / 'previous.conf'
    if not previous.exists() or (directory / 'committed').exists() or (directory / 'restored').exists():
        return
    atomic_write(TARGET, previous.read_bytes())
    restart()
    atomic_write(directory / 'restored', b'yes\n')
    state(directory, phase='restored', passed=False)


def address():
    status = dict(line.split('=', 1) for line in
                  command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'status').splitlines() if '=' in line)
    if status.get('wpa_state') != 'COMPLETED':
        return None
    interfaces = json.loads(command('/usr/sbin/ip', '-j', '-4', 'address', 'show', 'dev', 'wlan0'))
    addresses = [item['local'] for interface in interfaces for item in interface['addr_info']
                 if item.get('scope') == 'global' and item.get('family') == 'inet']
    return str(ipaddress.IPv4Address(addresses[0])) if len(addresses) == 1 else None


def apply(directory, seconds=120):
    if TARGET.is_symlink() or not TARGET.is_file() or (directory / 'previous.conf').exists():
        raise ValueError('Expected an existing regular Wi-Fi config and a fresh transaction')
    candidate = (directory / 'candidate.conf').read_bytes()
    atomic_write(directory / 'previous.conf', TARGET.read_bytes())
    try:
        state(directory, phase='applying', passed=False)
        atomic_write(TARGET, candidate)
        restart()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                ipv4 = address()
            except subprocess.SubprocessError:
                ipv4 = None  # The control socket/DHCP may still be starting.
            if ipv4:
                state(directory, phase='ready', address=ipv4, passed=False)
                commit = directory / 'commit'
                if commit.exists() and commit.read_text().strip() == ipv4:
                    if TARGET.read_bytes() != candidate:
                        raise ValueError('Wi-Fi configuration changed during verification')
                    atomic_write(directory / 'committed', b'yes\n')
                    state(directory, phase='committed', address=ipv4, passed=True)
                    return
            time.sleep(2)
        raise TimeoutError('Wi-Fi verification deadline expired')
    finally:
        restore(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--restore', action='store_true')
    parser.add_argument('--commit', type=ipaddress.IPv4Address)
    args = parser.parse_args()
    os.umask(0o077)
    if args.restore:
        restore(args.directory)
    elif args.commit:
        atomic_write(args.directory / 'commit', (str(args.commit) + '\n').encode())
    else:
        apply(args.directory)


if __name__ == '__main__':
    main()
