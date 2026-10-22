#!/usr/bin/env python3
"""Prepare a complete development version on the host for loop-free SSH import."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from dev_card import ROOT, attached, mounted, source_layout
from dev_images import import_release
from dev_initramfs import verify_u_initrd
from dev_systems import partuuid, slot_id


def prepare(args):
    from dev_bundle import pack_release
    source_layout(args.image, args.sha256)
    loader = verify_u_initrd(args.initramfs)
    with tempfile.TemporaryDirectory(prefix='gameshellneo-devbundle-') as temporary:
        work = Path(temporary)
        with attached(args.image, True) as device:
            with mounted(device + 'p1', work / 'boot', readonly=True) as boot, \
                    mounted(device + 'p2', work / 'root', readonly=True, filesystem='ext4') as root:
                import_release(root, boot, work / args.system, slot=args.system,
                    source_image_sha256=args.sha256, store_partuuid=args.store_partuuid,
                    initramfs=args.initramfs)
        result = pack_release(work / args.system, args.output)
    result.update(development_only=True, store_partuuid=args.store_partuuid, loader=loader)
    with args.output.with_suffix('.json').open('x') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    for path in (args.output, args.output.with_suffix('.json')):
        os.chown(path, int(os.environ['NEO_ARTIFACT_UID']), int(os.environ['NEO_ARTIFACT_GID']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--system', required=True)
    parser.add_argument('--store-partuuid', required=True)
    parser.add_argument('--initramfs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    slot_id(args.system)
    partuuid(args.store_partuuid, '03')
    if args.system == 'recovery' or args.output.suffix != '.tar':
        raise ValueError('Expected a fresh version identifier and .tar output')
    for path in (args.initramfs, args.output):
        if not path.resolve().is_relative_to(ROOT / '.local'):
            raise ValueError('Loader and bundle artifacts must stay in this checkout .local')
    for path in (args.output, args.output.with_suffix('.json')):
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
    if args.inside:
        print(json.dumps(prepare(args), indent=2))
        return
    if not os.environ.get('NEO_BUILD_STAGE'):
        raise ValueError('Use the saved dev:bundle Task for managed host extraction')
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    builder = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']
    subprocess.run(['docker', 'run', '--rm', '--network=none', '--pull=never', '--privileged',
        '--platform=' + builder['platform'], '--entrypoint=python3',
        '-e', 'NEO_ARTIFACT_UID=' + str(os.getuid()), '-e', 'NEO_ARTIFACT_GID=' + str(os.getgid()),
        '-v', str(ROOT) + ':/project', '-v', str(args.image.resolve().parent) + ':/source:ro',
        builder['image'], '/project/tools/prepare-dev-bundle.py', '--inside',
        '--image', '/source/' + args.image.name, '--sha256', args.sha256,
        '--system', args.system, '--store-partuuid', args.store_partuuid,
        '--initramfs', '/project/' + str(args.initramfs.resolve().relative_to(ROOT)),
        '--output', '/project/' + str(args.output.resolve().relative_to(ROOT))], check=True)


if __name__ == '__main__':
    main()
