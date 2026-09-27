"""Recovery archives must be complete and must never open a card for writing."""
import gzip
import hashlib
import importlib.util
import io
from pathlib import Path
import plistlib
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backup_macos', Path(__file__).parents[1] / 'backup-macos.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class RecoveryBackup(unittest.TestCase):
    def test_identity_accepts_linux_card_without_filesystem_uuid(self):
        info = dict(WholeDisk=True, Internal=False, VirtualOrPhysical='Physical', BusProtocol='USB',
                    RemovableMediaOrExternalDevice=True, Writable=False, TotalSize=8192,
                    DeviceBlockSize=512, MediaName='SD reader', DeviceTreePath='usb-path')
        listing = {'AllDisksAndPartitions': [{'DeviceIdentifier': 'disk16', 'Content': 'FDisk_partition_scheme',
                                              'Partitions': [{'DeviceIdentifier': 'disk16s1',
                                                              'Content': 'Linux', 'Size': 4096}]}]}
        with patch.object(backup.subprocess, 'check_output', side_effect=[plistlib.dumps(info),
                                                                        plistlib.dumps(listing)]):
            result = backup.identity('disk16')
        self.assertEqual(result['TotalSize'], 8192)
        self.assertEqual(result['partitions'][0]['Content'], 'Linux')
        info['Internal'] = True
        with patch.object(backup.subprocess, 'check_output', return_value=plistlib.dumps(info)), \
             self.assertRaises(RuntimeError):
            backup.identity('disk16')

    def test_bad_identifier_never_reaches_diskutil(self):
        for disk in ('disk0', 'disk16s1', '/dev/disk16', 'disk16; command'):
            with self.subTest(disk=disk), patch.object(backup.subprocess, 'check_output') as query, \
                 self.assertRaises(RuntimeError):
                backup.identity(disk)
            query.assert_not_called()

    def test_whole_card_archive_and_no_write_access(self):
        data = bytes(range(256)) * 4096
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'fake-card'
            source.write_bytes(data)
            destination = Path(folder) / 'recovery.img.gz'
            expected = {'device': 'disk16', 'TotalSize': len(data)}
            def open_card(path, mode, buffering):
                self.assertEqual((path, mode, buffering), ('/dev/rdisk16', 'rb', 0))
                return source.open(mode, buffering=buffering)
            with patch.object(backup.os, 'geteuid', return_value=0), \
                 patch.object(backup.shutil, 'disk_usage', return_value=SimpleNamespace(free=8 * 1024**3)), \
                 patch.object(backup, 'identity', return_value=expected), \
                 patch.object(backup.subprocess, 'run') as command, \
                 patch.object(backup, 'open', side_effect=open_card, create=True), \
                 patch.object(backup.stat, 'S_ISCHR', return_value=True), \
                 patch.object(backup, 'digest_file', wraps=backup.digest_file) as digest, \
                 patch.dict(backup.os.environ, {}, clear=True):
                # Only raw-device reads use the module-level open override.
                # Hashing archive files uses Path.open to keep that distinction explicit.
                result = backup.backup('disk16', destination)
            self.assertEqual(gzip.decompress(destination.read_bytes()), data)
            self.assertEqual(result['image_sha256'], hashlib.sha256(data).hexdigest())
            self.assertFalse(result['card_written'])
            self.assertEqual(digest.call_count, 2)
            self.assertEqual(command.call_args.args[0][-2:], ['eject', '/dev/disk16'])
            self.assertFalse(destination.with_name(destination.name + '.part').exists())

    def test_short_card_is_a_failure(self):
        with tempfile.TemporaryFile() as source:
            source.write(b'short')
            source.seek(0)
            with patch.object(backup, 'open', return_value=source, create=True), \
                 patch.object(backup.stat, 'S_ISCHR', return_value=True), \
                 self.assertRaisesRegex(RuntimeError, 'Unexpected end'):
                backup.read_card('/dev/rdisk16', 512, io.BytesIO())

    def test_changed_card_never_starts_reading(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(backup.os, 'geteuid', return_value=0), \
             patch.object(backup.shutil, 'disk_usage', return_value=SimpleNamespace(free=8 * 1024**3)), \
             patch.object(backup, 'identity', side_effect=[{'TotalSize': 512}, {'TotalSize': 1024}]), \
             patch.object(backup.subprocess, 'run'), patch.object(backup, 'read_card') as read, \
             self.assertRaisesRegex(RuntimeError, 'identity changed'):
            backup.backup('disk16', Path(folder) / 'recovery.img.gz')
        read.assert_not_called()

    def test_corrupt_archive_is_not_published_or_ejected(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(backup.os, 'geteuid', return_value=0), \
             patch.object(backup.shutil, 'disk_usage', return_value=SimpleNamespace(free=8 * 1024**3)), \
             patch.object(backup, 'identity', return_value={'TotalSize': 512}), \
             patch.object(backup.subprocess, 'run') as command, \
             patch.object(backup, 'read_card', return_value='wrong-hash'):
            destination = Path(folder) / 'recovery.img.gz'
            with self.assertRaisesRegex(RuntimeError, 'does not match'):
                backup.backup('disk16', destination)
            self.assertFalse(destination.exists())
            self.assertTrue(destination.with_name(destination.name + '.part').exists())
            self.assertEqual(command.call_count, 1)  # Only unmount, never eject on failure.


if __name__ == '__main__':
    unittest.main()
