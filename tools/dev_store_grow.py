#!/usr/bin/env python3
"""Plan an offline development-store expansion from the original recovery root.

Only --apply writes. It requires a fresh verified off-device backup receipt,
an isolated private mount namespace, and durable ownership on recovery p2.
The worker never selects a release, reboots, retries, shrinks, or rolls back.
"""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys


def _sibling(name, filename):
    path = Path(__file__).with_name(filename)
    if __name__ == '__main__' and '--apply' in sys.argv:
        # Check before executing imported code with device-writing privileges.
        for ancestor in (path.absolute(), *path.absolute().parents):
            info = ancestor.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('Apply dependencies must have secure root-owned paths on recovery')
        if path.stat().st_dev != Path('/').stat().st_dev:
            raise ValueError('Apply dependencies must be staged on original recovery p2')
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


# Keep the bootstrap's published geometry guards and receipts unchanged. Its
# native ioctl, canonical block identity, exclusion, and durable ledger helpers
# are shared by importing an independent module instance.
installer = _sibling('_development_store_growth_installer', 'install-dev-store.py')
schema = _sibling('_development_store_growth_schema', 'dev_store.py')
require = installer.require
real_path = installer.real_path
read_record = installer.read_record
save_record = installer.save_record
sync_directory = installer.sync_directory
root_directory = installer.root_directory
exclusive_device = installer.exclusive_device
filesystem = installer.filesystem
device_number = installer.device_number
mounts = installer.mounts

REGISTRY = Path('/var/lib/gameshellneo-development-store-grower')
BACKUP_REGISTRY = Path('/var/lib/gameshellneo-development-store-grow-backup')
PREFIX_BYTES = 16 * 1024 * 1024
SECTOR_BYTES = 512
P3_LENGTH = slice(490, 494)
PHYSICAL_BYTES = 64013467648
PHYSICAL_DISK = 'b9dab681'
PHYSICAL_IMAGE = 'd45bcea1e79e9d2518c9e8632642183eb06387a0868cce75e78838f50fd0faf9'
PHYSICAL_KERNEL = '6.18.54-gameshellneo24'
PHYSICAL_STORE_UUID = '905c31f6-8d2a-486c-8c57-ca1fd23ecd36'
RECOVERY_FLAG_SHA256 = 'dce033ba9041858b244d2f15c1f1b3111057d93756f64b07f02c73ec0de1ef84'
PARTITION_METHOD = 'sfdisk-surrogate-then-single-length-pwrite'


