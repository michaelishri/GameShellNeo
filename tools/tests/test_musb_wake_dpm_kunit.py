"""Guard the source boundary and reject inconclusive actual DPM executions."""
import importlib.util
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from kernel_candidates import include_candidates
from musb_wake_dpm_kunit import (CASES, CONTROL_ASSERTIONS, CONTROL_CASE, PATCHES,
                                 checked_cases, checked_control, selected_patches)

spec = importlib.util.spec_from_file_location('dpm_test_inputs', TOOLS / 'kernel-inputs.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)


def report(control=False):
    counts = dict(tests=len(CASES), passed=len(CASES) - int(control), failed=int(control),
                  crashed=0, skipped=0, errors=0)
    return dict(name='KUnit Test Group', arch='um', misc=counts, test_cases=[], sub_groups=[
        dict(name='musb-wake-dpm', arch='um', misc=counts.copy(), sub_groups=[], test_cases=[
            dict(name=name, status='FAIL' if control and name == CONTROL_CASE else 'PASS')
            for name in CASES])])


def control_log():
    lines = ['musb-wake-dpm', *CASES]
    for expression, values in CONTROL_ASSERTIONS.items():
        lines.extend(('# ' + CONTROL_CASE + ': EXPECTATION FAILED',
                      'Expected ' + expression + ', but', *values))
    lines.append('not ok 2 ' + CONTROL_CASE)
    return '\n'.join(lines)


class ProfileBoundary(unittest.TestCase):
    def test_exact_profile_leaves_production_and_retirement_independent(self):
        base = list(production.patches())
        original = list(base)
        queue = include_candidates(ROOT, 'musb-wake-startup', base)
        self.assertEqual(tuple(name for name, _ in selected_patches(queue)), PATCHES)
        self.assertEqual(base, original)
        self.assertEqual(len(queue), len(base) + 2)

    def test_incomplete_duplicate_reordered_and_composed_profiles_rejected(self):
        queue = include_candidates(ROOT, 'musb-wake-startup', list(production.patches()))
        selected = selected_patches(queue)
        for wrong in (selected[:-1], selected + selected[-1:], list(reversed(selected)),
                      queue + [('0061-mpfs-parent-resource-lifetime.patch', b'')],
                      queue + [('0039-musb-core-irq-retirement.patch', b'')]):
            with self.subTest(names=[name for name, _ in wrong]), self.assertRaises(ValueError):
                selected_patches(wrong)


class EvidenceBoundary(unittest.TestCase):
    def test_complete_positive_and_control_are_distinct(self):
        log = 'musb-wake-dpm\n' + '\n'.join(CASES)
        self.assertEqual(len(checked_cases(report(), log)), len(CASES))
        self.assertEqual(len(checked_control(report(True), control_log())), len(CASES))
        with self.assertRaises(ValueError):
            checked_cases(report(True), control_log())
        with self.assertRaises(ValueError):
            checked_control(report(), log)

    def test_missing_duplicate_extra_or_crashed_case_is_inconclusive(self):
        for control, checker in ((False, checked_cases), (True, checked_control)):
            for mode in ('missing', 'duplicate', 'extra', 'crash', 'wrong-status'):
                record = report(control)
                cases = record['sub_groups'][0]['test_cases']
                if mode == 'missing':
                    cases.pop()
                elif mode == 'duplicate':
                    cases[-1] = cases[0]
                elif mode == 'extra':
                    cases.append(dict(name='unowned_test', status='PASS'))
                elif mode == 'crash':
                    record['misc']['crashed'] = 1
                else:
                    cases[0]['status'] = 'FAIL'
                with self.subTest(control=control, mode=mode), self.assertRaises(ValueError):
                    checker(record, control_log())

    def test_control_binds_exact_assertions_values_and_case(self):
        valid = control_log()
        wrong_logs = (valid.replace('f->calls.prepare == 0', 'f->calls.prepare == 1'),
                      valid.replace('walk->after_end.armed == 0', 'walk->after_end.armed == 1'),
                      valid.replace('# ' + CONTROL_CASE + ':', '# dpm_policy_disabled_test:', 1),
                      valid + '\n# ' + CONTROL_CASE + ': EXPECTATION FAILED\nExpected other == 1, but\nother == 0',
                      valid.replace('Expected f->calls.noirq == 1U, but', 'Expected other == 1U, but'))
        for log in wrong_logs:
            with self.subTest(tail=log[-100:]), self.assertRaises(ValueError):
                checked_control(report(True), log)

    def test_kernel_diagnostics_reject_both_paths(self):
        for diagnostic in ('WARNING:', 'BUG:', 'Kernel panic', 'possible circular locking',
                           'sleeping function called', 'INFO: task worker blocked for more than'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                checked_control(report(True), control_log() + '\n' + diagnostic)
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                checked_cases(report(), 'musb-wake-dpm\n' + '\n'.join(CASES) + '\n' + diagnostic)


if __name__ == '__main__':
    unittest.main()
