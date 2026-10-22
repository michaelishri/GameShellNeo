#!/usr/bin/env python3
"""Plan an offline p3 replacement while running the original recovery root.

The explicit --apply mode owns a durable p2 ledger and an exclusive kernel
block-device claim. It never writes FAT, registers/selects a release or reboots.
An interrupted destructive attempt requires inspection; it cannot be retried
by choosing another state directory.
"""
import argparse
import contextlib
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import zlib

CHUNK = 4 * 1024 * 1024
METADATA_LIMIT = 16 * 1024 * 1024
SPACE_MARGIN = 64 * 1024 * 1024
REGISTRY = Path('/var/lib/gameshellneo-development-store-installer')
BLKGETSIZE64 = 0x80081272


def require(condition, message):
    if not condition:
        raise ValueError(message)


def real_path(value, *, exists=True):
    path = Path(value)
    require(path.is_absolute() and '..' not in path.parts, 'Use an absolute path without parent traversal')
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'Symlinks are not admitted: ' + str(path))
    if exists:
        path.stat()
    return path


@contextlib.contextmanager
def regular_file(path, *, private_root=False):
    path = real_path(path)
    if private_root:
        root_directory(path.parent, Path('/').stat().st_dev)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb', buffering=0) as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode), 'Expected a regular file: ' + str(path))
        if private_root:
            require(info.st_uid == 0 and not info.st_mode & 0o077,
                    'Admission records must be private root-owned files')
        yield stream


def read_record(path, *, private_root=False):
    with regular_file(path, private_root=private_root) as stream:
        data = stream.read(METADATA_LIMIT + 1)
    require(len(data) <= METADATA_LIMIT, 'Admission record exceeds its bound')
    value = json.loads(data)
    require(isinstance(value, dict), 'Expected a JSON admission object')
    return value, data


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_record(path, value):
    temporary = path.with_name(path.name + '.new')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def root_directory(path, device):
    path = real_path(path)
    for part in (path, *path.parents):
        info = part.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                'Installer state ancestors must be root-owned and not group/world writable')
    require(path.stat().st_dev == device, 'Installer state must stay on the running recovery filesystem')
    return path


class Operation:
    def __init__(self, path, registry, initial):
        self.path, self.registry = path, registry
        path.mkdir(mode=0o700)
        sync_directory(path.parent)
        self.record = dict(initial, schema=1, operation='development-store-install',
                           write_started=False, completed=False, phase='admission', events=[])
        self.log = (path / 'operation.log').open('xb', buffering=0)
        self.update('admission')
        save_record(registry / 'latest.json', {'state': str(path)})

    def update(self, phase, **values):
        self.record.update(values, phase=phase)
        self.record['events'].append({'phase': phase, **values})
        save_record(self.path / 'state.json', self.record)

    def close(self):
        self.log.close()