def validate_backup(backup):
    """Validate a complete unmounted checkpoint; do not trust attestation flags alone.

    Geometry is structural here so a disposable loop fixture exercises the
    same execution core. The public CLI additionally admits the one physical
    card and original root in runtime_admission(). No bypass is exposed.
    """
    schema._keys(backup, ('schema', 'operation', 'development_only', 'verified', 'root',
                          'parent', 'partitions', 'regions', 'mbr_hex',
                          'protected_prefix_sha256', 'card', 'catalog', 'flags',
                          'store_files', 'evidence'))
    require(type(backup['schema']) is int and backup['schema'] == 1 and
            backup['operation'] == 'development-store-growth-backup' and
            backup['development_only'] is True and backup['verified'] is True,
            'Expected a fully verified development-store growth backup')
    disk = schema._card(backup['card'])
    root = backup['root']
    schema._keys(root, ('boot_id', 'root_partuuid', 'directory_deployment', 'image_sha256', 'kernel'))
    schema._uuid(root['boot_id'])
    schema._digest(root['image_sha256'])
    schema._pattern(root['kernel'], '[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}', 'recovery kernel')
    require(root['root_partuuid'] == disk + '-02' and root['directory_deployment'] is False,
            'Backup must originate from fixed recovery p2')
    parent = backup['parent']
    schema._keys(parent, ('cid', 'bytes', 'sector_bytes', 'partuuid_prefix'))
    schema._pattern(parent['cid'], '[0-9a-f]{32}', 'SD-card CID')
    schema._integer(parent['bytes'])
    require(type(parent['sector_bytes']) is int and parent['sector_bytes'] == SECTOR_BYTES and
            parent['bytes'] % SECTOR_BYTES == 0 and parent['partuuid_prefix'] == disk,
            'Backup parent identity or sector geometry differs')
    end = schema._partitions(backup['partitions'], disk, filesystems=True)
    require(end < parent['bytes'] and parent['bytes'] // SECTOR_BYTES <= 0xffffffff,
            'Expansion requires trailing unallocated space within MBR addressing')
    schema._pattern(backup['mbr_hex'], '[0-9a-f]{1024}', 'complete lowercase MBR hex')
    schema._digest(backup['protected_prefix_sha256'])
    mbr = bytes.fromhex(backup['mbr_hex'])
    require(mbr[510:] == b'\x55\xaa' and not any(mbr[494:510]) and
            f'{struct.unpack("<I", mbr[440:444])[0]:08x}' == disk,
            'Checkpoint MBR signature, disk identity or partition count differs')
    for number, name in enumerate(('boot', 'recovery', 'store'), 1):
        part = backup['partitions'][name]
        entry = struct.unpack('<B3sB3sII', mbr[446 + 16 * (number - 1):462 + 16 * (number - 1)])
        require((entry[4], entry[5]) == (part['start_sector'], part['bytes'] // SECTOR_BYTES) and
                entry[0] in (0, 0x80) and entry[2] in ((0x0b, 0x0c, 0x0e) if number == 1 else (0x83,)),
                'Checkpoint MBR partition geometry or type differs: ' + name)
    require(backup['partitions']['boot']['start_sector'] * SECTOR_BYTES >= PREFIX_BYTES,
            'Reserved bootloader checkpoint overlaps the first partition')
    schema._keys(backup['regions'], ('prefix', 'boot', 'store'))
    filenames = set()
    for name, region in backup['regions'].items():
        schema._keys(region, ('file', 'offset_bytes', 'raw_bytes', 'raw_sha256', 'gzip_bytes',
                              'gzip_sha256', 'source_unmounted', 'verified_full_decompressed'))
        schema._basename(region['file'])
        schema._digest(region['raw_sha256'])
        schema._digest(region['gzip_sha256'])
        schema._integer(region['gzip_bytes'])
        expected = ((0, PREFIX_BYTES) if name == 'prefix' else
                    (backup['partitions'][name]['start_sector'] * SECTOR_BYTES,
                     backup['partitions'][name]['bytes']))
        require(type(region['offset_bytes']) is int and type(region['raw_bytes']) is int and
                (region['offset_bytes'], region['raw_bytes']) == expected and
                region['source_unmounted'] is True and region['verified_full_decompressed'] is True and
                region['file'].endswith('.gz') and region['file'] not in filenames and
                region['gzip_bytes'] <= region['raw_bytes'] * 2,
                'Backup region is incomplete, ambiguous or not verified while unmounted: ' + name)
        filenames.add(region['file'])
    schema._catalog(backup['catalog'])
    schema._keys(backup['flags'], schema.FLAGS)
    for digest in backup['flags'].values():
        schema._digest(digest)
    require(len(set(backup['flags'].values())) == 1, 'Backup flags must all select fixed recovery')
    pins = schema._filemap(backup['store_files'])
    required = schema.ADMIN_FILES | {'DEVBOOT.JSON', 'RELEASES.JSON'}
    required |= {'systems/' + name + '/' + item for name in backup['catalog']
                 for item in ('release.json', 'source-image.json', 'source-fstab')}
    require(required <= pins.keys(), 'Backup lacks complete administration and release/source pins')
    require(pins['DEVBOOT.JSON'] == hashlib.sha256(schema.json_bytes(backup['card'])).hexdigest() and
            pins['RELEASES.JSON'] == hashlib.sha256(schema.json_bytes(backup['catalog'])).hexdigest() and
            all(pins['systems/' + name + '/release.json'] == entry['manifest_sha256']
                for name, entry in backup['catalog'].items()), 'Checkpoint card/catalog pins differ')
    schema._keys(backup['evidence'], ('admission_sha256', 'checkpoint_result_sha256'))
    for digest in backup['evidence'].values():
        schema._digest(digest)
    return backup


def growth_plan(backup):
    validate_backup(backup)
    store = backup['partitions']['store']
    target = backup['parent']['bytes'] // SECTOR_BYTES - store['start_sector']
    old = store['bytes'] // SECTOR_BYTES
    require(0 < old < target <= 0xffffffff, 'Refusing shrink, no-op or oversized expansion')
    return dict(sector_bytes=SECTOR_BYTES, parent_bytes=backup['parent']['bytes'],
                start_sector=store['start_sector'], old_sectors=old, target_sectors=target,
                old_bytes=store['bytes'], target_bytes=target * SECTOR_BYTES)


def command(arguments, *, log=None, input=None):
    """Run once without a timeout; an observer disconnect must not kill filesystem writes."""
    arguments = [str(value) for value in arguments]
    if log is not None:
        log.write((json.dumps(arguments) + '\n').encode())
        os.fsync(log.fileno())
    result = subprocess.run(arguments, input=input, stdout=log or subprocess.PIPE,
                            stderr=log or subprocess.PIPE, check=False)
    if log is not None:
        os.fsync(log.fileno())
    require(result.returncode == 0, 'Command failed: ' + arguments[0] +
            ' (exit ' + str(result.returncode) + ')')
    return result.stdout


def require_private_mount_namespace():
    require(os.readlink('/proc/self/ns/mnt') != os.readlink('/proc/1/ns/mnt'),
            '--apply requires unshare --mount --propagation private')
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        optional = fields[6:fields.index('-')]
        require(not any(value.startswith(('shared:', 'master:', 'propagate_from:')) or
                        value == 'unbindable' for value in optional),
                'Every mount must have private propagation before filesystem ownership handoffs')


def _read_block(node, offset, count):
    path = real_path(node)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(stat.S_ISBLK(os.fstat(descriptor).st_mode), 'Expected a canonical block node')
        data = bytearray()
        while len(data) < count:
            piece = os.pread(descriptor, count - len(data), offset + len(data))
            require(piece, 'Unexpected block-device EOF')
            data.extend(piece)
        return bytes(data)
    finally:
        os.close(descriptor)


def read_mbr(parent_node):
    return _read_block(parent_node, 0, SECTOR_BYTES)


def ext4_geometry(node):
    superblock = _read_block(node, 1024, 1024)
    require(superblock[56:58] == b'\x53\xef', 'Store lacks an ext4 superblock')
    log_block_bytes = struct.unpack_from('<I', superblock, 24)[0]
    require(log_block_bytes <= 6, 'Unsupported ext4 block size')
    features = struct.unpack_from('<III', superblock, 92)
    blocks = struct.unpack_from('<I', superblock, 4)[0]
    if features[1] & 0x80:
        blocks |= struct.unpack_from('<I', superblock, 336)[0] << 32
    block_bytes = 1024 << log_block_bytes
    return dict(bytes=blocks * block_bytes, block_bytes=block_bytes,
                features=features, uuid_hex=superblock[104:120].hex())


def hash_region(node, offset, length):
    path = real_path(node)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(stat.S_ISBLK(os.fstat(descriptor).st_mode), 'Expected a canonical block node')
        digest, remaining = hashlib.sha256(), length
        while remaining:
            data = os.pread(descriptor, min(installer.CHUNK, remaining), offset)
            require(data, 'Unexpected checkpoint source EOF')
            digest.update(data)
            offset += len(data)
            remaining -= len(data)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _block_size(part):
    path = real_path(part['node'])
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISBLK(info.st_mode) and device_number(info.st_rdev) == part['device'],
                'Canonical node identity differs from admission')
        return struct.unpack('Q', fcntl.ioctl(descriptor, installer.BLKGETSIZE64, bytes(8)))[0]
    finally:
        os.close(descriptor)


