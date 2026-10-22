"""Explicit development packaging and Mac orchestration; never contact a Mac."""
import copy
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import remote

spec = importlib.util.spec_from_file_location('pack_dev_card_test', ROOT / 'tools/pack-dev-card.py')
packing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packing)
flash = packing.helper('flash-macos.py')


class DevelopmentTransfer(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.image = self.root / 'development.img'
        self.image.write_bytes(b'development fixture'.ljust(512, b'\0'))
        self.receipt = self.image.with_suffix('.json')
        self.record = dict(schema=1, operation='development-card-assembly', development_only=True,
                           offline_filesystem_checks='passed', recovery_root_byte_identical=True,
                           reserved_bootloader_prefix_byte_identical=True,
                           image='/project/.local/development.img', bytes=512,
                           sha256=hashlib.sha256(self.image.read_bytes()).hexdigest())
        self.receipt.write_text(json.dumps(self.record))
        self.output = self.root / 'development-transfer'
        self.production = self.root / 'production-flash'
        self.production.mkdir(mode=0o700)
        (self.production / 'transfer.json').write_bytes(b'preserved production selection')
        self.checkpoint = self.root / 'checkpoint.json'
        self.checkpoint.write_bytes(b'preserved recovery checkpoint')

    def pack(self):
        return packing.pack(self.image, self.receipt, self.output)

    def test_fresh_private_pack_preserves_production_and_has_complete_receipt(self):
        manifest = self.pack()
        self.assertTrue(manifest['development_only'])
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        self.assertEqual(gzip.decompress((self.output / manifest['compressed_file']).read_bytes()), self.image.read_bytes())
        self.assertEqual((self.output / 'development-card.json').read_bytes(), self.receipt.read_bytes())
        self.assertEqual((self.production / 'transfer.json').read_bytes(), b'preserved production selection')
        self.assertEqual(self.checkpoint.read_bytes(), b'preserved recovery checkpoint')
        self.assertEqual(remote.development_transfer(self.output), (self.output, manifest))
        self.assertNotIn('guard_timeout_seconds', manifest)
        for path in self.output.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        flash.verify_source(self.output / manifest['compressed_file'], manifest)

    def test_existing_output_and_symlink_never_overwrite_a_transfer(self):
        for output in (self.production, self.root / 'alias'):
            if output.name == 'alias':
                output.symlink_to(self.production, target_is_directory=True)
            with self.subTest(output=output.name), self.assertRaises(FileExistsError):
                packing.pack(self.image, self.receipt, output)
        self.assertEqual((self.production / 'transfer.json').read_bytes(), b'preserved production selection')

    def test_unqualified_receipts_and_changed_source_reject(self):
        for field, value in (('schema', True), ('development_only', False), ('offline_filesystem_checks', 'failed'),
                             ('recovery_root_byte_identical', False), ('bytes', 513), ('bytes', '512'),
                             ('reserved_bootloader_prefix_byte_identical', False),
                             ('image', 'production.img'), ('sha256', None)):
            self.receipt.write_text(json.dumps(dict(self.record, **{field: value})))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.pack()
            self.assertFalse(self.output.exists())
        missing = dict(self.record)
        missing.pop('reserved_bootloader_prefix_byte_identical')
        self.receipt.write_text(json.dumps(missing))
        with self.assertRaises(ValueError):
            self.pack()
        self.receipt.write_text(json.dumps(self.record))
        self.image.write_bytes(b'changed'.ljust(512, b'\0'))
        with self.assertRaisesRegex(ValueError, 'Source image differs'):
            self.pack()
        self.assertFalse((self.output / 'transfer.json').exists())

    def test_tampered_archive_or_receipt_rejects_before_ssh(self):
        manifest = self.pack()
        archive = self.output / manifest['compressed_file']
        archive.write_bytes(archive.read_bytes() + b'changed')
        with patch.dict(os.environ, NEO_DEVELOPMENT_TRANSFER=str(self.output)), \
                patch.object(remote, 'connect_mac') as connect, self.assertRaises(ValueError):
            remote.mac_action({}, 'stage', '')
        connect.assert_not_called()
        archive.write_bytes(archive.read_bytes()[:-7])
        receipt = self.output / 'development-card.json'
        receipt.write_text(json.dumps(dict(self.record, sha256='0' * 64)))
        with self.assertRaises(ValueError):
            remote.development_transfer(self.output)

    def test_public_directory_and_symlink_inputs_reject(self):
        self.pack()
        self.output.chmod(0o755)
        with self.assertRaises(ValueError):
            remote.development_transfer(self.output)
        self.output.chmod(0o700)
        link = self.root / 'linked-transfer'
        link.symlink_to(self.output, target_is_directory=True)
        with self.assertRaises(ValueError):
            remote.development_transfer(link)

    def test_explicit_stage_preserves_production_remote_selection(self):
        manifest = self.pack()
        client = MagicMock()
        sftp = client.open_sftp.return_value.__enter__.return_value
        sftp.normalize.return_value = '/Users/test'
        sftp.open.side_effect = lambda *_: io.StringIO(json.dumps(manifest))
        connection = MagicMock()
        connection.__enter__.return_value = client
        with patch.dict(os.environ, NEO_DEVELOPMENT_TRANSFER=str(self.output)), \
                patch.object(remote, 'connect_mac', return_value=connection) as connect, \
                patch.object(remote, 'upload') as upload, patch.object(remote, 'run') as run:
            remote.mac_action({'fixture': 'identity'}, 'stage', '', identity_local=self.root / 'hardware/.local')
        connect.assert_called_once_with({'fixture': 'identity'}, identity_local=self.root / 'hardware/.local')
        destinations = [call.args[2] for call in upload.call_args_list]
        directory = '/Users/test/.local/share/GameShellNeo/development/' + manifest['development_receipt_sha256']
        self.assertIn(directory + '/transfer.json', destinations)
        self.assertIn(directory + '/development-card.json', destinations)
        self.assertNotIn('/Users/test/.local/share/GameShellNeo/transfer.json', destinations)
        self.assertTrue(any('--source-only' in call.args[1] for call in run.call_args_list))
        self.assertFalse(any('--write' in call.args[1] for call in run.call_args_list))

    def test_selected_transfer_cannot_preflight_another_remote_image(self):
        manifest = self.pack()
        sftp = MagicMock()
        sftp.open.side_effect = lambda *_: io.StringIO(json.dumps(dict(manifest, image_sha256='0' * 64)))
        with self.assertRaisesRegex(ValueError, 'differs from the selected'):
            remote.staged_arguments(sftp, '/private/development', manifest)

    def test_development_receipt_is_checked_on_mac_source_verification(self):
        manifest = self.pack()
        (self.output / 'development-card.json').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'receipt checksum'):
            flash.verify_source(self.output / manifest['compressed_file'], manifest)


