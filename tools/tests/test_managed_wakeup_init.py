"""Guard actual-inline extraction and finite native result acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('managed_wakeup_source', ROOT / 'tools/managed_wakeup_init_source.py')
SOURCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE)


def report(control=False):
    rows = []
    for index, name in enumerate(SOURCE.CASES):
        failed_init = index in (1, 2)
        action = index != 3 and (not failed_init or control)
        rows.append(dict(name=name, failures=[dict(assertion=k, actual=a, expected=e)
            for k, a, e in (SOURCE.CONTROL_FAILURES.get(name, ()) if control else ())],
            observations=dict(result=(0 if action else (-17 if index == 2 else -12)),
                fault_hits=int(index in (1, 3)), source_allocations=(0 if index == 1 else (2 if index == 2 else 1)),
                source_frees_final=(0 if index == 1 else (2 if index == 2 else 1)),
                action_present=int(action), action_resets=int(index == 3),
                capable_after_release=int(failed_init and not control), device_releases=1, final_sources=0)))
    return dict(cases=rows)


def completed(data, *, code=0, stderr=''):
    return subprocess.CompletedProcess(['fixture'], code, json.dumps(data), stderr)


class ManagedWakeupSourceTests(unittest.TestCase):
    def test_function_requires_one_complete_definition(self):
        source = 'static inline int example(int value)\n{\n\tif (value) {\n\t\treturn value;\n\t}\n\treturn 0;\n}\n'
        self.assertEqual(SOURCE.function(source, 'example'), source)
        for bad in ('int example(int value);\n', source[:-3], source + source):
            with self.subTest(source=bad), self.assertRaises(ValueError):
                SOURCE.function(bad, 'example')

    def test_actual_success_and_precise_control_contract(self):
        self.assertEqual(len(SOURCE.checked_native('candidate', completed(report()))), 5)
        rows = SOURCE.checked_native('return-ignored', completed(report(True), code=1))
        self.assertEqual(sum(bool(r['failures']) for r in rows), 2)
        self.assertEqual(sum(len(r['failures']) for r in rows), 8)

    def test_control_refuses_raw_zero_and_unrelated_failures(self):
        bad = report(True)
        with self.assertRaises(ValueError):
            SOURCE.checked_native('return-ignored', completed(bad))
        bad['cases'][0]['failures'] = [dict(assertion='setup', actual=0, expected=1)]
        with self.assertRaises(ValueError):
            SOURCE.checked_native('return-ignored', completed(bad, code=1))

    def test_refuses_incomplete_reordered_or_duplicate_cases(self):
        good = report()
        for rows in (good['cases'][:-1], list(reversed(good['cases'])),
                     [good['cases'][0], *good['cases'][:-1]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                SOURCE.checked_native('candidate', completed(dict(cases=rows)))

    def test_refuses_crash_sanitizer_and_changed_raw_ownership(self):
        for code, stderr in ((-11, ''), (0, 'AddressSanitizer: error'), (1, '')):
            with self.subTest(code=code, stderr=stderr), self.assertRaises(ValueError):
                SOURCE.checked_native('candidate', completed(report(), code=code, stderr=stderr))
        for field, value in (('fault_hits', 0), ('device_releases', 2), ('final_sources', 1),
                             ('action_present', True)):
            bad = copy.deepcopy(report())
            bad['cases'][1]['observations'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                SOURCE.checked_native('candidate', completed(bad))


if __name__ == '__main__':
    unittest.main()
