import copy
import hashlib
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel_candidates import PROFILES, include_candidates
from omap_musb_mailbox_kunit import CASES, checked_cases
from omap_musb_mailbox_source import CORE, FILES, prepare, selected_diffs

ROOT = Path(__file__).resolve().parents[2]


class SourceAdmission(unittest.TestCase):
    def test_mixed_patch_headers_keep_all_real_targets(self):
        def chunk(name):
            return '--- a/' + name + '\n+++ b/' + name + '\n@@ -1 +1 @@\n-old\n+new\n'
        patch = 'diff --git a/' + CORE + ' b/' + CORE + '\n' + chunk(CORE)
        patch += chunk('other.c') + chunk(FILES[1])
        self.assertEqual(len(selected_diffs(patch)), 2)
        self.assertTrue(all('other.c' not in part for part in selected_diffs(patch)))

    def test_existing_plain_0042_is_not_silently_skipped(self):
        path = ROOT / 'kernel/candidates/musb-retirement/0042-musb-resume-work-retirement.patch'
        chunks = selected_diffs(path.read_text())
        self.assertEqual(len(chunks), 2)
        self.assertEqual({name for name in FILES if any('+++ b/' + name in part for part in chunks)},
                         {CORE, FILES[1]})

    def test_profile_is_explicit_without_wake_bridge_dependency(self):
        self.assertEqual(PROFILES['musb-omap-mailbox'], PROFILES['musb-retirement'] + (
            'musb-wake-startup/0029-musb-startup-runtime-pm.patch',
            'musb-omap-mailbox/0063-musb-omap-mailbox-lifetime.patch'))
        self.assertFalse(any('0026' in p or '0062' in p for p in PROFILES['musb-omap-mailbox']))
        queue = include_candidates(ROOT, 'musb-omap-mailbox', [])
        self.assertEqual(len(queue), len({name for name, _ in queue}))

    def test_preserved_candidate_identities(self):
        pins = {
            'musb-wake-startup/0026-musb-wake-irq-policy.patch': 'fc8c8d43c63d9f31b1d1e821d3492736841ca80be14b0e3d1a3282117b804e84',
            'musb-wake-startup/0029-musb-startup-runtime-pm.patch': '6c2193b516144840cc0d367161dd1a454eeb92c0472fee7ef26d576ddcb7a54b',
            'musb-retirement/0039-musb-core-irq-retirement.patch': '04450b969fd436452ff2aba6bb7bd7d62a04d7830071e71e6d36aa2fb2ff75dd',
            'musb-retirement/0060-sun4i-phy-detector-generation.patch': 'd1cc429523bed0c952955be24f4f28c657875f876276fe209ed452d79652804a',
            'musb-retirement/0061-mpfs-parent-resource-lifetime.patch': 'e610a1cf8dc84d448590f90dfa5a38fa6d6d5bfac2a39846a2d3612f1e3b71e4',
        }
        for relative, expected in pins.items():
            with self.subTest(path=relative):
                self.assertEqual(hashlib.sha256((ROOT / 'kernel/candidates' / relative).read_bytes()).hexdigest(), expected)

    def test_archive_only_extracts_bounded_regular_expected_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive = directory / 'source.tar.xz'
            with tarfile.open(archive, 'w:xz') as stream:
                for name in (*FILES, '../outside'):
                    payload = b'fixture\n'
                    entry = tarfile.TarInfo('linux-6.18.54/' + name)
                    entry.size = len(payload)
                    stream.addfile(entry, io.BytesIO(payload))
            with mock.patch('omap_musb_mailbox_source.queue_for', return_value=[]):
                paths, _ = prepare(ROOT, archive, {'linux': {'tag': 'v6.18.54'}}, directory / 'out')
            self.assertEqual(set(paths), set(FILES))
            self.assertFalse((directory / 'outside').exists())

    def test_symlinked_source_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive = directory / 'source.tar.xz'
            with tarfile.open(archive, 'w:xz') as stream:
                entry = tarfile.TarInfo('linux-6.18.54/' + CORE)
                entry.type = tarfile.SYMTYPE
                entry.linkname = '/etc/passwd'
                stream.addfile(entry)
            with self.assertRaisesRegex(ValueError, 'Unexpected pinned'):
                prepare(ROOT, archive, {'linux': {'tag': 'v6.18.54'}}, directory / 'out')


class KernelEvidence(unittest.TestCase):
    def setUp(self):
        counts = dict(tests=12, passed=12, failed=0, crashed=0, skipped=0, errors=0)
        suite = dict(name='omap-musb-mailbox', arch='um', misc=counts,
                     test_cases=[dict(name=name, status='PASS') for name in CASES], sub_groups=[])
        self.report = dict(name='KUnit Test Group', arch='um', misc=counts,
                           test_cases=[], sub_groups=[suite])
        self.log = 'omap-musb-mailbox\n' + '\n'.join(CASES)

    def test_exact_twelve_cases_include_real_parent_pm_gate(self):
        self.assertEqual(len(checked_cases(self.report, self.log)), 12)
        self.assertTrue({'held_parent_suspend_test', 'held_parent_resume_test',
                         'closed_parent_pm_test', 'rebound_parent_pm_test'} <= set(CASES))

    def test_missing_duplicate_or_wrong_suite_is_rejected(self):
        for mutation in ('missing', 'duplicate', 'suite'):
            report = copy.deepcopy(self.report)
            suite = report['sub_groups'][0]
            if mutation == 'suite':
                suite['name'] = 'musb-restart'
            elif mutation == 'missing':
                suite['test_cases'].pop()
            else:
                suite['test_cases'][-1] = suite['test_cases'][0]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                checked_cases(report, self.log)

    def test_failure_skip_missing_log_and_diagnostic_are_rejected(self):
        for status in ('FAIL', 'SKIP'):
            report = copy.deepcopy(self.report)
            report['sub_groups'][0]['test_cases'][0]['status'] = status
            with self.subTest(status=status), self.assertRaises(ValueError):
                checked_cases(report, self.log)
        for log in ('omap-musb-mailbox', self.log + '\nWARNING: suspicious RCU'):
            with self.subTest(log=log), self.assertRaises(ValueError):
                checked_cases(self.report, log)


if __name__ == '__main__':
    unittest.main()
