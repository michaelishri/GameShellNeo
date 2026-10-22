"""Offline installer admission, bounded I/O and durable ownership regressions."""
from contextlib import contextmanager, ExitStack
import copy
import errno
import gzip
import hashlib
import importlib.util
import io
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
SPEC = importlib.util.spec_from_file_location('development_store_installer', TOOLS / 'install-dev-store.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class BlockSizeRequest(unittest.TestCase):
    def test_arm32_and_64_bit_requests_match_the_literal_linux_abi(self):
        self.assertEqual(installer.blkgetsize64_request(4), 0x80041272)
        self.assertEqual(installer.blkgetsize64_request(8), 0x80081272)
        native = {4: 0x80041272, 8: 0x80081272}[struct.calcsize('N')]
        self.assertEqual(installer.blkgetsize64_request(), native)
        self.assertEqual(installer.BLKGETSIZE64, native)
        for invalid in (0, 2, 16, True, '4'):
            with self.subTest(width=invalid), self.assertRaises(ValueError):
                installer.blkgetsize64_request(invalid)


class ArchiveAndBlockIO(unittest.TestCase):
    def setUp(self):
        self.data = bytes(range(256)) * 1024
        self.gzip = gzip.compress(self.data, mtime=0)
        self.raw = {'bytes': len(self.data), 'sha256': sha(self.data)}
        self.compressed = {'bytes': len(self.gzip), 'sha256': sha(self.gzip)}

    def test_full_compressed_and_decompressed_admission(self):
        installer.verify_archive(io.BytesIO(self.gzip), self.compressed, self.raw)
        cases = [(self.gzip + b'extra', self.compressed, self.raw),
                 (self.gzip[:-6], dict(bytes=len(self.gzip) - 6, sha256=sha(self.gzip[:-6])), self.raw),
                 (b'not gzip', dict(bytes=8, sha256=sha(b'not gzip')), self.raw),
                 (self.gzip, self.compressed, dict(self.raw, bytes=len(self.data) - 1)),
                 (self.gzip, self.compressed, dict(self.raw, bytes=len(self.data) + 1)),
                 (self.gzip, self.compressed, dict(self.raw, sha256='0' * 64))]
        for data, compressed, raw in cases:
            with self.subTest(bytes=len(data), raw=raw), patch.object(installer.os, 'write') as writing:
                with self.assertRaises(ValueError):
                    installer.verify_archive(io.BytesIO(data), compressed, raw)
                writing.assert_not_called()

    def test_same_fd_write_fsync_rewind_and_full_readback_preserve_suffix(self):
        with tempfile.TemporaryFile() as target:
            suffix = b'outside declared raw boundary'
            target.write(b'X' * len(self.data) + suffix)
            target.flush()
            descriptor = target.fileno()
            progress = []
            result = installer.write_and_readback(descriptor, io.BytesIO(self.gzip), self.raw,
                                                  progress=progress.append)
            self.assertEqual(result, self.raw)
            target.seek(0)
            self.assertEqual(target.read(), self.data + suffix)
            self.assertEqual(progress[-1], len(self.data))

    def test_short_and_interrupted_syscalls_are_completed_without_restarting_the_image(self):
        actual_write, actual_read = os.write, os.read
        writes, reads = [], []

        def short_write(descriptor, data):
            writes.append(len(data))
            if len(writes) == 1:
                raise InterruptedError(errno.EINTR, 'injected interruption')
            return actual_write(descriptor, data[:16381])

        def short_read(descriptor, size):
            reads.append(size)
            if len(reads) == 1:
                raise InterruptedError(errno.EINTR, 'injected interruption')
            return actual_read(descriptor, min(size, 16379))

        with tempfile.TemporaryFile() as target, patch.object(installer.os, 'write', side_effect=short_write), \
                patch.object(installer.os, 'read', side_effect=short_read):
            self.assertEqual(installer.write_and_readback(target.fileno(), io.BytesIO(self.gzip), self.raw), self.raw)
        self.assertGreater(len(writes), 2)
        self.assertGreater(len(reads), 2)

    def test_zero_write_hard_failure_and_corrupt_or_short_readback_reject(self):
        for writing in (lambda *_: 0, Mock(side_effect=OSError(errno.EIO, 'injected I/O failure'))):
            with tempfile.TemporaryFile() as target, patch.object(installer.os, 'write', side_effect=writing), \
                    self.assertRaises((ValueError, OSError)):
                installer.write_and_readback(target.fileno(), io.BytesIO(self.gzip), self.raw)
        for data in (b'', b'changed' * 4096):
            with tempfile.TemporaryFile() as target, \
                    patch.object(installer.os, 'read', side_effect=[data, b'']), self.assertRaises(ValueError):
                installer.write_and_readback(target.fileno(), io.BytesIO(self.gzip), self.raw)

    def test_public_claim_rejects_a_regular_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'ordinary-file'
            target.write_bytes(b'preserved')
            with self.assertRaisesRegex(ValueError, 'block partition'):
                with installer.exclusive_device({'node': str(target), 'device': '8:3', 'bytes': 9}):
                    self.fail('A public regular-file claim must never succeed')
            self.assertEqual(target.read_bytes(), b'preserved')

    def test_symlink_and_nonregular_uploads_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root / 'actual'
            actual.write_bytes(self.gzip)
            link = root / 'link'
            link.symlink_to(actual)
            pipe = root / 'pipe'
            os.mkfifo(pipe)
            for path in (link, pipe):
                with self.subTest(path=path.name), self.assertRaises(ValueError):
                    with installer.regular_file(path):
                        self.fail('Untrusted upload type was accepted')

    def test_snapshot_copies_once_checks_space_and_retains_a_failed_upload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upload = root / 'upload.gz'
            upload.write_bytes(self.gzip)
            operation = types.SimpleNamespace(path=root / 'operation')
            operation.path.mkdir(mode=0o700)
            with patch.object(installer.os, 'statvfs', return_value=types.SimpleNamespace(f_bavail=0, f_frsize=4096)), \
                    self.assertRaisesRegex(ValueError, 'space'):
                installer.snapshot_archive(upload, operation, self.compressed)
            self.assertFalse(list(operation.path.iterdir()))
            copied = installer.snapshot_archive(upload, operation, self.compressed)
            upload.write_bytes(b'upload changed after private copying')
            self.assertEqual(copied.read_bytes(), self.gzip)
            self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o600)
            failed = types.SimpleNamespace(path=root / 'failed')
            failed.path.mkdir()
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                installer.snapshot_archive(upload, failed, self.compressed)
            self.assertTrue((failed.path / 'archive.img.gz').exists())


