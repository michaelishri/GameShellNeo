#!/usr/bin/env python3
"""Qualify exclusive store writes, mount veto and read-only fsck on a new loop image."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ('tools/install-dev-store.py', 'tools/check-dev-store-install.py',
          'tools/tests/test_dev_store_install.py')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fixture(work):
    from dev_card import attached
    spec = importlib.util.spec_from_file_location('dev_store_install_fixture', ROOT / 'tools/install-dev-store.py')
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    installer.require(os.geteuid() == 0, 'Loop fixture requires the isolated managed root container')
    before = {name: sha(ROOT / name) for name in INPUTS}
    image, archive, mount = work / 'new-store.ext4', work / 'new-store.ext4.gz', work / 'mount'
    mount.mkdir()
    with image.open('xb') as stream:
        stream.truncate(64 * 1024 * 1024)
    log = (work / 'fixture.log').open('xb', buffering=0)
    try:
        installer.command(['mkfs.ext4', '-F', image], log=log)
        with attached(image, False) as node:
            installer.command(['mount', '-t', 'ext4', node, mount], log=log)
            try:
                (mount / 'sentinel').write_bytes(b'complete independent store fixture\n')
                os.sync()
            finally:
                installer.command(['umount', '--', mount], log=log)
            with image.open('rb') as source, archive.open('xb') as target:
                with gzip.GzipFile(fileobj=target, mode='wb', mtime=0) as compressed:
                    while data := source.read(installer.CHUNK):
                        compressed.write(data)
            raw = {'bytes': image.stat().st_size, 'sha256': sha(image)}
            compressed = {'bytes': archive.stat().st_size, 'sha256': sha(archive)}
            target = dict(node=node, device=installer.device_number(Path(node).stat().st_rdev), bytes=raw['bytes'])
            with archive.open('rb', buffering=0) as source:
                installer.verify_archive(source, compressed, raw)
                with installer.exclusive_device(target) as descriptor:
                    result = subprocess.run(['mount', '-t', 'ext4', '-o', 'ro', node, str(mount)],
                                            stdout=log, stderr=log)
                    if result.returncode == 0:
                        installer.command(['umount', '--', mount], log=log)
                        raise ValueError('A mount succeeded while the exclusive claim was held')
                    readback = installer.write_and_readback(descriptor, source, raw)
                    installer.command(['e2fsck', '-f', '-n', '/proc/self/fd/' + str(descriptor)],
                                      log=log, pass_fds=(descriptor,))
                    # Check again after fsck while the very same claim is alive.
                    result = subprocess.run(['mount', '-t', 'ext4', '-o', 'ro', node, str(mount)],
                                            stdout=log, stderr=log)
                    if result.returncode == 0:
                        installer.command(['umount', '--', mount], log=log)
                        raise ValueError('Filesystem checker lost the exclusive claim')
            installer.command(['mount', '-t', 'ext4', '-o', 'ro,noload', node, mount], log=log)
            try:
                installer.require((mount / 'sentinel').read_bytes() == b'complete independent store fixture\n',
                                  'Post-claim read-only mount lost the store content')
            finally:
                installer.command(['umount', '--', mount], log=log)
        installer.require(before == {name: sha(ROOT / name) for name in INPUTS}, 'Fixture inputs changed while running')
        record = dict(passed=True, inputs=before, readback=readback, exclusive_mount_veto=True,
                      read_only_fsck_while_claimed=True, mount_after_claim=True,
                      scope='Only a newly allocated loop on a new synthetic regular ext4 image; no physical media.')
    except BaseException as error:
        record = dict(passed=False, inputs=before, error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        os.fsync(log.fileno())
        log.close()
        with (work / 'result.json').open('x') as stream:
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write('\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        fixture(args.inside)
        return
    if not os.environ.get('NEO_BUILD_STAGE'):
        raise ValueError('Use the saved test:dev-store-install Task')
    from managed_container import execute
    work = ROOT / '.local/build/dev-store-claim' / uuid.uuid4().hex
    work.mkdir(parents=True, mode=0o700)
    builder = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']
    execute('dev-store-claim', ['--pull=never', '--network=none', '--privileged',
        '--platform=' + builder['platform'], '--memory=512m', '--cpus=1', '--pids-limit=128',
        '--entrypoint=python3', '-v', f'{ROOT}:/project:ro', '-v', f'{work}:/fixture',
        builder['image'], '/project/tools/check-dev-store-install.py', '--inside', '/fixture'],
        work / 'managed', timeout=180)
    result = json.loads((work / 'result.json').read_text())
    if result.get('passed') is not True or result['inputs'] != {name: sha(ROOT / name) for name in INPUTS}:
        raise ValueError('Exclusive store fixture did not pass with the current inputs')
    print('Retained exclusive store fixture:', work.relative_to(ROOT))


if __name__ == '__main__':
    main()
