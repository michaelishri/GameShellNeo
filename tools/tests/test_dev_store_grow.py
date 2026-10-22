"""Growth admission and failure boundaries never resize unrelated or uncertain media."""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import dev_store_grow as grow


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checkpoint():
    """Independent physical-size receipt: every offset is a literal baseline."""
    disk = 'b9dab681'
    card = dict(schema=1, board='gameshellneo-cpi31', development_only=True,
                recovery_partuuid=disk + '-02', store_partuuid=disk + '-03',
                recovery_boot_files={'uImage': 'a' * 64, grow.schema.DTB: 'b' * 64},
                recovery_suspend_diagnostics=True)
    catalog = {name: dict(manifest_sha256=digest(name.encode())) for name in ('diag25', 'diag27')}
    parts = {'boot': dict(start_sector=32768, bytes=134217728, partuuid=disk + '-01', filesystem_uuid='1234-ABCD'),
             'recovery': dict(start_sector=294912, bytes=4143972352, partuuid=disk + '-02',
                              filesystem_uuid='11111111-2222-3333-4444-555555555555'),
             'store': dict(start_sector=8388608, bytes=4294967296, partuuid=disk + '-03',
                           filesystem_uuid='905c31f6-8d2a-486c-8c57-ca1fd23ecd36')}
    mbr = bytearray(512)
    mbr[440:444] = struct.pack('<I', 0xb9dab681)
    mbr[510:] = b'\x55\xaa'
    for number, name in enumerate(('boot', 'recovery', 'store')):
        part = parts[name]
        offset = 446 + number * 16
        mbr[offset:offset + 16] = struct.pack('<B3sB3sII', 0x80 if number == 0 else 0,
            b'\xfe\xff\xff', 0x0e if number == 0 else 0x83, b'\xfe\xff\xff',
            part['start_sector'], part['bytes'] // 512)
    regions = {}
    for name, offset, length in (('prefix', 0, 16777216), ('boot', 16777216, 134217728),
                               ('store', 4294967296, 4294967296)):
        regions[name] = dict(file=name + '.img.gz', offset_bytes=offset, raw_bytes=length,
            raw_sha256=digest(name.encode()), gzip_bytes=4096, gzip_sha256='c' * 64,
            source_unmounted=True, verified_full_decompressed=True)
    pins = {name: 'd' * 64 for name in grow.schema.ADMIN_FILES}
    pins.update({'DEVBOOT.JSON': digest(grow.schema.json_bytes(card)),
                 'RELEASES.JSON': digest(grow.schema.json_bytes(catalog))})
    for slot, release in catalog.items():
        pins.update({'systems/' + slot + '/release.json': release['manifest_sha256'],
                     'systems/' + slot + '/source-image.json': 'e' * 64,
                     'systems/' + slot + '/source-fstab': 'f' * 64})
    return dict(schema=1, operation='development-store-growth-backup', development_only=True,
        verified=True, root=dict(boot_id='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            root_partuuid=disk + '-02', directory_deployment=False,
            image_sha256='d45bcea1e79e9d2518c9e8632642183eb06387a0868cce75e78838f50fd0faf9',
            kernel='6.18.54-gameshellneo24'),
        parent=dict(cid='8' * 32, bytes=64013467648, sector_bytes=512, partuuid_prefix=disk),
        partitions=parts, regions=regions, mbr_hex=mbr.hex(), protected_prefix_sha256='0' * 64,
        card=card, catalog=catalog,
        flags={name: 'dce033ba9041858b244d2f15c1f1b3111057d93756f64b07f02c73ec0de1ef84'
               for name in grow.schema.FLAGS},
        store_files=pins, evidence=dict(admission_sha256='1' * 64, checkpoint_result_sha256='2' * 64))


class ReceiptAndCapacity(unittest.TestCase):
    def test_full_64gb_arithmetic_preserves_start_and_reaches_the_last_sector(self):
        backup = checkpoint()
        self.assertIs(grow.validate_backup(backup), backup)
        plan = grow.growth_plan(backup)
        self.assertEqual(plan, dict(sector_bytes=512, parent_bytes=64013467648, start_sector=8388608,
            old_sectors=8388608, target_sectors=116637696, old_bytes=4294967296, target_bytes=59718500352))
        self.assertEqual((plan['start_sector'] + plan['target_sectors']) * 512, 64013467648)
        self.assertEqual(backup, checkpoint(), 'Planning mutated its checkpoint')

    def test_incomplete_backup_or_untrusted_identity_and_pins_are_rejected(self):
        changes = [lambda b: b.update(verified=False), lambda b: b.update(schema=True),
            lambda b: b['root'].update(directory_deployment=True),
            lambda b: b['root'].update(root_partuuid='b9dab681-03'),
            lambda b: b['root'].update(boot_id='unverified'),
            lambda b: b['parent'].update(cid='not a card'),
            lambda b: b['parent'].update(sector_bytes=True),
            lambda b: b['parent'].update(partuuid_prefix='1234abcd'),
            lambda b: b['partitions']['store'].update(filesystem_uuid='not a uuid'),
            lambda b: b['partitions']['store'].update(start_sector=8388609),
            lambda b: b['regions']['store'].update(source_unmounted=False),
            lambda b: b['regions']['store'].update(verified_full_decompressed=False),
            lambda b: b['regions']['store'].update(raw_sha256='wrong hash'),
            lambda b: b['regions']['prefix'].update(offset_bytes=512),
            lambda b: b['regions']['boot'].update(file='store.img.gz'),
            lambda b: b['regions']['store'].update(raw_bytes=4096),
            lambda b: b['flags'].update({'good.scr': '0' * 64}),
            lambda b: b['store_files'].pop('admin/tools/dev_systems.py'),
            lambda b: b['store_files'].update({'../escape': '0' * 64}),
            lambda b: b['store_files'].update({'systems/diag25/release.json': '0' * 64}),
            lambda b: b['evidence'].pop('checkpoint_result_sha256')]
        for change in changes:
            backup = checkpoint()
            change(backup)
            with self.subTest(change=change), self.assertRaises(ValueError):
                grow.validate_backup(backup)

    def test_invalid_mbr_signature_disk_id_fourth_partition_or_p3_type_reject(self):
        for offset, value in ((510, 0), (440, 0), (494, 1), (482, 0x07), (490, 1)):
            backup = checkpoint()
            mbr = bytearray.fromhex(backup['mbr_hex'])
            mbr[offset] = value
            backup['mbr_hex'] = mbr.hex()
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                grow.validate_backup(backup)

    def test_shrink_already_grown_unaligned_and_mbr_overflow_have_no_growth_plan(self):
        for size in (8589934592, 8589934080, 64013467649, (0xffffffff + 1) * 512):
            backup = checkpoint()
            backup['parent']['bytes'] = size
            with self.subTest(parent_bytes=size), self.assertRaises(ValueError):
                grow.growth_plan(backup)

    def test_native_arm32_and_64bit_block_ioctls_match_linux_literals(self):
        self.assertEqual(grow.installer.blkgetsize64_request(4), 0x80041272)
        self.assertEqual(grow.installer.blkgetsize64_request(8), 0x80081272)
        self.assertEqual(grow.installer.BLKGETSIZE64,
                         {4: 0x80041272, 8: 0x80081272}[struct.calcsize('N')])


class FixedRecoveryIdentity(unittest.TestCase):
    def test_directory_deployment_markers_and_changed_boot_cannot_admit_apply(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / 'etc/gameshellneo/image.json'
            identity.parent.mkdir(parents=True)
            original = dict(root_partuuid='b9dab681-02', board='gameshellneo-cpi31', kernel=os.uname().release)
            identity.write_text(json.dumps(original))
            cmdline, boot = root / 'cmdline', root / 'boot'
            cmdline.write_text('console=tty0 root=PARTUUID=b9dab681-02')
            boot.write_text('fresh-recovery-boot\n')
            backup = dict(card=original, root=dict(root_partuuid='b9dab681-02', kernel=os.uname().release,
                image_sha256=digest(identity.read_bytes()), boot_id='fresh-recovery-boot'))
            def admit():
                return grow.installer.recovery_identity(backup, root=root, cmdline=cmdline, boot_id=boot)
            self.assertEqual(admit(), original)
            identity.write_text(json.dumps(dict(original, deployment='development-directory')))
            with self.assertRaisesRegex(ValueError, 'fixed recovery'):
                admit()
            identity.write_text(json.dumps(original))
            marker = identity.with_name('development-slot')
            marker.symlink_to(root / 'nonexistent-marker')
            with self.assertRaisesRegex(ValueError, 'directory root'):
                admit()
            marker.unlink()
            cmdline.write_text('console=tty0 neo.slot=diag27')
            with self.assertRaisesRegex(ValueError, 'command-line'):
                admit()
            cmdline.write_text('console=tty0')
            boot.write_text('another-boot')
            with self.assertRaisesRegex(ValueError, 'Boot changed'):
                admit()


class SuperblockAndSourcePins(unittest.TestCase):
    def test_ext4_superblock_parser_handles_64bit_counts_and_rejects_wrong_magic(self):
        raw = bytearray(1024)
        struct.pack_into('<I', raw, 4, 0x1234)
        struct.pack_into('<I', raw, 24, 2)
        struct.pack_into('<H', raw, 56, 0xef53)
        struct.pack_into('<III', raw, 92, 1, 0x80, 3)
        raw[104:120] = bytes(range(16))
        struct.pack_into('<I', raw, 336, 1)
        with patch.object(grow, '_read_block', return_value=raw):
            observed = grow.ext4_geometry('/dev/synthetic')
        self.assertEqual(observed['bytes'], ((1 << 32) + 0x1234) * 4096)
        self.assertEqual(observed['uuid_hex'], bytes(range(16)).hex())
        raw[56:58] = b'xx'
        with patch.object(grow, '_read_block', return_value=raw), self.assertRaises(ValueError):
            grow.ext4_geometry('/dev/synthetic')

    def test_changed_raw_source_or_reserved_prefix_is_rejected_before_resize(self):
        backup = checkpoint()
        admitted = dict(parent={'node': '/dev/synthetic'})
        hashes = {region['offset_bytes']: region['raw_sha256'] for region in backup['regions'].values()}
        hashes[512] = backup['protected_prefix_sha256']
        for changed_offset in (0, 16777216, 4294967296, 512):
            def hashed(_, offset, __):
                return 'f' * 64 if offset == changed_offset else hashes[offset]
            with self.subTest(offset=changed_offset), \
                    patch.object(grow, 'read_mbr', return_value=bytes.fromhex(backup['mbr_hex'])), \
                    patch.object(grow, 'hash_region', side_effect=hashed), self.assertRaises(ValueError):
                grow._verify_source(admitted, backup)

    def test_mbr_comparison_checks_every_byte_outside_the_new_p3_length(self):
        backup = checkpoint()
        expected = bytearray.fromhex(backup['mbr_hex'])
        expected[490:494] = struct.pack('<I', 116637696)
        for offset in (0, 440, 446, 454, 478, 486, 494, 510):
            changed = bytearray(expected)
            changed[offset] ^= 1
            with self.subTest(offset=offset), patch.object(grow, 'read_mbr', return_value=bytes(changed)), \
                    patch.object(grow, 'hash_region') as hashed, self.assertRaisesRegex(ValueError, 'MBR changed'):
                grow._verify_protected(dict(parent={'node': '/dev/synthetic'}), backup, bytes(expected))
            hashed.assert_not_called()


class SinglePartitionField(unittest.TestCase):
    def setUp(self):
        self.backup = checkpoint()
        self.original = bytes.fromhex(self.backup['mbr_hex'])
        self.plan = grow.growth_plan(self.backup)
        target = bytearray(self.original)
        target[490:494] = struct.pack('<I', 116637696)
        self.expected = bytes(target)

    def test_surrogate_chs_changes_never_reach_the_physical_candidate(self):
        surrogate = bytearray(self.expected)
        surrogate[479:482] = b'\x01\x02\x03'
        surrogate[483:486] = b'\x04\x05\x06'
        self.assertEqual(grow.validate_partition_candidate(self.original, bytes(surrogate), self.plan), self.expected)
        for offset in (0, 440, 446, 454, 462, 478, 482, 486, 494, 510):
            changed = bytearray(surrogate)
            changed[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                grow.validate_partition_candidate(self.original, bytes(changed), self.plan)

    def test_exactly_one_four_byte_pwrite_preserves_every_other_byte_and_suffix(self):
        with tempfile.TemporaryFile() as stream:
            suffix = b'preserved disk suffix' * 256
            stream.write(self.original + suffix)
            stream.flush()
            with patch.object(grow.os, 'pwrite', wraps=os.pwrite) as write:
                grow._write_length(stream.fileno(), self.original, self.expected)
            write.assert_called_once_with(stream.fileno(), self.expected[490:494], 490)
            stream.seek(0)
            self.assertEqual(stream.read(), self.expected + suffix)

    def test_changed_original_short_write_and_io_failure_are_never_retried(self):
        actual_pwrite = os.pwrite
        for failure in ('changed-original', 'short-write', 'interrupted-write', 'io-failure'):
            with self.subTest(failure=failure), tempfile.TemporaryFile() as stream:
                stream.write((b'X' + self.original[1:]) if failure == 'changed-original' else self.original)
                stream.flush()
                def writing(descriptor, data, offset):
                    if failure == 'short-write':
                        return actual_pwrite(descriptor, data[:2], offset)
                    if failure == 'interrupted-write':
                        raise InterruptedError('injected interrupted partition write')
                    if failure == 'io-failure':
                        raise OSError('injected partition I/O failure')
                    self.fail('Changed original MBR reached a partition write')
                with patch.object(grow.os, 'pwrite', side_effect=writing) as write, \
                        self.assertRaises((ValueError, OSError)):
                    grow._write_length(stream.fileno(), self.original, self.expected)
                self.assertEqual(write.call_count, 0 if failure == 'changed-original' else 1)

    def test_fsync_or_whole_mbr_readback_failure_preserves_the_original_failed_attempt(self):
        actual_pread = os.pread
        for failure in ('fsync', 'readback'):
            with self.subTest(failure=failure), tempfile.TemporaryFile() as stream:
                stream.write(self.original)
                stream.flush()
                def reading(descriptor, count, offset):
                    observed = actual_pread(descriptor, count, offset)
                    return b'X' + observed[1:] if observed == self.expected else observed
                with ExitStack() as stack:
                    write = stack.enter_context(patch.object(grow.os, 'pwrite', wraps=os.pwrite))
                    if failure == 'fsync':
                        stack.enter_context(patch.object(grow.os, 'fsync', side_effect=OSError('injected fsync failure')))
                    else:
                        stack.enter_context(patch.object(grow.os, 'pread', side_effect=reading))
                    with self.assertRaises((ValueError, OSError)):
                        grow._write_length(stream.fileno(), self.original, self.expected)
                self.assertEqual(write.call_count, 1)
                stream.seek(0)
                self.assertEqual(stream.read(512), self.expected, 'Failure attempted an automatic MBR rollback')

    def test_unexpected_surrogate_change_and_existing_plan_are_rejected(self):
        for failure in ('protected-byte', 'wrong-target', 'existing-plan'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)
                operation = types.SimpleNamespace(path=path, log=tempfile.TemporaryFile(), update=Mock())
                surrogate = path / 'partition-plan.img'
                if failure == 'existing-plan':
                    surrogate.write_bytes(b'preserve prior planner evidence')
                def planning(arguments, **options):
                    self.assertEqual(Path(arguments[-1]), surrogate)
                    self.assertEqual(surrogate.stat().st_size, 64013467648)
                    with surrogate.open('r+b') as stream:
                        self.assertEqual(stream.read(512), self.original)
                        changed = bytearray(self.expected)
                        changed[0 if failure == 'protected-byte' else 490] ^= 1
                        stream.seek(0)
                        stream.write(changed)
                try:
                    with patch.object(grow, 'command', side_effect=planning), self.assertRaises((ValueError, FileExistsError)):
                        grow.plan_partition(dict(parent=self.backup['parent'], growth=self.plan), self.backup, operation)
                    if failure == 'existing-plan':
                        self.assertEqual(surrogate.read_bytes(), b'preserve prior planner evidence')
                finally:
                    operation.log.close()

    def test_parent_alias_identity_capacity_and_lock_fail_before_a_length_write(self):
        for failure in ('regular-file', 'wrong-rdev', 'wrong-capacity', 'locked'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'parent'
                path.write_bytes(self.original)
                parent = dict(node=str(path), device='179:0', bytes=64013467648)
                info = types.SimpleNamespace(st_mode=(stat.S_IFREG if failure == 'regular-file' else stat.S_IFBLK),
                                            st_rdev=os.makedev(179, 1 if failure == 'wrong-rdev' else 0))
                with ExitStack() as stack:
                    stack.enter_context(patch.object(grow.os, 'fstat', return_value=info))
                    stack.enter_context(patch.object(grow.fcntl, 'ioctl', return_value=struct.pack('Q',
                        1 if failure == 'wrong-capacity' else 64013467648)))
                    stack.enter_context(patch.object(grow.fcntl, 'flock',
                        side_effect=BlockingIOError('injected competing parent writer') if failure == 'locked' else None))
                    write = stack.enter_context(patch.object(grow, '_write_length'))
                    with self.assertRaises(ValueError):
                        grow.write_partition_length(dict(parent=parent, growth=self.plan), self.backup,
                                                    self.expected, types.SimpleNamespace(update=Mock()))
                    write.assert_not_called()
                self.assertEqual(path.read_bytes(), self.original)


class LiveCardAdmission(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.parent = self.root / 'mmcblk-fixture'
        (self.parent / 'queue').mkdir(parents=True)
        (self.parent / 'device').mkdir()
        self.parent_node = self.root / 'card-node'
        self.parent_node.write_bytes(b'not real media')
        self.backup = checkpoint()
        (self.parent / 'size').write_text(str(64013467648 // 512))
        (self.parent / 'queue/logical_block_size').write_text('512')
        (self.parent / 'device/cid').write_text(self.backup['parent']['cid'])
        (self.parent / 'dev').write_text('179:0')
        self.root_number = grow.device_number(Path('/').stat().st_dev)
        self.parts = {number: dict(node='/dev/fixture' + str(number), device='179:' + str(number),
            number=number, parent=str(self.parent), sysfs=str(self.parent / str(number)),
            start_sector=self.backup['partitions'][name]['start_sector'],
            bytes=self.backup['partitions'][name]['bytes'])
            for number, name in enumerate(('boot', 'recovery', 'store'), 1)}
        self.parts[2]['device'] = self.root_number
        self.filesystems = {part['node']: dict(UUID=self.backup['partitions'][name]['filesystem_uuid'],
            PART_ENTRY_UUID=self.backup['partitions'][name]['partuuid'], TYPE='vfat' if name == 'boot' else 'ext4')
            for name, part in zip(('boot', 'recovery', 'store'), self.parts.values())}

    def admit(self):
        actual_stat = Path.stat
        def stat_node(path, *args, **kwargs):
            if path == self.parent_node:
                return types.SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(179, 0))
            return actual_stat(path, *args, **kwargs)
        with ExitStack() as stack:
            stack.enter_context(patch.object(Path, 'stat', stat_node))
            stack.enter_context(patch.object(grow, 'real_path', return_value=self.parent_node))
            stack.enter_context(patch.object(grow.installer, 'recovery_identity'))
            stack.enter_context(patch.object(grow, 'mounts', return_value=[]))
            stack.enter_context(patch.object(grow.installer, 'mounted_at'))
            stack.enter_context(patch.object(grow.installer, 'block_partition', return_value=self.parts[2]))
            stack.enter_context(patch.object(grow.installer, 'partition_set', return_value=self.parts))
            stack.enter_context(patch.object(grow, 'assert_unmounted'))
            stack.enter_context(patch.object(grow, 'assert_geometry'))
            stack.enter_context(patch.object(grow, 'filesystem', side_effect=lambda node: self.filesystems[node]))
            stack.enter_context(patch.object(grow.installer, 'unique_partuuids'))
            stack.enter_context(patch.object(grow, 'read_mbr', return_value=bytes.fromhex(self.backup['mbr_hex'])))
            return grow.runtime_admission(self.backup)

    def test_current_root_derived_card_is_admitted(self):
        admitted = self.admit()
        self.assertEqual(admitted['partitions']['store']['node'], '/dev/fixture3')
        self.assertEqual(admitted['parent']['cid'], self.backup['parent']['cid'])
        self.assertEqual(admitted['growth']['target_sectors'], 116637696)

    def test_card_cid_capacity_and_sector_size_must_match_the_fresh_receipt(self):
        for relative, text in (('device/cid', '9' * 32), ('size', '125026305'), ('queue/logical_block_size', '4096')):
            path = self.parent / relative
            saved = path.read_text()
            path.write_text(text)
            with self.subTest(field=relative), self.assertRaisesRegex(ValueError, 'Current card'):
                self.admit()
            path.write_text(saved)

    def test_changed_partition_start_size_parent_and_filesystem_uuid_reject(self):
        for key, value in (('start_sector', 8388609), ('bytes', 4294967808), ('parent', '/different-card')):
            original = self.parts[3][key]
            self.parts[3][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.admit()
            self.parts[3][key] = original
        for key in ('UUID', 'PART_ENTRY_UUID', 'TYPE'):
            saved = self.filesystems['/dev/fixture3'][key]
            self.filesystems['/dev/fixture3'][key] = 'wrong'
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, 'Filesystem UUID'):
                self.admit()
            self.filesystems['/dev/fixture3'][key] = saved

    def test_running_store_cannot_be_treated_as_fixed_recovery(self):
        self.parts[2]['number'] = 3
        with self.assertRaisesRegex(ValueError, 'fixed recovery'):
            self.admit()


class BusyDevices(unittest.TestCase):
    def setUp(self):
        self.admitted = dict(parent={'device': '179:0'}, partitions={name: {'device': '179:' + str(number)}
            for number, name in enumerate(('boot', 'recovery', 'store'), 1)})

    def test_mount_bind_and_block_aliases_are_rejected_by_device_number(self):
        for number in ('179:0', '179:1', '179:3'):
            for path in ('/store', '/bind-alias', '/unexpected-mount'):
                with self.subTest(device=number, point=path), \
                        patch.object(grow, 'mounts', return_value=[dict(device=number, point=path)]), \
                        self.assertRaisesRegex(ValueError, 'mounted aliases'):
                    grow.assert_unmounted(self.admitted)

    def test_holders_and_swap_aliases_veto_ownership_handoffs(self):
        original_read = Path.read_text
        def swap_text(path, *args, **kwargs):
            if str(path) == '/proc/swaps':
                return 'Filename Type Size Used Priority\n/dev/hidden-swap partition 4096 0 -2\n'
            return original_read(path, *args, **kwargs)
        with patch.object(grow, 'mounts', return_value=[]), patch.object(Path, 'is_dir', return_value=True):
            with patch.object(Path, 'iterdir', return_value=iter([Path('/fixture-holder')])):
                with self.assertRaisesRegex(ValueError, 'holders'):
                    grow.assert_unmounted(self.admitted)
            for mode in (stat.S_IFBLK, stat.S_IFREG):
                info = types.SimpleNamespace(st_mode=mode, st_rdev=os.makedev(179, 3), st_dev=os.makedev(179, 3))
                with self.subTest(swap_kind=mode), patch.object(Path, 'iterdir', side_effect=lambda: iter([])), \
                        patch.object(Path, 'read_text', swap_text), patch.object(Path, 'stat', return_value=info), \
                        self.assertRaisesRegex(ValueError, 'swap'):
                    grow.assert_unmounted(self.admitted)


class GrowthFailureBoundaries(unittest.TestCase):
    def fixture(self):
        backup = checkpoint()
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        parts = {name: dict(node='/dev/fixture' + str(number), device='179:' + str(number),
            number=number, parent='/sys/fixture', start_sector=backup['partitions'][name]['start_sector'],
            bytes=backup['partitions'][name]['bytes'])
            for number, name in enumerate(('boot', 'recovery', 'store'), 1)}
        admitted = dict(parent=dict(node='/dev/fixture', device='179:0', **backup['parent']),
                        partitions=parts, growth=grow.growth_plan(backup))
        operation = types.SimpleNamespace(path=root, log=self.enterContext(tempfile.TemporaryFile()),
                                          record=dict(write_started=False, completed=False, events=[]))
        def update(phase, **values):
            operation.record.update(values, phase=phase)
            operation.record['events'].append(dict(phase=phase, **values))
        operation.update = Mock(side_effect=update)
        return admitted, backup, operation

    @contextmanager
    def core(self, fixture, *, fail=None, protected_error=False, source_error=False, geometry_error=False,
             write_error=False):
        admitted, backup, operation = fixture
        claims, commands = set(), []
        @contextmanager
        def exclusive(target):
            self.assertNotIn(target['node'], claims)
            claims.add(target['node'])
            try:
                yield 55
            finally:
                claims.remove(target['node'])
        counts = {}
        def command(arguments, **options):
            name = str(arguments[0])
            commands.append([str(value) for value in arguments])
            counts[name] = counts.get(name, 0) + 1
            if name in ('e2fsck', 'resize2fs'):
                self.assertNotIn('/dev/fixture3', claims,
                                 'Filesystem utility must receive its own exclusive block-device claim')
                self.assertIn('/dev/fixture1', claims, 'Boot must remain protected during filesystem writes')
            if name in ('sfdisk', 'partx'):
                self.assertIn('/dev/fixture3', claims)
            if fail == (name, counts[name]):
                raise ValueError('injected ' + name + ' failure')
            if name == 'sfdisk':
                surrogate = Path(arguments[-1])
                self.assertEqual(surrogate.parent, operation.path)
                self.assertNotEqual(str(surrogate), admitted['parent']['node'])
                self.assertEqual(surrogate.stat().st_size, 64013467648)
                candidate = bytearray.fromhex(backup['mbr_hex'])
                candidate[490:494] = struct.pack('<I', 116637696)
                candidate[479:482] = b'\x01\x02\x03'
                with surrogate.open('r+b') as stream:
                    stream.write(candidate)
            return b''
        def write_length(*_):
            self.assertIn('/dev/fixture3', claims)
            if write_error:
                raise OSError('injected single length write failure')
            operation.update('growing-partition', write_bytes=4, write_offset_bytes=490)
        def geometry(_, *, grown=False):
            if geometry_error and grown:
                raise ValueError('kernel update did not take effect')
        def superblock(_):
            grown = any(values[0] == 'resize2fs' for values in commands)
            return dict(bytes=admitted['growth']['target_bytes' if grown else 'old_bytes'],
                        block_bytes=4096, features=(1, 2, 3), uuid_hex='a' * 32)
        with ExitStack() as stack:
            for name in ('require_private_mount_namespace', 'assert_unmounted', '_verify_identities', 'verify_contents'):
                stack.enter_context(patch.object(grow, name))
            stack.enter_context(patch.object(grow, 'assert_geometry', side_effect=geometry))
            stack.enter_context(patch.object(grow, '_verify_source',
                side_effect=ValueError('checkpoint hash differs') if source_error else None))
            stack.enter_context(patch.object(grow, '_verify_protected',
                side_effect=ValueError('MBR changed outside p3 length') if protected_error else None))
            stack.enter_context(patch.object(grow, 'exclusive_device', side_effect=exclusive))
            stack.enter_context(patch.object(grow, 'read_mbr', return_value=bytes.fromhex(backup['mbr_hex'])))
            stack.enter_context(patch.object(grow, 'ext4_geometry', side_effect=superblock))
            stack.enter_context(patch.object(grow, 'command', side_effect=command))
            stack.enter_context(patch.object(grow, 'write_partition_length', side_effect=write_length))
            yield commands
        self.assertFalse(claims)

    def test_complete_path_hands_exclusion_to_offline_utilities_then_verifies(self):
        fixture = self.fixture()
        admitted, backup, operation = fixture
        with self.core(fixture) as commands:
            grow.execute_growth(admitted, backup, operation)
        self.assertEqual([values[0] for values in commands],
                         ['e2fsck', 'sfdisk', 'e2fsck', 'partx', 'resize2fs', 'e2fsck'])
        self.assertIn('-n', commands[0])
        self.assertIn('-p', commands[2])
        self.assertIn('-n', commands[-1])
        self.assertIn('--no-reread', commands[1])
        self.assertIn('--no-tell-kernel', commands[1])
        self.assertIn('--lock=nonblock', commands[1], 'sfdisk optional lock arguments require the equals form')
        self.assertEqual(commands[3][1:4], ['--update', '--nr', '3'])
        self.assertTrue(operation.record['completed'])
        self.assertFalse(operation.record['boot_selection_changed'])
        self.assertFalse(operation.record['reboot_performed'])

    def test_each_utility_failure_stops_at_that_original_attempt(self):
        expected = ['e2fsck', 'sfdisk', 'e2fsck', 'partx', 'resize2fs', 'e2fsck']
        for stop, failure in enumerate((('e2fsck', 1), ('sfdisk', 1), ('e2fsck', 2),
                                        ('partx', 1), ('resize2fs', 1), ('e2fsck', 3))):
            fixture = self.fixture()
            admitted, backup, operation = fixture
            with self.subTest(failure=failure), self.core(fixture, fail=failure) as commands:
                with self.assertRaisesRegex(ValueError, 'injected'):
                    grow.execute_growth(admitted, backup, operation)
            self.assertEqual([values[0] for values in commands], expected[:stop + 1])
            self.assertFalse(operation.record['completed'])
            self.assertEqual(operation.record['write_started'], stop > 1)

    def test_full_backup_hash_failure_prevents_the_first_filesystem_write(self):
        fixture = self.fixture()
        with self.core(fixture, source_error=True) as commands, self.assertRaisesRegex(ValueError, 'checkpoint hash'):
            grow.execute_growth(*fixture)
        self.assertEqual([values[0] for values in commands], ['e2fsck'])
        self.assertFalse(fixture[2].record['write_started'])

    def test_written_mbr_mismatch_and_failed_kernel_update_cannot_reach_resize(self):
        for arguments in (dict(protected_error=True), dict(geometry_error=True)):
            fixture = self.fixture()
            with self.subTest(arguments=arguments), self.core(fixture, **arguments) as commands, \
                    self.assertRaises(ValueError):
                grow.execute_growth(*fixture)
            self.assertNotIn('resize2fs', [values[0] for values in commands])
            self.assertEqual(sum(values[0] == 'sfdisk' for values in commands), 1)
            self.assertFalse(fixture[2].record['completed'])

    def test_failed_single_partition_write_never_updates_kernel_or_retries(self):
        fixture = self.fixture()
        with self.core(fixture, write_error=True) as commands, self.assertRaisesRegex(OSError, 'single length'):
            grow.execute_growth(*fixture)
        self.assertEqual([values[0] for values in commands], ['e2fsck', 'sfdisk', 'e2fsck'])
        self.assertTrue(fixture[2].record['write_started'])
        self.assertFalse(fixture[2].record['completed'])

    def test_changed_admitted_target_never_reaches_a_claim_or_command(self):
        fixture = self.fixture()
        fixture[0]['growth']['target_bytes'] -= 4096
        with self.core(fixture) as commands, self.assertRaisesRegex(ValueError, 'Admitted target'):
            grow.execute_growth(*fixture)
        self.assertEqual(commands, [])

    def test_complete_filesystem_checks_cannot_hide_failed_content_validation(self):
        fixture = self.fixture()
        with self.core(fixture) as commands, \
                patch.object(grow, 'verify_contents', side_effect=ValueError('preserved setting changed')), \
                self.assertRaisesRegex(ValueError, 'preserved setting'):
            grow.execute_growth(*fixture)
        self.assertEqual([values[0] for values in commands][-2:], ['resize2fs', 'e2fsck'])
        self.assertFalse(fixture[2].record['completed'])

    def test_wrong_post_resize_filesystem_size_or_identity_never_completes(self):
        for field, value in (('bytes', 4294967296), ('uuid_hex', 'f' * 32), ('features', (9, 9, 9))):
            fixture = self.fixture()
            admitted, backup, operation = fixture
            original = dict(bytes=4294967296, block_bytes=4096, features=(1, 2, 3), uuid_hex='a' * 32)
            changed = dict(original, bytes=59718500352)
            changed[field] = value
            with self.subTest(field=field), self.core(fixture), \
                    patch.object(grow, 'ext4_geometry', side_effect=[original, changed]), self.assertRaises(ValueError):
                grow.execute_growth(admitted, backup, operation)
            self.assertFalse(operation.record['completed'])


class DurableOwnership(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual_fstat = os.fstat
            def root_owned(descriptor):
                info = actual_fstat(descriptor)
                return types.SimpleNamespace(st_mode=info.st_mode, st_uid=0)
            with ExitStack() as stack:
                stack.enter_context(patch.object(grow, 'BACKUP_REGISTRY', root / 'backup-registry'))
                stack.enter_context(patch.object(grow.installer, 'REGISTRY', root / 'bootstrap-registry'))
                stack.enter_context(patch.object(grow, 'root_directory', side_effect=lambda path, _: path))
                stack.enter_context(patch.object(grow.installer, 'root_directory', side_effect=lambda path, _: path))
                stack.enter_context(patch.object(grow.os, 'fstat', side_effect=root_owned))
                yield root, root / 'growth-registry'

    def test_duplicate_grow_and_bootstrap_writers_cannot_overlap(self):
        with self.fixture() as (root, registry):
            with grow.ownership(root / 'first', {}, registry=registry):
                with self.assertRaisesRegex(ValueError, 'Another'):
                    with grow.ownership(root / 'second', {}, registry=registry):
                        self.fail('Duplicate growth writer was admitted')
                with self.assertRaisesRegex(ValueError, 'Another'):
                    with grow.installer.ownership(root / 'bootstrap', {}, registry=grow.installer.REGISTRY):
                        self.fail('Bootstrap writer overlapped growth')
            self.assertFalse((root / 'second').exists())
            self.assertFalse((root / 'bootstrap').exists())

    def test_observer_interruption_preserves_original_log_and_rejects_new_operation(self):
        with self.fixture() as (root, registry):
            with self.assertRaisesRegex(RuntimeError, 'observer disconnected'):
                with grow.ownership(root / 'first', {}, registry=registry) as operation:
                    operation.log.write(b'original destructive operation\n')
                    operation.update('growing-partition', write_started=True)
                    raise RuntimeError('observer disconnected')
            original = (root / 'first/state.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'unresolved'):
                with grow.ownership(root / 'second', {}, registry=registry):
                    self.fail('Unresolved destructive operation was retried')
            self.assertEqual((root / 'first/state.json').read_bytes(), original)
            self.assertIn('observer disconnected', json.loads(original)['error'])
            self.assertIn(b'original destructive operation', (root / 'first/operation.log').read_bytes())
            self.assertFalse((root / 'second').exists())

    def test_backup_writer_and_unresolved_bootstrap_each_exclude_a_new_growth(self):
        with self.fixture() as (root, registry):
            grow.BACKUP_REGISTRY.mkdir()
            with (grow.BACKUP_REGISTRY / 'backup.lock').open('wb') as lock:
                os.fchmod(lock.fileno(), 0o600)
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError, 'Another'):
                    with grow.ownership(root / 'during-backup', {}, registry=registry):
                        self.fail('Growth overlapped a verified-backup writer')
            with self.assertRaisesRegex(RuntimeError, 'old interrupted bootstrap'):
                with grow.installer.ownership(root / 'old-bootstrap', {}, registry=grow.installer.REGISTRY) as operation:
                    operation.update('writing', write_started=True)
                    raise RuntimeError('old interrupted bootstrap')
            with self.assertRaisesRegex(ValueError, 'unresolved bootstrap'):
                with grow.ownership(root / 'new-growth', {}, registry=registry):
                    self.fail('Growth bypassed an unresolved bootstrap operation')
            self.assertFalse((root / 'during-backup').exists())
            self.assertFalse((root / 'new-growth').exists())


class ReadOnlyInterfaces(unittest.TestCase):
    def test_status_reads_the_retained_original_without_resuming_or_rewriting_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            original = b'{"operation":"development-store-growth","phase":"growing-filesystem","completed":false}\n'
            (path / 'state.json').write_bytes(original)
            args = types.SimpleNamespace(status=path, apply=False)
            with patch.object(grow, 'execute_growth') as execute, patch.object(grow, 'ownership') as ownership:
                result = grow.run_growth(args)
            self.assertTrue(result['read_only'])
            self.assertFalse(result['record']['completed'])
            self.assertEqual((path / 'state.json').read_bytes(), original)
            self.assertEqual([entry.name for entry in path.iterdir()], ['state.json'])
            execute.assert_not_called()
            ownership.assert_not_called()

    def test_nonroot_apply_fails_before_reading_or_creating_state(self):
        args = types.SimpleNamespace(status=None, apply=True, backup_receipt=Path('/fixture/backup.json'),
                                     state=Path('/fixture/fresh'))
        with patch.object(grow.os, 'geteuid', return_value=1000), patch.object(grow, 'read_record') as read, \
                patch.object(grow, 'ownership') as ownership, self.assertRaisesRegex(ValueError, 'root'):
            grow.run_growth(args)
        read.assert_not_called()
        ownership.assert_not_called()

    def test_plan_has_no_writer_or_filesystem_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = types.SimpleNamespace(status=None, apply=False, backup_receipt=Path(temporary) / 'backup.json',
                                         state=Path(temporary) / 'fresh')
            backup = checkpoint()
            with patch.object(grow, 'read_record', return_value=(backup, b'checkpoint')), \
                    patch.object(grow, 'runtime_admission', return_value={'growth': grow.growth_plan(backup)}), \
                    patch.object(grow, 'root_directory', side_effect=lambda path, _: path), \
                    patch.object(grow, 'command') as command, patch.object(grow, 'ownership') as ownership:
                result = grow.run_growth(args)
            self.assertTrue(result['plan'])
            self.assertFalse(result['executed'])
            self.assertFalse(args.state.exists())
            command.assert_not_called()
            ownership.assert_not_called()

    def test_already_grown_media_refuses_reapply_and_read_only_plan_without_a_write(self):
        for apply in (False, True):
            with self.subTest(apply=apply), tempfile.TemporaryDirectory() as temporary:
                backup = checkpoint()
                backup['parent']['bytes'] = 8589934592
                args = types.SimpleNamespace(status=None, apply=apply,
                    backup_receipt=Path(temporary) / 'backup.json', state=Path(temporary) / 'fresh')
                def admission(value):
                    return grow.growth_plan(value)
                with patch.object(grow.os, 'geteuid', return_value=0), \
                        patch.object(grow, '_check_location'), patch.object(grow, 'require_private_mount_namespace'), \
                        patch.object(grow, 'read_record', return_value=(backup, b'checkpoint')), \
                        patch.object(grow, 'runtime_admission', side_effect=admission), \
                        patch.object(grow, 'command') as command, patch.object(grow, 'ownership') as ownership, \
                        self.assertRaises(ValueError):
                    grow.run_growth(args)
                self.assertFalse(args.state.exists())
                command.assert_not_called()
                ownership.assert_not_called()


if __name__ == '__main__':
    unittest.main()