class RecoveryIdentity(unittest.TestCase):
    def test_original_root_boot_and_no_development_provenance_are_mandatory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / 'etc/gameshellneo/image.json'
            identity.parent.mkdir(parents=True)
            cmdline, boot = root / 'cmdline', root / 'boot-id'
            cmdline.write_text('console=tty0 root=PARTUUID=1234abcd-02')
            boot.write_text('test-boot\n')
            original = dict(root_partuuid='1234abcd-02', board='gameshellneo-cpi31', kernel=os.uname().release)
            identity.write_text(json.dumps(original))
            backup = {'root': {'root_partuuid': '1234abcd-02', 'boot_id': 'test-boot',
                              'kernel': os.uname().release, 'image_sha256': sha(identity.read_bytes())},
                      'card': {'board': 'gameshellneo-cpi31'}}
            check = lambda: installer.recovery_identity(backup, root=root, cmdline=cmdline, boot_id=boot)
            self.assertEqual(check(), original)
            for changed in (dict(original, deployment='development-directory'),
                            dict(original, root_partuuid='1234abcd-03'),
                            dict(original, board='different-board'), dict(original, kernel='different-kernel'),
                            dict(original, extra='changed-original-identity')):
                identity.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, 'original fixed recovery'):
                    check()
            identity.write_text(json.dumps(original))
            marker = identity.with_name('development-slot')
            marker.write_text('marker')
            with self.assertRaisesRegex(ValueError, 'directory root'):
                check()
            marker.unlink()
            marker.symlink_to(root / 'missing')
            with self.assertRaises(ValueError):
                check()
            marker.unlink()
            cmdline.write_text('neo.dev=1')
            with self.assertRaisesRegex(ValueError, 'command-line'):
                check()
            cmdline.write_text('console=tty0')
            boot.write_text('different-boot')
            with self.assertRaisesRegex(ValueError, 'Boot changed'):
                check()

    def test_duplicate_kernel_partition_identities_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            events = []
            for name in ('one', 'two'):
                event = Path(temporary) / name / 'uevent'
                event.parent.mkdir()
                event.write_text('PARTUUID=1234abcd-03\n')
                events.append(event)
            for selected in ([], events):
                with patch.object(Path, 'glob', return_value=selected), self.assertRaisesRegex(ValueError, 'duplicated'):
                    installer.unique_partuuids(['1234abcd-03'])
            with patch.object(Path, 'glob', return_value=events[:1]):
                installer.unique_partuuids(['1234abcd-03'])


