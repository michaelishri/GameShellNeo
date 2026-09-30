"""Recovery selection must use matching provenance, not the latest build metadata."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recovery_image as recovery
import remote


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / '.local/recovery/previous'
        self.directory.mkdir(parents=True)
        self.raw = self.root / '.local/artifacts/old.img'
        self.gz = self.root / '.local/flash/old.img.gz'
        for path, data in ((self.raw, b'raw'), (self.gz, b'compressed')):
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
        self.transfer = dict(image='old.img', image_bytes=3, image_sha256=recovery.digest(self.raw),
                             compressed_file='old.img.gz', compressed_bytes=10,
                             compressed_sha256=recovery.digest(self.gz))
        lock = dict(image_version='previous')
        self.records = {
            'transfer.json': self.transfer,
            'artifacts.json': dict(image='.local/artifacts/old.img', compressed='.local/flash/old.img.gz',
                                   image_sha256=self.transfer['image_sha256'],
                                   compressed_sha256=self.transfer['compressed_sha256']),
            'verification.json': dict(image='old.img', bytes=3, sha256=self.transfer['image_sha256'],
                                      offline_verification='passed'),
            'image-manifest.json': dict(version='previous', kernel='kernel', sources=lock),
            'kernel-completed.json': dict(kernel_release='kernel'),
            'sources.lock.json': lock,
            'kernel.config': 'fixture',
        }
        self.save()

    def save(self):
        for name, value in self.records.items():
            (self.directory / name).write_text(json.dumps(value))
        (self.directory / 'metadata-sha256.json').write_text(json.dumps({name:
            recovery.digest(self.directory/name) for name in self.records}))

    def test_selection_does_not_depend_on_current_metadata(self):
        self.assertEqual(recovery.resolve(self.root, 'previous'),
                         (self.gz, self.directory/'transfer.json', self.transfer))

    def test_mismatches_even_with_rehashed_metadata_are_rejected(self):
        saved = deepcopy(self.records)
        for filename, key, value in (
                ('transfer.json', 'image', 'new.img'),
                ('transfer.json', 'image_bytes', 4),
                ('image-manifest.json', 'version', 'other'),
                ('kernel-completed.json', 'kernel_release', 'other'),
                ('artifacts.json', 'image', '../old.img'),
                ('verification.json', 'offline_verification', 'failed')):
            self.records = deepcopy(saved)
            self.records[filename][key] = value
            self.save()
            with self.subTest(filename=filename, key=key), self.assertRaises(ValueError):
                recovery.resolve(self.root, 'previous')

    def test_damaged_files_and_escape_are_rejected(self):
        for name in ('../previous', '', '/previous', 'previous;cmd'):
            with self.assertRaises(ValueError):
                recovery.resolve(self.root, name)
        for path in (self.raw, self.gz, self.directory/'sources.lock.json'):
            saved = path.read_bytes()
            path.write_bytes(b'damaged')
            with self.assertRaises(ValueError):
                recovery.resolve(self.root, 'previous')
            path.write_bytes(saved)

    def test_remote_selection_waits_for_verification_and_reuses_archive(self):
        sftp = MagicMock()
        sftp.stat.return_value = SimpleNamespace(st_size=10)
        selected = recovery.resolve(self.root, 'previous')
        with patch.object(remote, 'upload') as upload, patch.object(remote, 'run') as run:
            run.side_effect = RuntimeError('bad compressed or decompressed hash')
            with self.assertRaises(RuntimeError):
                remote.stage_recovery(None, sftp, '/private', selected)
            sftp.posix_rename.assert_not_called()
            run.side_effect = None
            remote.stage_recovery(None, sftp, '/private', selected)
            sftp.posix_rename.assert_called_once_with('/private/transfer-recovery.json', '/private/transfer.json')
            self.assertTrue(all(call.args[1] == selected[1] for call in upload.call_args_list))
            self.assertIn('--source-only', run.call_args.args[1])
            self.assertIn('--target /private/target.json', run.call_args.args[1])

    def test_missing_archive_does_not_silently_transfer_on_hotspot(self):
        sftp = MagicMock()
        sftp.stat.side_effect = FileNotFoundError()
        with patch.object(remote, 'upload') as upload:
            with self.assertRaises(ValueError):
                remote.stage_recovery(None, sftp, '/private', recovery.resolve(self.root, 'previous'))
            upload.assert_not_called()
        sftp.posix_rename.assert_not_called()


if __name__ == '__main__':
    unittest.main()