def writer_handles(devices, *, process_root=Path('/proc')):
    """Reject observable raw writers even when they ignore advisory locks.

    A nonexclusive writable block descriptor can predate our O_EXCL claim.
    Match its actual device number, including aliases, rather than its name.
    Exiting processes/descriptors are harmless; unreadable or malformed live
    records remain an admission failure. Only this worker's own claims are
    excluded. Filesystem utilities have exited at every caller boundary.
    """
    for process in process_root.iterdir():
        if not process.name.isdecimal() or int(process.name) == os.getpid():
            continue
        try:
            entries = list((process / 'fd').iterdir())
        except (FileNotFoundError, ProcessLookupError):
            continue
        for entry in entries:
            try:
                info = entry.stat()
                if not stat.S_ISBLK(info.st_mode) or device_number(info.st_rdev) not in devices:
                    continue
                fields = [line.split(maxsplit=1)[1:] for line in
                          (process / 'fdinfo' / entry.name).read_text().splitlines()
                          if line.startswith('flags:')]
                require(len(fields) == 1 and len(fields[0]) == 1 and
                        re.fullmatch('[0-7]+', fields[0][0]) is not None,
                        'Cannot verify access mode of an existing raw card descriptor')
                flags = int(fields[0][0], 8)
                require(flags & os.O_ACCMODE == os.O_RDONLY,
                        'A process has the card or one of its partitions open for raw writing' +
                        ' (PID ' + process.name + ', FD ' + entry.name + ')')
            except (FileNotFoundError, ProcessLookupError):
                continue


