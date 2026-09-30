#!/usr/bin/env python3
"""Preserve verified current-image metadata before advancing the build identity."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def artifact(directory, name):
    if not isinstance(name, str) or Path(name).name != name or name in ('', '.', '..'):
        raise ValueError('Invalid artifact filename')
    return directory / name


def main():
    os.umask(0o077)
    name = os.environ.get('NEO_CHECKPOINT_NAME', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', name):
        raise ValueError('Supply NAME using lowercase letters, numbers and hyphens')
    artifacts, flash = ROOT / '.local/artifacts', ROOT / '.local/flash'
    report = json.loads((artifacts / 'verification.json').read_text())
    manifest = json.loads((artifacts / 'image-manifest.json').read_text())
    kernel = json.loads((artifacts / 'kernel-completed.json').read_text())
    transfer = json.loads((flash / 'transfer.json').read_text())
    image = artifact(artifacts, report['image'])
    compressed = artifact(flash, transfer['compressed_file'])
    if (report['offline_verification'] != 'passed' or
            manifest['version'] != manifest['sources']['image_version'] or
            kernel['kernel_release'] != manifest['kernel'] or
            transfer['image'] != image.name or transfer['image_sha256'] != report['sha256'] or
            transfer['image_bytes'] != report['bytes'] or
            image.stat().st_size != report['bytes'] or digest(image) != report['sha256'] or
            compressed.stat().st_size != transfer['compressed_bytes'] or
            digest(compressed) != transfer['compressed_sha256']):
        raise ValueError('Current image, kernel and transfer metadata do not agree')
    recovery = ROOT / '.local/recovery'
    recovery.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = recovery / name
    if destination.exists():
        raise ValueError('Checkpoint already exists; choose a new NAME')
    with tempfile.TemporaryDirectory(dir=recovery) as directory:
        stage = Path(directory) / 'checkpoint'
        stage.mkdir()
        for filename in ('verification.json', 'image-manifest.json', 'kernel-completed.json',
                         'kernel.config', 'compiler.txt', 'packages.txt'):
            shutil.copy2(artifacts / filename, stage / filename)
        shutil.copytree(artifacts / 'kernel-patches', stage / 'kernel-patches')
        shutil.copy2(flash / 'transfer.json', stage / 'transfer.json')
        (stage / 'sources.lock.json').write_text(json.dumps(manifest['sources'], indent=2) + '\n')
        (stage / 'artifacts.json').write_text(json.dumps(dict(
            image=str(image.relative_to(ROOT)), image_sha256=report['sha256'],
            compressed=str(compressed.relative_to(ROOT)), compressed_sha256=transfer['compressed_sha256'],
            note='Artifacts retained at these paths, not duplicated. Metadata is from the completed '
                 'image, not current working-tree inputs.'), indent=2) + '\n')
        (stage / 'metadata-sha256.json').write_text(json.dumps({str(p.relative_to(stage)): digest(p)
            for p in sorted(stage.rglob('*')) if p.is_file()}, indent=2) + '\n')
        stage.rename(destination)
    print('Verified recovery checkpoint:', destination.relative_to(ROOT))
    print('Retained image:', image.name)


if __name__ == '__main__':
    main()
