#!/usr/bin/env python3
"""Verify a bundled image or prepare its private, checked transfer archive."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def current_image():
    report = json.loads((ROOT / '.local/artifacts/verification.json').read_text())
    if report['offline_verification'] != 'passed' or Path(report['image']).name != report['image']:
        raise ValueError('Expected a verified image bundle')
    return ROOT / '.local/artifacts' / report['image'], report


def pack(image, report, output):
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = image.name + '.gz'
    destination = output / name
    partial = destination.with_suffix('.gz.part')
    digest, size = hashlib.sha256(), 0
    try:
        with image.open('rb') as source, partial.open('wb') as target:
            with gzip.GzipFile(filename='', fileobj=target, mode='wb', compresslevel=1, mtime=0) as compressed:
                while data := source.read(4 * 1024 * 1024):
                    digest.update(data)
                    size += len(data)
                    compressed.write(data)
        if (digest.hexdigest(), size) != (report['sha256'], report['bytes']):
            raise ValueError('Source image differs from its offline verification record')
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    with destination.open('rb') as stream:
        compressed_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest = {'image': image.name, 'image_sha256': digest.hexdigest(), 'image_bytes': size,
                'compressed_file': name, 'compressed_bytes': destination.stat().st_size,
                'compressed_sha256': compressed_sha}
    temporary = output / 'transfer.json.part'
    temporary.write_text(json.dumps(manifest, indent=2) + '\n')
    temporary.replace(output / 'transfer.json')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['verify', 'pack'])
    args = parser.parse_args()
    os.umask(0o077)
    selected = os.environ.get('NEO_IMAGE')
    if args.action == 'verify':
        image = Path(selected).resolve() if selected else current_image()[0]
        subprocess.run([str(ROOT / 'tools/verify-image.sh'), str(image)], check=True)
    else:
        image, report = current_image()
        if selected:
            image = Path(selected).resolve()
        manifest = pack(image, report, ROOT / '.local/flash')
        print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