def assert_unmounted(admitted):
    parts = admitted['partitions']
    blocked = {parts[name]['device'] for name in ('boot', 'store')} | {admitted['parent']['device']}
    require(not any(record['device'] in blocked for record in mounts()),
            'Boot or store has mounted aliases; cleanly unmount both before expansion')
    for part in (*parts.values(), admitted['parent']):
        holders = Path('/sys/dev/block') / part['device'] / 'holders'
        require(holders.is_dir() and not any(holders.iterdir()), 'Card has device-mapper or other holders')
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        path = Path(installer.unescape_mount(line.split()[0]))
        info = path.stat()
        number = device_number(info.st_rdev if stat.S_ISBLK(info.st_mode) else info.st_dev)
        require(number not in blocked, 'Boot or store is in use as swap')
    writer_handles({admitted['parent']['device'], *(part['device'] for part in parts.values())})


def assert_geometry(admitted, *, grown=False):
    plan = admitted['growth']
    parent = admitted['parent']
    require(_block_size(parent) == plan['parent_bytes'], 'Parent kernel capacity changed')
    for name, part in admitted['partitions'].items():
        actual = installer.block_partition(part['device'])
        expected_bytes = plan['target_bytes'] if name == 'store' and grown else part['bytes']
        require(all(actual[key] == part[key] for key in ('node', 'device', 'number', 'parent', 'start_sector')) and
                actual['bytes'] == expected_bytes and _block_size(actual) == expected_bytes,
                'Kernel partition geometry or native block size differs: ' + name)
    mbr = read_mbr(parent['node'])
    require(mbr[510:] == b'\x55\xaa', 'Current MBR has no valid signature')
    for number, name in enumerate(('boot', 'recovery', 'store'), 1):
        start, size = struct.unpack('<II', mbr[454 + 16 * (number - 1):462 + 16 * (number - 1)])
        part = admitted['partitions'][name]
        expected_bytes = plan['target_bytes'] if name == 'store' and grown else part['bytes']
        require((start, size * SECTOR_BYTES) == (part['start_sector'], expected_bytes),
                'On-disk partition geometry differs from kernel admission: ' + name)


def _verify_identities(admitted, backup):
    identities = []
    for name, part in admitted['partitions'].items():
        saved, actual = backup['partitions'][name], filesystem(part['node'])
        require(actual.get('PART_ENTRY_UUID') == saved['partuuid'] and
                actual.get('UUID') == saved['filesystem_uuid'] and
                actual.get('TYPE') == ('vfat' if name == 'boot' else 'ext4'),
                'Filesystem UUID, type or PARTUUID differs: ' + name)
        identities.append(saved['partuuid'])
    installer.unique_partuuids(identities)


def runtime_admission(backup):
    """Public admission derives every canonical node from the actual running p2."""
    plan = growth_plan(backup)
    require(backup['parent']['partuuid_prefix'] == PHYSICAL_DISK and
            backup['parent']['bytes'] == PHYSICAL_BYTES and
            backup['root']['image_sha256'] == PHYSICAL_IMAGE and
            backup['root']['kernel'] == PHYSICAL_KERNEL and
            backup['partitions']['store']['filesystem_uuid'] == PHYSICAL_STORE_UUID and
            set(backup['catalog']) == {'diag25', 'diag27'} and
            backup['flags'] == {name: RECOVERY_FLAG_SHA256 for name in schema.FLAGS},
            'This command only admits the reviewed Samsung development card and original recovery')
    for name, expected in {'boot': (32768, 262144 * SECTOR_BYTES),
                           'recovery': (294912, 8093696 * SECTOR_BYTES),
                           'store': (8388608, 8388608 * SECTOR_BYTES)}.items():
        part = backup['partitions'][name]
        require((part['start_sector'], part['bytes']) == expected, 'Physical baseline geometry differs: ' + name)
    require(plan['target_sectors'] == 116637696, 'Physical expansion target differs')
    installer.recovery_identity(backup)
    records = mounts()
    root_number = device_number(Path('/').stat().st_dev)
    installer.mounted_at(Path('/'), records, device=root_number, filesystem_type='ext4')
    recovery = installer.block_partition(root_number)
    require(recovery['number'] == 2, 'Running root must be original fixed recovery p2')
    numbered = installer.partition_set(recovery)
    parent_path = Path(recovery['parent'])
    parent_node = real_path('/dev/' + parent_path.name)
    info = parent_node.stat()
    parent_number = (parent_path / 'dev').read_text().strip()
    require(stat.S_ISBLK(info.st_mode) and device_number(info.st_rdev) == parent_number,
            'Parent card node differs from root-derived sysfs identity')
    parent = dict(node=str(parent_node), device=parent_number,
                  bytes=int((parent_path / 'size').read_text()) * SECTOR_BYTES,
                  cid=(parent_path / 'device/cid').read_text().strip(),
                  sector_bytes=int((parent_path / 'queue/logical_block_size').read_text()),
                  partuuid_prefix=backup['parent']['partuuid_prefix'])
    require(all(parent[key] == value for key, value in backup['parent'].items()),
            'Current card CID, capacity, sector size or disk identity differs from the fresh backup')
    parts = {name: numbered[number] for number, name in enumerate(('boot', 'recovery', 'store'), 1)}
    for name, part in parts.items():
        require(part['parent'] == recovery['parent'] and
                all(part[key] == backup['partitions'][name][key] for key in ('start_sector', 'bytes')),
                'Root-derived partition differs from backup: ' + name)
    admitted = dict(root_device=root_number, parent=parent, partitions=parts, physical_admission=True,
                    growth=plan, boot_id=backup['root']['boot_id'])
    assert_unmounted(admitted)
    assert_geometry(admitted)
    _verify_identities(admitted, backup)
    require(read_mbr(parent['node']).hex() == backup['mbr_hex'], 'Current MBR differs from fresh checkpoint')
    return admitted