class LiveAdmission(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.boot, self.store, self.parent = [self.root / name for name in ('boot', 'store', 'card')]
        for path in (self.boot, self.store, self.parent / 'device', self.parent / 'queue'):
            path.mkdir(parents=True, exist_ok=True)
        (self.parent / 'size').write_text('32768')
        (self.parent / 'device/cid').write_text('a' * 32)
        (self.parent / 'queue/logical_block_size').write_text('512')
        self.args = types.SimpleNamespace(boot=self.boot, store=self.store)
        self.parts = {number: dict(node='/dev/fixture' + str(number), device='8:' + str(number),
            number=number, parent=str(self.parent), start_sector=number * 1024, bytes=1024 * 512)
            for number in (1, 2, 3)}
        self.backup = dict(root={'boot_id': 'test-boot'}, parent={'bytes': 32768 * 512,
            'sector_bytes': 512, 'cid': 'a' * 32}, partitions={}, card={'card': 'fixture'},
            catalog={'diag26': {'manifest_sha256': 'a' * 64}}, flags={}, store_files={})
        for number, name in ((1, 'boot'), (2, 'recovery'), (3, 'store')):
            self.backup['partitions'][name] = dict(start_sector=number * 1024, bytes=1024 * 512,
                partuuid='1234abcd-0' + str(number), filesystem_uuid='uuid-' + name)
        for name in ('next.scr', 'good.scr', 'recover.scr'):
            (self.boot / name).write_bytes(b'recovery descriptor')
            self.backup['flags'][name] = sha(b'recovery descriptor')
        (self.store / 'DEVBOOT.JSON').write_text(json.dumps(self.backup['card']))
        (self.store / 'RELEASES.JSON').write_text(json.dumps(self.backup['catalog']))
        (self.store / 'failed-import.log').write_bytes(b'preserve original failure')
        self.backup['store_files'] = {'failed-import.log': sha(b'preserve original failure')}
        self.manifest = {'target': {'parent_minimum_bytes': 8 * 1024 * 1024}}
        self.records = [dict(point='/', root='/', device='8:2', filesystem='ext4', options=['rw'], super_options=[]),
            dict(point=str(self.boot), root='/', device='8:1', filesystem='vfat', options=['rw'],
                 super_options=['shortname=mixed']),
            dict(point=str(self.store), root='/', device='8:3', filesystem='ext4', options=['rw'], super_options=[])]
        self.filesystems = {'/dev/fixture' + str(number): dict(PART_ENTRY_UUID=saved['partuuid'],
            UUID=saved['filesystem_uuid'], TYPE='vfat' if number == 1 else 'ext4')
            for number, saved in enumerate(self.backup['partitions'].values(), 1)}

    def admit(self):
        with patch.object(installer, 'recovery_identity'), patch.object(installer, 'mounts', return_value=self.records), \
                patch.object(installer, 'device_number', return_value='8:2'), \
                patch.object(installer, 'block_partition', return_value=self.parts[2]), \
                patch.object(installer, 'partition_set', return_value=self.parts), \
                patch.object(installer, 'filesystem', side_effect=lambda node: self.filesystems[node]), \
                patch.object(installer, 'unique_partuuids'):
            return installer.runtime_admission(self.args, self.manifest, self.backup, verify_boot=Mock())

    def test_complete_recovery_admission(self):
        admitted = self.admit()
        self.assertEqual(admitted['target']['device'], '8:3')
        self.assertEqual(admitted['parent'], self.backup['parent'])

    def test_mount_alias_bind_wrong_type_and_hidden_fat_case_reject(self):
        original = copy.deepcopy(self.records)
        changes = [(2, 'device', '8:4'), (2, 'root', '/systems/diag26/root'),
                   (1, 'filesystem', 'msdos'), (1, 'super_options', ['shortname=lower']),
                   (0, 'root', '/systems/diag26/root')]
        for index, key, value in changes:
            self.records = copy.deepcopy(original)
            self.records[index][key] = value
            with self.subTest(change=(index, key)), self.assertRaises(ValueError):
                self.admit()
        self.records = copy.deepcopy(original)
        self.records.append(dict(self.records[2], point='/other-alias'))
        with self.assertRaisesRegex(ValueError, 'multiple mounts'):
            self.admit()

    def test_parent_card_geometry_and_filesystem_identity_are_exact(self):
        for filename, data in (('size', '32769'), ('device/cid', 'b' * 32), ('queue/logical_block_size', '4096')):
            path = self.parent / filename
            original = path.read_text()
            path.write_text(data)
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, 'parent card'):
                self.admit()
            path.write_text(original)
        for key, value in (('start_sector', 999), ('bytes', 123), ('parent', '/different/card')):
            original = self.parts[3][key]
            self.parts[3][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'geometry'):
                self.admit()
            self.parts[3][key] = original
        for key in ('UUID', 'PART_ENTRY_UUID', 'TYPE'):
            original = self.filesystems['/dev/fixture3'][key]
            self.filesystems['/dev/fixture3'][key] = 'wrong'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'identity differs'):
                self.admit()
            self.filesystems['/dev/fixture3'][key] = original

    def test_running_root_store_and_changed_catalog_flags_or_original_failure_reject(self):
        self.parts[2]['number'] = 3
        with self.assertRaisesRegex(ValueError, 'fixed recovery partition'):
            self.admit()
        self.parts[2]['number'] = 2
        for path in (self.store / 'RELEASES.JSON', self.store / 'failed-import.log', self.boot / 'next.scr'):
            original = path.read_bytes()
            path.write_bytes(b'{}' if path.suffix == '.JSON' else b'changed')
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                self.admit()
            path.write_bytes(original)
        (self.boot / 'next.scr').rename(self.boot / 'NEXT.SCR')
        with self.assertRaisesRegex(ValueError, 'lowercase'):
            self.admit()


