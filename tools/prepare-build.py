#!/usr/bin/env python3
"""Stage locked public sources and hash-checked private inputs for Armbian."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
LOCK = json.loads((ROOT / 'build/sources.lock.json').read_text())


def run(*command, **kwargs):
    return subprocess.run([str(p) for p in command], check=True, **kwargs)


def checked_copy(source, destination, expected):
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        raise SystemExit(f'Input checksum failed: {source.name}')
    shutil.copyfile(source, destination)


def stage_radio(radio, reference, inputs, cache):
    """Keep owner NVRAM private; public blobs require locked URL and digest."""
    for kind in ('firmware', 'nvram', 'license'):
        asset = radio.get(kind)
        if asset is None:
            continue
        filename = asset['filename']
        if Path(filename).name != filename:
            raise ValueError('Radio inputs must use plain filenames')
        source = reference / filename
        if 'url' in asset:
            if not asset['url'].startswith('https://'):
                raise ValueError('Public radio inputs require HTTPS')
            cache.mkdir(parents=True, exist_ok=True)
            source = cache / asset['sha256']
            if not source.exists():
                with urllib.request.urlopen(asset['url'], timeout=60) as response:
                    data = response.read(2 * 1024 * 1024 + 1)
                if len(data) > 2 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != asset['sha256']:
                    raise ValueError('Public radio download failed the locked checksum: ' + kind)
                temporary = source.with_suffix('.part')
                try:
                    temporary.write_bytes(data)
                    temporary.replace(source)
                finally:
                    temporary.unlink(missing_ok=True)
        checked_copy(source, inputs / filename, asset['sha256'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bootloader', type=Path, required=True)
    parser.add_argument('--radio-directory', type=Path, required=True)
    args = parser.parse_args()
    LOCAL.mkdir(exist_ok=True, mode=0o700)
    LOCAL.chmod(0o700)
    for name in ('sources', 'inputs', 'build', 'artifacts', 'downloads'):
        (LOCAL / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    armbian = LOCAL / 'sources/armbian'
    if not armbian.exists():
        run('git', 'clone', '--filter=blob:none', '--no-checkout', LOCK['armbian']['url'], armbian)
        run('git', '-C', armbian, 'fetch', '--depth=1', 'origin', LOCK['armbian']['commit'])
        run('git', '-C', armbian, 'checkout', '--detach', LOCK['armbian']['commit'])
    if subprocess.check_output(['git', '-C', str(armbian), 'rev-parse', 'HEAD'], text=True).strip() != LOCK['armbian']['commit']:
        raise SystemExit('Armbian checkout differs from the lock')
    for patch in sorted((ROOT / 'build/armbian-patches').glob('*.patch')):
        # Idempotent only if the exact patch is present; never reset other edits.
        test = subprocess.run(['git', '-C', str(armbian), 'apply', '--reverse', '--check', str(patch)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if test.returncode:
            run('git', '-C', armbian, 'apply', '--check', patch)
            run('git', '-C', armbian, 'apply', patch)
    shutil.copytree(ROOT / 'build/armbian', armbian / 'userpatches', dirs_exist_ok=True)
    checked_copy(args.bootloader, LOCAL / 'inputs' / LOCK['bootloader']['filename'], LOCK['bootloader']['sha256'])
    stage_radio(LOCK['radio'], args.radio_directory, LOCAL / 'inputs', LOCAL / 'downloads/radio')
    for archive, stamp, expected in [('debian', LOCK['debian']['snapshot'], LOCK['debian']['inrelease_sha256']),
                                     ('debian-security', LOCK['debian']['security_snapshot'], LOCK['debian']['security_inrelease_sha256'])]:
        suite = 'trixie' if archive == 'debian' else 'trixie-security'
        path = LOCAL / 'inputs' / f'{archive}.InRelease'
        if not path.exists():
            with urllib.request.urlopen(f'https://snapshot.debian.org/archive/{archive}/{stamp}/dists/{suite}/InRelease', timeout=60) as stream:
                path.write_bytes(stream.read())
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit(f'Unexpected {archive} snapshot metadata')
    print('Locked sources, bootstrap patch and private inputs staged.')


if __name__ == '__main__':
    main()