class GuardDuration(unittest.TestCase):
    def test_eight_gib_is_explicitly_budgeted_and_defaults_remain_900(self):
        size = 8 * 1024 ** 3
        record = dict(schema=1, operation='development-card-assembly', development_only=True,
                      offline_filesystem_checks='passed', recovery_root_byte_identical=True,
                      reserved_bootloader_prefix_byte_identical=True,
                      image='dev.img', bytes=size, sha256='a' * 64)
        packing.validate_receipt(record, 'dev.img', size)
        self.assertEqual(flash.development_guard_seconds(size), 2168)
        self.assertEqual(flash.selected_guard_seconds(dict(image_bytes=size)), 900)
        manifest = dict(development_only=True, image_bytes=size, guard_timeout_seconds=2168)
        self.assertEqual(flash.selected_guard_seconds(manifest, 2168), 2168)
        sftp = MagicMock()
        manifest.update(compressed_file='dev.img.gz')
        sftp.open.side_effect = lambda *_: io.StringIO(json.dumps(manifest))
        arguments = remote.staged_arguments(sftp, '/private', manifest)
        self.assertEqual(arguments[-2:], ['--guard-seconds', '2168'])

    def test_insufficient_overlong_or_non_development_extension_reject(self):
        manifest = dict(development_only=True, image_bytes=8 * 1024 ** 3)
        for value in (0, 900, 2167, 3601, True, '2168'):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                flash.selected_guard_seconds(manifest, value)
        for changed in (dict(manifest, development_only=False), dict(manifest, image_bytes=4 * 1024 ** 3)):
            with self.assertRaises(RuntimeError):
                flash.selected_guard_seconds(changed, 2168)
        with self.assertRaises(RuntimeError):
            flash.development_guard_seconds(14 * 1024 ** 3)
        sftp = MagicMock()
        sftp.open.side_effect = lambda *_: io.StringIO(json.dumps(dict(manifest, compressed_file='dev.img.gz')))
        with self.assertRaises(ValueError):
            remote.staged_arguments(sftp, '/private')

    def test_expired_extended_guard_stops_before_any_mount_or_disk_operation(self):
        guard = flash.MountGuard('disk16', 2168)
        guard.process = MagicMock()
        guard.process.poll.return_value = -signal.SIGALRM
        with patch.object(flash.subprocess, 'run') as run, self.assertRaisesRegex(RuntimeError, 'guard exited'):
            guard.verify_veto('disk16s1')
        run.assert_not_called()

    def test_bad_extended_budget_fails_before_the_target_is_inspected(self):
        manifest = dict(development_only=True, image_bytes=8 * 1024 ** 3)
        with patch.object(flash.os, 'geteuid', return_value=0), \
                patch.object(flash, 'validate_target') as validate, self.assertRaises(RuntimeError):
            flash.flash(Path('unused.img.gz'), {}, manifest, guard_seconds=2167)
        validate.assert_not_called()

    @unittest.skipUnless(shutil.which('cc'), 'native C compiler required')
    def test_native_guard_duration_parser_and_expiry_boundaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'guard-test'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-DNEO_MAC_GUARD_TEST',
                str(ROOT / 'tools/macos-mount-guard.c'), '-o', str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True)


class HardwareIdentity(unittest.TestCase):
    def test_existing_identity_paths_are_reused_without_copying_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            hardware = Path(temporary) / 'hardware'
            hardware.mkdir()
            (hardware / '.env').touch()  # Empty synthetic fixture, never the owner's file.
            config = {'M2_MACBOOK_AIR_IP': '192.0.2.1', 'M2_MACBOOK_AIR_USERNAME': 'test',
                      'M2_MACBOOK_AIR_KEY': '.local/ssh/mac-key'}
            known = hardware / '.local/ssh/known_hosts'
            known.parent.mkdir(parents=True)
            known.touch()
            with patch.object(remote, 'load_env', return_value=copy.deepcopy(config)) as load:
                actual, local = remote.hardware_mac_config(hardware)
            load.assert_called_once_with(hardware / '.env')
            self.assertEqual(local, hardware / '.local')
            self.assertEqual(actual['M2_MACBOOK_AIR_KEY'], str(hardware / '.local/ssh/mac-key'))
            with patch.object(remote.paramiko, 'SSHClient') as factory:
                remote.connect_mac(actual, identity_local=local)
            factory.return_value.load_host_keys.assert_called_once_with(str(known))
            self.assertIsInstance(factory.return_value.set_missing_host_key_policy.call_args.args[0],
                                  remote.paramiko.RejectPolicy)


if __name__ == '__main__':
    unittest.main()
