#!/usr/bin/env python3
"""Build, verify and select prebuilt USB-policy boot scripts; never reboot."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import zlib

PARAMETER = 'axp20x_usb_power.gameshellneo_slow_poll'
MODES = ('stock', 'experimental')


def boot_script(partuuid, mode=None):
    if not re.fullmatch(r'[0-9a-fA-F]{8}-02', partuuid) or mode not in (*MODES, None):
        raise ValueError('Unexpected root PARTUUID or USB policy')
    option = '' if mode is None else f' {PARAMETER}={int(mode == "experimental")}'
    return (f'setenv bootargs console=tty0 console=ttyS0,115200n8 root=PARTUUID={partuuid} '
            f'rootfstype=ext4 rootwait rw panic=10{option}\n'
            'if fatload mmc 0:1 0x48000000 uImage; then\n'
            '  if fatload mmc 0:1 0x49000000 sun8i-r16-clockworkpi-cpi3.dtb; then\n'
            '    bootm 0x48000000 - 0x49000000\n  fi\nfi\n'
            'echo "GameShellNeo boot failed"\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def script_source(data):
    if len(data) < 72:
        raise ValueError('Truncated U-Boot script')
    header = bytearray(data[:64])
    magic, hcrc, _, size, _, _, dcrc, _, arch, kind, compression, _ = struct.unpack('>7I4B32s', header)
    header[4:8] = b'\0' * 4
    payload = data[64:]
    if (magic != 0x27051956 or zlib.crc32(header) != hcrc or len(payload) != size or
            zlib.crc32(payload) != dcrc or (arch, kind, compression) != (2, 6, 0)):
        raise ValueError('Invalid U-Boot script header or checksum')
    length, terminator = struct.unpack('>2I', payload[:8])
    if terminator or length != len(payload) - 8:
        raise ValueError('Unexpected U-Boot script payload')
    return payload[8:]


def verify_scripts(boot, identity):
    record = identity['usb_poll_boot']
    expected_names = {f'boot-usb-{mode}.{suffix}' for mode in MODES for suffix in ('cmd', 'scr')}
    if set(record['files']) != expected_names:
        raise ValueError('Unexpected boot-policy manifest')
    data = {}
    for name, expected in record['files'].items():
        path = boot / name
        if path.is_symlink():
            raise ValueError('Boot-policy files must be regular files')
        data[name] = path.read_bytes()
        if sha(data[name]) != expected:
            raise ValueError('Boot-policy file hash mismatch: ' + name)
    for mode in MODES:
        source = data[f'boot-usb-{mode}.cmd']
        if source != boot_script(identity['root_partuuid'], mode) or script_source(data[f'boot-usb-{mode}.scr']) != source:
            raise ValueError('Unexpected boot-policy source or compiled script')
    selected = (boot / 'boot.scr').read_bytes()
    mode = next((mode for mode in MODES if selected == data[f'boot-usb-{mode}.scr']), None)
    if mode is None:
        raise ValueError('Current boot.scr is not a verified policy variant')
    return data, mode


def atomic_write(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.usb-policy-', dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def select(boot, identity, mode):
    if mode not in MODES:
        raise ValueError('Expected stock or experimental')
    data, previous = verify_scripts(boot, identity)
    # boot.scr is the bootloader's input. Replace it last: an interruption
    # between the two writes leaves the previous valid executable selected.
    atomic_write(boot / 'boot.cmd', data[f'boot-usb-{mode}.cmd'])
    atomic_write(boot / 'boot.scr', data[f'boot-usb-{mode}.scr'])
    _, selected = verify_scripts(boot, identity)
    if selected != mode:
        raise ValueError('Boot selection readback failed')
    return {'previous_next_boot': previous, 'next_boot': mode, 'reboot_performed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('status', *MODES), default='status')
    args = parser.parse_args()
    identity = json.loads(Path('/etc/gameshellneo/image.json').read_text())
    boot = Path('/boot')
    if identity['board'] != 'gameshellneo-cpi31' or 'usb_poll_boot' not in identity:
        raise ValueError('This image has no verified USB polling experiment')
    if os.uname().release != identity['kernel']:
        raise ValueError('Running kernel differs from image manifest')
    if not boot.is_mount():
        raise ValueError('/boot must be mounted')
    with Path('/run/lock/gameshellneo-usb-policy.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.mode != 'status':
            print(json.dumps(select(boot, identity, args.mode)), flush=True)
        _, selected = verify_scripts(boot, identity)
        requested = Path('/sys/module/axp20x_usb_power/parameters/gameshellneo_slow_poll').read_text().strip()
        log = subprocess.check_output(['journalctl', '-b', '-k', '--no-pager', '-o', 'cat'], text=True)
        messages = [line for line in log.splitlines() if 'GameShellNeo USB polling:' in line]
        active = [line for line in messages if 'experimental absent=250ms, fast=50ms' in line]
        stock = [line for line in messages if 'stock: opt-in disabled' in line]
        passed = requested in ('Y', 'N') and len(messages) == 1 and bool(active if requested == 'Y' else stock)
        result = {'running_requested': requested, 'running_policy_messages': messages,
                  'running_policy_verified': passed, 'next_boot': selected,
                  'boot_source_matches': (boot / 'boot.cmd').read_bytes() == boot_script(identity['root_partuuid'], selected),
                  'hardware_qualified': False}
        print(json.dumps(result, indent=2), flush=True)
        return 0 if passed and result['boot_source_matches'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
