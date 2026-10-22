import copy
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kernel_candidates import PROFILES, include_candidates
from musb_terminal_wake_kunit import CASES, checked_cases
from musb_terminal_wake_source import CORE, FILES, compare_semantics, selected_diffs

ROOT = Path(__file__).resolve().parents[2]


class SourceAdmission(unittest.TestCase):
    def test_plain_unified_patch_is_not_silently_omitted(self):
        patch = ('From: fixture\n---\n\n--- a/' + CORE + '\n+++ b/' + CORE +
                 '\n@@ -1 +1 @@\n-old\n+new\n')
        self.assertEqual(len(selected_diffs(patch)), 1)

    def test_git_and_plain_chunks_select_only_actual_targets(self):
        def chunk(name):
            return '--- a/' + name + '\n+++ b/' + name + '\n@@ -1 +1 @@\n-old\n+new\n'
        patch = 'diff --git a/' + CORE + ' b/' + CORE + '\n' + chunk(CORE)
        patch += 'diff --git a/other.c b/other.c\n' + chunk('other.c')
        patch += chunk('drivers/usb/musb/musb_core.h')
        chunks = selected_diffs(patch)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all('other.c' not in part for part in chunks))

    def test_existing_plain_0042_reaches_both_core_and_header(self):
        patch = (ROOT / 'kernel/candidates/musb-retirement/0042-musb-resume-work-retirement.patch').read_text()
        chunks = selected_diffs(patch)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(any('+++ b/' + name in chunk for name in FILES) for chunk in chunks))

    def test_bridge_preserves_qualified_policy_bodies(self):
        names = ('musb_disarm_wake', 'musb_init_wakeup', 'musb_cleanup_wakeup',
                 'musb_suspend', 'musb_resume')
        source = ''.join('static int ' + name + '(void)\n{\n\treturn 0;\n}\n' for name in names)
        self.assertEqual(set(compare_semantics(source, source)), set(names))
        changed = source.replace('return 0;', 'return 1;', 1)
        with self.assertRaisesRegex(ValueError, 'differs from 0026'):
            compare_semantics(changed, source)

    def test_combined_profile_is_explicit_and_does_not_duplicate_0026(self):
        combined = PROFILES['musb-terminal-wake']
        self.assertEqual(combined, PROFILES['musb-retirement'] + (
            'musb-wake-startup/0029-musb-startup-runtime-pm.patch',
            'musb-terminal-wake/0062-musb-terminal-wake-handoff.patch'))
        self.assertFalse(any('0026' in name for name in combined))
        self.assertEqual(PROFILES['musb-wake-startup'], (
            'musb-wake-startup/0026-musb-wake-irq-policy.patch',
            'musb-wake-startup/0029-musb-startup-runtime-pm.patch'))
        queue = include_candidates(ROOT, 'musb-terminal-wake', [])
        self.assertEqual(len(queue), len({name for name, _ in queue}))

    def test_original_qualified_candidate_hashes_are_preserved(self):
        pins = {
            'musb-wake-startup/0026-musb-wake-irq-policy.patch': 'fc8c8d43c63d9f31b1d1e821d3492736841ca80be14b0e3d1a3282117b804e84',
            'musb-wake-startup/0029-musb-startup-runtime-pm.patch': '6c2193b516144840cc0d367161dd1a454eeb92c0472fee7ef26d576ddcb7a54b',
            'musb-retirement/0039-musb-core-irq-retirement.patch': '04450b969fd436452ff2aba6bb7bd7d62a04d7830071e71e6d36aa2fb2ff75dd',
            'musb-retirement/0060-sun4i-phy-detector-generation.patch': 'd1cc429523bed0c952955be24f4f28c657875f876276fe209ed452d79652804a',
            'musb-retirement/0061-mpfs-parent-resource-lifetime.patch': 'e610a1cf8dc84d448590f90dfa5a38fa6d6d5bfac2a39846a2d3612f1e3b71e4',
        }
        for name, expected in pins.items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((ROOT / 'kernel/candidates' / name).read_bytes()).hexdigest(), expected)


class KernelEvidence(unittest.TestCase):
    def setUp(self):
        counts = dict(tests=len(CASES), passed=len(CASES), failed=0, crashed=0, skipped=0, errors=0)
        suite = dict(name='musb-terminal-wake', arch='um', misc=counts,
                     test_cases=[dict(name=name, status='PASS') for name in CASES], sub_groups=[])
        self.report = dict(name='KUnit Test Group', arch='um', misc=counts,
                           test_cases=[], sub_groups=[suite])
        self.log = 'musb-terminal-wake\n' + '\n'.join(CASES)

    def test_exact_eight_cases_are_required(self):
        self.assertEqual(len(checked_cases(self.report, self.log)), 8)

    def test_missing_and_duplicate_case_rejected(self):
        for changed in (self.report['sub_groups'][0]['test_cases'][:-1],
                        self.report['sub_groups'][0]['test_cases'][:-1] +
                        [self.report['sub_groups'][0]['test_cases'][0]]):
            with self.subTest(cases=changed):
                report = copy.deepcopy(self.report)
                report['sub_groups'][0]['test_cases'] = changed
                with self.assertRaises(ValueError):
                    checked_cases(report, self.log)

    def test_failure_skip_wrong_suite_and_kernel_diagnostic_rejected(self):
        for status in ('FAIL', 'SKIP'):
            report = copy.deepcopy(self.report)
            report['sub_groups'][0]['test_cases'][0]['status'] = status
            with self.assertRaises(ValueError):
                checked_cases(report, self.log)
        report = copy.deepcopy(self.report)
        report['sub_groups'][0]['name'] = 'musb-irq'
        with self.assertRaises(ValueError):
            checked_cases(report, self.log)
        for diagnostic in ('WARNING:', 'BUG:', 'sleeping function called', 'Kernel panic'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                checked_cases(self.report, self.log + diagnostic)


if __name__ == '__main__':
    unittest.main()
