"""Protect evidence and non-scratch data during explicit compiler cleanup."""
import fcntl
import importlib.util
import json
import shutil
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'prune_driver', Path(__file__).resolve().parents[1] / 'prune-driver-scratch.py')
prune = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prune)


class PruneTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.suite = 'brcmfmac-pm-tests'
        self.work = self.root / '.local/build' / self.suite
        self.work.mkdir(parents=True)
        (self.work / '.lock').touch()
        self.trees = []
        for suffix in ('a', 'b', 'c'):
            path = self.work / ('kernel-' + suffix * 16)
            (path / 'source').mkdir(parents=True)
            (path / 'source/Makefile').write_text('source')
            (path / 'output').mkdir()
            (path / 'output/.config').write_text('configuration')
            self.trees.append(path)
        self.evidence = {key: {'scratch': str(path.relative_to(self.root))}
                         for key, path in zip(('arm_build', 'arm_debug_build'), self.trees[:2])}
        self.save_evidence()
        (self.work / 'evidence.json').write_text('retained test evidence')
        for name in ('recovery', 'artifacts', 'downloads', 'diagnostics', 'provisioning'):
            path = self.root / '.local' / name
            path.mkdir()
            (path / 'sentinel').write_text('preserve')

    def save_evidence(self):
        (self.work / 'compile-evidence.json').write_text(json.dumps(self.evidence))

    def test_preview_then_apply_preserves_current_builds_evidence_and_private_data(self):
        result = prune.prune(self.root, self.suite)
        self.assertEqual(result['candidates'], [str(self.trees[2].relative_to(self.root))])
        self.assertTrue(self.trees[2].exists())
        self.assertFalse(list(self.work.glob('prune-*.json')))
        result = prune.prune(self.root, self.suite, apply=True)
        self.assertEqual(result['removed'], result['candidates'])
        self.assertFalse(self.trees[2].exists())
        self.assertTrue(all(p.exists() for p in self.trees[:2]))
        self.assertEqual(json.loads((self.work / 'compile-evidence.json').read_text()), self.evidence)
        self.assertEqual((self.work / 'evidence.json').read_text(), 'retained test evidence')
        self.assertEqual(len(list((self.root / '.local').glob('*/sentinel'))), 5)
        self.assertEqual(json.loads(next(self.work.glob('prune-*.json')).read_text()), result)

    def test_active_suite_is_not_pruned(self):
        with (self.work / '.lock').open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                prune.prune(self.root, self.suite, apply=True)
        self.assertTrue(self.trees[2].exists())

    def test_pruning_shared_scratch_retains_cache(self):
        source = self.work / '.sources' / ('source-' + 'a' * 64) / 'source'
        source.mkdir(parents=True)
        (source / 'Makefile').write_text('shared source')
        shutil.rmtree(self.trees[2] / 'source')
        (self.trees[2] / 'source').symlink_to('../.sources/source-' + 'a' * 64 + '/source')
        result = prune.prune(self.root, self.suite, apply=True)
        self.assertEqual(len(result['removed']), 1)
        self.assertEqual((source / 'Makefile').read_text(), 'shared source')

    def test_missing_or_escaping_evidence_is_not_pruned(self):
        for value in ('../../recovery', '.local/build/other/kernel-' + 'a' * 16,
                      '.local/build/' + self.suite + '/kernel-' + 'd' * 16):
            with self.subTest(value=value):
                self.evidence['arm_build']['scratch'] = value
                self.save_evidence()
                with self.assertRaises(ValueError):
                    prune.prune(self.root, self.suite, apply=True)
                self.assertTrue(self.trees[2].exists())
        (self.work / 'compile-evidence.json').unlink()
        with self.assertRaises(FileNotFoundError):
            prune.prune(self.root, self.suite, apply=True)

    def test_unexpected_contents_rejected_before_any_removal(self):
        (self.trees[2] / 'keep-this').write_text('unknown')
        with self.assertRaises(ValueError):
            prune.prune(self.root, self.suite, apply=True)
        self.assertTrue(self.trees[2].exists())

    def test_symlink_candidates_cannot_escape(self):
        link = self.work / ('kernel-' + 'd' * 16)
        link.symlink_to(self.root / '.local/recovery', target_is_directory=True)
        with self.assertRaises(ValueError):
            prune.prune(self.root, self.suite, apply=True)
        self.assertTrue((self.root / '.local/recovery/sentinel').exists())
        self.assertTrue(self.trees[2].exists())

    def test_suite_symlink_is_rejected(self):
        other = self.work.with_name('brcmfmac-lifecycle-tests')
        other.symlink_to(self.work, target_is_directory=True)
        with self.assertRaises(ValueError):
            prune.prune(self.root, other.name, apply=True)

    def test_invalid_suite_is_rejected(self):
        with self.assertRaises(ValueError):
            prune.prune(self.root, '../../recovery', apply=True)


if __name__ == '__main__':
    unittest.main()
