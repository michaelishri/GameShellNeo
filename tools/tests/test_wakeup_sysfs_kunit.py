"""Require actual named kernel outcomes and current owned sysfs control results."""
import copy
from contextlib import contextmanager, ExitStack, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from wakeup_sysfs_kunit import CASES, CONTROL_CASES, checked_cases, checked_control, test_patch
from wakeup_sysfs_source import PATCH

spec = importlib.util.spec_from_file_location('sysfs_runner_under_test', TOOLS / 'check-wakeup-sysfs-kunit.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def report(control=False):
    counts = dict(tests=12, passed=8 if control else 12, failed=4 if control else 0,
                  crashed=0, skipped=0, errors=0)
    return dict(name='KUnit Test Group', arch='um', misc=counts, test_cases=[], sub_groups=[
        dict(name='wakeup-sysfs', arch='um', misc=counts.copy(), sub_groups=[], test_cases=[
            dict(name=name, status='FAIL' if control and name in CONTROL_CASES else 'PASS')
            for name in CASES])])


# Verbatim KTAP from pinned Linux 6.18.54 control run8402ea6f. The original
# wrapper rejected its numeric errno rendering; that historical result remains.
COMPILED_CONTROL_KTAP = '''KTAP version 1
1..1
    KTAP version 1
    # Subtest: wakeup-sysfs
    # module: wakeup
    1..12
    ok 1 sysfs_enable_test
    ok 2 sysfs_disable_test
    ok 3 sysfs_enabled_idempotent_test
    ok 4 sysfs_disabled_idempotent_test
    ok 5 sysfs_invalid_request_test
    # sysfs_object_alloc_error_test: fault-observation result=8 disabled=1 hits=1 objects=0 names=0 ids=0
    # sysfs_object_alloc_error_test: EXPECTATION FAILED at drivers/base/power/wakeup-sysfs-kunit.c:318
    Expected result == -12, but
        result == 8 (0x8)
    not ok 6 sysfs_object_alloc_error_test
    # sysfs_name_alloc_error_test: fault-observation result=8 disabled=1 hits=1 objects=0 names=0 ids=0
    # sysfs_name_alloc_error_test: EXPECTATION FAILED at drivers/base/power/wakeup-sysfs-kunit.c:318
    Expected result == -12, but
        result == 8 (0x8)
    not ok 7 sysfs_name_alloc_error_test
    # sysfs_id_alloc_error_test: fault-observation result=8 disabled=1 hits=1 objects=0 names=0 ids=0
    # sysfs_id_alloc_error_test: EXPECTATION FAILED at drivers/base/power/wakeup-sysfs-kunit.c:318
    Expected result == -12, but
        result == 8 (0x8)
    not ok 8 sysfs_id_alloc_error_test
    # sysfs_registration_error_test: fault-observation result=8 disabled=1 hits=1 objects=0 names=0 ids=0
    # sysfs_registration_error_test: EXPECTATION FAILED at drivers/base/power/wakeup-sysfs-kunit.c:318
    Expected result == -12, but
        result == 8 (0x8)
    not ok 9 sysfs_registration_error_test
    ok 10 sysfs_two_enables_test
    # sysfs_disable_enable_srcu_test: srcu-observation observer=500 detached=1 blocked=1 old-alive=1 enabled=8
    ok 11 sysfs_disable_enable_srcu_test
    # sysfs_unregister_active_write_test: context-observation entered=500 unpublished=500 finished-early=0 foreign-result=0
    ok 12 sysfs_unregister_active_write_test
# wakeup-sysfs: pass:8 fail:4 skip:0 total:12
# Totals: pass:8 fail:4 skip:0 total:12
not ok 1 wakeup-sysfs
reboot: System halted

'''


def control_log():
    return COMPILED_CONTROL_KTAP


class KernelOutcomeAdmission(unittest.TestCase):
    def test_positive_and_exact_four_failure_control_are_distinct(self):
        self.assertEqual(len(checked_cases(report(), 'wakeup-sysfs\n' + '\n'.join(CASES))), 12)
        self.assertEqual(len(checked_control(report(True), control_log())), 12)
        with self.assertRaises(ValueError):
            checked_cases(report(True), control_log())
        with self.assertRaises(ValueError):
            checked_control(report(), control_log())

    def test_missing_duplicate_other_failed_case_or_diagnostic_rejects(self):
        for mode in ('missing', 'duplicate', 'wrong-fail', 'skip', 'crash', 'extra-suite'):
            value = report(True)
            cases = value['sub_groups'][0]['test_cases']
            if mode == 'missing':
                cases.pop()
            elif mode == 'duplicate':
                cases[-1] = cases[0]
            elif mode == 'wrong-fail':
                cases[0]['status'] = 'FAIL'
            elif mode == 'skip':
                cases[-1]['status'] = 'SKIP'
            elif mode == 'crash':
                value['misc']['crashed'] = 1
            else:
                value['sub_groups'].append(copy.deepcopy(value['sub_groups'][0]))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                checked_control(value, control_log())
        for text in ('WARNING:', 'BUG:', 'Kernel panic', 'possible circular locking',
                     'sleeping function called', 'INFO: task worker blocked for more than'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                checked_control(report(True), control_log() + '\n' + text)

    def test_exact_assertions_observed_values_gate_and_ownership_are_required(self):
        good = control_log()
        for bad in (good.replace('result == 8', 'result == -5', 1),
                    good.replace('Expected result == -12', 'Expected other == -12', 1),
                    good.replace('disabled=1', 'disabled=0', 1), good.replace('hits=1', 'hits=0', 1),
                    good.replace('ids=0', 'ids=1', 1), good.replace('objects=0', 'objects=1', 1),
                    good.replace('names=0', 'names=1', 1),
                    good + '\n# sysfs_enable_test: EXPECTATION FAILED\nExpected other == 1, but\nother == 0'):
            with self.subTest(tail=bad[-100:]), self.assertRaises(ValueError):
                checked_control(report(True), bad)

    def test_compiled_numeric_errno_and_exact_rendered_values_are_required(self):
        good = control_log()
        self.assertEqual(len(checked_control(report(True), good)), 12)
        for bad in (good.replace('Expected result == -12', 'Expected result == -5', 1),
                    good.replace('Expected result == -12', 'Expected result == -ENOMEM', 1),
                    good.replace('result == 8 (0x8)', 'result == 80 (0x50)', 1),
                    good.replace('result == 8 (0x8)', 'result == 8 (0x9)', 1),
                    good.replace('result == 8 (0x8)', 'result == 8', 1),
                    good.replace('result == 8 (0x8)', 'result == 8 (0x8)\n-ENOMEM == -12', 1),
                    good.replace('EXPECTATION FAILED', 'ASSERTION FAILED', 1),
                    good.replace('drivers/base/power/wakeup-sysfs-kunit.c:', 'other.c:', 1)):
            with self.subTest(log=bad[-100:]), self.assertRaises(ValueError):
                checked_control(report(True), bad)

    def test_candidate_must_be_explicit_once_before_source_preparation(self):
        for queue in ([], [('different.patch', b'')], [(Path(PATCH).name, b'')] * 2):
            with self.subTest(queue=queue), self.assertRaisesRegex(ValueError, 'Exactly one'):
                test_patch(None, None, None, queue, None, None)


class RunnerAdmission(unittest.TestCase):
    @contextmanager
    def executor(self, *, prior=('test.log', 'results.json'), produced=(), outcome='expected'):
        """Drive actual maintained main with disposable source/executor boundaries."""
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            config_text = 'CONFIG_KUNIT=y\n'
            builder = dict(image='fixture-builder', platform='linux/amd64', jobs=1)
            metadata = dict(tree_sha256='b' * 64)
            paths = ('tools/check-wakeup-sysfs-kunit.py', 'tools/wakeup_sysfs_kunit.py',
                     'tools/wakeup_sysfs_source.py', 'tools/musb_restart_kunit.py',
                     'tools/kernel_sources.py', 'tools/kernel_checks.py', 'tools/kernel-inputs.py',
                     'tools/managed_container.py', 'tools/docker-stage.py',
                     'tools/tests/test_wakeup_sysfs_kunit.py', 'build/sources.lock.json',
                     'kernel/tests/wakeup-sysfs-kunit.config', 'kernel/tests/wakeup-sysfs-kunit.c',
                     'kernel/tests/wakeup-sysfs-kunit.h', 'Taskfile.yml', PATCH)
            for name in paths:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture\n')
            (root / 'build/sources.lock.json').write_text(json.dumps(dict(linux=dict(tag='vfixture'), builder=builder)))
            (root / 'kernel/tests/wakeup-sysfs-kunit.config').write_text(config_text)
            (root / 'tools/kernel-inputs.py').write_text('def patches(): yield from []\ndef apply_queue(*args): pass\n')
            work = root / '.local/build/wakeup-sysfs-kunit-errors-ignored'
            key = hashlib.sha256((metadata['tree_sha256'] + config_text + builder['image']).encode()).hexdigest()[:16]
            scratch = work / ('kernel-' + key)
            output = scratch / 'output'
            output.mkdir(parents=True)
            (output / '.config').write_text(config_text)
            (output / 'linux').write_bytes(b'fixture kernel')
            payload = {'test.log': control_log().encode(), 'results.json': json.dumps(report(True)).encode()}
            targets = {'test.log': output / 'test.log', 'results.json': scratch / 'results.json'}
            for name in prior:
                targets[name].write_bytes(payload[name])
            identity = dict(schema=1, workspace='fixture-workspace', stage='wakeup-sysfs-kunit', run='a' * 32)
            terminal = dict(outcome='exited', exit_code=1, returncode=1, stop_requested=False,
                            job=identity, state=dict(Running=False, Status='exited', ExitCode=1,
                                                    OOMKilled=False, Error=''))
            observed = copy.deepcopy(terminal)
            if outcome == 'stopped':
                observed['stop_requested'] = True
            elif outcome == 'oom':
                observed['state']['OOMKilled'] = True
            elif outcome == 'running':
                observed['state']['Running'] = True
            elif outcome == 'wrong-result':
                observed['job']['run'] = 'b' * 32
            harness = SimpleNamespace(work=work, scratch=scratch, payload=payload,
                                      before_execution=None, result_observations=0)

            def execute(stage, arguments, attempt, *, timeout):
                attempt.mkdir(parents=True)
                harness.before_execution = {name: path.exists() for name, path in targets.items()}
                for name in produced:
                    targets[name].write_bytes(payload[name])
                if outcome == 'unresolved':
                    raise RuntimeError('Managed run remains unresolved')
                if outcome == 'zero':
                    value = copy.deepcopy(terminal)
                    value.update(exit_code=0, returncode=0)
                    value['state']['ExitCode'] = 0
                    return value
                raise runner.ManagedCommandFailure(identity, terminal)

            def result_for(receipt):
                harness.result_observations += 1
                return identity, observed, root

            support = SimpleNamespace(__file__=str(root / 'tools/wakeup_sysfs_kunit.py'),
                test_patch=lambda *args, **kwargs: ('9999-fixture.patch', b'fixture'),
                checked_control=checked_control, CONTROL_CASES=CONTROL_CASES, LIMITS='host executor fixture')
            for name, value in (('ROOT', root), ('__file__', str(root / 'tools/check-wakeup-sysfs-kunit.py')),
                                ('archive_for', lambda lock: root / 'archive'), ('support', support),
                                ('ensure_source', lambda *args, **kwargs: (root / 'source', {}, metadata)),
                                ('execute', execute), ('result_for', result_for),
                                ('owns_active', lambda identity: outcome == 'active-owner')):
                stack.enter_context(mock.patch.object(runner, name, value))
            stack.enter_context(mock.patch.object(sys, 'argv', ['runner', '--control', 'errors-ignored']))
            stack.enter_context(redirect_stdout(io.StringIO()))
            yield harness

    def test_stale_or_partial_outputs_cannot_qualify_a_failed_rebuild(self):
        for prior in (('test.log', 'results.json'), ('test.log',), ('results.json',)):
            for produced in ((), ('test.log',), ('results.json',)):
                with self.subTest(prior=prior, produced=produced), self.executor(
                        prior=prior, produced=produced) as f:
                    with self.assertRaisesRegex(RuntimeError, 'current-execution'):
                        runner.main()
                    self.assertEqual(f.before_execution, {'test.log': False, 'results.json': False})
                    self.assertFalse((f.work / 'control-evidence.json').exists())
                    history = list((f.scratch / 'previous-runs').iterdir())
                    self.assertEqual(len(history), 1)
                    self.assertEqual({p.name for p in history[0].iterdir()}, set(prior))
                    for name in prior:
                        self.assertEqual((history[0] / name).read_bytes(), f.payload[name])

    def test_new_identical_output_and_original_released_raw1_qualify(self):
        with self.executor(produced=('test.log', 'results.json')) as f:
            runner.main()
            self.assertEqual(f.before_execution, {'test.log': False, 'results.json': False})
            evidence = json.loads((f.work / 'control-evidence.json').read_text())
            self.assertEqual(evidence['managed_result']['exit_code'], 1)
            self.assertEqual(evidence['expected_ktap_assertion'], 'result == -12')
            self.assertEqual(evidence['expected_ktap_value'], 'result == 8 (0x8)')
            for name in f.payload:
                self.assertEqual(evidence['artifacts'][name], hashlib.sha256(f.payload[name]).hexdigest())

    def test_normal_raw0_unresolved_or_non_original_outcomes_reject(self):
        for outcome in ('zero', 'unresolved', 'active-owner', 'stopped', 'oom', 'running', 'wrong-result'):
            with self.subTest(outcome=outcome), self.executor(
                    produced=('test.log', 'results.json'), outcome=outcome) as f:
                with self.assertRaises(RuntimeError):
                    runner.main()
                self.assertFalse((f.work / 'control-evidence.json').exists())
                if outcome in ('zero', 'unresolved'):
                    self.assertEqual(f.result_observations, 0)


if __name__ == '__main__':
    unittest.main()