@contextlib.contextmanager
def ownership(state, initial, *, registry=REGISTRY):
    device = Path('/').stat().st_dev
    root_directory(registry.parent, device)
    if not registry.exists():
        registry.mkdir(mode=0o700)
        sync_directory(registry.parent)
    root_directory(registry, device)
    descriptor = os.open(registry / 'writer.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'rb', buffering=0) as lock:
        info = os.fstat(lock.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o077,
                'Invalid installer ownership lock')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another development-store installer owns the recovery lock') from error
        latest = registry / 'latest.json'
        if latest.exists() or latest.is_symlink():
            previous, _ = read_record(latest, private_root=True)
            old = root_directory(real_path(previous['state']).parent, device) / Path(previous['state']).name
            record, _ = read_record(old / 'state.json', private_root=True)
            require(not record.get('write_started') or record.get('completed') is True,
                    'Previous destructive attempt is unresolved; inspect its retained state, do not retry')
        state = real_path(state, exists=False)
        root_directory(state.parent, device)
        require(not state.exists(), 'Use a fresh unique state directory; retained attempts cannot be reused')
        operation = Operation(state, registry, initial)
        try:
            yield operation
        except BaseException as error:
            message = type(error).__name__ + ': ' + str(error)
            try:
                operation.update('failed', error=message)
            except BaseException as persistence_error:
                operation.log.write((message + '\nFailure state persistence: ' +
                                     repr(persistence_error) + '\n').encode())
                os.fsync(operation.log.fileno())
            raise
        finally:
            operation.close()


def command(arguments, *, log=None, pass_fds=()):
    result = subprocess.run([str(item) for item in arguments], check=False,
                            stdout=log or subprocess.PIPE, stderr=log or subprocess.PIPE,
                            pass_fds=pass_fds)
    if log is not None:
        os.fsync(log.fileno())
    require(result.returncode == 0, 'Command failed: ' + str(arguments[0]) + ' (exit ' + str(result.returncode) + ')')
    return result.stdout


def unescape_mount(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def mounts(path=Path('/proc/self/mountinfo')):
    result = []
    for line in path.read_text().splitlines():
        fields = line.split()
        separator = fields.index('-')
        result.append(dict(device=fields[2], root=unescape_mount(fields[3]),
                           point=unescape_mount(fields[4]), options=fields[5].split(','),
                           filesystem=fields[separator + 1], source=unescape_mount(fields[separator + 2]),
                           super_options=fields[separator + 3].split(',')))
    return result


def device_number(number):
    return f'{os.major(number)}:{os.minor(number)}'


def block_partition(number):
    """Resolve only the kernel's canonical partition, never a /dev/disk alias."""
    sysfs = (Path('/sys/dev/block') / number).resolve(strict=True)
    partition = int((sysfs / 'partition').read_text())
    parent = sysfs.parent
    node = real_path('/dev/' + sysfs.name)
    info = node.stat()
    require(stat.S_ISBLK(info.st_mode) and device_number(info.st_rdev) == number,
            'Canonical partition node differs from sysfs')
    return dict(node=str(node), number=partition, device=number, sysfs=str(sysfs),
                parent=str(parent), start_sector=int((sysfs / 'start').read_text()),
                bytes=int((sysfs / 'size').read_text()) * 512)


def partition_set(root):
    parent = Path(root['parent'])
    result = {}
    for path in parent.iterdir():
        if not (path / 'partition').is_file():
            continue
        part = block_partition((path / 'dev').read_text().strip())
        require(part['number'] not in result, 'Ambiguous card partition number')
        result[part['number']] = part
    require(set(result) == {1, 2, 3}, 'Expected exactly boot, recovery and development-store partitions')
    return result


def filesystem(node):
    output = command(['blkid', '-p', '-o', 'export', node]).decode()
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def unique_partuuids(expected):
    found = {value: [] for value in expected}
    for event in Path('/sys/class/block').glob('*/uevent'):
        values = dict(line.split('=', 1) for line in event.read_text().splitlines() if '=' in line)
        value = values.get('PARTUUID')
        if value in found:
            found[value].append(event.parent.name)
    require(all(len(names) == 1 for names in found.values()), 'Missing or duplicated card PARTUUID')


def mounted_at(path, records, *, device=None, filesystem_type=None):
    path = real_path(path)
    matching = [record for record in records if record['point'] == str(path)]
    require(len(matching) == 1, 'Expected one exact mount at ' + str(path))
    record = matching[0]
    require(record['root'] == '/', 'Bind or directory-root mounts are not admitted')
    if device is not None:
        require(record['device'] == device, 'Mount belongs to another block device')
        require(len([item for item in records if item['device'] == device]) == 1,
                'The partition has multiple mounts or bind aliases')
    if filesystem_type is not None:
        require(record['filesystem'] == filesystem_type, 'Unexpected mounted filesystem type')
    return record


def gzip_chunks(stream, expected_bytes):
    total = 0
    stream.seek(0)
    try:
        with gzip.GzipFile(fileobj=stream, mode='rb') as source:
            while data := source.read(min(CHUNK, expected_bytes - total + 1)):
                total += len(data)
                require(total <= expected_bytes, 'Decompressed store exceeds its exact declared size')
                yield data
    except (OSError, EOFError, zlib.error) as error:
        raise ValueError('Invalid or truncated gzip store archive') from error
    require(total == expected_bytes, 'Decompressed store is truncated')


def verify_archive(stream, compressed, raw):
    stream.seek(0)
    calculated = hashlib.sha256()
    total = 0
    while data := stream.read(CHUNK):
        total += len(data)
        require(total <= compressed['bytes'], 'Compressed store exceeds its declared size')
        calculated.update(data)
    require((total, calculated.hexdigest()) == (compressed['bytes'], compressed['sha256']),
            'Compressed store size or SHA-256 differs')
    calculated = hashlib.sha256()
    for data in gzip_chunks(stream, raw['bytes']):
        calculated.update(data)
    require(calculated.hexdigest() == raw['sha256'], 'Decompressed store SHA-256 differs')


def snapshot_archive(path, operation, compressed):
    available = os.statvfs(operation.path)
    require(available.f_bavail * available.f_frsize >= compressed['bytes'] + SPACE_MARGIN,
            'Recovery filesystem lacks space for a private verified archive and evidence')
    output = operation.path / 'archive.img.gz'
    calculated, total = hashlib.sha256(), 0
    with regular_file(path) as source, output.open('xb', buffering=0) as target:
        os.fchmod(target.fileno(), 0o600)
        while data := source.read(CHUNK):
            total += len(data)
            require(total <= compressed['bytes'], 'Uploaded archive exceeds its declared size')
            calculated.update(data)
            write_all(target.fileno(), data)
        os.fsync(target.fileno())
    sync_directory(operation.path)
    require((total, calculated.hexdigest()) == (compressed['bytes'], compressed['sha256']),
            'Uploaded archive size or SHA-256 differs')
    return output


def write_all(descriptor, data):
    remaining = memoryview(data)
    while remaining:
        try:
            written = os.write(descriptor, remaining)
        except InterruptedError:
            continue
        require(0 < written <= len(remaining), 'Block write made no valid progress')
        remaining = remaining[written:]


def write_and_readback(descriptor, source, raw, *, progress=None):
    """Internal FD core; the public caller admits and exclusively claims a block node."""
    os.lseek(descriptor, 0, os.SEEK_SET)
    calculated, total = hashlib.sha256(), 0
    for data in gzip_chunks(source, raw['bytes']):
        write_all(descriptor, data)
        calculated.update(data)
        total += len(data)
        if progress is not None:
            progress(total)
    require((total, calculated.hexdigest()) == (raw['bytes'], raw['sha256']), 'Written source pin differs')
    os.fsync(descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)
    calculated, remaining = hashlib.sha256(), raw['bytes']
    while remaining:
        try:
            data = os.read(descriptor, min(CHUNK, remaining))
        except InterruptedError:
            continue
        require(bool(data), 'Block readback ended before the declared boundary')
        calculated.update(data)
        remaining -= len(data)
    require(calculated.hexdigest() == raw['sha256'], 'Full block readback SHA-256 differs')
    return {'bytes': raw['bytes'], 'sha256': calculated.hexdigest()}


@contextlib.contextmanager
def exclusive_device(target):
    path = real_path(target['node'])
    descriptor = os.open(path, os.O_RDWR | os.O_EXCL | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISBLK(info.st_mode) and device_number(info.st_rdev) == target['device'],
                'Exclusive descriptor is not the admitted block partition')
        size = struct.unpack('Q', fcntl.ioctl(descriptor, BLKGETSIZE64, bytes(8)))[0]
        require(size == target['bytes'], 'Claimed block size differs from the admitted target')
        require(not any(record['device'] == target['device'] for record in mounts()),
                'Target remains mounted after its exclusive claim')
        yield descriptor
    finally:
        os.close(descriptor)


def verify_file_pins(directory, pins):
    for relative, expected in pins.items():
        path = Path(relative)
        require(not path.is_absolute() and path.parts and
                all(part not in ('.', '..') for part in path.parts), 'Unsafe pinned relative path')
        with regular_file(directory / path) as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        require(actual == expected, 'Saved admission file changed: ' + relative)


def recovery_identity(backup, *, root=Path('/'), cmdline=Path('/proc/cmdline'),
                      boot_id=Path('/proc/sys/kernel/random/boot_id')):
    identity, data = read_record(root / 'etc/gameshellneo/image.json')
    require('deployment' not in identity and identity.get('root_partuuid') == backup['root']['root_partuuid'] and
            identity.get('board') == backup['card']['board'] and
            identity.get('kernel') == backup['root']['kernel'] == os.uname().release and
            hashlib.sha256(data).hexdigest() == backup['root']['image_sha256'],
            'Installer requires the original fixed recovery identity')
    for marker in (root / 'etc/gameshellneo/development-slot', root / 'run/gameshellneo-development-slot'):
        require(not marker.exists() and not marker.is_symlink(), 'A development-directory root is not admitted')
    require(not any(arg.startswith('neo.') for arg in cmdline.read_text().split()),
            'Development command-line arguments are not admitted')
    require(boot_id.read_text().strip() == backup['root']['boot_id'], 'Boot changed since the verified backup')
    return identity


def runtime_admission(args, manifest, backup, *, verify_boot):
    """Read the mounted old store without holding a store-side lock or descriptor."""
    recovery_identity(backup)
    records = mounts()
    root_mount = mounted_at(Path('/'), records, device=device_number(Path('/').stat().st_dev),
                            filesystem_type='ext4')
    recovery = block_partition(root_mount['device'])
    require(recovery['number'] == 2, 'Running root is not the fixed recovery partition')
    parts = partition_set(recovery)
    parent = Path(recovery['parent'])
    actual_parent = dict(bytes=int((parent / 'size').read_text()) * 512,
                         cid=(parent / 'device/cid').read_text().strip(),
                         sector_bytes=int((parent / 'queue/logical_block_size').read_text()))
    require(all(actual_parent[key] == backup['parent'][key] for key in actual_parent),
            'Current parent card CID, capacity or sector size differs from the verified backup')
    require(actual_parent['bytes'] >= manifest['target']['parent_minimum_bytes'], 'Card is smaller than the package geometry')
    identities = []
    for number, name in ((1, 'boot'), (2, 'recovery'), (3, 'store')):
        part, saved = parts[number], backup['partitions'][name]
        require(part['parent'] == recovery['parent'] and
                all(part[key] == saved[key] for key in ('start_sector', 'bytes')),
                'Partition parent or geometry differs from the verified backup: ' + name)
        values = filesystem(part['node'])
        require(values.get('PART_ENTRY_UUID') == saved['partuuid'] and
                values.get('UUID') == saved['filesystem_uuid'] and
                values.get('TYPE') == ('vfat' if number == 1 else 'ext4'),
                'Partition filesystem/PARTUUID identity differs: ' + name)
        identities.append(saved['partuuid'])
    unique_partuuids(identities)
    boot_mount = mounted_at(args.boot, records, device=parts[1]['device'], filesystem_type='vfat')
    require('shortname=mixed' in boot_mount['super_options'] + boot_mount['options'],
            'Boot FAT must use shortname=mixed')
    mounted_at(args.store, records, device=parts[3]['device'], filesystem_type='ext4')
    require(parts[3]['device'] != root_mount['device'], 'Refusing to replace the running root')
    verify_boot(args.boot, manifest)
    names = [path.name for path in args.boot.iterdir()]
    for name, expected in backup['flags'].items():
        require([entry for entry in names if entry.casefold() == name] == [name],
                'Boot flags must have unique lowercase directory entries')
        verify_file_pins(args.boot, {name: expected})
    card, _ = read_record(args.store / 'DEVBOOT.JSON')
    catalog, _ = read_record(args.store / 'RELEASES.JSON')
    require(card == backup['card'] and catalog == backup['catalog'],
            'Old store card/catalog differs from the backup admission')
    verify_file_pins(args.store, backup['store_files'])
    return dict(root_device=root_mount['device'], target=parts[3], parent=actual_parent,
                boot_id=backup['root']['boot_id'])


def check_installer_location(root_device):
    for path in (Path(__file__).absolute(), Path(__file__).with_name('dev_store.py').absolute()):
        root_directory(path.parent, Path('/').stat().st_dev)
        with regular_file(path, private_root=False) as stream:
            info = os.fstat(stream.fileno())
            require(device_number(info.st_dev) == root_device and info.st_uid == 0 and not info.st_mode & 0o022,
                    'Stage the installer and shared validator as root-owned files on fixed recovery p2')


def verify_new_admin(args, manifest, operation):
    """Run only the pinned administration tree from the fully verified new store."""
    tools = args.store / 'admin/tools'
    code = '''import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from dev_systems import Card, boot_bundle, child, sha
from dev_bundle import _metadata
card = Card(pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]))
assert card.releases == {}, 'New store catalog must remain empty'
directory = child(card.store, 'systems/' + sys.argv[4])
release, digest = _metadata(directory, sys.argv[4], card.record['store_partuuid'])
assert digest == sys.argv[5], 'New store manifest differs'
assert release['kernel'] == sys.argv[6], 'New store kernel differs'
assert boot_bundle(directory / 'boot', True) == release['boot_files'], 'New store boot assets differ'
for relative, expected in release['immutable_files'].items():
    assert sha(child(directory / 'root', relative)) == expected, 'New store immutable input differs'
print(json.dumps({'complete_slot': sys.argv[4], 'catalog_unchanged': True}))
'''
    command([sys.executable, '-I', '-c', code, tools, args.boot, args.store,
             manifest['slot']['id'], manifest['slot']['manifest_sha256'], manifest['slot']['kernel']],
            log=operation.log)


def replace_store(args, manifest, backup, operation, admitted, schema):
    snapshot = snapshot_archive(args.archive, operation, manifest['archive'])
    with regular_file(snapshot, private_root=True) as source:
        verify_archive(source, manifest['archive'], manifest['raw'])
        operation.update('archive-verified')
        # Hashes, mount aliases, card geometry and boot identity must still match
        # after the potentially long copy/decompression. All old-store readers
        # have closed before the clean unmount below.
        again = runtime_admission(args, manifest, backup, verify_boot=schema.verify_boot)
        require(again == admitted, 'Admission changed while preparing the private archive')
        operation.update('unmounting-store')
        command(['umount', '--', args.store], log=operation.log)
        require(not any(item['device'] == admitted['target']['device'] for item in mounts()),
                'Store remains mounted; refusing a block write')
        require(not any(args.store.iterdir()), 'Unmounted store mountpoint must be empty')
        operation.update('claiming-target')
        with exclusive_device(admitted['target']) as descriptor:
            # Durable before the first write, including a crash during that write.
            operation.update('writing', write_started=True, written_bytes=0)
            result = write_and_readback(descriptor, source, manifest['raw'],
                progress=lambda count: operation.update('writing', written_bytes=count))
            operation.update('readback-verified', readback=result)
            command(['e2fsck', '-f', '-n', '/proc/self/fd/' + str(descriptor)],
                    log=operation.log, pass_fds=(descriptor,))
            operation.update('filesystem-verified')
    # No failure above reaches this mount. The exclusive kernel claim has now
    # closed after the complete byte readback and a non-writing filesystem check.
    schema.verify_boot(args.boot, manifest)
    recovery_identity(backup)
    operation.update('mounting-new-store')
    command(['mount', '-t', 'ext4', '-o', 'rw,noatime', '--', admitted['target']['node'], args.store],
            log=operation.log)
    try:
        mounted_at(args.store, mounts(), device=admitted['target']['device'], filesystem_type='ext4')
        identity = filesystem(admitted['target']['node'])
        require(identity.get('UUID') == manifest['raw']['filesystem_uuid'], 'New store filesystem UUID differs')
        schema.verify_store(args.store, manifest)
        verify_new_admin(args, manifest, operation)
        schema.verify_boot(args.boot, manifest)
        recovery_identity(backup)
    except BaseException:
        # A verified image may still fail post-mount admission. Do not select it;
        # attempt only a clean unmount and retain both errors if it is now busy.
        try:
            command(['umount', '--', args.store], log=operation.log)
        except BaseException as error:
            operation.update('post-mount-cleanup-failed', cleanup_error=type(error).__name__ + ': ' + str(error))
        raise
    operation.update('complete', completed=True, boot_selection_changed=False,
                     registered=False, reboot_performed=False, filesystem_check='passed')
    return operation.record


def run_install(args):
    if args.apply:
        require(os.geteuid() == 0, '--apply requires real root privileges')
        check_installer_location(device_number(Path('/').stat().st_dev))
    # This module is staged alongside this program on p2. No p3 administration
    # module is imported until after its new block image has been verified.
    import dev_store as schema
    args.boot, args.store = real_path(args.boot), real_path(args.store)
    loaded_manifest = schema.load_json(args.manifest)
    loaded_backup = schema.load_json(args.backup_receipt)
    manifest, manifest_data = read_record(args.manifest, private_root=args.apply)
    backup, backup_data = read_record(args.backup_receipt, private_root=args.apply)
    require(manifest == loaded_manifest and backup == loaded_backup, 'Admission inputs changed while reading')
    schema.validate_manifest(manifest)
    schema.validate_backup(backup, manifest)
    admitted = runtime_admission(args, manifest, backup, verify_boot=schema.verify_boot)
    args.state = real_path(args.state, exists=False)
    root_directory(args.state.parent, Path('/').stat().st_dev)
    require(not args.state.exists(), 'Use a fresh unique state directory')
    if not args.apply:
        with regular_file(args.archive) as source:
            verify_archive(source, manifest['archive'], manifest['raw'])
        result = dict(plan=True, executed=False, admitted=admitted, state=str(args.state),
                      boot_selection_changed=False, registered=False, reboot_performed=False)
        print(json.dumps(result, indent=2))
        return result
    check_installer_location(admitted['root_device'])
    initial = dict(admission=admitted, manifest_sha256=hashlib.sha256(manifest_data).hexdigest(),
                   backup_receipt_sha256=hashlib.sha256(backup_data).hexdigest())
    with ownership(args.state, initial) as operation:
        with (operation.path / 'manifest.json').open('xb') as stream:
            stream.write(manifest_data)
            stream.flush()
            os.fsync(stream.fileno())
        with (operation.path / 'backup-receipt.json').open('xb') as stream:
            stream.write(backup_data)
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(operation.path)
        result = replace_store(args, manifest, backup, operation, admitted, schema)
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'manifest', 'backup-receipt', 'boot', 'store', 'state'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='Replace admitted, unmounted p3; never change boot selection')
    args = parser.parse_args()
    if args.apply and os.geteuid() != 0:
        parser.error('--apply requires real root privileges')
    os.umask(0o077)
    run_install(args)


if __name__ == '__main__':
    main()
