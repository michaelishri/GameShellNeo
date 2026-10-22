#!/usr/bin/env python3
"""Exercise unchanged U-Boot 2018 FAT code on disposable FAT16 regular files."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '9da7fb4a39149c3061cb148bfbaa76b4b52b9008'
SOURCES = {
    'fs/fat/fat.c': '5e7df52648abb81acc9fc34ba36081b6329fbe432791c87268517fffd72a381a',
    'fs/fat/fat_write.c': '9dd669b6dff0c35a5f20f67fa1f67635d2cc7b5e135c4b281926bd0b5f0de249',
    'include/fat.h': '78eaf06dccc48c66af1ab7a10c34e3f1c3f565da6cbebc79171f30d4278626bb',
}
INPUTS = ('tools/check-dev-fat-writer.py', 'tools/dev-fat-writer-fixture.c',
          'tools/tests/test_dev_fat_writer.py')
SHIMS = ('common.h', 'command.h', 'config.h', 'blk.h', 'exports.h', 'fs.h', 'part.h',
         'malloc.h', 'memalign.h', 'asm/byteorder.h', 'linux/compiler.h', 'linux/ctype.h',
         'div64.h', 'linux/math64.h')
VOLUME_BYTES = 128 * 1024 * 1024


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def sources(directory, *, fetch=False):
    records = {}
    for relative, expected in SOURCES.items():
        path = directory / relative
        url = f'https://raw.githubusercontent.com/u-boot/u-boot/{COMMIT}/{relative}'
        if fetch and not path.exists():
            with urllib.request.urlopen(url, timeout=25) as response:
                data = response.read(256 * 1024 + 1)
            if len(data) > 256 * 1024 or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Pinned upstream FAT source differs: ' + relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(data)
            path.chmod(0o444)
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise ValueError('Pinned upstream FAT source differs: ' + relative)
        records[relative] = dict(sha256=expected, bytes=path.stat().st_size, url=url)
    return dict(commit=COMMIT, unchanged=True, exact_vendor_source=False, files=records)


def run(*arguments, allowed=(0,)):
    result = subprocess.run([str(value) for value in arguments], capture_output=True,
                            text=True, timeout=60)
    if result.stdout:
        print(result.stdout, end='', flush=True)
    if result.stderr:
        print(result.stderr, end='', flush=True)
    if result.returncode not in allowed:
        raise RuntimeError(f'{arguments[0]} exited {result.returncode}')
    return result


@contextlib.contextmanager
def mounted_fat(image, mount, shortname):
    """Only a newly allocated loop on a fixture-owned regular image is touched."""
    if image.is_symlink() or not image.is_file() or image.stat().st_size != VOLUME_BYTES:
        raise ValueError('Expected the new regular fixture volume')
    device = run('losetup', '--find').stdout.strip()
    if not device.startswith('/dev/loop') or not device.removeprefix('/dev/loop').isdigit():
        raise ValueError('Unexpected free loop device')
    node = Path(device)
    major, minor = map(int, (Path('/sys/class/block') / node.name / 'dev').read_text().strip().split(':'))
    expected = os.makedev(major, minor)
    if not node.exists() and not node.is_symlink():
        os.mknod(node, stat.S_IFBLK | 0o600, expected)
    if node.is_symlink() or not stat.S_ISBLK(node.stat().st_mode) or node.stat().st_rdev != expected:
        raise ValueError('Fixture loop node identity differs')
    run('losetup', device, image)
    try:
        if shortname not in ('mixed', 'winnt'):
            raise ValueError('Unsupported fixture shortname policy')
        run('mount', '-t', 'vfat', '-o', 'rw,shortname=' + shortname, device, mount)
        try:
            yield mount
        finally:
            run('umount', mount)
    finally:
        run('losetup', '--detach', device)


def audit(image, short_alias=b'NEXT    SCR'):
    """Independent FAT16 directory/chain reader, not the U-Boot implementation."""
    with image.open('rb') as stream:
        header = stream.read(512)
        if len(header) != 512 or header[510:] != b'\x55\xaa':
            raise ValueError('Invalid fixture FAT boot sector')
        sector = struct.unpack_from('<H', header, 11)[0]
        per_cluster = header[13]
        reserved = struct.unpack_from('<H', header, 14)[0]
        fats = header[16]
        entries = struct.unpack_from('<H', header, 17)[0]
        fat_sectors = struct.unpack_from('<H', header, 22)[0]
        total = struct.unpack_from('<H', header, 19)[0] or struct.unpack_from('<I', header, 32)[0]
        if sector != 512 or per_cluster not in (1, 2, 4, 8, 16, 32, 64, 128) or not entries or fats != 2:
            raise ValueError('Unsupported fixture FAT geometry')
        root_start = (reserved + fats * fat_sectors) * sector
        data_start = root_start + (entries * 32 + sector - 1) // sector * sector
        clusters = (total * sector - data_start) // (sector * per_cluster)
        if not 4085 <= clusters < 65525 or not fat_sectors:
            raise ValueError('Expected FAT16 fixture')
        stream.seek(reserved * sector)
        fat = stream.read(fat_sectors * sector)
        stream.seek(root_start)
        directory = stream.read(entries * 32)
        found, long_parts = [], []
        for offset in range(0, len(directory), 32):
            entry = directory[offset:offset + 32]
            if entry[0] == 0:
                break
            if entry[0] == 0xe5:
                long_parts = []
                continue
            if entry[11] == 0x0f:
                long_parts.append(entry[1:11] + entry[14:26] + entry[28:32])
                continue
            long_name = b''.join(reversed(long_parts)).decode('utf-16-le').split('\0', 1)[0].rstrip('\uffff')
            long_parts = []
            if entry[11] & 0x18 or entry[:11] != short_alias:
                continue
            size = struct.unpack_from('<I', entry, 28)[0]
            cluster = struct.unpack_from('<H', entry, 26)[0]
            if not 0 < size <= 65536:
                raise ValueError('Unexpected fixture payload size')
            content = bytearray()
            seen = set()
            while len(content) < size:
                if cluster in seen or not 2 <= cluster < clusters + 2:
                    raise ValueError('Invalid fixture FAT chain')
                seen.add(cluster)
                stream.seek(data_start + (cluster - 2) * sector * per_cluster)
                content += stream.read(sector * per_cluster)
                cluster = struct.unpack_from('<H', fat, cluster * 2)[0]
            found.append(dict(root_offset=root_start + offset, short_name=entry[:11].decode(),
                              ntres=entry[12], long_name=long_name or None, bytes=size,
                              sha256=hashlib.sha256(content[:size]).hexdigest(),
                              raw_entry=entry.hex()))
    return dict(short_alias=short_alias.decode(), bytes=image.stat().st_size,
                sector_bytes=sector, cluster_sectors=per_cluster,
                root_entries=entries, next_entries=found)


def atomic_next(mount, payload):
    """Match the selector's temp/fsync/replace/directory-fsync path exactly."""
    temporary = mount / '.selector-temporary'
    with temporary.open('xb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, mount / 'next.scr')
    fd = os.open(mount, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    presented = [path.name for path in mount.iterdir() if path.name.casefold() == 'next.scr']
    if presented != ['next.scr'] or (mount / 'next.scr').read_bytes() != payload:
        raise ValueError('Atomic replacement did not present one lowercase file with unchanged bytes')
    return presented


def worker(work):
    if os.geteuid() != 0:
        raise PermissionError('Linux FAT mounting requires the managed root fixture')
    original = sources(work / 'sources')
    input_before = {name: sha(ROOT / name) for name in INPUTS}
    shims = work / 'shims'
    for name in SHIMS:
        path = shims / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('/* Platform shim supplied by dev-fat-writer-fixture.c. */\n')
    binary = work / 'fat-writer'
    compile_result = run('cc', '-std=gnu11', '-O1', '-g', '-fsanitize=undefined',
        '-fno-sanitize-recover=all', '-Werror=implicit-function-declaration',
        '-I' + str(shims), '-I' + str(work / 'sources/include'),
        '-I' + str(work / 'sources/fs/fat'), ROOT / 'tools/dev-fat-writer-fixture.c', '-o', binary)
    (work / 'compile.log').write_text(compile_result.stdout + compile_result.stderr)
    original_payload = b'A' * 2653
    good = b'B' * 2266
    good_path = work / 'good.bin'
    good_path.write_bytes(good)
    mount = work / 'mount'
    mount.mkdir()
    results = []
    for name, filename, case_bits, shortname, long_name in (
            ('uppercase', 'NEXT.SCR', 0, 'mixed', None),
            ('lowercase-winnt', 'next.scr', 0x18, 'winnt', None),
            ('lowercase-mixed', 'next.scr', 0, 'mixed', 'next.scr'),
            ('migrate-distinct-backup', 'next.scr', 0, 'mixed', 'next.scr')):
        image = work / (name + '.fat16')
        with image.open('xb') as stream:
            stream.truncate(VOLUME_BYTES)
        run('mkfs.fat', '-F', '16', '-s', '4', '-n', 'NEOFIXTURE', image)
        migration = None
        with mounted_fat(image, mount, shortname):
            (mount / ('NEXT.SCR' if name == 'migrate-distinct-backup' else filename)).write_bytes(original_payload)
            os.sync()
        initial = audit(image)
        if name == 'migrate-distinct-backup':
            before_migration = initial
            if (len(initial['next_entries']) != 1 or initial['next_entries'][0]['ntres'] != 0 or
                    initial['next_entries'][0]['long_name'] is not None):
                raise ValueError('Migration must start with the original uppercase-only directory entry')
            with mounted_fat(image, mount, shortname):
                if (mount / 'OLDNEXT.SCR').exists():
                    raise ValueError('Fixture backup name must be fresh')
                os.rename(mount / 'NEXT.SCR', mount / 'OLDNEXT.SCR')
                directory_fd = os.open(mount, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                presented = atomic_next(mount, original_payload)
            initial = audit(image)
            backup = audit(image, b'OLDNEXT SCR')
            if (len(initial['next_entries']) != 1 or len(backup['next_entries']) != 1 or
                    any(record['next_entries'][0]['sha256'] != hashlib.sha256(original_payload).hexdigest()
                        for record in (initial, backup))):
                raise ValueError('Uppercase migration changed the original descriptor bytes')
            migration = dict(before=before_migration, after=initial, presented=presented,
                             backup=backup, descriptor_bytes_preserved=True,
                             strategy='distinct backup basename, then fresh lowercase atomic publication')
            save(work / 'uppercase-to-lowercase-migration.json', migration)
        if (len(initial['next_entries']) != 1 or initial['next_entries'][0]['ntres'] != case_bits or
                initial['next_entries'][0]['long_name'] != long_name):
            raise ValueError('Linux-created case metadata does not match the fixture')
        stages = [('first-write', good_path, good)]
        if name.startswith('lowercase'):
            stages += [('after-linux-atomic-replace', good_path, good),
                       ('repeated-write', work / 'different-good.bin', b'D' * 3879)]
        for stage, payload, expected in stages:
            if stage == 'after-linux-atomic-replace':
                with mounted_fat(image, mount, shortname):
                    atomic_next(mount, b'C' * 4301)
                replaced = audit(image)
                if (len(replaced['next_entries']) != 1 or replaced['next_entries'][0]['ntres'] != case_bits or
                        replaced['next_entries'][0]['long_name'] != long_name):
                    raise ValueError('Atomic Linux replacement lost lowercase FAT metadata')
                save(work / (name + '-linux-replace.json'), replaced)
            if not payload.exists():
                payload.write_bytes(expected)
            writer = run(binary, image, payload, filename)
            (work / f'{name}-{stage}-writer.log').write_text(writer.stdout + writer.stderr)
            outcome = json.loads(next(line.removeprefix('FIXTURE_RESULT ') for line in writer.stdout.splitlines()
                                      if line.startswith('FIXTURE_RESULT ')))
            observed = audit(image)
            if migration is not None and audit(image, b'OLDNEXT SCR') != migration['backup']:
                raise ValueError('Legacy writer changed the retained migration backup')
            check = run('fsck.fat', '-v', '-n', image, allowed=(0, 1))
            (work / f'{name}-{stage}-fsck.log').write_text(check.stdout + check.stderr)
            entries = observed['next_entries']
            if name == 'uppercase':
                if (len(entries) != 2 or outcome['matches_payload'] is not False or
                        entries[0]['sha256'] != hashlib.sha256(original_payload).hexdigest() or
                        entries[1]['sha256'] != hashlib.sha256(good).hexdigest() or
                        check.returncode == 0 or 'Duplicate directory entry' not in check.stdout + check.stderr):
                    raise ValueError('The unchanged 2018 writer did not reproduce the uppercase duplicate')
            elif (len(entries) != 1 or entries[0]['ntres'] != case_bits or entries[0]['long_name'] != long_name or
                    entries[0]['sha256'] != hashlib.sha256(expected).hexdigest() or
                    outcome['matches_payload'] is not True or check.returncode != 0):
                raise ValueError('Lowercase writer replacement or filesystem qualification failed')
            results.append(dict(case=name, stage=stage, shortname_policy=shortname, migration=migration,
                                initial=initial, writer=outcome,
                                after=observed, fsck_exit=check.returncode))
    if input_before != {name: sha(ROOT / name) for name in INPUTS} or sources(work / 'sources') != original:
        raise ValueError('Fixture or upstream source inputs changed during execution')
    result = dict(passed=True, inputs=input_before, sources=original, cases=results,
                  binary_sha256=sha(binary), limits='Native unchanged upstream2018 FAT code with POSIX '
                  'block I/O; Linux-created FAT16 entries. No exact vendor binary/controller/hush, '
                  'card, power-loss, boot or PM qualification.')
    save(work / 'result.json', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        worker(args.inside)
        return
    if not os.environ.get('NEO_BUILD_STAGE'):
        raise ValueError('Use the saved test:dev-fat-writer Task')
    from managed_container import execute
    work = ROOT / '.local/build/dev-fat-writer' / uuid.uuid4().hex
    work.mkdir(parents=True, mode=0o700)
    snapshot = work / 'inputs'
    for name in INPUTS:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        target.chmod(0o444)
    input_hashes = {name: sha(snapshot / name) for name in INPUTS}
    if input_hashes != {name: sha(ROOT / name) for name in INPUTS}:
        raise ValueError('Fixture inputs changed during snapshot')
    save(work / 'input-manifest.json', input_hashes)
    cache = ROOT / '.local/build/dev-fat-writer-source'
    manifest = sources(cache, fetch=True)
    shutil.copytree(cache, work / 'sources')
    save(work / 'source-manifest.json', manifest)
    builder = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']
    execute('dev-fat-writer', ['--pull=never', '--network=none', '--privileged',
        '--platform=' + builder['platform'], '--memory=512m', '--cpus=1', '--pids-limit=128',
        '--entrypoint=python3', '-v', f'{ROOT}:/project:ro', '-v', f'{work}:/fixture',
        builder['image'], '/fixture/inputs/tools/check-dev-fat-writer.py', '--inside', '/fixture'],
        work / 'managed', timeout=180)
    result = json.loads((work / 'result.json').read_text())
    if result.get('passed') is not True or result['inputs'] != {name: sha(ROOT / name) for name in INPUTS}:
        raise ValueError('FAT writer fixture did not pass')
    print('Retained FAT writer qualification:', work.relative_to(ROOT))


if __name__ == '__main__':
    main()
