"""Reject the wrong wake profile and incomplete real-kernel evidence."""
import copy
from contextlib import contextmanager, ExitStack, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from kernel_candidates import include_candidates
from musb_wake_kunit import (CASES, CONTROL_ASSERTIONS, CONTROL_FAILURES, PATCHES,
                             checked_cases, checked_control, selected_patches)

ROOT = TOOLS.parent
spec = importlib.util.spec_from_file_location('wake_test_inputs', TOOLS / 'kernel-inputs.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)
runner_spec = importlib.util.spec_from_file_location('wake_runner_under_test', TOOLS / 'check-musb-restart-kunit.py')
runner = importlib.util.module_from_spec(runner_spec)
runner_spec.loader.exec_module(runner)


class WakeInputs(unittest.TestCase):
    def test_exact_separate_wake_profile(self):
        base = list(production.patches())
        queue = include_candidates(ROOT, 'musb-wake-startup', base)
        self.assertEqual(tuple(name for name, _ in selected_patches(queue)), PATCHES)
        self.assertEqual(list(production.patches()), base)
        with self.assertRaises(ValueError):
            selected_patches(base)
        with self.assertRaises(ValueError):
            selected_patches(include_candidates(ROOT, 'musb-retirement', base))

    def test_missing_duplicate_reordered_or_composed_profile_rejects(self):
        queue = include_candidates(ROOT, 'musb-wake-startup', list(production.patches()))
        selected = selected_patches(queue)
        bad_inputs = [selected[:-1], selected + [selected[-1]], list(reversed(selected)),
                      selected + [('0039-musb-core-irq-retirement.patch', b'foreign')]]
        for candidate in bad_inputs:
            with self.subTest(names=[name for name, _ in candidate]), self.assertRaises(ValueError):
                selected_patches(candidate)

    def test_control_is_rejected_before_preparation_for_other_suites(self):
        result = subprocess.run([sys.executable, str(TOOLS / 'check-musb-restart-kunit.py'),
                                 '--suite', 'irq', '--wake-control', 'policy-ignored'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--wake-control requires --suite wake', result.stderr)
        self.assertEqual(result.stdout, '')


class WakeEvidence(unittest.TestCase):
    def setUp(self):
        counts = dict(tests=len(CASES), passed=len(CASES), failed=0, crashed=0, skipped=0, errors=0)
        self.report = dict(name='KUnit Test Group', arch='um', misc=counts, test_cases=[],
            sub_groups=[dict(name='musb-wake', arch='um', misc=counts, sub_groups=[],
                             test_cases=[dict(name=name, status='PASS') for name in CASES])])
        self.log = 'musb-wake\n' + '\n'.join(CASES)

    def test_complete_requested_suite(self):
        self.assertEqual(len(checked_cases(self.report, self.log)), len(CASES))

    def test_incomplete_or_different_kernel_results_reject(self):
        for mode in ('missing', 'duplicate', 'FAIL', 'SKIP', 'other-suite', 'extra-suite', 'wrong-arch'):
            report = copy.deepcopy(self.report)
            suite = report['sub_groups'][0]
            cases = suite['test_cases']
            if mode == 'missing':
                cases.pop()
            elif mode == 'duplicate':
                cases[-1] = cases[0]
            elif mode == 'other-suite':
                suite['name'] = 'musb-irq'
            elif mode == 'extra-suite':
                report['sub_groups'].append(copy.deepcopy(suite))
            elif mode == 'wrong-arch':
                report['arch'] = suite['arch'] = 'arm'
            else:
                cases[0]['status'] = mode
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                checked_cases(report, self.log)

    def test_diagnostics_or_missing_log_reject(self):
        for diagnostic in ('WARNING:', 'BUG:', 'not ok ', 'sleeping function called',
                           'possible circular locking', 'Kernel panic'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                checked_cases(self.report, self.log + diagnostic)
        with self.assertRaises(ValueError):
            checked_cases(self.report, 'musb-wake')


class WakeControl(unittest.TestCase):
    def setUp(self):
        counts = dict(tests=len(CASES), passed=len(CASES) - len(CONTROL_FAILURES),
                      failed=len(CONTROL_FAILURES), crashed=0, skipped=0, errors=0)
        self.report = dict(name='KUnit Test Group', arch='um', misc=counts, test_cases=[],
            sub_groups=[dict(name='musb-wake', arch='um', misc=counts, sub_groups=[], test_cases=[
                dict(name=name, status='FAIL' if name in CONTROL_FAILURES else 'PASS') for name in CASES])])
        self.log = 'musb-wake\n' + '\n'.join(CASES) + '''
    # wake_unsupported_irq_test: ASSERTION FAILED at fixture.c:1
        musb_suspend(f->device) == -6
    not ok 2 wake_unsupported_irq_test
    # wake_policy_disabled_test: EXPECTATION FAILED at fixture.c:2
        before.armed == 1
        after.references == 1
    not ok 5 wake_policy_disabled_test
    # wake_peer_first_test: EXPECTATION FAILED at fixture.c:3
        state.references == 2
    not ok 7 wake_peer_first_test
    # wake_peer_last_test: EXPECTATION FAILED at fixture.c:4
        state.references == 2
    not ok 8 wake_peer_last_test
    # wake_disarm_error_test: EXPECTATION FAILED at fixture.c:5
        wake_snapshot(f).references == 1
        f->arms == 3
    Expected f->musb.irq_wake to be false, but is true
    not ok 10 wake_disarm_error_test
'''

    def test_executed_expected_control_is_distinct_from_success(self):
        self.assertEqual(set(CONTROL_FAILURES), {
            'wake_unsupported_irq_test', 'wake_policy_disabled_test', 'wake_peer_first_test',
            'wake_peer_last_test', 'wake_disarm_error_test'})
        self.assertEqual(len(checked_control(self.report, self.log)), len(CASES))
        with self.assertRaises(ValueError):
            checked_cases(self.report, self.log)
        positive = WakeEvidence()
        positive.setUp()
        with self.assertRaises(ValueError):
            checked_control(positive.report, positive.log)

    def test_control_rejects_missing_or_unexpected_failures(self):
        for mode in ('missing', 'duplicate', 'unexpected-pass', 'unexpected-failure', 'crash'):
            report = copy.deepcopy(self.report)
            suite = report['sub_groups'][0]
            cases = suite['test_cases']
            if mode == 'missing':
                cases.pop()
            elif mode == 'duplicate':
                cases[-1] = cases[0]
            elif mode == 'unexpected-pass':
                next(case for case in cases if case['name'] in CONTROL_FAILURES)['status'] = 'PASS'
            elif mode == 'unexpected-failure':
                cases[0]['status'] = 'FAIL'
            else:
                suite['misc']['crashed'] = 1
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                checked_control(report, self.log)

    def test_control_requires_actual_irq_assertions_without_kernel_faults(self):
        for text in (self.log.replace('before.armed', ''), self.log.replace('after.references', ''),
                     self.log.replace('f->arms == 3', 'f->arms == 2'),
                     self.log.replace('# wake_disarm_error_test:', '# wake_arm_error_test:'),
                     self.log + 'WARNING:', self.log + 'BUG:', self.log + 'Kernel panic'):
            with self.subTest(log=text[-50:]), self.assertRaises(ValueError):
                checked_control(self.report, text)


class WakeRunnerFreshness(unittest.TestCase):
    @contextmanager
    def cached_runner(self, *, prior=('test.log', 'results.json'), produced=(), failure='expected'):
        """Drive actual main; only source preparation and the managed executor are replaced."""
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            config_text = 'CONFIG_KUNIT=y\n'
            builder = dict(image='fixture-builder', platform='linux/amd64', jobs=1)
            metadata = dict(tree_sha256='a' * 64)
            lock = dict(linux=dict(tag='vfixture'), builder=builder)
            paths = ('tools/check-musb-restart-kunit.py', 'tools/musb_wake_kunit.py',
                     'tools/musb_restart_kunit.py', 'tools/kernel_sources.py',
                     'tools/kernel_candidates.py', 'tools/kernel_checks.py', 'tools/kernel-inputs.py',
                     'tools/managed_container.py', 'tools/docker-stage.py',
                     'tools/tests/test_musb_wake_kunit.py', 'kernel/tests/musb-wake-kunit.c',
                     'kernel/tests/musb-wake-kunit.config', 'build/sources.lock.json', 'Taskfile.yml')
            for name in paths:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture\n')
            (root / 'build/sources.lock.json').write_text(json.dumps(lock))
            (root / 'kernel/tests/musb-wake-kunit.config').write_text(config_text)
            (root / 'tools/kernel-inputs.py').write_text('def patches(): return []\ndef apply_queue(*args): pass\n')
            work = root / '.local/build/musb-wake-kunit-policy-ignored'
            identity = hashlib.sha256((metadata['tree_sha256'] + config_text + builder['image']).encode()).hexdigest()[:16]
            scratch = work / ('kernel-' + identity)
            output = scratch / 'output'
            output.mkdir(parents=True)
            (output / '.config').write_text(config_text)
            (output / 'linux').write_bytes(b'unchanged cached binary')
            counts = dict(tests=len(CASES), passed=len(CASES) - len(CONTROL_FAILURES),
                          failed=len(CONTROL_FAILURES), crashed=0, skipped=0, errors=0)
            report = dict(name='KUnit Test Group', arch='um', misc=counts, test_cases=[], sub_groups=[
                dict(name='musb-wake', arch='um', misc=counts, sub_groups=[], test_cases=[
                    dict(name=name, status='FAIL' if name in CONTROL_FAILURES else 'PASS') for name in CASES])])
            lines = ['musb-wake', *CASES]
            for name, assertions in CONTROL_ASSERTIONS.items():
                lines.extend(('# ' + name + ': EXPECTATION FAILED', *assertions, 'not ok 1 ' + name))
            payload = {'test.log': '\n'.join(lines).encode(), 'results.json': json.dumps(report).encode()}
            targets = {'test.log': output / 'test.log', 'results.json': scratch / 'results.json'}
            for name in prior:
                targets[name].write_bytes(payload[name])
            harness = SimpleNamespace(root=root, work=work, scratch=scratch, targets=targets,
                                      payload=payload, before_execution=None)
            identity = dict(schema=1, workspace='fixture-workspace', stage='musb-wake-kunit', run='a' * 32)
            terminal = dict(outcome='exited', exit_code=1, returncode=1, stop_requested=False,
                            job=identity, state=dict(Running=False, Status='exited', ExitCode=1,
                                                    OOMKilled=False, Error=''))
            observed = copy.deepcopy(terminal)
            if failure == 'stopped':
                observed['stop_requested'] = True
            elif failure == 'oom':
                observed['state']['OOMKilled'] = True
            elif failure == 'running':
                observed['state']['Running'] = True
            elif failure == 'wrong-result':
                observed['job']['run'] = 'b' * 32

            def execute(stage, arguments, attempt, *, timeout):
                attempt.mkdir(parents=True)
                harness.before_execution = {name: path.exists() for name, path in targets.items()}
                for name in produced:
                    targets[name].write_bytes(payload[name])
                if failure == 'unresolved':
                    raise RuntimeError('Managed run remains unresolved')
                # Both a compiler failure and an executed negative control use exit 1.
                raise runner.ManagedCommandFailure(identity, terminal)

            support = SimpleNamespace(__file__=str(root / 'tools/musb_wake_kunit.py'),
                test_patch=lambda *args, **kwargs: ('9999-fixture.patch', b'fixture'),
                checked_control=checked_control, CONTROL_FAILURES=CONTROL_FAILURES, LIMITS='host executor fixture')
            for name, value in (('ROOT', root), ('__file__', str(root / 'tools/check-musb-restart-kunit.py')),
                                ('archive_for', lambda lock: root / 'archive'),
                                ('include_candidates', lambda *args: []),
                                ('ensure_source', lambda *args, **kwargs: (root / 'source', {}, metadata)),
                                ('execute', execute), ('result_for', lambda receipt: (identity, observed, root)),
                                ('owns_active', lambda identity: failure == 'active-owner')):
                stack.enter_context(mock.patch.object(runner, name, value))
            stack.enter_context(mock.patch.object(runner.importlib, 'import_module', return_value=support))
            stack.enter_context(mock.patch.object(sys, 'argv', ['runner', '--suite', 'wake', '--wake-control', 'policy-ignored']))
            stack.enter_context(redirect_stdout(io.StringIO()))
            yield harness

    def test_failed_rebuild_rejects_stale_results_and_retains_every_prior_file(self):
        for prior in (('test.log', 'results.json'), ('test.log',), ('results.json',)):
            with self.subTest(prior=prior), self.cached_runner(prior=prior) as harness:
                with self.assertRaisesRegex(RuntimeError, 'current-execution'):
                    runner.main()
                self.assertEqual(harness.before_execution, {'test.log': False, 'results.json': False})
                self.assertFalse((harness.work / 'control-evidence.json').exists())
                retained = list((harness.scratch / 'previous-runs').iterdir())
                self.assertEqual(len(retained), 1)
                self.assertEqual({path.name for path in retained[0].iterdir()}, set(prior))
                for name in prior:
                    self.assertEqual((retained[0] / name).read_bytes(), harness.payload[name])

    def test_partial_new_execution_results_are_inconclusive(self):
        for produced in (('test.log',), ('results.json',)):
            with self.subTest(produced=produced), self.cached_runner(produced=produced) as harness:
                with self.assertRaisesRegex(RuntimeError, 'current-execution'):
                    runner.main()
                self.assertFalse((harness.work / 'control-evidence.json').exists())

    def test_new_identical_results_are_valid_without_content_inequality(self):
        with self.cached_runner(produced=('test.log', 'results.json')) as harness:
            runner.main()
            self.assertEqual(harness.before_execution, {'test.log': False, 'results.json': False})
            evidence = json.loads((harness.work / 'control-evidence.json').read_text())
            for name in ('test.log', 'results.json'):
                self.assertEqual(evidence['artifacts'][name], hashlib.sha256(harness.payload[name]).hexdigest())

    def test_only_expected_original_failure_after_released_ownership_can_recover(self):
        for failure in ('unresolved', 'active-owner', 'stopped', 'oom', 'running', 'wrong-result'):
            with self.subTest(failure=failure), self.cached_runner(
                    produced=('test.log', 'results.json'), failure=failure) as harness:
                with self.assertRaises(RuntimeError):
                    runner.main()
                self.assertFalse((harness.work / 'control-evidence.json').exists())


if __name__ == '__main__':
    unittest.main()