class GrowthOperation(installer.Operation):
    def update(self, phase, **values):
        self.record['operation'] = 'development-store-growth'
        super().update(phase, **values)


# ownership() refers to its module's Operation. This private import instance
# therefore keeps the exact bootstrap ledger semantics with the growth label.
installer.Operation = GrowthOperation


@contextlib.contextmanager
def _interlock(registry, name, description):
    root_device = Path('/').stat().st_dev
    root_directory(registry.parent, root_device)
    if not registry.exists():
        registry.mkdir(mode=0o700)
        sync_directory(registry.parent)
    root_directory(registry, root_device)
    descriptor = os.open(registry / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'rb', buffering=0) as lock:
        info = os.fstat(lock.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o077,
                'Invalid ' + description + ' ownership lock')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another ' + description + ' owns the card') from error
        yield


@contextlib.contextmanager
def ownership(state, initial, *, registry=REGISTRY):
    """Exclude checkpoints and bootstrap writes without rewriting their receipts."""
    with _interlock(BACKUP_REGISTRY, 'backup.lock', 'development-store checkpoint'), \
            _interlock(installer.REGISTRY, 'writer.lock', 'development-store installer'):
        latest = installer.REGISTRY / 'latest.json'
        if latest.exists() or latest.is_symlink():
            previous, _ = read_record(latest, private_root=True)
            record, _ = read_record(real_path(previous['state']) / 'state.json', private_root=True)
            require(not record.get('write_started') or record.get('completed') is True,
                    'An unresolved bootstrap attempt must be inspected before expansion')
        with installer.ownership(state, initial, registry=registry) as operation:
            yield operation


def _verify_source(admitted, backup):
    parent = admitted['parent']['node']
    require(read_mbr(parent).hex() == backup['mbr_hex'], 'MBR changed since checkpoint')
    for name, region in backup['regions'].items():
        require(hash_region(parent, region['offset_bytes'], region['raw_bytes']) == region['raw_sha256'],
                'Full unmounted source SHA-256 differs from checkpoint: ' + name)
    require(hash_region(parent, SECTOR_BYTES, PREFIX_BYTES - SECTOR_BYTES) ==
            backup['protected_prefix_sha256'], 'Reserved bootloader region changed')


def _verify_protected(admitted, backup, expected_mbr):
    parent = admitted['parent']['node']
    require(read_mbr(parent) == expected_mbr, 'MBR changed outside the admitted p3 length field')
    require(hash_region(parent, SECTOR_BYTES, PREFIX_BYTES - SECTOR_BYTES) ==
            backup['protected_prefix_sha256'], 'Reserved bootloader region changed')
    boot = backup['regions']['boot']
    require(hash_region(parent, boot['offset_bytes'], boot['raw_bytes']) == boot['raw_sha256'],
            'Boot partition changed during expansion')


