#!/usr/bin/env python3
"""Build an opt-in development loader; never fetch or install dependencies."""
import argparse
import json
import os
from pathlib import Path
import uuid

from dev_initramfs import ROOT, build_initramfs, write_artifact
from managed_container import execute


def builder_path(value):
    path = Path(value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Managed loader inputs and artifacts must be inside this checkout')
    return '/project/' + path.relative_to(ROOT).as_posix()


def build_managed(args):
    if args.architecture != 'armhf' or args.inside:
        raise ValueError('The managed builder mode is for ARM development artifacts')
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    dependencies = json.loads((ROOT / 'development/multiboot/dependencies.lock.json').read_text())
    expected = args.busybox_sha256 or dependencies['busybox']['binary_sha256']
    command = ['/project/tools/build-dev-initramfs.py', '--inside', '--architecture', 'armhf',
               '--busybox', builder_path(args.busybox), '--busybox-sha256', expected,
               '--output', builder_path(args.output), '--emulator', '/usr/bin/qemu-arm-static']
    if args.u_initrd:
        command += ['--u-initrd', builder_path(args.u_initrd)]
    evidence = ROOT / '.local/build/dev-initramfs-build' / uuid.uuid4().hex
    result = execute('dev-initramfs-build', ['--pull=never', '--network=none',
        '--platform', lock['builder']['platform'], '--user', f'{os.getuid()}:{os.getgid()}',
        '--memory=512m', '--cpus=1', '--pids-limit=64', '--cap-drop=ALL',
        '--security-opt=no-new-privileges', '--entrypoint=python3', '-v', f'{ROOT}:/project',
        lock['builder']['image'], *command], evidence, timeout=40)
    record = json.loads(Path(str(args.output) + '.json').read_text())
    record.update(builder=lock['builder'], managed_run=result['job']['run'],
                  managed_evidence=str(evidence.relative_to(ROOT)))
    data = (json.dumps(record, sort_keys=True, indent=2) + '\n').encode()
    write_artifact(Path(str(args.output) + '.json'), data)
    if args.u_initrd:
        write_artifact(Path(str(args.u_initrd) + '.json'), data)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--busybox', required=True, type=Path)
    parser.add_argument('--busybox-sha256')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--architecture', choices=('armhf', 'x86_64-test'), default='armhf')
    parser.add_argument('--emulator', type=Path)
    parser.add_argument('--u-initrd', type=Path)
    parser.add_argument('--builder', action='store_true', help='use the locked offline ARM builder and its emulator')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.builder:
        result = build_managed(args)
    else:
        result = build_initramfs(args.busybox, args.output, architecture=args.architecture,
                                expected_sha256=args.busybox_sha256, emulator=args.emulator,
                                u_initrd=args.u_initrd)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
