"""Regress complete numeric admission on the actual native observation route."""
import json
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

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


class ResetReadonlyViewTests(unittest.TestCase):
    def entries(self):
        return {name: ['file', 0, 'a' * 64] for name in
                set(checks.OVERLAY_MEMBERS) | {'.gameshellneo-patches.json', 'unchanged.c'}}

    def pins(self):
        return {name: 'b' * 64 for name in
                set(checks.OVERLAY_MEMBERS) | {'.gameshellneo-patches.json'}}

    def test_complete_view_preserves_every_other_entry(self):
        original = self.entries()
        view = checks.derived_view_inventory(original, self.pins())
        self.assertEqual(view['unchanged.c'], original['unchanged.c'])
        self.assertEqual(original[checks.DRIVER + 'sdio.c'][2], 'a' * 64)
        self.assertEqual(view[checks.DRIVER + 'sdio.c'][2], 'b' * 64)

    def test_old_stamp_cannot_be_omitted(self):
        pins = self.pins()
        del pins['.gameshellneo-patches.json']
        with self.assertRaises(ValueError):
            checks.derived_view_inventory(self.entries(), pins)

    def test_extra_override_is_rejected(self):
        pins = self.pins()
        pins['unrelated.c'] = 'c' * 64
        with self.assertRaises(ValueError):
            checks.derived_view_inventory(self.entries(), pins)

    def test_override_cannot_follow_source_link(self):
        entries = self.entries()
        entries[checks.DRIVER + 'sdio.c'] = ['link', 'other']
        with self.assertRaises(ValueError):
            checks.derived_view_inventory(entries, self.pins())

    def test_source_hash_must_be_complete(self):
        pins = self.pins()
        pins[checks.DRIVER + 'sdio.c'] = 'b' * 65
        with self.assertRaises(ValueError):
            checks.derived_view_inventory(self.entries(), pins)

    def test_only_new_output_is_writable_and_offline_builder_is_pinned(self):
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        mounts = {name: Path('/new/overrides') / name for name in self.pins()}
        args = checks.stage_arguments(ROOT, Path('/new/output'), Path('/old/source'), mounts, lock)
        volumes = [args[index + 1] for index, item in enumerate(args) if item == '-v']
        self.assertEqual([value for value in volumes if not value.endswith(':ro')], ['/new/output:/qualification'])
        self.assertIn('--pull=never', args)
        self.assertEqual(args[args.index('--network') + 1], 'none')
        self.assertEqual(args[args.index('--cpus=1')], '--cpus=1')
        self.assertIn(lock['builder']['image'], args)

    def test_missing_mount_is_rejected(self):
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        with self.assertRaises(ValueError):
            checks.stage_arguments(ROOT, Path('/new'), Path('/old'), {}, lock)

    def prepare_fixture(self, directory):
        from kernel_sources import inventory, digest as inventory_digest, source_spec
        project = directory / 'project'
        (project / 'build').mkdir(parents=True)
        shutil.copyfile(ROOT / 'build/sources.lock.json', project / 'build/sources.lock.json')
        candidates = project / 'kernel/candidates'
        candidates.mkdir(parents=True)
        for name in ('0057-brcmfmac-eapol-ownership.patch', '0073-brcmfmac-reset-ownership.patch'):
            shutil.copyfile(ROOT / 'kernel/candidates' / name, candidates / name)
        source = directory / 'cache/source'
        candidate = directory / 'candidate'
        for name in checks.SOURCE_FILES:
            for tree in (source, candidate):
                path = tree / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('unchanged member ' + name)
        for name in checks.OVERLAY_MEMBERS:
            (candidate / name).write_text('current native member ' + name)
        old_extra = candidates / '0057-brcmfmac-eapol-ownership.patch'
        old_manifest = [dict(name=old_extra.name, sha256=checks.file_hash(old_extra))]
        (source / '.gameshellneo-patches.json').write_text(json.dumps(old_manifest) + '\n')
        lock = json.loads((project / 'build/sources.lock.json').read_text())
        metadata = dict(spec=source_spec(lock, old_manifest), tree_sha256=inventory_digest(inventory(source)))
        (source.parent / 'metadata.json').write_text(json.dumps(metadata))
        receipt = directory / 'retained.json'
        receipt.write_text(json.dumps(dict(path=str(source), metadata=metadata)))
        output = directory / 'output'
        output.mkdir()
        return project, source, candidate, receipt, output, metadata['tree_sha256']

    def prepare(self, fixture):
        project, source, candidate, receipt, output, expected = fixture
        with mock.patch.object(checks, 'kernel_inputs', return_value=SimpleNamespace(patches=lambda: [])), \
                mock.patch.object(checks, 'RETAINED_TREE_SHA256', expected):
            return checks.prepare_source_view(project, receipt, candidate, output)

    def test_actual_preparation_is_readonly_and_stamp_names_new_profile(self):
        from kernel_sources import inventory, digest as inventory_digest
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.prepare_fixture(Path(temporary))
            source, mounts, proof = self.prepare(fixture)
            self.assertEqual(inventory_digest(inventory(source)), fixture[-1])
            stamp = json.loads(mounts['.gameshellneo-patches.json'].read_text())
            self.assertEqual([item['name'] for item in stamp], ['0073-brcmfmac-reset-ownership.patch'])
            self.assertNotEqual(proof['base_inventory_sha256'], proof['effective_inventory_sha256'])

    def test_actual_preparation_rejects_changed_retained_member(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.prepare_fixture(Path(temporary))
            (fixture[1] / 'lib/klist.c').write_text('tampered retained member')
            with self.assertRaisesRegex(ValueError, 'actual inventory changed'):
                self.prepare(fixture)

    def test_actual_preparation_rejects_unmapped_selected_difference(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.prepare_fixture(Path(temporary))
            (fixture[2] / 'lib/klist.c').write_text('unmapped native change')
            with self.assertRaisesRegex(ValueError, 'differs from qualified native'):
                self.prepare(fixture)

    def test_actual_preparation_rejects_override_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = self.prepare_fixture(Path(temporary))
            target = fixture[2] / (checks.DRIVER + 'sdio.c')
            target.unlink()
            target.symlink_to(fixture[1] / (checks.DRIVER + 'sdio.c'))
            with self.assertRaisesRegex(ValueError, 'regular file'):
                self.prepare(fixture)

    def test_wrong_arm_elf_is_rejected(self):
        with self.assertRaises(ValueError):
            checks.check_arm_elf('Class: ELF64\nMachine: AArch64\n')

    def test_compiler_warning_rejects_successful_raw_build(self):
        with self.assertRaises(ValueError):
            checks.check_driver_diagnostics('sdio.c:123: warning: unexpected declaration\n')

    def test_intended_config_override_message_is_not_a_compiler_warning(self):
        checks.check_driver_diagnostics('Value of CONFIG_BRCMDBG is redefined by fragment\n')


if __name__ == '__main__':
    unittest.main()
