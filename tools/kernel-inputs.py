#!/usr/bin/env python3
"""Export the auditable patch queue or apply it to a pristine locked kernel."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def patches():
    queue = {}
    for path in sorted((ROOT / 'kernel/patches').glob('*.patch')):
        queue[path.name] = path.read_bytes()
    parts = []
    overlay = ROOT / 'kernel/overlay'
    for path in sorted(overlay.rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(overlay).as_posix()
        parts.append(f'diff --git a/{name} b/{name}\nnew file mode 100644\n')
        parts.extend(difflib.unified_diff([], path.read_text().splitlines(True),
                                         fromfile='/dev/null', tofile=f'b/{name}'))
    queue['0003-gameshell-new-files.patch'] = ''.join(parts).encode()
    yield from sorted(queue.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--export', type=Path)
    group.add_argument('--apply', type=Path)
    args = parser.parse_args()
    queue = list(patches())
    manifest = [{'name': n, 'sha256': hashlib.sha256(b).hexdigest()} for n, b in queue]
    if args.export:
        args.export.mkdir(parents=True, exist_ok=True)
        expected = {n for n, _ in queue}
        extra = {p.name for p in args.export.glob('*.patch')} - expected
        if extra:
            raise SystemExit(f'Unexpected patches in export directory: {sorted(extra)}')
        for name, data in queue:
            (args.export / name).write_bytes(data)
        (args.export / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    else:
        source = args.apply.resolve()
        stamp = source / '.gameshellneo-patches.json'
        if stamp.exists():
            if json.loads(stamp.read_text()) != manifest:
                raise SystemExit('Patch inputs changed: apply to a fresh kernel extraction.')
            print('Kernel already has this patch queue.')
            return
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        seed = source / 'arch/arm/configs/sunxi_defconfig'
        if hashlib.sha256(seed.read_bytes()).hexdigest() != lock['linux']['defconfig_sha256']:
            raise SystemExit('Unexpected upstream kernel configuration seed.')
        makefile = (source / 'Makefile').read_text()
        for line in ('VERSION = 6', 'PATCHLEVEL = 18', 'SUBLEVEL = 54'):
            if line not in makefile.splitlines():
                raise SystemExit('Expected Linux 6.18.54 source.')
        # Validate the entire queue before changing any file.
        combined = b''.join(data for _, data in queue)
        for dry in (True, False):
            command = ['patch', '--batch', '--forward', '-p1']
            if dry:
                command.append('--dry-run')
            subprocess.run(command, input=combined, cwd=source, check=True,
                           stdout=subprocess.DEVNULL)
        stamp.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
