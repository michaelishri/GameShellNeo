#!/usr/bin/env python3
"""Read-only input and disk-headroom checks before expensive build stages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3
# Planning allowances, not measured peak bounds or reserved disk space.
HEADROOM = {'kernel': 6 * GIB, 'image': 10 * GIB}


def checked_input(path, asset):
    if not re.fullmatch(r'[0-9a-f]{64}', asset['sha256']):
        raise ValueError('Invalid locked input digest')
    try:
        info = path.stat()
    except FileNotFoundError:
        raise ValueError(f'Missing input: {path}; supply explicit BOOTLOADER/RADIO_DIR paths') from None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'Input is not a regular file: {path}')
    if 'size_bytes' in asset and info.st_size != asset['size_bytes']:
        raise ValueError(f'Input size differs from lock: {path}')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != asset['sha256']:
        raise ValueError(f'Input checksum differs from lock: {path}')
    return dict(path=str(path), sha256=digest, bytes=info.st_size, status='verified')


def check_inputs(lock, bootloader, radio, local):
    records = [dict(kind='bootloader', **checked_input(bootloader, lock['bootloader']))]
    for kind in ('firmware', 'nvram', 'license'):
        asset = lock['radio'].get(kind)
        if asset is None:
            continue
        name = asset['filename']
        if not name or name in ('.', '..') or Path(name).name != name:
            raise ValueError('Radio inputs must use plain filenames')
        if not re.fullmatch(r'[0-9a-f]{64}', asset['sha256']):
            raise ValueError('Invalid locked radio digest')
        if 'url' in asset:
            if not asset['url'].startswith('https://'):
                raise ValueError('Public radio inputs require HTTPS')
            source = local/'downloads/radio'/asset['sha256']
            if not source.exists() and not source.is_symlink():
                records.append(dict(kind=kind, status='download-required'))
                continue  # Full build runs prepare before compilation.
        else:
            source = radio/name
        records.append(dict(kind=kind, **checked_input(source, asset)))
    return records


def filesystem(path):
    """Resolve symlinked scratch storage, without creating missing directories."""
    current = path.resolve()
    while not current.exists():
        current = current.parent
    if not current.is_dir():
        raise ValueError(f'Build storage is not a directory: {current}')
    return current.stat().st_dev, shutil.disk_usage(current).free, str(current)


def check_space(root, scope, lock):
    local = root/'.local'
    paths = {
        'kernel': [local/'downloads', local/'sources'/('linux-'+lock['linux']['tag'].removeprefix('v')),
                   local/'build/kernel', local/'kernel-install'],
        'image': [local/'sources/armbian/output', local/'sources/armbian/cache',
                  local/'sources/armbian/.tmp', local/'artifacts', local/'build'],
    }
    roles = ('kernel', 'image') if scope == 'full' else (scope,)
    groups = {}
    for role in roles:
        for path in paths[role]:
            device, free, existing = filesystem(path)
            group = groups.setdefault(device, dict(free_bytes=free, roles=set(), paths=set()))
            group['free_bytes'] = min(group['free_bytes'], free)
            group['roles'].add(role); group['paths'].add(existing)
    records = []
    for group in groups.values():
        required = sum(HEADROOM[role] for role in group['roles'])
        record = dict(free_bytes=group['free_bytes'], required_bytes=required,
                      roles=sorted(group['roles']), paths=sorted(group['paths']))
        if group['free_bytes'] < required:
            raise ValueError('Insufficient build headroom: '
                             f'{group["free_bytes"]/GIB:.2f} GiB free; {required/GIB:g} GiB required '
                             f'for {", ".join(record["roles"])} at {record["paths"][0]}')
        records.append(record)
    return records


def preflight(root, scope, bootloader, radio):
    if scope not in ('full', 'kernel', 'image', 'inputs'):
        raise ValueError('Use SCOPE=full/kernel/image/inputs')
    lock = json.loads((root/'build/sources.lock.json').read_text())
    inputs = [] if scope == 'kernel' else check_inputs(lock, bootloader, radio, root/'.local')
    storage = [] if scope == 'inputs' else check_space(root, scope, lock)
    return dict(schema=1, scope=scope, passed=True, inputs=inputs, storage=storage,
                limits='Snapshot only; no reservation, Docker-storage check or guaranteed peak estimate. Final stage checks remain required.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('full', 'kernel', 'image', 'inputs'),
                        default=os.environ.get('NEO_PREFLIGHT_SCOPE', 'full'))
    parser.add_argument('--bootloader', type=Path, default=os.environ.get(
        'NEO_BOOTLOADER', '../GameShell/Code/Kernel/v0.2/u-boot-sunxi-with-spl.bin'))
    parser.add_argument('--radio-directory', type=Path, default=os.environ.get(
        'NEO_RADIO_DIR', '.local/hardware-baseline/2026-09-27/radio-reference'))
    args = parser.parse_args()
    try:
        result = preflight(ROOT, args.scope, args.bootloader, args.radio_directory)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Build preflight failed: {error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
