"""Reject inconclusive frontend source observations and inert controls."""
import copy
from pathlib import Path
import subprocess
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from wakeup_sysfs_source import (ERROR_CASES, NATIVE_CASES, NATIVE_FAILURES,
                                 checked_native, frontend, variants)


def output(name):
    lines = []
    for case in NATIVE_CASES:
        expected = {'enable': 8, 'disable': 9, 'enabled_idempotent': 8,
                    'disabled_idempotent': 9, 'invalid_request': -22,
                    'concurrent_enable': 8}.get(case, -12)
        failing = case in NATIVE_FAILURES[name]
        result = expected
        if failing:
            result = 8 if case in ERROR_CASES else (-12 if case == 'enabled_idempotent' else -17)
        policy = int(case in ('enable', 'enabled_idempotent', 'concurrent_enable'))
        calls = int(case != 'invalid_request')
        lines.append(f'{"FAIL" if failing else "PASS"} {case} result={result} '
                     f'expected={expected} policy={policy} calls={calls}')
    return subprocess.CompletedProcess(['fixture'], int(bool(NATIVE_FAILURES[name])),
                                       '\n'.join(lines) + '\n', '')


class NativeObservationAdmission(unittest.TestCase):
    def test_all_declared_control_outcomes_are_distinct_from_success(self):
        for name in NATIVE_FAILURES:
            with self.subTest(name=name):
                self.assertEqual(len(checked_native(name, output(name))), 10)
        with self.assertRaises(ValueError):
            checked_native('candidate', output('upstream'))

    def test_setup_crash_missing_duplicate_or_unrelated_failure_rejects(self):
        original = output('upstream')
        for mode in ('compiler', 'signal', 'stderr', 'missing', 'duplicate', 'wrong-result',
                     'wrong-policy', 'wrong-count', 'unexpected-pass', 'unrelated-failure'):
            result = copy.deepcopy(original)
            lines = result.stdout.splitlines()
            if mode == 'compiler':
                result.stdout = ''
            elif mode == 'signal':
                result.returncode = -11
            elif mode == 'stderr':
                result.stderr = 'runtime error: unexpected diagnostic\n'
            elif mode == 'missing':
                result.stdout = '\n'.join(lines[:-1])
            elif mode == 'duplicate':
                result.stdout = '\n'.join([*lines[:-1], lines[0]])
            elif mode == 'wrong-result':
                result.stdout = result.stdout.replace('object_alloc_error result=8',
                                                       'object_alloc_error result=-5')
            elif mode == 'wrong-policy':
                result.stdout = result.stdout.replace('expected=-12 policy=0',
                                                       'expected=-12 policy=1', 1)
            elif mode == 'wrong-count':
                result.stdout = result.stdout.replace('expected=-12 policy=0 calls=1',
                                                       'expected=-12 policy=0 calls=0', 1)
            elif mode == 'unexpected-pass':
                result.stdout = result.stdout.replace('FAIL object_alloc_error', 'PASS object_alloc_error')
            else:
                result.stdout = result.stdout.replace('PASS enable ', 'FAIL enable ')
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                checked_native('upstream', result)


class ActualFrontendBoundary(unittest.TestCase):
    def test_missing_or_changed_definition_rejects(self):
        for source in ('', 'static ssize_t wakeup_store(void);\n',
                       'static ssize_t wakeup_store(void)\n{\n}\n'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                frontend(source)

    def test_unchanged_source_cannot_be_a_candidate(self):
        source = ('static const char _enabled[] = "enabled";\n'
                  'static const char _disabled[] = "disabled";\n'
                  'static ssize_t wakeup_store(void)\n{\n\treturn 0;\n}\n')
        with self.assertRaisesRegex(ValueError, 'did not change'):
            variants(source, source)


if __name__ == '__main__':
    unittest.main()
