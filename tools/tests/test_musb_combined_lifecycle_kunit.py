"""Admission tests for the new joined route, with explicit synthetic reports."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import musb_combined_lifecycle_kunit as joined


def report(mode):
    suite, names = joined.SUITES[mode]
    failed = int(mode != 'positive')
    counts = dict(tests=len(names), passed=len(names) - failed, failed=failed,
                  crashed=0, skipped=0, errors=0)
    cases = [dict(name=name, status='PASS' if not failed else 'FAIL') for name in names]
    group = dict(name=suite, arch='um', misc=counts.copy(), sub_groups=[], test_cases=cases)
    return dict(name='KUnit Test Group', arch='um', misc=counts.copy(), test_cases=[], sub_groups=[group])


def literal(pattern):
    # Only materialize the contract's bounded variable source lines. This data
    # is synthetic validator input, not Linux execution evidence.
    pattern = pattern.replace('[1-9][0-9]*', '27')
    import re
    return re.sub(r'\\(.)', r'\1', pattern)


def log(mode):
    return '\n'.join(literal(line) for line in joined.diagnostic_contract(mode)) + '\n'


class JoinedDiagnosticTests(unittest.TestCase):
    def test_complete_positive_and_two_exact_control_streams(self):
        for mode in joined.SUITES:
            with self.subTest(mode=mode):
                cases = joined.checked_cases(report(mode), log(mode), mode=mode)
                self.assertEqual(len(cases), len(joined.SUITES[mode][1]))

    def test_cleanup_timeout_and_slow_warning_before_and_after_observation(self):
        for mode in joined.SUITES:
            case = joined.SUITES[mode][1][0]
            anchor = '# ' + case + ': owned '
            text = log(mode)
            ownership = next(line for line in text.splitlines() if line.startswith(anchor))
            for diagnostic in ('test case cleanup timed out', 'Test should be marked slow (runtime: 1.000000000s)',
                               'unrecognized lifecycle diagnostic'):
                for before in (False, True):
                    extra = '# ' + case + ': ' + diagnostic
                    changed = text.replace(ownership, extra + '\n' + ownership if before else ownership + '\n' + extra)
                    with self.subTest(mode=mode, diagnostic=diagnostic, before=before):
                        with self.assertRaisesRegex(ValueError, 'entire joined'):
                            joined.checked_cases(report(mode), changed, mode=mode)

    def test_different_control_assertion_or_observation_is_inconclusive(self):
        for mode in ('terminal-control', 'work-control'):
            text = log(mode)
            for changed in (text.replace('to be false, but is true', 'to be true, but is false', 1),
                            text.replace('refs=0', 'refs=-1', 1),
                            text.replace('EXPECTATION FAILED', 'ASSERTION FAILED', 1)):
                with self.assertRaises(ValueError):
                    joined.checked_cases(report(mode), changed, mode=mode)

    def test_diagnostic_outside_cases_or_after_terminal_is_rejected(self):
        for mode in joined.SUITES:
            for changed in (log(mode).replace('1..1\n', '1..1\n# extra suite message\n', 1),
                            log(mode) + 'late unexplained message\n',
                            'WARNING: before KTAP\n' + log(mode)):
                with self.assertRaises(ValueError):
                    joined.checked_cases(report(mode), changed, mode=mode)

    def test_missing_duplicate_and_reordered_cases_are_rejected(self):
        positive = report('positive')
        for change in ('missing', 'duplicate', 'reorder'):
            changed = copy.deepcopy(positive)
            cases = changed['sub_groups'][0]['test_cases']
            if change == 'missing':
                cases.pop()
            elif change == 'duplicate':
                cases[-1] = cases[0]
            else:
                cases.reverse()
            with self.assertRaises(ValueError):
                joined.checked_cases(changed, log('positive'), mode='positive')

    def test_normal_return_or_parser_error_cannot_be_a_control(self):
        for mode in ('terminal-control', 'work-control'):
            for changes in (dict(passed=1, failed=0), dict(errors=1)):
                changed = report(mode)
                changed['misc'].update(changes)
                changed['sub_groups'][0]['misc'].update(changes)
                with self.assertRaises(ValueError):
                    joined.checked_cases(changed, log(mode), mode=mode)

    def test_control_requires_terminal_one_and_released_owner(self):
        normal = dict(outcome='exited', exit_code=1, returncode=1, stop_requested=False,
                      state=dict(Running=False, Status='exited', ExitCode=1, OOMKilled=False, Error=''))
        joined.terminal_result(normal, mode='terminal-control')
        for change in (dict(exit_code=0, returncode=0), dict(stop_requested=True),
                       dict(state=dict(Running=True, Status='running', ExitCode=1)),
                       dict(outcome='timeout')):
            with self.assertRaises(ValueError):
                joined.terminal_result(normal | change, mode='terminal-control')

    def test_source_failure_log_is_bound_to_exact_case_and_error(self):
        text = log('positive')
        for changed in (text.replace('error -EIO:', 'error -ENOMEM:', 1),
                        text.replace('musb_init_controller failed', 'unrelated operation failed', 1),
                        text.replace('musb-combined-child.0:', 'musb-combined-child.1:', 1)):
            with self.assertRaises(ValueError):
                joined.checked_cases(report('positive'), changed, mode='positive')


class JoinedViewTests(unittest.TestCase):
    def test_function_anchor_tolerates_nested_block_but_rejects_ambiguous_token(self):
        source = 'static int sample(void)\n{\n\tif (ready) {\n\t\treturn 1;\n\t}\n\treturn 0;\n}\n'
        changed = joined._replace_function(source, 'sample', '\n{\n', '\n{\n\tobserve();\n')
        self.assertIn('observe();', changed)
        with self.assertRaises(ValueError):
            joined._replace_function(source, 'sample', '{\n', '{\nobserve();\n')

    def test_kconfig_seam_is_exact_one_context_and_no_generic_host_admission(self):
        config = ('config USB_MUSB_SUNXI\n\ttristate "Allwinner (sunxi)"\n'
                  '\tdepends on ARCH_SUNXI\n\tdepends on EXTCON\n')
        root = Path(__file__).resolve().parents[2]
        with patch.object(joined, '_core', return_value='core'), \
             patch.object(joined, '_sunxi', return_value='sunxi'), \
             patch.object(joined, '_phy', return_value='phy'), \
             patch.object(joined, 'control_functions', return_value='static int control_sunxi_musb_exit(void)\n{\n}\n'):
            texts = {joined.CORE: '', joined.SUNXI: '', joined.PHY: '', joined.KCONFIG: config}
            result = joined.replacements(root, texts)
            self.assertEqual(set(result), set(joined.TARGETS) - {joined.STAMP})
            self.assertIn('depends on ARCH_SUNXI || (COMPILE_TEST && KUNIT)', result[joined.KCONFIG])
            self.assertIn('USB_MUSB_SUNXI=y', result[joined.KCONFIG])
            for wrong in (config.replace('ARCH_SUNXI', 'ARCH_OTHER'), config + config):
                with self.assertRaises(ValueError):
                    joined.replacements(root, {**texts, joined.KCONFIG: wrong})

    def test_actual_view_inventory_rejects_extra_target_or_wrong_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / 'owned').write_text('before')
            expected = joined.inventory(source)
            joined.verify_view(source, expected)
            (source / 'owned').write_text('after')
            with self.assertRaises(ValueError):
                joined.verify_view(source, expected)
            (source / 'owned').write_text('before')
            (source / 'extra').write_text('not declared')
            with self.assertRaises(ValueError):
                joined.verify_view(source, expected)

    def test_prepared_view_cannot_self_declare_different_generated_bytes(self):
        import importlib.util
        import hashlib
        import json
        module_path = Path(__file__).resolve().parents[1] / 'check-musb-combined-lifecycle-kunit.py'
        spec = importlib.util.spec_from_file_location('joined_linux_check_for_test', module_path)
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original = {name: ['file', 0, hashlib.sha256(b'old').hexdigest()] for name in joined.TARGETS}
            generated = {name: b'current generated bytes' for name in joined.TARGETS}
            expected = copy.deepcopy(original)
            for name, data in generated.items():
                expected[name][2] = hashlib.sha256(data).hexdigest()
                target = directory / 'files' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            patch_bytes = b'exact append bytes'
            (directory / 'append.patch').write_bytes(patch_bytes)
            regenerated = dict(replacements={name: hashlib.sha256(data).hexdigest()
                                            for name, data in generated.items()},
                test_append=dict(name='append.patch', sha256=hashlib.sha256(patch_bytes).hexdigest()))
            view = dict(**regenerated, inputs={'current': 'pin'}, tree_sha256=joined.digest(expected),
                        diagnostic_streams={mode: joined.diagnostic_contract(mode) for mode in joined.SUITES})
            for name, data in (('base-inventory.json', original), ('view-inventory.json', expected), ('view.json', view)):
                (directory / name).write_text(json.dumps(data))
            with patch.object(check, 'pins', return_value={'current': 'pin'}), \
                 patch.object(check, 'generated_view', return_value=(generated, patch_bytes, regenerated)), \
                 patch.object(check, 'TREE_SHA256', joined.digest(original)):
                check.admitted_preparation(directory, Path('/explicit/owned/source'))
                target = directory / 'files' / joined.CORE
                target.write_bytes(b'stale or altered source')
                with self.assertRaisesRegex(ValueError, 'replacement changed'):
                    check.admitted_preparation(directory, Path('/explicit/owned/source'))
                changed_view = copy.deepcopy(view)
                changed_view['replacements'][joined.CORE] = hashlib.sha256(target.read_bytes()).hexdigest()
                (directory / 'view.json').write_text(json.dumps(changed_view))
                with self.assertRaisesRegex(ValueError, 'current source generator'):
                    check.admitted_preparation(directory, Path('/explicit/owned/source'))

    def test_disk_floor_preserves_remaining_reservation_and_headroom(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            total = joined.FLOOR + joined.HEADROOM + joined.HARD_CAP
            with patch.object(joined.shutil, 'disk_usage') as usage:
                usage.return_value.free = total
                joined.resources(path, path, starting=True)
                usage.return_value.free = total - 1
                with self.assertRaisesRegex(RuntimeError, 'resource floor'):
                    joined.resources(path, path, starting=True)


class NativeHistoricalAdmissionTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        module_path = Path(__file__).resolve().parents[1] / 'check-musb-combined-lifecycle.py'
        spec = importlib.util.spec_from_file_location('combined_native_check_for_test', module_path)
        self.native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.native)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original = {}
        for name in self.native.MAINTAINED:
            data = (self.native.ROOT / name).read_bytes()
            self.original[name] = data
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.previous = dict(stage='native', inputs={name: joined.hashlib.sha256(data).hexdigest()
                                                    for name, data in self.original.items()})
        self.receipt = self.root / 'receipt.json'
        self.receipt.write_text('explicit synthetic test receipt')
        self.root_patch = patch.object(self.native, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.blob_patch = patch.object(self.native, '_git_blob', side_effect=lambda ref, name: self.original[name])
        self.blob_patch.start()
        self.addCleanup(self.blob_patch.stop)

    def test_default_refuses_context_pin_drift_without_explicit_history(self):
        (self.root / 'Taskfile.yml').write_bytes(self.original['Taskfile.yml'] + b'# unrelated context\n')
        with self.assertRaisesRegex(ValueError, 'exact native inputs'):
            self.native.native_admission(self.previous, self.receipt)

    def test_exact_original_source_ref_and_git_blob_pins_are_required(self):
        with self.assertRaisesRegex(ValueError, 'exact original'):
            self.native.native_admission(self.previous, self.receipt, source_ref='0' * 40)
        self.previous['inputs']['Taskfile.yml'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Git blobs'):
            self.native.native_admission(self.previous, self.receipt, source_ref=self.native.ORIGINAL_NATIVE_REF)

    def test_native_body_type_projector_or_flags_drift_is_refused(self):
        path = self.root / 'kernel/tests/musb_combined_lifecycle_test.c'
        path.write_bytes(self.original[str(path.relative_to(self.root))] + b'\n/* changed type */\n')
        with self.assertRaisesRegex(ValueError, 'C/type/projector'):
            self.native.native_admission(self.previous, self.receipt, source_ref=self.native.ORIGINAL_NATIVE_REF)
        path.write_bytes(self.original[str(path.relative_to(self.root))])
        checker = self.root / 'tools/check-musb-combined-lifecycle.py'
        for before, after in (("'-O2'", "'-O3'"),
                              ('if result.returncode != code', 'if result.returncode == code')):
            checker.write_text(self.original[str(checker.relative_to(self.root))].decode().replace(before, after, 1))
            with self.assertRaisesRegex(ValueError, 'flags or complete result validator'):
                self.native.native_admission(self.previous, self.receipt, source_ref=self.native.ORIGINAL_NATIVE_REF)

    def test_original_task_behavior_drift_or_duplicate_is_refused(self):
        path = self.root / 'Taskfile.yml'
        for text in (self.original['Taskfile.yml'].decode().replace(
                'musb-combined-lifecycle.py {{.CLI_ARGS}}', 'musb-combined-lifecycle.py --unsafe', 1),
                self.original['Taskfile.yml'].decode() +
                '\n  test:musb-combined-lifecycle:\n    cmds: [false]\n'):
            path.write_text(text)
            with self.assertRaisesRegex(ValueError, 'Task'):
                self.native.native_admission(self.previous, self.receipt, source_ref=self.native.ORIGINAL_NATIVE_REF)


if __name__ == '__main__':
    unittest.main()
