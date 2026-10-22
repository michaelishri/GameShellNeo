#!/usr/bin/env python3
"""Qualify offline growth on newly allocated, partitioned regular-image loops."""
import argparse
import contextlib
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import select
import shutil
import stat
import struct
import subprocess
import sys
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ('tools/dev_store_grow.py', 'tools/check-dev-store-grow.py',
          'tools/tests/test_dev_store_grow.py', 'tools/install-dev-store.py',
          'tools/dev_card.py', 'tools/dev_store.py', 'tools/dev_systems.py',
          'tools/dev_boot_scripts.py', 'tools/usb_poll_boot.py', 'tools/check-dev-store.py',
          'tools/tests/fixtures/development-store-mbr.hex')
MIB = 1024 * 1024
SECTOR = 512


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tree_snapshot(root):
    """Capture content plus every metadata kind, without following symlinks."""
    checker = load_module('growth_metadata_checker', 'check-dev-store.py')
    result = checker.root_metadata(root)
    for relative, record in result['entries'].items():
        path = root if relative == '.' else root / relative
        record['inode'] = path.lstat().st_ino
        if stat.S_ISREG(record['mode']):
            record['bytes'] = path.lstat().st_size
            record['sha256'] = sha(path)
    return result


def snapshot_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write_file(root, relative, data, *, uid=0, gid=0, mode=0o644):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.chown(path, uid, gid)
    path.chmod(mode)
    return path


def boot_assets(directory):
    directory.mkdir(parents=True, exist_ok=True)
    def image(payload, kind):
        fields = [0x27051956, 0, 0, len(payload), 0, 0, zlib.crc32(payload),
                  5, 2, kind, 0, b'growth fixture']
        fields[1] = zlib.crc32(struct.pack('>7I4B32s', *fields))
        return struct.pack('>7I4B32s', *fields) + payload
    write_file(directory, 'uImage', image(b'fixture Linux payload', 2))
    write_file(directory, 'uInitrd', image(b'fixture initramfs payload', 3))
    write_file(directory, 'sun8i-r16-clockworkpi-cpi3.dtb',
               struct.pack('>10I', 0xd00dfeed, 40, 40, 40, 40, 17, 16, 0, 0, 0))


