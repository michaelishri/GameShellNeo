"""Retention must preserve recovery and refuse unsafe or active build state."""
import contextlib
import fcntl
import gzip
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('prune_retained', Path(__file__).resolve().parents[1]/'prune-retained.py')
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)


class RetentionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for path in ('build', 'artifacts', 'flash', 'previous-kernels'):
            (self.root/'.local'/path).mkdir(parents=True)
        (self.root/'.local/build/workflow.lock').touch()
        self.images, self.snapshots = [], []
        for version in range(1, 5):
            data = ('image ' + str(version)).encode()
            checksum = retention.digest(self.write('.local/temporary', data))
            name = f'GameShellNeo-0.1.0-diagnostic.{version}-cpi31-{checksum[:12]}.img'
            self.images.append(self.write('.local/artifacts/'+name, data))
            self.write('.local/flash/'+name+'.gz', gzip.compress(data))
            snapshot = self.root/'.local/previous-kernels'/f'20261001T00000{version}Z-1'
            for directory in ('kernel', 'linux-6.18.54', 'kernel-install'):
                (snapshot/directory).mkdir(parents=True)
            (snapshot/'artifact-metadata.tar').write_bytes(b'metadata')
            (snapshot/'kernel/.config').write_bytes(b'config')
            (snapshot/'kernel-completed.json').write_bytes(b'{}')
            self.snapshots.append(snapshot)
        self.current(self.images[-1])
        self.write('.local/artifacts/SHA256SUMS', ''.join(
            retention.digest(p) + '  ' + p.name + '\n' for p in self.images).encode())

    def write(self, name, data):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def current(self, path):
        self.write('.local/artifacts/verification.json', json.dumps(
            dict(offline_verification='passed', image=path.name)).encode())

    def prune(self, apply=False, keep=3):
        with contextlib.redirect_stdout(io.StringIO()):
            return retention.prune(self.root, keep, apply)

    def test_preview_and_apply_keep_three_and_compressed_history(self):
        expected = [str(self.images[0].relative_to(self.root)), str(self.snapshots[0].relative_to(self.root))]
        preview = self.prune()
        self.assertEqual(preview['images'] + preview['snapshots'], expected)
        self.assertTrue(self.images[0].exists())
        result = self.prune(True)
        self.assertEqual(result['removed'], expected)
        self.assertTrue(result['completed'])
        for path in self.images[1:] + self.snapshots[1:]:
            self.assertTrue(path.exists())
        for path in self.images:
            self.assertTrue((self.root/'.local/flash'/(path.name+'.gz')).is_file())
        saved = self.root/'.local/retention/kernel-metadata'/self.snapshots[0].name
        self.assertEqual((saved/'kernel.config').read_bytes(), b'config')
        self.assertEqual((saved/'artifact-metadata.tar').read_bytes(), b'metadata')
        catalog = (self.root/'.local/artifacts/SHA256SUMS').read_text()
        self.assertNotIn(self.images[0].name, catalog)
        self.assertTrue(all(p.name in catalog for p in self.images[1:]))
        self.assertEqual(self.prune(True)['removed'], [])

    def test_current_image_protected_even_if_older_than_retention_window(self):
        self.current(self.images[0])
        self.assertEqual(self.prune()['images'], [])

    def test_build_lock_refuses_even_preview(self):
        with (self.root/'.local/build/workflow.lock').open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.prune(True)
        self.assertTrue(self.images[0].exists())

    def test_mismatched_gzip_prevents_all_deletion(self):
        (self.root/'.local/flash'/(self.images[0].name+'.gz')).write_bytes(gzip.compress(b'wrong'))
        with self.assertRaises(ValueError):
            self.prune(True)
        self.assertTrue(all(p.exists() for p in self.images + self.snapshots))

    def test_checkpoint_failure_prevents_all_deletion(self):
        (self.root/'.local/recovery/named').mkdir(parents=True)
        with patch.object(retention, 'resolve', side_effect=ValueError('bad checkpoint')) as check:
            with self.assertRaises(ValueError):
                self.prune(True)
            check.assert_called_once_with(self.root, 'named')
        self.assertTrue(all(p.exists() for p in self.images + self.snapshots))

    def test_metadata_conflict_prevents_all_deletion(self):
        self.write('.local/retention/kernel-metadata/'+self.snapshots[0].name+'/artifact-metadata.tar', b'other')
        with self.assertRaises(ValueError):
            self.prune(True)
        self.assertTrue(all(p.exists() for p in self.images + self.snapshots))

    def test_unexpected_snapshot_data_and_symlinks_refused(self):
        extra = self.snapshots[0]/'keep-me'
        extra.touch()
        with self.assertRaises(ValueError):
            self.prune(True)
        extra.unlink()
        archive = self.snapshots[0]/'artifact-metadata.tar'
        archive.unlink()
        archive.symlink_to(self.snapshots[1]/archive.name)
        with self.assertRaises(ValueError):
            self.prune(True)
        self.assertTrue(self.images[0].exists())

    def test_image_symlink_or_unrecognized_image_refused(self):
        path = self.root/'.local/artifacts/unknown.img'
        path.touch()
        with self.assertRaises(ValueError):
            self.prune(True)
        path.unlink()
        first = self.images[0]
        first.unlink()
        first.symlink_to(self.images[1])
        with self.assertRaises(ValueError):
            self.prune(True)

    def test_missing_archive_and_invalid_keep_refused(self):
        for keep in (0, 1, -1, True):
            with self.assertRaises(ValueError):
                self.prune(True, keep)
        (self.root/'.local/flash'/(self.images[0].name+'.gz')).unlink()
        with self.assertRaises(ValueError):
            self.prune(True)
        self.assertTrue(self.images[0].exists())


if __name__ == '__main__':
    unittest.main()
