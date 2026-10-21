"""Protect evidence and non-scratch data during explicit compiler cleanup."""
import fcntl
import importlib.util
import json
import shutil
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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

    def usb_fixture(self):
        work = self.work.with_name('usb-policy-tests')
        self.work.rename(work)
        self.work = work
        self.suite = work.name
        self.trees = [work / p.name for p in self.trees]
        obj = self.trees[0] / 'output/drivers/power/supply/axp20x_usb_power.o'
        obj.parent.mkdir(parents=True)
        obj.write_bytes(b'qualified object')
        record = dict(scratch=str(self.trees[0].relative_to(self.root)),
                      config_sha256=prune.sha256(self.trees[0] / 'output/.config'),
                      objects={'drivers/power/supply/axp20x_usb_power.o': prune.sha256(obj)})
        self.evidence = {'arm_build': record}
        self.save_evidence()
        (work / 'evidence.json').write_text('{}')
        return record, obj

    def test_usb_policy_preserves_qualified_output_and_removes_two_superseded_trees(self):
        record, obj = self.usb_fixture()
        result = prune.prune(self.root, self.suite, apply=True)
        self.assertEqual(len(result['removed']), 2)
        self.assertTrue(self.trees[0].exists())
        self.assertEqual(prune.sha256(obj), record['objects']['drivers/power/supply/axp20x_usb_power.o'])
        self.assertFalse(any(p.exists() for p in self.trees[1:]))

    def test_usb_policy_extra_evidence_reference_is_retained(self):
        record, obj = self.usb_fixture()
        extra = self.trees[1] / 'output/drivers/power/supply/axp20x_usb_power.o'
        extra.parent.mkdir(parents=True)
        extra.write_bytes(obj.read_bytes())
        other = dict(record, scratch=str(self.trees[1].relative_to(self.root)))
        (self.work / 'board-evidence.json').write_text(json.dumps({'nested': [other]}))
        result = prune.prune(self.root, self.suite, apply=True)
        self.assertEqual(result['removed'], [str(self.trees[2].relative_to(self.root))])
        self.assertTrue(self.trees[1].exists())

    def test_usb_policy_output_mismatch_stops_before_any_deletion(self):
        _record, obj = self.usb_fixture()
        obj.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'differs from evidence'):
            prune.prune(self.root, self.suite, apply=True)
        self.assertTrue(all(p.exists() for p in self.trees))

    def test_usb_policy_object_paths_cannot_override_config_or_escape(self):
        record, _obj = self.usb_fixture()
        for name in ('.config', 'drivers/../../.config', '/etc/passwd'):
            with self.subTest(name=name):
                record['objects'] = {name: record['config_sha256']}
                self.save_evidence()
                with self.assertRaisesRegex(ValueError, 'object path'):
                    prune.prune(self.root, self.suite, apply=True)
                self.assertTrue(all(p.exists() for p in self.trees))

    def test_usb_policy_evidence_symlink_stops_before_any_deletion(self):
        self.usb_fixture()
        (self.work / 'board-evidence.json').symlink_to(self.work / 'compile-evidence.json')
        with self.assertRaisesRegex(ValueError, 'regular evidence'):
            prune.prune(self.root, self.suite, apply=True)
        self.assertTrue(all(p.exists() for p in self.trees))


if __name__ == '__main__':
    unittest.main()
