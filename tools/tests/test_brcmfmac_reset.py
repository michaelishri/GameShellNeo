"""Regress complete numeric admission on the actual native observation route."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import brcmfmac_reset_checks as checks


class ResetOutputAdmissionTests(unittest.TestCase):
    case = 'reset_unbound_f2_sync_refused'
    failure = ('reset_errno', -19, 0)

    def control_output(self):
        return checks.formatted_output(
            self.case, checks.baseline_metrics(self.case), self.failure).encode()

    def admit_control(self, stdout=None, stderr=b'', exit_code=1):
        return checks.admit_output(
            self.case, dict(exit_code=exit_code),
            self.control_output() if stdout is None else stdout, stderr,
            metrics=checks.baseline_metrics(self.case), failure=self.failure)

    def test_exact_negative_result_is_accepted(self):
        result = self.admit_control()
        self.assertEqual(result['raw_exit_code'], 1)

    def test_exact_success_is_accepted(self):
        case = 'reset_bound_async'
        checks.admit_output(case, dict(exit_code=0),
                            checks.formatted_output(case, checks.expected_metrics(case)).encode(), b'')

    def test_control_raw_zero_is_rejected(self):
        with self.assertRaises(ValueError):
            self.admit_control(exit_code=0)

    def test_control_other_raw_status_is_rejected(self):
        for code in (-6, -11, 2, 137, True, '1'):
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.admit_control(exit_code=code)

    def test_numeric_prefix_in_outcome_is_rejected(self):
        with self.assertRaises(ValueError):
            self.admit_control(self.control_output().replace(b'expected=-19 ', b'expected=-190 '))

    def test_numeric_prefix_in_observation_is_rejected(self):
        with self.assertRaises(ValueError):
            self.admit_control(self.control_output().replace(b' teardown=1 ', b' teardown=10 '))

    def test_wrong_errno_is_rejected(self):
        with self.assertRaises(ValueError):
            self.admit_control(self.control_output().replace(b'observed=0', b'observed=-5'))

    def test_extra_failure_is_rejected(self):
        with self.assertRaises(ValueError):
            self.admit_control(self.control_output() +
                               b'FAIL case=reset_pm_failed assertion=reset_errno expected=-112 observed=0\n')

    def test_extra_assertion_is_rejected(self):
        with self.assertRaises(ValueError):
            self.admit_control(self.control_output() +
                               b'FAIL case=reset_unbound_f2_sync_refused assertion=other expected=0 observed=1\n')

    def test_duplicate_observation_is_rejected(self):
        output = self.control_output()
        with self.assertRaises(ValueError):
            self.admit_control(output.splitlines(keepends=True)[0] + output)

    def test_missing_result_is_rejected(self):
        with self.assertRaises(ValueError):
            self.admit_control(self.control_output().splitlines(keepends=True)[0])

    def test_wrong_case_is_rejected(self):
        with self.assertRaises(ValueError):
            self.admit_control(self.control_output().replace(self.case.encode(), b'reset_bound_async'))

    def test_wrong_assertion_is_rejected(self):
        with self.assertRaises(ValueError):
            self.admit_control(self.control_output().replace(b'assertion=reset_errno', b'assertion=other'))

    def test_unexpected_stdout_diagnostic_is_rejected(self):
        with self.assertRaises(ValueError):
            self.admit_control(b'WARNING: diagnostic\n' + self.control_output())

    def test_stderr_is_rejected(self):
        with self.assertRaises(ValueError):
            self.admit_control(stderr=b'AddressSanitizer: diagnostic\n')

    def test_failing_case_is_not_a_success(self):
        with self.assertRaises(ValueError):
            checks.admit_output(self.case, dict(exit_code=0), self.control_output(), b'')

    def make_binary(self, directory, stdout, code):
        path = directory / 'fixture'
        path.write_text('#!' + sys.executable + '\nimport sys\n'
                        'sys.stdout.buffer.write(' + repr(stdout) + ')\n'
                        'sys.exit(' + str(code) + ')\n')
        path.chmod(0o755)
        return path

    def test_actual_observe_rejects_raw_zero_and_retains_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary = self.make_binary(directory, self.control_output(), 0)
            with self.assertRaises(ValueError):
                checks.observe(binary, self.case, directory,
                               metrics=checks.baseline_metrics(self.case), failure=self.failure)
            record = json.loads((directory / (self.case + '.json')).read_text())
            self.assertEqual(record['exit_code'], 0)
            self.assertEqual((directory / (self.case + '.stdout')).read_bytes(), self.control_output())

    def test_actual_observe_rejects_extra_failure_after_saving_raw_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            output = self.control_output() + b'FAIL case=other assertion=other expected=0 observed=1\n'
            binary = self.make_binary(directory, output, 1)
            with self.assertRaises(ValueError):
                checks.observe(binary, self.case, directory,
                               metrics=checks.baseline_metrics(self.case), failure=self.failure)
            self.assertEqual((directory / (self.case + '.stdout')).read_bytes(), output)

    def test_current_identical_negative_outputs_are_accepted_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = self.make_binary(root, self.control_output(), 1)
            for name in ('first', 'second'):
                directory = root / name
                directory.mkdir()
                checks.observe(binary, self.case, directory,
                               metrics=checks.baseline_metrics(self.case), failure=self.failure)
            self.assertEqual((root / 'first' / (self.case + '.stdout')).read_bytes(),
                             (root / 'second' / (self.case + '.stdout')).read_bytes())

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary = self.make_binary(directory, self.control_output(), 1)
            path = directory / (self.case + '.stdout')
            path.write_bytes(b'original')
            with self.assertRaises(FileExistsError):
                checks.observe(binary, self.case, directory,
                               metrics=checks.baseline_metrics(self.case), failure=self.failure)
            self.assertEqual(path.read_bytes(), b'original')

    def test_saved_output_hash_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            binary = self.make_binary(directory, self.control_output(), 1)
            checks.observe(binary, self.case, directory,
                           metrics=checks.baseline_metrics(self.case), failure=self.failure)
            (directory / (self.case + '.stdout')).write_bytes(b'changed')
            with self.assertRaises(ValueError):
                checks.admit_saved(directory, self.case,
                                   metrics=checks.baseline_metrics(self.case), failure=self.failure)


class ResetSourceBoundaryTests(unittest.TestCase):
    def test_ambiguous_function_is_rejected(self):
        with self.assertRaises(ValueError):
            checks.extract('int f(void)\n{\n}\nint f(void)\n{\n}\n', 'int f(')

    def test_unprojected_whole_patch_is_rejected(self):
        patch = ('--- a/drivers/mmc/core/core.c\n+++ b/drivers/mmc/core/core.c\n'
                 '--- a/other.c\n+++ b/other.c\n').encode()
        with self.assertRaises(ValueError):
            checks.selected_queue([('test.patch', patch)])

    def test_symlink_archive_is_rejected_before_reading(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            target = directory / 'archive'
            target.write_bytes(b'not read')
            link = directory / 'link'
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'existing regular'):
                checks.prepare(ROOT, link, directory / 'attempt')

    def test_wrong_archive_identity_is_rejected_without_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive = directory / 'archive'
            archive.write_bytes(b'not the locked archive')
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                checks.prepare(ROOT, archive, directory / 'attempt')
            self.assertFalse((directory / 'attempt').exists())


if __name__ == '__main__':
    unittest.main()