def seed_store(root, boot, disk, recovery_assets):
    """Use two version roots, settings, capabilities, ACLs and link aliases."""
    import dev_store
    from dev_systems import boot_bundle, initialize
    for name in dev_store.ADMIN_FILES:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = ROOT / name.removeprefix('admin/')
        if source.is_file():
            shutil.copyfile(source, destination)
        else:
            destination.write_bytes(b'fixture inactive loader receipt\n')
    for slot in ('diag25', 'diag27'):
        prefix = 'systems/' + slot + '/'
        write_file(root, prefix + 'source-image.json', b'original source: ' + slot.encode())
        write_file(root, prefix + 'source-fstab', b'PARTUUID=' + disk.encode() + b'-03 / ext4 defaults 0 1\n')
        write_file(root, prefix + 'root/etc/gameshellneo/image.json', b'{"fixture":true}\n')
        write_file(root, prefix + 'root/etc/gameshellneo/development-slot',
                   ('schema=1\nid=' + slot + '\nkernel=6.18.54-growth-fixture\n').encode())
        write_file(root, prefix + 'root/etc/settings.ini', b'volume=17\nbrightness=41\n',
                   uid=1234, gid=2345, mode=0o640)
        tool = write_file(root, prefix + 'root/usr/bin/tool', b'complete version ' + slot.encode(),
                          uid=123, gid=456, mode=0o4751)
        os.link(tool, tool.with_name('tool-hardlink'))
        tool.with_name('tool-relative').symlink_to('tool')
        tool.with_name('tool-absolute').symlink_to('/usr/bin/tool')
        os.setxattr(tool, 'user.growth-fixture', b'preserve\x00binary\xff')
    write_file(root, 'settings/owner.json', b'{"preserve":true}\n', uid=3456, gid=4567, mode=0o600)
    write_file(root, 'systems/.diag25-bundle-fixture1/archive.tar', b'retained original failed archive')
    write_file(root, 'systems/.diag25-bundle-fixture1/operation.log', b'retained original failure')
    capability = struct.pack('<5I', 0x02000001, 1 << 13, 0, 0, 0)
    capable = write_file(root, 'systems/diag27/root/usr/bin/capable', b'capability sentinel', mode=0o755)
    os.setxattr(capable, 'security.capability', capability)
    require(os.getxattr(capable, 'security.capability') == capability,
            'Native fixture cannot retain security.capability')
    devices = root / 'systems/diag27/root/dev'
    devices.mkdir()
    os.mkfifo(devices / 'fixture-fifo', 0o640)
    os.mknod(devices / 'fixture-null', stat.S_IFCHR | 0o600, os.makedev(1, 3))
    # Linux's POSIX ACL xattr ABI avoids depending on an optional setfacl CLI.
    acl = struct.pack('<I', 2) + b''.join(struct.pack('<HHI', *entry) for entry in (
        (1, 6, 0xffffffff), (2, 4, 4321), (4, 4, 0xffffffff),
        (16, 4, 0xffffffff), (32, 0, 0xffffffff)))
    acl_path = root / 'settings/owner.json'
    os.setxattr(acl_path, 'system.posix_acl_access', acl)
    require(os.getxattr(acl_path, 'system.posix_acl_access') == acl,
            'Native fixture cannot retain POSIX ACLs')
    for slot in ('diag25', 'diag27'):
        directory = root / 'systems' / slot
        version_root = directory / 'root'
        boot_assets(directory / 'boot')
        release = dict(schema=1, board=dev_store.BOARD, slot=slot,
            kernel='6.18.54-growth-fixture', store_partuuid=disk + '-03',
            source_image_sha256='1' * 64, boot_files=boot_bundle(directory / 'boot', True),
            immutable_files={str(path.relative_to(version_root)): sha(path)
                             for path in version_root.rglob('*') if stat.S_ISREG(path.lstat().st_mode)})
        write_file(directory, 'release.json', dev_store.json_bytes(release))
    card = initialize(boot, root, recovery_partuuid=disk + '-02', recovery_boot=recovery_assets,
                      releases=['diag25', 'diag27'], recovery_suspend_diagnostics=True)
    catalog = json.loads((root / 'RELEASES.JSON').read_bytes())
    for path in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True) + [root]:
        os.utime(path, ns=(1700000000123456789, 1700000000123456789), follow_symlinks=False)
    files = {str(path.relative_to(root)): sha(path) for path in root.rglob('*')
             if stat.S_ISREG(path.lstat().st_mode)}
    return card, catalog, files


def partition_record(node):
    info = Path(node).stat()
    number = f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}'
    sysfs = (Path('/sys/dev/block') / number).resolve(strict=True)
    return dict(node=str(node), device=number, number=int((sysfs / 'partition').read_text()),
                sysfs=str(sysfs), parent=str(sysfs.parent),
                start_sector=int((sysfs / 'start').read_text()),
                bytes=int((sysfs / 'size').read_text()) * SECTOR)


def make_image(path, disk):
    """Create only a fresh sparse fixture; never accept an existing device."""
    require(not path.exists() and path.suffix == '.img', 'Use a fresh fixture image')
    mbr = bytearray(SECTOR)
    mbr[:440] = (bytes(range(256)) * 2)[:440]
    mbr[440:444] = struct.pack('<I', int(disk, 16))
    for index, (start, sectors, kind) in enumerate(((32768, 32768, 0x0e),
                                                  (65536, 131072, 0x83),
                                                  (196608, 131072, 0x83))):
        offset = 446 + 16 * index
        mbr[offset:offset + 16] = struct.pack('<B3sB3sII', 0x80 if index == 0 else 0,
            b'\xfe\xff\xff', kind, b'\xfe\xff\xff', start, sectors)
    mbr[510:512] = b'\x55\xaa'
    with path.open('xb') as stream:
        stream.truncate(384 * MIB)
        stream.seek(0)
        stream.write(mbr)
        stream.seek(8192)
        stream.write((b'preserve reserved SPL/U-Boot bytes\n' * 20000)[:548864])
        stream.flush()
        os.fsync(stream.fileno())


