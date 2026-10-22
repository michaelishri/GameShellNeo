#!/usr/bin/env python3
"""Pack an explicitly selected development card into a fresh private directory."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def helper(filename):
    spec = importlib.util.spec_from_file_location('development_' + Path(filename).stem.replace('-', '_'), ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_receipt(report, image_name, image_bytes):
    if (not isinstance(report, dict) or type(report.get('schema')) is not int or report['schema'] != 1 or
            report.get('operation') != 'development-card-assembly' or
            report.get('development_only') is not True or report.get('offline_filesystem_checks') != 'passed' or
            report.get('recovery_root_byte_identical') is not True or
            report.get('reserved_bootloader_prefix_byte_identical') is not True or
            not isinstance(report.get('image'), str) or Path(report['image']).name != image_name or
            type(report.get('bytes')) is not int or report['bytes'] <= 0 or report['bytes'] % 512 or
            report['bytes'] != image_bytes or not isinstance(report.get('sha256'), str) or
            not re.fullmatch('[0-9a-f]{64}', report['sha256'])):
        raise ValueError('Development card receipt, size or offline qualification differs')
    return report


def pack(image, receipt, output):
    image, receipt, output = map(Path, (image, receipt, output))
    if image.is_symlink() or not image.is_file() or image.suffix != '.img':
        raise ValueError('Expected an explicitly selected regular development .img file')
    if receipt.is_symlink() or not receipt.is_file():
        raise ValueError('Expected a regular development card receipt')
    receipt_bytes = receipt.read_bytes()
    report = validate_receipt(json.loads(receipt_bytes), image.name, image.stat().st_size)
    policy = helper('flash-macos.py')
    seconds = policy.development_guard_seconds(report['bytes'])
    # mkdir's exclusive creation protects every existing production transfer or
    # checkpoint, including one accidentally selected as this output directory.
    previous = os.umask(0o077)
    try:
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        manifest = helper('pack-image.py').pack(image, report, output)
        with (output / 'development-card.json').open('xb') as stream:
            stream.write(receipt_bytes)
        manifest.update(development_only=True, development_receipt_file='development-card.json',
                        development_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest())
        if report['bytes'] > policy.LARGE_IMAGE_BYTES:
            manifest['guard_timeout_seconds'] = seconds
        temporary = output / 'transfer.development.json.part'
        with temporary.open('x') as stream:
            stream.write(json.dumps(manifest, indent=2) + '\n')
        temporary.replace(output / 'transfer.json')
    finally:
        os.umask(previous)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(pack(args.image, args.receipt, args.output), indent=2))


if __name__ == '__main__':
    main()
