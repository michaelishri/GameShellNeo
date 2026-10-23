"""Joined qualification must preserve source selection and complete outcomes."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import musb_combined_lifecycle_source as source

spec = importlib.util.spec_from_file_location('combined_checker', TOOLS / 'check-musb-combined-lifecycle.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class JoinedSourceTests(unittest.TestCase):
    def test_exact_existing_queue(self):
        selected, metadata = source.queue(TOOLS.parent)
        self.assertEqual(len(selected), 45)
        self.assertEqual(source.digest(metadata), source.SPEC_SHA256)
        self.assertNotIn('0026-musb-wake-irq-policy.patch', [name for name, _ in selected])
        self.assertEqual(selected[-1][0], '0062-musb-terminal-wake-handoff.patch')

    def test_changed_queue_is_rejected(self):
        selected, _ = source.queue(TOOLS.parent)
        with patch.object(source, 'queue_for', return_value=selected[:-1]):
            with self.assertRaisesRegex(ValueError, 'exact terminal45'):
                source.queue(TOOLS.parent)

    def test_complete_irqreturn_body(self):
        text = 'static irqreturn_t handler(int irq)\n{\n\tif (irq) {\n\t\treturn 1;\n\t}\n\treturn 0;\n}\n'
        self.assertEqual(source.function(text, 'handler'), text)
        with self.assertRaisesRegex(ValueError, 'Missing'):
            source.function(text, 'absent')


class JoinedOutcomeTests(unittest.TestCase):
    def positive(self):
        return ''.join('CASE ' + name + ' PASS\n' for name in source.CASES) + \
            'MUSB combined lifecycle: 14 actual-source families passed\n'

    def result(self, text, code=0, stderr=''):
        return subprocess.CompletedProcess([], code, text, stderr)

    def test_complete_positive(self):
        self.assertEqual(len(checker.checked_native(self.result(self.positive()))['cases']), 14)

    def test_positive_requires_whole_ordered_stream(self):
        valid = self.positive()
        for changed in (valid.replace(source.CASES[0], source.CASES[1], 1),
                        valid.replace('CASE ' + source.CASES[0] + ' PASS\n', ''),
                        valid + 'extra diagnostic\n', '\n' + valid):
            with self.subTest(changed=changed[:60]):
                with self.assertRaises(ValueError):
                    checker.checked_native(self.result(changed))

    def test_positive_rejects_nonzero_and_stderr(self):
        for result in (self.result(self.positive(), 1), self.result(self.positive(), stderr='warning\n')):
            with self.assertRaises(ValueError):
                checker.checked_native(result)

    def test_exact_control_observations(self):
        for control, (name, fields) in source.CONTROLS.items():
            valid = ''.join('FAIL ' + name + ' ' + field + '\n' for field in fields)
            valid += 'CASE ' + name + ' FAIL\nCONTROL ' + control + f' {len(fields)} observations\n'
            checker.checked_native(self.result(valid, 1), control=control)
            for text, code in ((valid, 0), (valid + 'extra\n', 1), (valid.replace(fields[0], 'other'), 1)):
                with self.subTest(control=control, code=code, text=text):
                    with self.assertRaises(ValueError):
                        checker.checked_native(self.result(text, code), control=control)


if __name__ == '__main__':
    unittest.main()