class FixtureOperation:
    """The production lower-level core receives an ordinary durable operation."""
    def __init__(self, path):
        self.path = path
        path.mkdir(mode=0o700)
        self.log = (path / 'operation.log').open('xb', buffering=0)
        self.record = dict(write_started=False, completed=False, events=[])

    def update(self, phase, **values):
        self.record.update(values, phase=phase)
        self.record['events'].append(dict(phase=phase, **values))
        temporary = self.path / 'state.new'
        with temporary.open('w') as stream:
            json.dump(self.record, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path / 'state.json')

    def close(self):
        os.fsync(self.log.fileno())
        self.log.close()


def range_hash(path, offset, length):
    digest = hashlib.sha256()
    with Path(path).open('rb', buffering=0) as stream:
        stream.seek(offset)
        while length:
            data = stream.read(min(length, MIB))
            require(data, 'Fixture image ended within a protected range')
            digest.update(data)
            length -= len(data)
    return digest.hexdigest()


def backup_regions(work, image, parts):
    regions = {}
    for name, offset, size in (('prefix', 0, 16 * MIB),
                              ('boot', parts['boot']['start_sector'] * SECTOR, parts['boot']['bytes']),
                              ('store', parts['store']['start_sector'] * SECTOR, parts['store']['bytes'])):
        archive = work / (name + '.img.gz')
        digest = hashlib.sha256()
        with image.open('rb') as source, archive.open('xb') as output:
            source.seek(offset)
            with gzip.GzipFile(fileobj=output, mode='wb', mtime=0) as compressed:
                remaining = size
                while remaining:
                    data = source.read(min(remaining, MIB))
                    require(data, 'Truncated fresh fixture backup')
                    digest.update(data)
                    compressed.write(data)
                    remaining -= len(data)
        with gzip.open(archive, 'rb') as stream:
            restored = hashlib.file_digest(stream, 'sha256').hexdigest()
        require(restored == digest.hexdigest(), 'Fresh fixture backup readback differs')
        regions[name] = dict(file=archive.name, offset_bytes=offset, raw_bytes=size,
            raw_sha256=digest.hexdigest(), gzip_bytes=archive.stat().st_size, gzip_sha256=sha(archive),
            source_unmounted=True, verified_full_decompressed=True)
    return regions


def filesystem(node):
    output = subprocess.check_output(['blkid', '-p', '-o', 'export', str(node)], text=True)
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


@contextlib.contextmanager
def mounted(grow, node, point, log, *, filesystem_type='ext4', readonly=False):
    point.mkdir(exist_ok=True)
    options = ('ro,noload' if filesystem_type == 'ext4' else 'ro,shortname=mixed') if readonly else (
        'rw,noatime' if filesystem_type == 'ext4' else 'rw,shortname=mixed')
    grow.command(['mount', '-t', filesystem_type, '-o', options, node, point], log=log)
    try:
        yield point
    finally:
        grow.command(['umount', '--', point], log=log)


