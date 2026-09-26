#!/usr/bin/env python3
"""Prepare the local workspace and verify the exact locked Docker builder."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SMOKE_CHECK = r'''
set -euo pipefail
export PYTHONPATH=/armbian-pip/base/lib/python3.13/site-packages PATH=/armbian-pip/base/bin:$PATH
for program in make mkimage dtc qemu-arm fsck.fat e2fsck losetup gpg zstd rsync dt-doc-validate dt-mk-schema dt-validate; do
    command -v "$program" >/dev/null
done
compiler="${NEO_CROSS_COMPILE}gcc"
"$compiler" --version
python3 -c 'import dtschema; print("dtschema:", dtschema.__version__)'
printf 'int main(void) { return 0; }\n' | "$compiler" -x c -static -o /tmp/neo-arm-check -
qemu-arm /tmp/neo-arm-check
echo 'ARM compilation/emulation and image/device-tree tools: ready.'
'''


def locked_builder(lock):
    builder = lock['builder']
    if not re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', builder['image']):
        raise ValueError('Builder must be pinned by SHA-256 digest, not a mutable tag')
    if builder['platform'] != 'linux/amd64':
        raise ValueError('This build workflow supports linux/amd64 only')
    return builder


def validate_image(builder, image):
    if image['Os'] + '/' + image['Architecture'] != builder['platform']:
        raise ValueError('Downloaded builder platform differs from sources.lock.json')
    if builder['image'] not in image.get('RepoDigests', []):
        raise ValueError('Downloaded builder digest differs from sources.lock.json')


def prepare_workspace(root):
    local = root / '.local'
    local.mkdir(mode=0o700, exist_ok=True)
    local.chmod(0o700)
    for name in ('build', 'downloads', 'sources', 'inputs', 'artifacts', 'ssh', 'provisioning'):
        (local / name).mkdir(mode=0o700, exist_ok=True)
    env = root / '.env'
    try:
        # Exclusive creation makes repeat runs preserve all existing secrets.
        with env.open('x') as stream:
            stream.write((root / '.env.example').read_text())
        print('Created private .env template; fill its blank values before provisioning.')
    except FileExistsError:
        print('Preserved existing .env.')
    env.chmod(0o600)


def main():
    os.umask(0o077)
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    builder = locked_builder(lock)
    prepare_workspace(ROOT)
    print('Pulling pinned builder:', builder['image'], flush=True)
    subprocess.run(['docker', 'pull', '--platform', builder['platform'], builder['image']], check=True)
    image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', builder['image']], text=True))[0]
    validate_image(builder, image)
    subprocess.run(['docker', 'run', '--rm', '--pull=never', '--platform', builder['platform'],
                    '--network=none', '--entrypoint', 'bash',
                    '-e', 'NEO_CROSS_COMPILE=' + builder['cross_compile'],
                    builder['image'], '-c', SMOKE_CHECK], check=True)
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'image': builder['image'],
              'platform': builder['platform'], 'image_id': image['Id'], 'smoke_check': 'passed'}
    destination = ROOT / '.local/build/setup.json'
    temporary = destination.with_suffix('.json.part')
    temporary.write_text(json.dumps(report, indent=2) + '\n')
    temporary.replace(destination)
    print('Build environment ready. Record: .local/build/setup.json')
    print('Next: supply private inputs, then task prepare, task provision and task build (see README).')


if __name__ == '__main__':
    main()
