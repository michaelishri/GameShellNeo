"""Candidate integration must never silently change the production queue."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kernel_checks
from kernel_candidates import PROFILES, candidate_paths, include_candidates, patch_path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('candidate_test_inputs', ROOT / 'tools/kernel-inputs.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)


class CandidateQueues(unittest.TestCase):
    def test_default_queue_excludes_every_deferred_candidate(self):
        queue = list(production.patches())
        names = {name for name, _ in queue}
        for profile in PROFILES:
            paths = candidate_paths(ROOT, profile)
            self.assertTrue(all(path.is_file() for path in paths))
            self.assertFalse(names & {path.name for path in paths})
            candidate = include_candidates(ROOT, profile, queue)
            self.assertEqual(dict(candidate), dict(queue, **{path.name: path.read_bytes() for path in paths}))
            self.assertEqual(list(production.patches()), queue)

    def test_promoted_duplicate_unknown_or_missing_inputs_reject(self):
        profile = 'power-supply-lifetime'
        name = Path(PROFILES[profile][0]).name
        for queue in ([(name, b'promoted')], [('prior.patch', b'a'), ('prior.patch', b'b')]):
            with self.assertRaises(ValueError):
                include_candidates(ROOT, profile, queue)
        with self.assertRaises(ValueError):
            include_candidates(ROOT, 'unknown', [])
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(FileNotFoundError):
            include_candidates(Path(temporary), profile, [])
        for name in ('../fix.patch', '/fix.patch', 'fix'):
            with self.assertRaises(ValueError):
                patch_path(ROOT, name)

    def test_object_build_replays_the_explicit_queue_and_records_all_hashes(self):
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source = work / 'source'
            for profile in (*PROFILES, None):
                with self.subTest(profile=profile), \
                        patch.object(kernel_checks, 'ensure_source', return_value=(source, [], {})) as ensure, \
                        patch.object(kernel_checks, 'attach_source'), \
                        patch.object(kernel_checks, 'build_objects', return_value={'ok': True}):
                    result = kernel_checks.compile_objects(work / 'archive', lock, work,
                        ['drivers/usb/musb/musb_core.o'], candidate_profile=profile)
                    self.assertEqual(result, {'ok': True})
                    manifest = ensure.call_args.args[4]
                    recorded = ensure.call_args.kwargs['recorded_patches']
                    expected = list(production.patches())
                    if profile:
                        expected = include_candidates(ROOT, profile, expected)
                        self.assertEqual(recorded, expected)
                    else:
                        self.assertIsNone(recorded)
                    self.assertEqual(manifest, [dict(name=name, sha256=hashlib.sha256(data).hexdigest())
                                                for name, data in expected])


if __name__ == '__main__':
    unittest.main()