@contextlib.contextmanager
def other_namespace_mount(node, point, log):
    """Mount after the worker namespace is private; its mountinfo stays empty."""
    point.mkdir()
    code = ('import subprocess,sys; '
            'subprocess.run(["mount","-t","ext4","-o","ro,noload",sys.argv[1],sys.argv[2]],check=True); '
            'print("mounted in another namespace",flush=True); sys.stdin.buffer.read(1); '
            'subprocess.run(["umount","--",sys.argv[2]],check=True)')
    process = subprocess.Popen(['unshare', '--mount', '--propagation', 'private', sys.executable,
        '-c', code, node, str(point)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
    try:
        require(select.select([process.stdout], [], [], 10)[0], 'Fixture race mount did not become ready')
        require(process.stdout.readline() == b'mounted in another namespace\n',
                'Fixture race could not mount its disposable store')
        yield process
    finally:
        try:
            process.communicate(input=b'!', timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        require(process.returncode == 0, 'Fixture race mount did not cleanly unmount')


def fixture_case(work, grow, *, race=False):
    from dev_card import attached
    from dev_systems import Card
    work.mkdir()
    image = work / 'new-card.img'
    disk = uuid.uuid4().hex[:8]
    make_image(image, disk)
    recovery_assets = work / 'recovery-assets'
    boot_assets(recovery_assets)
    log = (work / 'fixture.log').open('xb', buffering=0)
    operation = None
    try:
        with attached(image, False) as node:
            grow.command(['mkfs.fat', '-F', '16', node + 'p1'], log=log)
            for number in (2, 3):
                grow.command(['mkfs.ext4', '-F', node + 'p' + str(number)], log=log)
            with mounted(grow, node + 'p2', work / 'recovery', log) as recovery:
                write_file(recovery, 'etc/original-fixed-recovery', b'fixed recovery remains byte-identical\n')
                os.sync()
            with mounted(grow, node + 'p1', work / 'boot', log, filesystem_type='vfat') as boot, \
                    mounted(grow, node + 'p3', work / 'store', log) as store:
                card, catalog, pins = seed_store(store, boot, disk, recovery_assets)
                expected_status = Card(boot, store).status()
                flags = {name: sha(boot / name) for name in ('next.scr', 'good.scr', 'recover.scr')}
                os.sync()
                metadata_before = tree_snapshot(store)
            parts = {name: partition_record(node + 'p' + str(number)) for number, name in (
                (1, 'boot'), (2, 'recovery'), (3, 'store'))}
            saved_parts = {name: dict(start_sector=part['start_sector'], bytes=part['bytes'],
                partuuid=disk + '-0' + str(part['number']), filesystem_uuid=filesystem(part['node'])['UUID'])
                for name, part in parts.items()}
            regions = backup_regions(work, image, saved_parts)
            parent_info = Path(node).stat()
            parent = dict(node=node, device=f'{os.major(parent_info.st_rdev)}:{os.minor(parent_info.st_rdev)}',
                bytes=image.stat().st_size, sector_bytes=SECTOR, cid='8' * 32, partuuid_prefix=disk)
            backup = dict(schema=1, operation='development-store-growth-backup', development_only=True,
                verified=True, root=dict(boot_id=str(uuid.uuid4()), root_partuuid=disk + '-02',
                    directory_deployment=False, image_sha256='7' * 64, kernel=os.uname().release),
                parent={key: value for key, value in parent.items() if key not in ('node', 'device')},
                partitions=saved_parts, regions=regions, mbr_hex='',
                protected_prefix_sha256=range_hash(image, SECTOR, 16 * MIB - SECTOR),
                card=card, catalog=catalog, flags=flags, store_files=pins,
                evidence=dict(admission_sha256='9' * 64, checkpoint_result_sha256='a' * 64))
            # Do not read the complete sparse card just to capture the MBR.
            with image.open('rb') as stream:
                backup['mbr_hex'] = stream.read(SECTOR).hex()
            grow.validate_backup(backup)
            admitted = dict(root_device=parts['recovery']['device'], root=backup['root'], parent=parent,
                            partitions=parts, growth=grow.growth_plan(backup))
            expected_bytes = admitted['growth']['target_bytes']
            before_mbr = bytes.fromhex(backup['mbr_hex'])
            recovery_hash = range_hash(image, saved_parts['recovery']['start_sector'] * SECTOR,
                                       saved_parts['recovery']['bytes'])
            (work / 'backup-receipt.json').write_text(json.dumps(backup, indent=2, sort_keys=True) + '\n')
            operation = FixtureOperation(work / 'operation')
            attempts = []
            original_command = grow.command
            @contextlib.contextmanager
            def command_observer():
                def command(arguments, **options):
                    attempts.append([str(value) for value in arguments])
                    if race and str(arguments[0]) == 'resize2fs':
                        with other_namespace_mount(node + 'p3', work / 'other-namespace', log):
                            require(not any(record['device'] == parts['store']['device'] for record in grow.mounts()),
                                    'External mount leaked into the worker namespace and could select online resize')
                            return original_command(arguments, **options)
                    return original_command(arguments, **options)
                grow.command = command
                try:
                    yield
                finally:
                    grow.command = original_command
            with mounted(grow, node + 'p2', work / 'recovery', log, readonly=True):
                if not race:
                    primary, alias = work / 'primary-store-mount', work / 'store-bind-alias'
                    primary.mkdir()
                    alias.mkdir()
                    grow.command(['mount', '-t', 'ext4', '-o', 'ro,noload', node + 'p3', primary], log=log)
                    try:
                        grow.command(['mount', '--bind', primary, alias], log=log)
                    finally:
                        grow.command(['umount', '--', primary], log=log)
                    alias_operation = FixtureOperation(work / 'alias-rejected-operation')
                    try:
                        try:
                            grow.execute_growth(admitted, backup, alias_operation)
                        except ValueError as error:
                            require('mounted aliases' in str(error), 'Alias fixture failed for an unrelated reason')
                        else:
                            raise ValueError('Mounted bind alias was accepted for growth')
                        require(not alias_operation.record.get('write_started'), 'Alias rejection occurred after a write')
                        require(grow.read_mbr(node) == before_mbr, 'Alias rejection changed the partition table')
                        require(range_hash(image, regions['store']['offset_bytes'], regions['store']['raw_bytes']) ==
                                regions['store']['raw_sha256'], 'Alias rejection changed the original filesystem')
                    finally:
                        alias_operation.close()
                        grow.command(['umount', '--', alias], log=log)
                with command_observer():
                    if race:
                        try:
                            grow.execute_growth(admitted, backup, operation)
                        except (ValueError, OSError) as error:
                            operation.update('fixture-expected-failure', error=str(error))
                        else:
                            raise ValueError('resize2fs accepted a store mounted outside its namespace')
                    else:
                        grow.execute_growth(admitted, backup, operation)
                after_mbr = grow.read_mbr(node)
                require(before_mbr[:490] + before_mbr[494:] == after_mbr[:490] + after_mbr[494:],
                        'MBR changed outside the four p3 length bytes')
                require(struct.unpack('<I', after_mbr[490:494])[0] == admitted['growth']['target_sectors'],
                        'MBR p3 length does not reach the end of the fixture card')
                require(range_hash(image, SECTOR, 16 * MIB - SECTOR) == backup['protected_prefix_sha256'],
                        'Reserved bootloader prefix changed')
                require(range_hash(image, saved_parts['boot']['start_sector'] * SECTOR,
                                   saved_parts['boot']['bytes']) == regions['boot']['raw_sha256'],
                        'Boot partition changed')
                require(range_hash(image, saved_parts['recovery']['start_sector'] * SECTOR,
                                   saved_parts['recovery']['bytes']) == recovery_hash,
                        'Mounted fixed recovery partition changed')
                if race:
                    require(operation.record.get('completed') is not True and operation.record.get('write_started'),
                            'Failed resize was reported complete or lost destructive intent')
                    require(sum(values[0] == 'resize2fs' for values in attempts) == 1,
                            'Failed resize was automatically retried')
                    require(not any(values[0] in ('reboot', 'shutdown') for values in attempts),
                            'Failure invoked a reboot')
                    require('busy' in (operation.path / 'operation.log').read_text().lower(),
                            'Race failure does not show the real exclusive-open busy rejection')
                    return dict(race_mount_excluded_from_worker_view=True, offline_resize_busy_veto=True,
                                no_retry_or_rollback=True, completed=False)
                require(operation.record.get('completed') is True, 'Growth never reached authoritative completion')
                require(partition_record(node + 'p3')['bytes'] == expected_bytes,
                        'Kernel p3 geometry differs from the expanded MBR')
                with mounted(grow, node + 'p1', work / 'boot', log, filesystem_type='vfat', readonly=True) as boot, \
                        mounted(grow, node + 'p3', work / 'store', log, readonly=True) as store:
                    metadata_after = tree_snapshot(store)
                    require(metadata_before == metadata_after, 'Full store content or metadata changed during resize')
                    require(Card(boot, store).status() == expected_status, 'Catalog or fixed recovery selection changed')
                    require(filesystem(node + 'p3')['UUID'] == saved_parts['store']['filesystem_uuid'],
                            'The ext4 filesystem UUID changed')
                header = subprocess.check_output(['dumpe2fs', '-h', node + 'p3'], stderr=log, text=True)
                values = dict(line.split(':', 1) for line in header.splitlines() if ':' in line)
                require(int(values['Block count']) * int(values['Block size']) == expected_bytes,
                        'Filesystem did not grow to the partition boundary')
                with mounted(grow, node + 'p3', work / 'store', log) as store:
                    root_times = store.stat()
                    probe = store / '.growth-bounded-write-probe'
                    payload = bytes(range(256)) * 1024
                    with probe.open('xb') as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                    require(probe.read_bytes() == payload, 'Bounded expanded-filesystem readback failed')
                    probe.unlink()
                    os.utime(store, ns=(root_times.st_atime_ns, root_times.st_mtime_ns))
                    os.sync()
                    require(tree_snapshot(store) == metadata_before,
                            'Bounded write/read/delete changed preserved store data or metadata')
            (work / 'metadata-before.json').write_text(json.dumps(metadata_before, indent=2, sort_keys=True) + '\n')
            (work / 'metadata-after.json').write_text(json.dumps(metadata_after, indent=2, sort_keys=True) + '\n')
            return dict(old_partition_bytes=saved_parts['store']['bytes'], target_partition_bytes=expected_bytes,
                mbr_only_p3_length_changed=True, boot_and_mounted_recovery_byte_identical=True,
                reserved_prefix_byte_identical=True, metadata_sha256=snapshot_hash(metadata_before),
                metadata_entries=len(metadata_before['entries']),
                metadata_and_content_preserved=True, two_releases_verified=True,
                mounted_bind_alias_rejected_before_write=True,
                security_capability_preserved=True, posix_acl_preserved=True,
                bounded_write_read_delete_bytes=256 * 1024)
    finally:
        if operation:
            operation.close()
            # These synthetic-only copies let the ordinary host user inspect
            # failures without weakening the production operation directory.
            shutil.copyfile(operation.path / 'operation.log', work / 'operation.log')
            if (operation.path / 'state.json').exists():
                shutil.copyfile(operation.path / 'state.json', work / 'operation-state.json')
        os.fsync(log.fileno())
        log.close()


def full_capacity_plan(work, grow):
    """Exercise actual sfdisk with the live MBR and exact 64 GB capacity."""
    work.mkdir()
    receipts = load_module('growth_test_receipts', 'tests/test_dev_store_grow.py')
    backup = receipts.checkpoint()
    raw = bytes.fromhex((ROOT / 'tools/tests/fixtures/development-store-mbr.hex').read_text())
    require(hashlib.sha256(raw).hexdigest() ==
            '79fc38e3713407f8cbf0393cd9b28a4c347f13868f2ea474a6a35881768f6417',
            'Captured live MBR fixture differs from its read-only receipt')
    backup['mbr_hex'] = raw.hex()
    grow.validate_backup(backup)
    admitted = dict(parent=backup['parent'], growth=grow.growth_plan(backup))
    operation = FixtureOperation(work / 'operation')
    try:
        expected = grow.plan_partition(admitted, backup, operation)
        require(expected[:490] + expected[494:] == raw[:490] + raw[494:],
                'Full-capacity planner changed protected physical MBR bytes')
        require(struct.unpack('<II', expected[486:494]) == (8388608, 116637696),
                'Full-capacity planner changed the start or target sector count')
        surrogate = operation.path / 'partition-plan.img'
        require(surrogate.stat().st_size == 64013467648 and surrogate.stat().st_blocks * 512 < MIB,
                'Full-capacity planner did not use a bounded sparse regular image')
        with surrogate.open('rb') as stream:
            planned = stream.read(SECTOR)
        write_file(work, 'captured-live-before.mbr', raw)
        write_file(work, 'validated-physical-after.mbr', expected)
        return dict(parent_bytes=64013467648, original_start_sector=8388608,
            original_store_bytes=4294967296, target_sectors=116637696, target_store_bytes=59718500352,
            live_mbr_sha256=hashlib.sha256(raw).hexdigest(),
            candidate_mbr_sha256=hashlib.sha256(expected).hexdigest(),
            surrogate_changed_offsets=[offset for offset, (before, after) in enumerate(zip(raw, planned))
                                       if before != after],
            physical_candidate_changed_offsets=[offset for offset, (before, after) in enumerate(zip(raw, expected))
                                                if before != after],
            sparse_regular_image=True, physical_write_performed=False)
    finally:
        operation.close()
        shutil.copyfile(operation.path / 'operation.log', work / 'operation.log')
        if (operation.path / 'state.json').exists():
            shutil.copyfile(operation.path / 'state.json', work / 'operation-state.json')


def fixture(work):
    require(os.geteuid() == 0 and work == Path('/fixture'), 'Use the isolated managed root fixture')
    import dev_store_grow as grow
    before = {name: sha(ROOT / name) for name in INPUTS}
    record = dict(passed=False, inputs=before, hardware_qualified=False)
    swap_view = False
    try:
        grow.require_private_mount_namespace()
        # /proc/swaps is host-global, while its source paths need not exist in
        # Docker. These loops are allocated later from new regular images and
        # cannot be preexisting swap. Give the private fixture this exact view;
        # unit tests separately exercise real block and file swap aliases.
        swaps = work / 'fixture-proc-swaps'
        swaps.write_text('Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n')
        subprocess.run(['mount', '--bind', swaps, '/proc/swaps'], check=True)
        swap_view = True
        subprocess.run(['mount', '-o', 'remount,bind,ro', '/proc/swaps'], check=True)
        record['fixture_swap_view'] = 'Newly allocated loops only; hidden host swap paths excluded in private namespace'
        record['full_capacity_plan'] = full_capacity_plan(work / 'full-capacity-plan', grow)
        record['growth'] = fixture_case(work / 'growth', grow)
        record['external_mount_race'] = fixture_case(work / 'external-mount-race', grow, race=True)
        require(before == {name: sha(ROOT / name) for name in INPUTS}, 'Growth fixture inputs changed while running')
        record.update(passed=True, scope='New synthetic partitioned regular-image loops only; no physical media.')
    except BaseException as error:
        record['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        if swap_view:
            subprocess.run(['umount', '--', '/proc/swaps'], check=True)
        with (work / 'result.json').open('x') as stream:
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--inside', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.container:
        # PID1 retains the original Docker mount namespace. The worker must be
        # its unshared child so the production guard can verify the separation.
        result = subprocess.run(['unshare', '--mount', '--propagation', 'private',
            sys.executable, str(Path(__file__).resolve()), '--inside', str(args.container)])
        raise SystemExit(result.returncode)
    if args.inside:
        fixture(args.inside)
        return
    require(os.environ.get('NEO_BUILD_STAGE'), 'Use the saved test:dev-store-grow Task')
    from managed_container import execute
    work = ROOT / '.local/build/dev-store-grow' / uuid.uuid4().hex
    work.mkdir(parents=True, mode=0o700)
    builder = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']
    execute('dev-store-grow', ['--pull=never', '--network=none', '--privileged',
        '--platform=' + builder['platform'], '--memory=768m', '--cpus=1', '--pids-limit=128',
        '--entrypoint=python3', '-v', f'{ROOT}:/project:ro', '-v', f'{work}:/fixture',
        builder['image'], '/project/tools/check-dev-store-grow.py', '--container', '/fixture'],
        work / 'managed', timeout=300)
    result = json.loads((work / 'result.json').read_text())
    require(result.get('passed') is True and result['inputs'] == {name: sha(ROOT / name) for name in INPUTS},
            'Store growth fixture did not pass with current inputs')
    print('Retained offline growth fixture:', work.relative_to(ROOT))


if __name__ == '__main__':
    main()
