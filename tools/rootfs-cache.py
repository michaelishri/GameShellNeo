#!/usr/bin/env python3
"""Record locally built rootfs provenance; authorize reuse only on an exact match."""
import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.local/sources/armbian/cache/rootfs'
LEDGER = ROOT / '.local/build/rootfs-cache.json'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inputs():
    # These two fields are consumed only by final image/kernel assembly.
    # Keep every other field, including unknown future fields, conservative.
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    del lock['image_version']
    del lock['linux']['localversion']
    encoded = json.dumps(lock, sort_keys=True, separators=(',', ':')).encode()
    paths = [ROOT / 'tools/build-image.sh']
    for folder in ('build/armbian', 'build/armbian-patches'):
        paths += [p for p in (ROOT / folder).rglob('*') if p.is_file() and p.name != 'gameshellneo.sh']
    result = {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}
    # Different key name deliberately rejects the old whole-lock ledger.
    result['base_rootfs_lock_v2'] = hashlib.sha256(encoded).hexdigest()
    # Final image edits do not invalidate a base rootfs. Its APT source policy does.
    tree = ast.parse((ROOT / 'tools/image.py').read_text())
    policy = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'apt_sources')
    result['apt_sources_policy'] = hashlib.sha256(ast.dump(policy).encode()).hexdigest()
    extension = (ROOT / 'build/armbian/extensions/gameshellneo.sh').read_text()
    for name in ('extension_prepare_config__gameshellneo', 'custom_apt_repo__gameshellneo'):
        body = re.search(r'(?ms)^function ' + name + r'\(\) \{.*?^}', extension).group()
        result[name] = hashlib.sha256(body.encode()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['record', 'check'])
    args = parser.parse_args()
    if args.action == 'record':
        candidates = list(CACHE.glob('rootfs-armhf-trixie-minimal_*.tar.zst'))
        if not candidates:
            raise SystemExit('No locally built rootfs cache to record')
        path = max(candidates, key=lambda p: p.stat().st_mtime_ns)
        LEDGER.write_text(json.dumps({'name': path.name, 'sha256': sha(path), 'inputs': inputs()}, indent=2) + '\n')
    else:
        if not LEDGER.exists():
            raise SystemExit(1)
        ledger = json.loads(LEDGER.read_text())
        path = CACHE / ledger['name']
        if ledger['inputs'] != inputs() or not path.is_file() or sha(path) != ledger['sha256']:
            raise SystemExit(1)
        print(ledger['name'])
        print(ledger['sha256'])


if __name__ == '__main__':
    main()
