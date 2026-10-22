#!/usr/bin/env python3
"""Authenticate the development-only ARM BusyBox in the locked managed builder."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
import uuid

from dev_initramfs import ROOT, sha256, write_artifact
from managed_container import execute

LOCK = ROOT / 'development/multiboot/dependencies.lock.json'


def dependencies():
    lock = json.loads(LOCK.read_text())
    project = json.loads((ROOT / 'build/sources.lock.json').read_text())
    repository, package = lock['repository'], lock['busybox']
    expected_url = 'https://snapshot.debian.org/archive/debian/' + project['debian']['snapshot'] + '/'
    if (lock.get('development_only') is not True or lock.get('schema_version') != 1 or
            repository['url'] != expected_url or repository['suite'] != 'trixie' or
            repository['inrelease_sha256'] != project['debian']['inrelease_sha256'] or
            repository['packages_path'] != 'main/binary-armhf/Packages.xz' or
            package['package'] != 'busybox-static' or package['architecture'] != 'armhf' or
            not re.fullmatch(r'pool/main/b/busybox/busybox-static_[A-Za-z0-9.+~-]+_armhf[.]deb', package['filename'])):
        raise ValueError('Expected a development-only package from the locked Debian snapshot')
    for value in (repository['inrelease_sha256'], repository['packages_sha256'],
                  package['sha256'], package['binary_sha256']):
        if not re.fullmatch('[0-9a-f]{64}', value):
            raise ValueError('Expected SHA-256 dependency pins')
    return lock, project


def fetch(url, destination, digest, *, size=None):
    maximum = size if size is not None else 1024 * 1024
    if destination.exists():
        data = destination.read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=40) as stream:
            data = stream.read(maximum + 1)
    if len(data) > maximum or (size is not None and len(data) != size) or sha256(data) != digest:
        raise ValueError('Downloaded/cached dependency differs: ' + destination.name)
    write_artifact(destination, data)
    return data


def worker(cache):
    lock, _ = dependencies()
    repository, package = lock['repository'], lock['busybox']
    base = repository['url']
    release = fetch(base + 'dists/trixie/InRelease', cache / 'InRelease', repository['inrelease_sha256'])
    keyring = Path('/usr/share/keyrings/debian-archive-keyring.gpg')
    if sha256(keyring.read_bytes()) != lock['authentication']['keyring_sha256']:
        raise ValueError('Builder archive keyring differs')
    with tempfile.TemporaryDirectory(dir=cache) as home:
        authenticated = subprocess.run(['gpg', '--no-options', '--batch', '--homedir', home,
            '--status-fd=1', '--no-default-keyring', '--keyring', str(keyring),
            '--verify', str(cache / 'InRelease')], capture_output=True, text=True, check=True, timeout=20)
    signatures = re.findall(r'\[GNUPG:\] VALIDSIG (\w+)', authenticated.stdout)
    if set(signatures) != set(lock['authentication']['valid_signatures']):
        raise ValueError('Archive signature identities differ')
    write_artifact(cache / 'signature.log', (authenticated.stdout + authenticated.stderr).encode())
    section = release.decode().split('\nSHA256:\n', 1)[1]
    rows = [line.split() for line in section.splitlines() if line.startswith(' ')]
    expected = [row for row in rows if len(row) == 3 and row[2] == repository['packages_path']]
    if expected != [[repository['packages_sha256'], str(repository['packages_size']), repository['packages_path']]]:
        raise ValueError('Signed package-index hash differs')
    compressed = fetch(base + 'dists/trixie/' + repository['packages_path'], cache / 'Packages.xz',
                       repository['packages_sha256'], size=repository['packages_size'])
    records = []
    for stanza in lzma.decompress(compressed).decode().split('\n\n'):
        fields = dict(line.split(': ', 1) for line in stanza.splitlines()
                      if line and not line.startswith(' ') and ': ' in line)
        if fields.get('Package') == 'busybox-static' and fields.get('Architecture') == 'armhf':
            records.append(fields)
    if len(records) != 1 or any(records[0].get(field) != str(package[key]) for field, key in
            (('Version', 'version'), ('Filename', 'filename'), ('SHA256', 'sha256'), ('Size', 'size'))):
        raise ValueError('Authenticated package record differs')
    archive = cache / Path(package['filename']).name
    fetch(base + package['filename'], archive, package['sha256'], size=package['size'])
    with tempfile.TemporaryDirectory(dir=cache) as temporary:
        extracted = Path(temporary)
        subprocess.run(['dpkg-deb', '-x', str(archive), str(extracted)], check=True, timeout=20)
        candidates = [extracted / name for name in ('bin/busybox', 'usr/bin/busybox')
                      if (extracted / name).is_file()]
        if len(candidates) != 1 or sha256(candidates[0].read_bytes()) != package['binary_sha256']:
            raise ValueError('Authenticated BusyBox binary differs')
        write_artifact(cache / 'busybox-armhf', candidates[0].read_bytes())
        (cache / 'busybox-armhf').chmod(0o755)
        copyright_file = extracted / 'usr/share/doc/busybox-static/copyright'
        write_artifact(cache / 'copyright', copyright_file.read_bytes())
    write_artifact(cache / 'verified.json', (json.dumps(dict(
        dependency_lock_sha256=sha256(LOCK.read_bytes()), binary_sha256=package['binary_sha256'],
        valid_signatures=signatures), indent=2, sort_keys=True) + '\n').encode())


def prepare(output):
    lock, project = dependencies()
    identity = sha256(LOCK.read_bytes())[:16]
    cache = ROOT / '.local/build/dev-busybox' / identity
    cache.mkdir(parents=True, exist_ok=True)
    attempt = ROOT / '.local/build/dev-busybox-fetch-runs' / uuid.uuid4().hex
    result = execute('dev-busybox-fetch', ['--pull=never', '--platform=linux/amd64',
        '--network=bridge', '--memory=512m', '--cpus=1', '--pids-limit=64', '--cap-drop=ALL',
        '--security-opt=no-new-privileges', '--user', f'{os.getuid()}:{os.getgid()}',
        '--entrypoint=python3', '-v', f'{ROOT}:/project:ro', '-v', f'{cache}:/work',
        project['builder']['image'], '/project/tools/fetch-dev-busybox.py', '--worker', '/work'],
        attempt, timeout=180)
    binary = (cache / 'busybox-armhf').read_bytes()
    if sha256(binary) != lock['busybox']['binary_sha256']:
        raise ValueError('Retained BusyBox differs')
    write_artifact(output, binary)
    Path(output).chmod(0o755)
    record = dict(schema_version=1, development_only=True, binary_sha256=sha256(binary),
                  dependency_lock_sha256=sha256(LOCK.read_bytes()), builder=project['builder'],
                  managed_run=result['job']['run'], evidence=str(attempt.relative_to(ROOT)),
                  cache=str(cache.relative_to(ROOT)))
    write_artifact(Path(str(output) + '.json'), (json.dumps(record, indent=2, sort_keys=True) + '\n').encode())
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/multiboot/busybox-armhf')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
    else:
        print(json.dumps(prepare(args.output), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
