"""Admission/source-boundary regressions; driver semantics run in the C suite."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import brcmfmac_eapol_checks as checks


def observation(name):
    return (f'OBSERVE {name} result=0 pending=0 other_pending=0 firmware_calls=0 '
            'frees=0 barriers=0 wakes=0 tx_errors=0\n')


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

    def run_oracle(self, output, raw=0, stderr='', *, failure=False, assertion=None, observe=True):
        if observe:
            output = observation('timeout_single') + output
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
        self.run_oracle('PASS timeout_single\n')
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

    def test_observe_route_rejects_added_wrong_case_assertion_and_diagnostic(self):
        terminal = 'FAIL timeout_single timeout_errno expected=-110 actual=1\n'
        for extra in ('FAIL interface_isolation unexpected expected=1 actual=0\n',
                      'FAIL timeout_single unrelated expected=1 actual=0\n',
                      'runtime error: unexpected diagnostic\n'):
            for output in (terminal + extra, extra + terminal):
                with self.subTest(output=output), self.assertRaises(RuntimeError):
                    self.run_oracle(output, raw=1, failure=True, assertion=('timeout_errno', -110, 1))

    def test_observe_route_requires_exactly_one_complete_observation(self):
        terminal = 'PASS timeout_single\n'
        for output in (terminal, observation('timeout_multiple') + terminal,
                       observation('timeout_single') * 2 + terminal,
                       observation('timeout_single').replace('frees=0', 'frees=bad') + terminal,
                       observation('timeout_single') + terminal.rstrip('\n')):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                self.run_oracle(output, observe=False)

    def test_successful_observe_route_rejects_extra_failure_or_diagnostic(self):
        for extra in ('FAIL interface_isolation unrelated expected=0 actual=1\n', 'unexpected diagnostic\n'):
            with self.subTest(extra=extra), self.assertRaises(RuntimeError):
                self.run_oracle('PASS timeout_single\n' + extra)

    def test_bool_is_not_an_original_process_exit_code(self):
        with self.assertRaises(RuntimeError):
            self.run_oracle('FAIL timeout_single timeout_errno expected=-110 actual=1\n',
                            raw=True, failure=True, assertion=('timeout_errno', -110, 1))


class NativeProvenanceTests(unittest.TestCase):
    """Disposable metadata fixtures exercise the maintained read-only route.

    Projection/mutation are seams here; actual Linux bodies and compiling
    mutations are qualified by the separate native/ARM fixture executions.
    """
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.previous = self.root / 'attempts/original'
        self.destination = self.root / 'attempts/current'
        self.previous.mkdir(parents=True)
        self.destination.mkdir()
        self.source = self.root / 'current-source'
        for name in checks.MAINTAINED:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('maintained:' + name)
        for source in (self.source, self.previous / 'candidate-source'):
            for name in checks.SOURCE_FILES:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('selected source:' + name)
        self.types, self.functions = 'actual types\n', 'actual functions\n'
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(checks, 'projection', return_value=(self.types, self.functions)).start()
        mock.patch.object(checks, 'mutate', side_effect=lambda text, name: text + name + '\n').start()
        self.record = {'status': 'passed', 'inputs': checks.inputs(self.root), 'results': {}}
        self.record['inputs']['tools/brcmfmac_eapol_checks.py'] = 'historical helper input'
        for label in ('candidate', 'sanitizer', *checks.CONTROLS):
            directory = self.previous / label
            directory.mkdir()
            functions = self.functions + label + '\n' if label in checks.CONTROLS else self.functions
            for name, value in {'eapol_types.h': self.types, 'eapol_functions.h': functions,
                                'fixture': 'original binary:' + label,
                                'compile.stdout': '', 'compile.stderr': ''}.items():
                (directory / name).write_text(value)
            compile_record = dict(command=['cc', *checks.compiler_flags(label == 'sanitizer'), '-I', str(directory),
                str(self.root / 'kernel/tests/brcmfmac_eapol_test.c'), '-o', str(directory / 'fixture')],
                returncode=0, stdout_sha256=checks.digest(b''), stderr_sha256=checks.digest(b''))
            self.write(directory / 'compile.json', compile_record)
            original = dict(types_sha256=checks.digest(self.types.encode()),
                            functions_sha256=checks.digest(functions.encode()),
                            binary_sha256=checks.file_hash(directory / 'fixture'), cases={})
            names = (checks.CONTROLS[label][2],) if label in checks.CONTROLS else checks.CASES
            for name in names:
                if label in checks.CONTROLS:
                    assertion, expected, actual = checks.CONTROLS[label][3]
                    output = f'FAIL {name} {assertion} expected={expected} actual={actual}\n'
                else:
                    output = 'PASS ' + name + '\n'
                output = observation(name) + output
                (directory / (name + '.stdout')).write_text(output)
                (directory / (name + '.stderr')).write_text('')
                case = dict(command=[str(directory / 'fixture'), name],
                            returncode=1 if label in checks.CONTROLS else 0,
                            stdout_sha256=checks.digest(output.encode()), stderr_sha256=checks.digest(b''))
                self.write(directory / (name + '.json'), case)
                original['cases'][name] = case
            self.record['results'][label] = original
        self.write(self.previous / 'result.json', self.record)
        self.write(self.previous / 'sources.json',
                   {'candidate': {name: checks.file_hash(self.source / name) for name in checks.SOURCE_FILES}})

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value) + '\n')

    def admit(self):
        return checks.admit_native(self.root, self.source, self.destination, self.previous)

    def test_identical_executables_admitted_without_execution_or_original_writes(self):
        before = {str(path.relative_to(self.previous)): checks.file_hash(path)
                  for path in self.previous.rglob('*') if path.is_file()}
        with mock.patch.object(checks.subprocess, 'run', side_effect=AssertionError('must not execute')):
            proof = self.admit()
        after = {str(path.relative_to(self.previous)): checks.file_hash(path)
                 for path in self.previous.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(proof['changed_host_inputs'], ['tools/brcmfmac_eapol_checks.py'])
        self.assertEqual(len(proof['verified']), 9)

    def test_changed_fixture_dependency_refused(self):
        (self.root / 'kernel/tests/brcmfmac_eapol_test.c').write_text('changed fixture')
        with self.assertRaisesRegex(ValueError, 'dependency changed'):
            self.admit()

    def test_changed_shared_applicator_refused(self):
        (self.root / 'tools/kernel-inputs.py').write_text('changed applicator')
        with self.assertRaisesRegex(ValueError, 'dependency changed'):
            self.admit()

    def test_changed_current_selected_source_refused(self):
        (self.source / checks.SOURCE_FILES[0]).write_text('different current source')
        with self.assertRaisesRegex(ValueError, 'source files differ'):
            self.admit()

    def test_changed_original_binary_refused(self):
        (self.previous / 'candidate/fixture').write_text('different binary')
        with self.assertRaisesRegex(ValueError, 'input/binary differs'):
            self.admit()

    def test_different_compiler_flags_refused(self):
        path = self.previous / 'candidate/compile.json'
        value = json.loads(path.read_text())
        value['command'].insert(1, '-DNDEBUG')
        self.write(path, value)
        with self.assertRaisesRegex(ValueError, 'compile provenance differs'):
            self.admit()

    def test_changed_output_hash_refused(self):
        (self.previous / 'candidate/empty_wait.stdout').write_text('new output at old path\n')
        with self.assertRaisesRegex(ValueError, 'case provenance differs'):
            self.admit()

    def change_control(self, *, raw=None, text=None):
        label = 'positive_timeout'
        name = checks.CONTROLS[label][2]
        directory = self.previous / label
        case = self.record['results'][label]['cases'][name]
        if raw is not None:
            case['returncode'] = raw
        if text is not None:
            text = observation(name) + text
            (directory / (name + '.stdout')).write_text(text)
            case['stdout_sha256'] = checks.digest(text.encode())
        self.write(directory / (name + '.json'), case)
        self.write(self.previous / 'result.json', self.record)

    def test_consistent_control_metadata_with_wrong_raw_exit_refused(self):
        self.change_control(raw=0)
        with self.assertRaisesRegex(RuntimeError, 'Unexpected actual fixture'):
            self.admit()

    def test_consistent_control_metadata_with_numeric_prefix_refused(self):
        self.change_control(text='FAIL timeout_single timeout_errno expected=-110 actual=10\n')
        with self.assertRaisesRegex(RuntimeError, 'different assertion/value'):
            self.admit()

    def test_admit_route_rejects_added_wrong_case_assertion_and_diagnostic(self):
        terminal = 'FAIL timeout_single timeout_errno expected=-110 actual=1\n'
        for extra in ('FAIL interface_isolation unexpected expected=1 actual=0\n',
                      'FAIL timeout_single unrelated expected=1 actual=0\n',
                      'runtime error: unexpected diagnostic\n'):
            with self.subTest(extra=extra), self.assertRaisesRegex(RuntimeError, 'Unexpected actual fixture'):
                self.change_control(text=terminal + extra)
                self.admit()


if __name__ == '__main__':
    unittest.main()
