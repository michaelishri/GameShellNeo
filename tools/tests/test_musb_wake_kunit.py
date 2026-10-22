"""Reject the wrong wake profile and incomplete real-kernel evidence."""
import copy
import importlib.util
from pathlib import Path
import sys
import subprocess
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from kernel_candidates import include_candidates
from musb_wake_kunit import CASES, CONTROL_FAILURES, PATCHES, checked_cases, checked_control, selected_patches

ROOT = TOOLS.parent
spec = importlib.util.spec_from_file_location('wake_test_inputs', TOOLS / 'kernel-inputs.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)


class WakeInputs(unittest.TestCase):
    def test_exact_separate_wake_profile(self):
        base = list(production.patches())
        queue = include_candidates(ROOT, 'musb-wake-startup', base)
        self.assertEqual(tuple(name for name, _ in selected_patches(queue)), PATCHES)
        self.assertEqual(list(production.patches()), base)
        with self.assertRaises(ValueError):
            selected_patches(base)
        with self.assertRaises(ValueError):
            selected_patches(include_candidates(ROOT, 'musb-retirement', base))

    def test_missing_duplicate_reordered_or_composed_profile_rejects(self):
        queue = include_candidates(ROOT, 'musb-wake-startup', list(production.patches()))
        selected = selected_patches(queue)
        bad_inputs = [selected[:-1], selected + [selected[-1]], list(reversed(selected)),
                      selected + [('0039-musb-core-irq-retirement.patch', b'foreign')]]
        for candidate in bad_inputs:
            with self.subTest(names=[name for name, _ in candidate]), self.assertRaises(ValueError):
                selected_patches(candidate)

    def test_control_is_rejected_before_preparation_for_other_suites(self):
        result = subprocess.run([sys.executable, str(TOOLS / 'check-musb-restart-kunit.py'),
                                 '--suite', 'irq', '--wake-control', 'policy-ignored'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--wake-control requires --suite wake', result.stderr)
        self.assertEqual(result.stdout, '')


class WakeEvidence(unittest.TestCase):
    def setUp(self):
        counts = dict(tests=len(CASES), passed=len(CASES), failed=0, crashed=0, skipped=0, errors=0)
        self.report = dict(name='KUnit Test Group', arch='um', misc=counts, test_cases=[],
            sub_groups=[dict(name='musb-wake', arch='um', misc=counts, sub_groups=[],
                             test_cases=[dict(name=name, status='PASS') for name in CASES])])
        self.log = 'musb-wake\n' + '\n'.join(CASES)

    def test_complete_requested_suite(self):
        self.assertEqual(len(checked_cases(self.report, self.log)), len(CASES))

    def test_incomplete_or_different_kernel_results_reject(self):
        for mode in ('missing', 'duplicate', 'FAIL', 'SKIP', 'other-suite', 'extra-suite', 'wrong-arch'):
            report = copy.deepcopy(self.report)
            suite = report['sub_groups'][0]
            cases = suite['test_cases']
            if mode == 'missing':
                cases.pop()
            elif mode == 'duplicate':
                cases[-1] = cases[0]
            elif mode == 'other-suite':
                suite['name'] = 'musb-irq'
            elif mode == 'extra-suite':
                report['sub_groups'].append(copy.deepcopy(suite))
            elif mode == 'wrong-arch':
                report['arch'] = suite['arch'] = 'arm'
            else:
                cases[0]['status'] = mode
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                checked_cases(report, self.log)

    def test_diagnostics_or_missing_log_reject(self):
        for diagnostic in ('WARNING:', 'BUG:', 'not ok ', 'sleeping function called',
                           'possible circular locking', 'Kernel panic'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                checked_cases(self.report, self.log + diagnostic)
        with self.assertRaises(ValueError):
            checked_cases(self.report, 'musb-wake')


class WakeControl(unittest.TestCase):
    def setUp(self):
        counts = dict(tests=len(CASES), passed=len(CASES) - len(CONTROL_FAILURES),
                      failed=len(CONTROL_FAILURES), crashed=0, skipped=0, errors=0)
        self.report = dict(name='KUnit Test Group', arch='um', misc=counts, test_cases=[],
            sub_groups=[dict(name='musb-wake', arch='um', misc=counts, sub_groups=[], test_cases=[
                dict(name=name, status='FAIL' if name in CONTROL_FAILURES else 'PASS') for name in CASES])])
        self.log = 'musb-wake\n' + '\n'.join(CASES) + '\nbefore.armed\nafter.references'

    def test_executed_expected_control_is_distinct_from_success(self):
        self.assertEqual(len(checked_control(self.report, self.log)), len(CASES))
        with self.assertRaises(ValueError):
            checked_cases(self.report, self.log)
        positive = WakeEvidence()
        positive.setUp()
        with self.assertRaises(ValueError):
            checked_control(positive.report, positive.log)

    def test_control_rejects_missing_or_unexpected_failures(self):
        for mode in ('missing', 'duplicate', 'unexpected-pass', 'unexpected-failure', 'crash'):
            report = copy.deepcopy(self.report)
            suite = report['sub_groups'][0]
            cases = suite['test_cases']
            if mode == 'missing':
                cases.pop()
            elif mode == 'duplicate':
                cases[-1] = cases[0]
            elif mode == 'unexpected-pass':
                next(case for case in cases if case['name'] in CONTROL_FAILURES)['status'] = 'PASS'
            elif mode == 'unexpected-failure':
                cases[0]['status'] = 'FAIL'
            else:
                suite['misc']['crashed'] = 1
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                checked_control(report, self.log)

    def test_control_requires_actual_irq_assertions_without_kernel_faults(self):
        for text in (self.log.replace('before.armed', ''), self.log.replace('after.references', ''),
                     self.log + 'WARNING:', self.log + 'BUG:', self.log + 'Kernel panic'):
            with self.subTest(log=text[-50:]), self.assertRaises(ValueError):
                checked_control(self.report, text)


if __name__ == '__main__':
    unittest.main()
