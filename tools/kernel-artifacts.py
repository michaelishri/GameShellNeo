#!/usr/bin/env python3
"""Record/check the completed kernel stage before image assembly."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory():
    spec = importlib.util.spec_from_file_location('inputs', ROOT / 'tools/kernel-inputs.py')
    inputs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inputs)
    kernel = ROOT / '.local/build/kernel'
    release = (kernel / 'include/config/kernel.release').read_text().strip()
    modules = ROOT / '.local/kernel-install/lib/modules' / release
    files = [kernel / p for p in ('.config', 'System.map', 'include/config/kernel.release',
             'arch/arm/boot/zImage', 'arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dtb')]
    installed = sorted(modules.rglob('*.ko'))
    if not installed:
        raise SystemExit('Kernel module installation is incomplete')
    files.extend(installed)
    def digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'kernel_release': release,
            'patches': {n: hashlib.sha256(b).hexdigest() for n, b in inputs.patches()},
            'fragment_sha256': digest(ROOT / 'kernel/gameshellneo.config'),
            'files': {str(p.relative_to(ROOT)): digest(p) for p in files}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['record', 'check'])
    args = parser.parse_args()
    path = ROOT / '.local/build/kernel-completed.json'
    current = inventory()
    if args.action == 'record':
        path.write_text(json.dumps(current, indent=2) + '\n')
    elif json.loads(path.read_text()) != current:
        raise SystemExit('Kernel inputs/artifacts changed; rebuild the kernel stage')
    print(f'Kernel stage {args.action}: {len(current["files"])} files checked')


if __name__ == '__main__':
    main()