def validate_partition_candidate(original, candidate, plan):
    """Use sfdisk's LBA validation while preserving the original physical CHS bytes.

    Modern libfdisk recalculates both CHS fields even for a size-only change.
    Those six bytes may differ on the disposable surrogate, but never on the
    actual card. Every other byte except p3's four-byte length must match.
    """
    require(len(original) == len(candidate) == SECTOR_BYTES and
            original[510:] == candidate[510:] == b'\x55\xaa',
            'Partition planner requires complete valid original and candidate MBRs')
    allowed = {*range(479, 482), *range(483, 486), *range(490, 494)}
    require(all(before == after for offset, (before, after) in enumerate(zip(original, candidate))
                if offset not in allowed),
            'Partition planner changed protected MBR bytes outside p3 CHS and length')
    require(original[482] == candidate[482] == 0x83 and
            struct.unpack_from('<II', original, 486) == (plan['start_sector'], plan['old_sectors']) and
            struct.unpack_from('<II', candidate, 486) == (plan['start_sector'], plan['target_sectors']) and
            0 < plan['old_sectors'] < plan['target_sectors'] <= 0xffffffff,
            'Partition planner changed p3 start, type, or exact growth target')
    expected = bytearray(original)
    expected[P3_LENGTH] = struct.pack('<I', plan['target_sectors'])
    return bytes(expected)


