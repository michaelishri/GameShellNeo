#!/usr/bin/env python3
"""Verify and collect a private image with its provenance and build logs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--image', type=Path)
    group.add_argument('--latest', action='store_true')
    args = parser.parse_args()
    image = args.image
    if args.latest:
        candidates = list((LOCAL / 'sources/armbian/output/images').glob('*.img'))
        if not candidates:
            raise SystemExit('No assembled image exists')
        image = max(candidates, key=lambda p: p.stat().st_mtime_ns)
    image = image.resolve()
    output = LOCAL / 'artifacts'
    output.mkdir(mode=0o700, exist_ok=True)
    with (LOCAL / 'build/image-verify.log').open('w') as log:
        subprocess.run([str(ROOT / 'tools/verify-image.sh'), str(image)], check=True, stdout=log, stderr=subprocess.STDOUT)
    digest = sha(image)
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    name = f'GameShellNeo-{lock["image_version"]}-cpi31-{digest[:12]}.img'
    destination = output / name
    if destination.exists():
        if sha(destination) != digest:
            raise SystemExit('Existing artifact name has different contents')
    else:
        try:
            os.link(image, destination)
        except OSError:
            shutil.copyfile(image, destination)
    destination.chmod(0o600)
    logs = output / 'logs'
    logs.mkdir(exist_ok=True)
    for pattern in ('*.log', 'schema-validator-packages.txt'):
        for path in (LOCAL / 'build').glob(pattern):
            shutil.copyfile(path, logs / path.name)
    report = {'image': name, 'sha256': digest, 'bytes': image.stat().st_size,
              'offline_verification': 'passed', 'hardware_qualified': False,
              'checks': ['MBR boundaries', 'bootloader readback', 'FAT16/ext4 fsck',
                         'U-Boot CRCs and addresses', 'kernel/DTB/modules/radio hashes',
                         'private identity permissions', 'service policy']}
    (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    entries = []
    for path in sorted(output.rglob('*')):
        if path.is_file() and path.name != 'SHA256SUMS':
            entries.append(f'{digest if path == destination else sha(path)}  {path.relative_to(output)}')
    (output / 'SHA256SUMS').write_text('\n'.join(entries) + '\n')
    print(destination)
    print('Offline verification passed. Hardware qualification remains NEO-5.')


if __name__ == '__main__':
    main()
