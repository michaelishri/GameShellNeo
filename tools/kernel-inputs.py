#!/usr/bin/env python3
"""Export the auditable patch queue or apply it to a pristine locked kernel."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

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


def apply_queue(source, queue):
    # A concatenated `patch --dry-run` checks later patches against unchanged
    # files, so overlapping patches can falsely fail. Replay the whole queue
    # on just its input files in scratch, then apply the same verified sequence.
    combined = b''.join(data for _, data in queue)
    targets = set(re.findall(rb'^\+\+\+ b/([^\t\n]+)', combined, re.M))
    if not targets:
        raise ValueError('Patch queue has no target files')
    with tempfile.TemporaryDirectory(prefix='gameshellneo-patch-check-') as temporary:
        scratch = Path(temporary)
        for target in targets:
            relative = Path(target.decode())
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe patch target')
            original = source / relative
            if original.is_symlink():
                raise ValueError('Patch target is a symlink')
            if original.exists():
                destination = scratch / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, destination)
        for tree in (scratch, source):
            result = subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1'],
                                    input=combined, cwd=tree, capture_output=True)
            if result.returncode:
                raise RuntimeError('Patch queue failed before completion:\n' +
                                   (result.stdout + result.stderr).decode(errors='replace'))


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
        apply_queue(source, queue)
        stamp.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