class DurableOwnership(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / 'registry'
            actual_fstat = os.fstat

            def root_owned(descriptor):
                info = actual_fstat(descriptor)
                return types.SimpleNamespace(st_mode=info.st_mode, st_uid=0)

            with patch.object(installer, 'root_directory', side_effect=lambda path, _: path), \
                    patch.object(installer.os, 'fstat', side_effect=root_owned):
                yield root, registry

    def test_duplicate_writer_retained_failure_and_uncertain_write_block_fresh_attempts(self):
        with self.fixture() as (root, registry):
            with installer.ownership(root / 'first', {'test': True}, registry=registry) as operation:
                with self.assertRaisesRegex(ValueError, 'Another.*owns'):
                    with installer.ownership(root / 'second', {}, registry=registry):
                        self.fail('A duplicate writer was admitted')
                operation.update('writing', write_started=True)
                with self.assertRaisesRegex(RuntimeError, 'injected interruption'):
                    raise RuntimeError('injected interruption')
            # Simulate a process dying after its durable destructive intent.
            with self.assertRaisesRegex(ValueError, 'unresolved'):
                with installer.ownership(root / 'third', {}, registry=registry):
                    self.fail('Uncertain destructive attempt was retried')
            saved = json.loads((root / 'first/state.json').read_text())
            self.assertTrue(saved['write_started'])
            self.assertFalse(saved['completed'])
            self.assertFalse((root / 'third').exists())

    def test_failure_keeps_original_error_log_state_and_all_operation_files(self):
        with self.fixture() as (root, registry):
            with self.assertRaisesRegex(RuntimeError, 'original write failure'):
                with installer.ownership(root / 'failed', {}, registry=registry) as operation:
                    (operation.path / 'archive.img.gz').write_bytes(b'original private archive')
                    operation.update('writing', write_started=True)
                    raise RuntimeError('original write failure')
            saved = json.loads((root / 'failed/state.json').read_text())
            self.assertEqual(saved['phase'], 'failed')
            self.assertIn('original write failure', saved['error'])
            self.assertEqual((root / 'failed/archive.img.gz').read_bytes(), b'original private archive')
            self.assertTrue((root / 'failed/operation.log').exists())

    def test_nonroot_apply_is_rejected_before_loading_inputs_or_mutating(self):
        args = types.SimpleNamespace(apply=True)
        with patch.object(installer.os, 'geteuid', return_value=1000), \
                patch.object(installer, 'read_record') as records, \
                patch.object(installer, 'check_installer_location') as location, self.assertRaisesRegex(ValueError, 'root'):
            installer.run_install(args)
        records.assert_not_called()
        location.assert_not_called()


class ReplacementSequence(unittest.TestCase):
    def fixture(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        store, boot, operation_path = root / 'store', root / 'boot', root / 'operation'
        for path in (store, boot, operation_path):
            path.mkdir()
        archive = operation_path / 'archive.img.gz'
        archive.write_bytes(b'private fixture')
        args = types.SimpleNamespace(archive=root / 'upload.gz', store=store, boot=boot)
        target = dict(node='/dev/fixture3', device='8:3', bytes=512)
        admitted = dict(root_device='8:2', target=target)
        manifest = dict(archive={'bytes': 32, 'sha256': 'a' * 64},
                        raw={'bytes': 512, 'sha256': 'b' * 64, 'filesystem_uuid': 'new-uuid'})
        operation = types.SimpleNamespace(path=operation_path, log=self.enterContext(tempfile.TemporaryFile()),
                                          update=Mock(), record={})
        schema = types.SimpleNamespace(verify_boot=Mock(), verify_store=Mock())
        return args, manifest, {}, operation, admitted, schema, archive

    @contextmanager
    def mocked(self, fixture, *, write_error=None, verification_error=None, command_error=None):
        args, manifest, backup, operation, admitted, schema, archive = fixture
        commands, claimed = [], {'active': False, 'closed': False}
        @contextmanager
        def exclusive(_):
            claimed['active'] = True
            try:
                yield 123
            finally:
                claimed.update(active=False, closed=True)
        @contextmanager
        def private(*_, **__):
            yield io.BytesIO()
        def execute(values, **options):
            commands.append(values)
            if values[0] == 'e2fsck':
                self.assertTrue(claimed['active'])
                self.assertEqual(values, ['e2fsck', '-f', '-n', '/proc/self/fd/123'])
                self.assertEqual(options['pass_fds'], (123,))
            if values[0] == 'mount':
                self.assertFalse(claimed['active'])
                self.assertTrue(claimed['closed'])
            if command_error == values[0]:
                raise ValueError('injected ' + values[0] + ' failure')
        with ExitStack() as patches:
            patches.enter_context(patch.object(installer, 'snapshot_archive', return_value=archive))
            patches.enter_context(patch.object(installer, 'regular_file', side_effect=private))
            patches.enter_context(patch.object(installer, 'verify_archive', side_effect=verification_error))
            patches.enter_context(patch.object(installer, 'runtime_admission', return_value=admitted))
            patches.enter_context(patch.object(installer, 'mounts', return_value=[]))
            patches.enter_context(patch.object(installer, 'exclusive_device', side_effect=exclusive))
            patches.enter_context(patch.object(installer, 'command', side_effect=execute))
            patches.enter_context(patch.object(installer, 'write_and_readback', return_value=manifest['raw'],
                                                side_effect=write_error))
            patches.enter_context(patch.object(installer, 'mounted_at'))
            patches.enter_context(patch.object(installer, 'filesystem', return_value={'UUID': 'new-uuid'}))
            patches.enter_context(patch.object(installer, 'recovery_identity'))
            patches.enter_context(patch.object(installer, 'verify_new_admin'))
            yield commands, claimed

    def test_write_failure_never_mounts_and_retains_destructive_intent(self):
        fixture = self.fixture()
        args, manifest, backup, operation, admitted, schema, _ = fixture
        with self.mocked(fixture, write_error=OSError('interrupted write')) as (commands, claimed):
            with self.assertRaisesRegex(OSError, 'interrupted write'):
                installer.replace_store(args, manifest, backup, operation, admitted, schema)
        self.assertEqual(commands, [['umount', '--', args.store]])
        self.assertTrue(any(call.kwargs.get('write_started') is True for call in operation.update.call_args_list))
        schema.verify_store.assert_not_called()

    def test_gzip_or_busy_unmount_failure_cannot_reach_a_target_claim(self):
        for options, message in (({'verification_error': ValueError('corrupt gzip')}, 'corrupt gzip'),
                                 ({'command_error': 'umount'}, 'umount failure')):
            fixture = self.fixture()
            args, manifest, backup, operation, admitted, schema, _ = fixture
            with self.mocked(fixture, **options) as (commands, claimed):
                with self.assertRaisesRegex(ValueError, message):
                    installer.replace_store(args, manifest, backup, operation, admitted, schema)
            self.assertFalse(claimed['active'] or claimed['closed'])
            self.assertFalse(any(call.kwargs.get('write_started') for call in operation.update.call_args_list))
            self.assertFalse(any(values[0] == 'mount' for values in commands))

    def test_fsck_failure_keeps_the_verified_target_unmounted(self):
        fixture = self.fixture()
        args, manifest, backup, operation, admitted, schema, _ = fixture
        with self.mocked(fixture, command_error='e2fsck') as (commands, claimed):
            with self.assertRaisesRegex(ValueError, 'e2fsck failure'):
                installer.replace_store(args, manifest, backup, operation, admitted, schema)
        self.assertTrue(claimed['closed'])
        self.assertEqual([values[0] for values in commands], ['umount', 'e2fsck'])
        schema.verify_store.assert_not_called()

    def test_only_complete_readback_and_protected_fsck_allow_mount_and_validation(self):
        fixture = self.fixture()
        args, manifest, backup, operation, admitted, schema, _ = fixture
        with self.mocked(fixture) as (commands, claimed):
            installer.replace_store(args, manifest, backup, operation, admitted, schema)
        self.assertEqual([values[0] for values in commands], ['umount', 'e2fsck', 'mount'])
        schema.verify_store.assert_called_once_with(args.store, manifest)
        self.assertEqual(operation.update.call_args.args, ('complete',))
        self.assertEqual(operation.update.call_args.kwargs, dict(completed=True, boot_selection_changed=False,
            registered=False, reboot_performed=False, filesystem_check='passed'))

    def test_post_mount_rejection_attempts_only_clean_unmount_and_never_completes(self):
        fixture = self.fixture()
        args, manifest, backup, operation, admitted, schema, _ = fixture
        schema.verify_store.side_effect = ValueError('changed complete slot')
        with self.mocked(fixture) as (commands, claimed):
            with self.assertRaisesRegex(ValueError, 'changed complete slot'):
                installer.replace_store(args, manifest, backup, operation, admitted, schema)
        self.assertEqual([values[0] for values in commands], ['umount', 'e2fsck', 'mount', 'umount'])
        self.assertFalse(any(call.args == ('complete',) for call in operation.update.call_args_list))


if __name__ == '__main__':
    unittest.main()
