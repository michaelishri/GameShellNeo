"""Admission/source-boundary regressions; driver semantics run in the C suite."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import brcmfmac_eapol_checks as checks


class EapolBoundaryTests(unittest.TestCase):
    def test_actual_deadline_whitespace_and_numeric_value(self):
        for whitespace in (' ', '\t\t\t'):
            value = '#define MAX_WAIT_FOR_8021X_TX' + whitespace + 'msecs_to_jiffies(950)'
            self.assertEqual(checks.deadline(value + '\n'), value)
        for value in ('9500', '951', '950 + 0'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'deadline'):
                checks.deadline('#define MAX_WAIT_FOR_8021X_TX\tmsecs_to_jiffies(' + value + ')')

    def test_arm_receipt_cannot_accept_native_elf(self):
        checks.check_arm_elf('  Class: ELF32\n  Machine: ARM\n')
        for text in ('  Class: ELF64\n  Machine: ARM\n',
                     '  Class: ELF32\n  Machine: Intel 80386\n',
                     '  Class: ELF320\n  Machine: ARM\n'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'ARM32'):
                checks.check_arm_elf(text)

    def test_patch_selection_keeps_complete_overlapping_driver_patches(self):
        one = b'+++ b/' + checks.SOURCE_FILES[0].encode() + b'\n'
        other = b'+++ b/kernel/time/timekeeping.c\n'
        self.assertEqual(checks.selected_queue([('one', one), ('unrelated', other)]), [('one', one)])

    def test_patch_selection_refuses_silent_partial_patch(self):
        data = ('+++ b/' + checks.SOURCE_FILES[0] + '\n+++ b/other.c\n').encode()
        with self.assertRaisesRegex(ValueError, 'unprojected'):
            checks.selected_queue([('mixed', data)])

    def test_missing_selected_queue_is_not_pristine_source_success(self):
        with self.assertRaisesRegex(ValueError, 'No production'):
            checks.selected_queue([])

    def test_extraction_keeps_function_body(self):
        source = 'int irrelevant;\nstatic int function(void)\n{\n\tif (1) {\n\t\treturn 2;\n\t}\n\treturn 0;\n}\n'
        self.assertEqual(checks.extract(source, 'static int function('), source.split('\n', 1)[1])

    def test_ambiguous_actual_declaration_rejected(self):
        source = 'int function(void)\n{\n}\n' * 2
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            checks.extract(source, 'int function(')

    def test_missing_actual_declaration_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            checks.extract('int other(void)\n{\n}\n', 'int function(')

    def test_control_requires_unique_source_target(self):
        old = checks.CONTROLS['reset_count'][0]
        for source in ('unrelated', old + old):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'not unique'):
                checks.mutate(source, 'reset_count')

    def test_locked_archive_rejection_happens_before_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'build').mkdir()
            (root / 'build/sources.lock.json').write_text('{"linux":{"tarball_sha256":"wrong"}}')
            archive = root / 'wrong.tar.xz'
            archive.write_bytes(b'not a kernel')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                checks.prepare(root, archive, root)
            self.assertFalse((root / 'upstream').exists())

    def run_oracle(self, output, raw=0, stderr='', *, failure=False, assertion=None):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            def execute(argv, directory, name, **kwargs):
                # Model a NEW terminal subprocess observation, including all
                # output files; never consult historical fixture artifacts.
                (directory / (name + '.stdout')).write_text(output)
                (directory / (name + '.stderr')).write_text(stderr)
                return {'returncode': raw}
            with mock.patch.object(checks, 'command', side_effect=execute), contextlib.redirect_stdout(io.StringIO()):
                return checks.observe_cases(destination / 'binary', destination,
                                            only=('timeout_single',),
                                            failures={'timeout_single'} if failure else set(),
                                            assertion=assertion)

    def test_positive_requires_current_success_and_raw_zero(self):
        self.run_oracle('OBSERVE timeout_single result=0\nPASS timeout_single\n')
        with self.assertRaises(RuntimeError):
            self.run_oracle('PASS timeout_single\n', raw=1)

    def test_negative_requires_original_raw_one(self):
        output = 'FAIL timeout_single timeout_errno expected=-110 actual=1\n'
        self.run_oracle(output, raw=1, failure=True, assertion=('timeout_errno', -110, 1))
        for raw in (0, 2, -11):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                self.run_oracle(output, raw=raw, failure=True, assertion=('timeout_errno', -110, 1))

    def test_negative_rejects_different_assertion_or_case(self):
        for output in ('FAIL timeout_single other expected=-110 actual=1\n',
                       'FAIL timeout_multiple timeout_errno expected=-110 actual=1\n'):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                self.run_oracle(output, raw=1, failure=True, assertion=('timeout_errno', -110, 1))

    def test_negative_rejects_numeric_prefix_and_different_observation(self):
        for actual in ('10', '-1', '2'):
            with self.subTest(actual=actual), self.assertRaises(RuntimeError):
                self.run_oracle('FAIL timeout_single timeout_errno expected=-110 actual=' + actual + '\n',
                                raw=1, failure=True, assertion=('timeout_errno', -110, 1))

    def test_duplicate_result_rejected(self):
        with self.assertRaises(RuntimeError):
            self.run_oracle('PASS timeout_single\nPASS timeout_single\n')

    def test_sanitizer_or_other_stderr_rejects_expected_failure(self):
        with self.assertRaises(RuntimeError):
            self.run_oracle('FAIL timeout_single timeout_errno expected=-110 actual=1\n',
                            raw=1, stderr='runtime error: broken\n', failure=True,
                            assertion=('timeout_errno', -110, 1))


if __name__ == '__main__':
    unittest.main()
