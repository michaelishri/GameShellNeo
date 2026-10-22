#!/usr/bin/env python3
"""Plan or assemble a development-only card image; never address a physical disk."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from dev_card import assemble, fresh_output, layout, source_layout

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovery-image', type=Path, required=True)
    parser.add_argument('--recovery-sha256', required=True)
    parser.add_argument('--system-image', type=Path, required=True)
    parser.add_argument('--system-sha256', required=True)
    parser.add_argument('--system', required=True)
    parser.add_argument('--initramfs', type=Path, required=True, help='Validated ARM uInitrd')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bytes', type=int, default=8 * 1024 ** 3)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for path in (args.output, args.initramfs):
        if not path.resolve().is_relative_to(ROOT / '.local'):
            raise ValueError('Development output/initramfs must stay in this worktree .local directory')
    if not args.build:
        plan = layout(source_layout(args.recovery_image, args.recovery_sha256), args.bytes)
        source_layout(args.system_image, args.system_sha256)
        print(json.dumps(dict(plan=plan, executed=False), indent=2))
        return
    if args.inside:
        result = assemble(args.recovery_image, args.system_image, args.output,
            recovery_hash=args.recovery_sha256, release_hash=args.system_sha256,
            system=args.system, initramfs=args.initramfs, output_bytes=args.bytes)
        for path in (args.output, args.output.with_suffix('.json')):
            os.chown(path, int(os.environ['NEO_ARTIFACT_UID']), int(os.environ['NEO_ARTIFACT_GID']))
        print(json.dumps(result, indent=2))
        return
    if not os.environ.get('NEO_BUILD_STAGE'):
        raise ValueError('Run image assembly through tools/run-logged.sh or its saved Task')
    fresh_output(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    builder = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']
    command = ['docker', 'run', '--rm', '--network=none', '--pull=never', '--privileged',
               '--platform=' + builder['platform'],
               '-e', 'NEO_ARTIFACT_UID=' + str(os.getuid()),
               '-e', 'NEO_ARTIFACT_GID=' + str(os.getgid()),
               '--entrypoint', 'python3', '-v', str(ROOT) + ':/project',
               '-v', str(args.recovery_image.resolve().parent) + ':/source-recovery:ro',
               '-v', str(args.system_image.resolve().parent) + ':/source-system:ro', builder['image'],
               '/project/tools/build-dev-card.py', '--inside', '--build',
               '--recovery-image', '/source-recovery/' + args.recovery_image.name,
               '--recovery-sha256', args.recovery_sha256,
               '--system-image', '/source-system/' + args.system_image.name,
               '--system-sha256', args.system_sha256, '--system', args.system,
               '--initramfs', '/project/' + str(args.initramfs.resolve().relative_to(ROOT)),
               '--output', '/project/' + str(args.output.resolve().relative_to(ROOT)),
               '--bytes', str(args.bytes)]
    subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