def plan_partition(admitted, backup, operation):
    """Run the actual sfdisk command on one private sparse surrogate, never the card."""
    original = bytes.fromhex(backup['mbr_hex'])
    surrogate = operation.path / 'partition-plan.img'
    descriptor = os.open(surrogate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.ftruncate(descriptor, admitted['parent']['bytes'])
        installer.write_all(descriptor, original)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    sync_directory(operation.path)
    operation.update('planning-partition', partition_method=PARTITION_METHOD,
                     surrogate={'file': surrogate.name, 'bytes': admitted['parent']['bytes'],
                                'initial_mbr_sha256': hashlib.sha256(original).hexdigest()})
    command(['sfdisk', '-N', '3', '--no-reread', '--no-tell-kernel', '--wipe', 'never',
             '--wipe-partitions', 'never', '--lock=nonblock', surrogate],
            log=operation.log,
            input=('size=' + str(admitted['growth']['target_sectors']) + '\n').encode())
    with installer.regular_file(surrogate) as stream:
        require(os.fstat(stream.fileno()).st_size == admitted['parent']['bytes'],
                'Partition surrogate capacity changed')
        candidate = stream.read(SECTOR_BYTES)
    expected = validate_partition_candidate(original, candidate, admitted['growth'])
    operation.update('partition-plan-verified', partition_method=PARTITION_METHOD,
                     surrogate={'file': surrogate.name, 'bytes': admitted['parent']['bytes'],
                                'initial_mbr_sha256': hashlib.sha256(original).hexdigest(),
                                'planned_mbr_sha256': hashlib.sha256(candidate).hexdigest()},
                     expected_mbr_sha256=hashlib.sha256(expected).hexdigest())
    return expected


def _write_length(descriptor, original, expected):
    """FD core: exactly one four-byte write, with no repair or short-write retry."""
    require(len(original) == len(expected) == SECTOR_BYTES and
            original[:490] == expected[:490] and original[494:] == expected[494:] and
            0 < struct.unpack_from('<I', original, 490)[0] < struct.unpack_from('<I', expected, 490)[0],
            'Physical MBR update must change only p3 length and only grow')
    require(os.pread(descriptor, SECTOR_BYTES, 0) == original,
            'Physical MBR changed before its single length-field write')
    written = os.pwrite(descriptor, expected[P3_LENGTH], P3_LENGTH.start)
    require(written == 4, 'Incomplete partition-length write; inspect retained state without retrying')
    os.fsync(descriptor)
    require(os.pread(descriptor, SECTOR_BYTES, 0) == expected,
            'Physical MBR readback differs after its single length-field write')


def write_partition_length(admitted, backup, expected, operation):
    """The caller owns p3's kernel claim; also honor parent-device advisory writers."""
    parent = admitted['parent']
    descriptor = os.open(real_path(parent['node']), os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISBLK(info.st_mode) and device_number(info.st_rdev) == parent['device'],
                'Writable parent descriptor differs from root-derived card identity')
        size = struct.unpack('Q', fcntl.ioctl(descriptor, installer.BLKGETSIZE64, bytes(8)))[0]
        require(size == parent['bytes'], 'Writable parent capacity differs from admission')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another partition-table writer owns the parent card lock') from error
        original = bytes.fromhex(backup['mbr_hex'])
        require(expected == validate_partition_candidate(original, expected, admitted['growth']),
                'Physical MBR differs from the validated growth target')
        operation.update('growing-partition', partition_method=PARTITION_METHOD,
                         write_offset_bytes=P3_LENGTH.start, write_bytes=4)
        _write_length(descriptor, original, expected)
    finally:
        os.close(descriptor)


def verify_contents(admitted, backup, operation):
    """Mount privately read-only after all offline writes and checks completed."""
    boot, store = operation.path / 'boot-readonly', operation.path / 'store-readonly'
    boot.mkdir(mode=0o700)
    store.mkdir(mode=0o700)
    parts = admitted['partitions']
    command(['mount', '-t', 'vfat', '-o', 'ro,shortname=mixed', '--', parts['boot']['node'], boot],
            log=operation.log)
    try:
        command(['mount', '-t', 'ext4', '-o', 'ro,noload', '--', parts['store']['node'], store],
                log=operation.log)
        try:
            records = mounts()
            for name, path, kind in (('boot', boot, 'vfat'), ('store', store, 'ext4')):
                mounted = installer.mounted_at(path, records, device=parts[name]['device'], filesystem_type=kind)
                require('ro' in mounted['options'], 'Post-growth content validation must stay read-only')
            card, _ = read_record(store / 'DEVBOOT.JSON')
            catalog, _ = read_record(store / 'RELEASES.JSON')
            boot_card, _ = read_record(boot / 'DEVBOOT.JSON')
            require(card == boot_card == backup['card'] and catalog == backup['catalog'],
                    'Card or registered catalog changed during growth')
            installer.verify_file_pins(store, backup['store_files'])
            installer.verify_file_pins(boot, backup['flags'])
            code = '''import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from dev_systems import Card
card = Card(pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]))
status = card.status()
assert status['next_system'] == status['confirmed_system'] == 'recovery'
assert status['trial_pending'] is False
for name in card.releases:
    card.verify(name)
print(json.dumps(status, sort_keys=True))
'''
            command([sys.executable, '-I', '-c', code, store / 'admin/tools', boot, store], log=operation.log)
        finally:
            command(['umount', '--', store], log=operation.log)
    finally:
        command(['umount', '--', boot], log=operation.log)
    assert_unmounted(admitted)


def execute_growth(admitted, backup, operation):
    """Shared mutation path for admitted physical media and disposable loop fixtures.

    The CLI is the sole physical-root admission path. Fixtures may construct
    admitted from their own sysfs loop identity but use every write/check here.
    """
    require_private_mount_namespace()
    require(admitted['growth'] == growth_plan(backup), 'Admitted target differs from checkpoint geometry')
    assert_unmounted(admitted)
    assert_geometry(admitted)
    _verify_identities(admitted, backup)
    parts, plan = admitted['partitions'], admitted['growth']
    parent, target = admitted['parent']['node'], parts['store']
    # Boot is never mounted during writes. A kernel claim prevents a mount from
    # another namespace while p3 ownership passes to filesystem utilities.
    with exclusive_device(parts['boot']):
        operation.update('checking-original-filesystem')
        command(['e2fsck', '-f', '-n', target['node']], log=operation.log)
        original_filesystem = ext4_geometry(target['node'])
        require(original_filesystem['bytes'] == plan['old_bytes'],
                'Original ext4 size differs from the checkpoint partition')
        with exclusive_device(target):
            assert_unmounted(admitted)
            assert_geometry(admitted)
            _verify_source(admitted, backup)
            if admitted.get('physical_admission') is True:
                require(runtime_admission(backup) == admitted,
                        'Recovery identity or card admission changed during complete source hashing')
            operation.update('source-checkpoint-verified')
            expected_mbr = plan_partition(admitted, backup, operation)
        # These utilities open their own O_EXCL claim. Holding a wrapper claim
        # would conflict with e2fsprogs. Private mount visibility keeps their
        # mounted-filesystem lookup on the offline branch; an external mount
        # race then causes their exclusive open to fail rather than online-grow.
        assert_unmounted(admitted)
        operation.update('preparing-filesystem', write_started=True)
        command(['e2fsck', '-f', '-p', target['node']], log=operation.log)
        with exclusive_device(target):
            assert_unmounted(admitted)
            assert_geometry(admitted)
            require(read_mbr(parent).hex() == backup['mbr_hex'], 'MBR changed before partition write')
            write_partition_length(admitted, backup, expected_mbr, operation)
            _verify_protected(admitted, backup, expected_mbr)
            operation.update('partition-table-verified', mbr_hex=expected_mbr.hex())
            command(['partx', '--update', '--nr', '3', parent], log=operation.log)
            assert_geometry(admitted, grown=True)
            operation.update('kernel-geometry-verified', target_bytes=plan['target_bytes'])
        assert_unmounted(admitted)
        operation.update('growing-filesystem')
        command(['resize2fs', '-p', target['node']], log=operation.log)
        operation.update('checking-grown-filesystem')
        command(['e2fsck', '-f', '-n', target['node']], log=operation.log)
        grown_filesystem = ext4_geometry(target['node'])
        require(grown_filesystem['bytes'] == plan['target_bytes'] and
                all(grown_filesystem[key] == original_filesystem[key]
                    for key in ('block_bytes', 'features', 'uuid_hex')),
                'Grown ext4 size, features or filesystem identity differs')
        assert_unmounted(admitted)
        assert_geometry(admitted, grown=True)
        _verify_identities(admitted, backup)
        _verify_protected(admitted, backup, expected_mbr)
        operation.update('filesystem-verified')
    operation.update('verifying-preserved-contents')
    verify_contents(admitted, backup, operation)
    with exclusive_device(parts['boot']):
        grown_target = dict(target, bytes=plan['target_bytes'])
        with exclusive_device(grown_target):
            assert_unmounted(admitted)
            assert_geometry(admitted, grown=True)
            _verify_identities(admitted, backup)
            _verify_protected(admitted, backup, expected_mbr)
    operation.update('complete', completed=True, boot_selection_changed=False, reboot_performed=False,
                     target_bytes=plan['target_bytes'], filesystem_bytes=grown_filesystem['bytes'],
                     filesystem_check='passed',
                     catalog_unchanged=True, flags_unchanged=True)
    return operation.record


def _check_location():
    device = Path('/').stat().st_dev
    for filename in ('dev_store_grow.py', 'install-dev-store.py', 'dev_store.py'):
        path = real_path(Path(__file__).with_name(filename).absolute())
        root_directory(path.parent, device)
        with installer.regular_file(path) as stream:
            info = os.fstat(stream.fileno())
            require(info.st_dev == device and info.st_uid == 0 and not info.st_mode & 0o022,
                    'Stage worker and shared validators as root-owned files on original recovery p2')


def operation_status(path):
    path = real_path(path)
    record, _ = read_record(path / 'state.json')
    require(record.get('operation') == 'development-store-growth', 'Not a growth operation state')
    return dict(state=str(path), record=record, read_only=True,
                observation='Inspect the original service and logs; an observer timeout does not stop its writes')


def run_growth(args):
    if args.status is not None:
        require(not args.apply, '--status cannot apply changes')
        return operation_status(args.status)
    require(args.backup_receipt is not None and args.state is not None,
            'Planning and apply require --backup-receipt and a fresh --state directory')
    if args.apply:
        require(os.geteuid() == 0, '--apply requires real root privileges')
        require_private_mount_namespace()
        _check_location()
    backup, backup_data = read_record(args.backup_receipt, private_root=args.apply)
    admitted = runtime_admission(backup)
    state = real_path(args.state, exists=False)
    root_directory(state.parent, Path('/').stat().st_dev)
    require(not state.exists(), 'Use a fresh unique state directory; retained operations cannot be reused')
    if not args.apply:
        return dict(plan=True, executed=False, admitted=admitted, state=str(state),
                    boot_selection_changed=False, reboot_performed=False)
    initial = dict(admission=admitted, backup_receipt_sha256=hashlib.sha256(backup_data).hexdigest())
    with ownership(state, initial) as operation:
        with (operation.path / 'backup-receipt.json').open('xb', buffering=0) as stream:
            os.fchmod(stream.fileno(), 0o600)
            installer.write_all(stream.fileno(), backup_data)
            os.fsync(stream.fileno())
        sync_directory(operation.path)
        # Re-admit after obtaining both durable writer locks. No claim is held
        # while a filesystem utility performs its own exclusive device open.
        require(runtime_admission(backup) == admitted, 'Recovery admission changed while obtaining ownership')
        return execute_growth(admitted, backup, operation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-receipt', type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--status', type=Path, help='Read retained operation state without creating or resuming it')
    parser.add_argument('--apply', action='store_true', help='Expand admitted offline p3; never select or reboot')
    args = parser.parse_args()
    os.umask(0o077)
    result = run_growth(args)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
