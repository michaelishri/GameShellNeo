"""Guard the source boundary and reject inconclusive actual DPM executions."""
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
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from kernel_candidates import include_candidates
from musb_wake_dpm_kunit import (CASES, CONTROL_ASSERTIONS, CONTROL_CASE, PATCHES,
                                 checked_cases, checked_control, selected_patches)

spec = importlib.util.spec_from_file_location('dpm_test_inputs', TOOLS / 'kernel-inputs.py')
production = importlib.util.module_from_spec(spec)
spec.loader.exec_module(production)
runner_spec = importlib.util.spec_from_file_location(
    'dpm_runner_under_test', TOOLS / 'check-musb-wake-dpm-kunit.py')
runner = importlib.util.module_from_spec(runner_spec)
runner_spec.loader.exec_module(runner)


def report(control=False):
    counts = dict(tests=len(CASES), passed=len(CASES) - int(control), failed=int(control),
                  crashed=0, skipped=0, errors=0)
    return dict(name='KUnit Test Group', arch='um', misc=counts, test_cases=[], sub_groups=[
        dict(name='musb-wake-dpm', arch='um', misc=counts.copy(), sub_groups=[], test_cases=[
            dict(name=name, status='FAIL' if control and name == CONTROL_CASE else 'PASS')
            for name in CASES])])


def control_log():
    lines = ['musb-wake-dpm', *CASES]
    for expression, values in CONTROL_ASSERTIONS.items():
        lines.extend(('# ' + CONTROL_CASE + ': EXPECTATION FAILED',
                      'Expected ' + expression + ', but', *values))
    lines.append('not ok 2 ' + CONTROL_CASE)
    return '\n'.join(lines)


class ProfileBoundary(unittest.TestCase):
    def test_exact_profile_leaves_production_and_retirement_independent(self):
        base = list(production.patches())
        original = list(base)
        queue = include_candidates(ROOT, 'musb-wake-startup', base)
        self.assertEqual(tuple(name for name, _ in selected_patches(queue)), PATCHES)
        self.assertEqual(base, original)
        self.assertEqual(len(queue), len(base) + 2)

    def test_incomplete_duplicate_reordered_and_composed_profiles_rejected(self):
        queue = include_candidates(ROOT, 'musb-wake-startup', list(production.patches()))
        selected = selected_patches(queue)
        for wrong in (selected[:-1], selected + selected[-1:], list(reversed(selected)),
                      queue + [('0061-mpfs-parent-resource-lifetime.patch', b'')],
                      queue + [('0039-musb-core-irq-retirement.patch', b'')]):
            with self.subTest(names=[name for name, _ in wrong]), self.assertRaises(ValueError):
                selected_patches(wrong)


class EvidenceBoundary(unittest.TestCase):
    def test_complete_positive_and_control_are_distinct(self):
        log = 'musb-wake-dpm\n' + '\n'.join(CASES)
        self.assertEqual(len(checked_cases(report(), log)), len(CASES))
        self.assertEqual(len(checked_control(report(True), control_log())), len(CASES))
        with self.assertRaises(ValueError):
            checked_cases(report(True), control_log())
        with self.assertRaises(ValueError):
            checked_control(report(), log)

    def test_missing_duplicate_extra_or_crashed_case_is_inconclusive(self):
        for control, checker in ((False, checked_cases), (True, checked_control)):
            for mode in ('missing', 'duplicate', 'extra', 'crash', 'wrong-status'):
                record = report(control)
                cases = record['sub_groups'][0]['test_cases']
                if mode == 'missing':
                    cases.pop()
                elif mode == 'duplicate':
                    cases[-1] = cases[0]
                elif mode == 'extra':
                    cases.append(dict(name='unowned_test', status='PASS'))
                elif mode == 'crash':
                    record['misc']['crashed'] = 1
                else:
                    cases[0]['status'] = 'FAIL'
                with self.subTest(control=control, mode=mode), self.assertRaises(ValueError):
                    checker(record, control_log())

    def test_control_binds_exact_assertions_values_and_case(self):
        valid = control_log()
        wrong_logs = (valid.replace('f->calls.prepare == 0', 'f->calls.prepare == 1'),
                      valid.replace('walk->after_end.armed == 0', 'walk->after_end.armed == 1'),
                      valid.replace('# ' + CONTROL_CASE + ':', '# dpm_policy_disabled_test:', 1),
                      valid + '\n# ' + CONTROL_CASE + ': EXPECTATION FAILED\nExpected other == 1, but\nother == 0',
                      valid.replace('Expected f->calls.noirq == 1U, but', 'Expected other == 1U, but'))
        for log in wrong_logs:
            with self.subTest(tail=log[-100:]), self.assertRaises(ValueError):
                checked_control(report(True), log)

    def test_kernel_diagnostics_reject_both_paths(self):
        for diagnostic in ('WARNING:', 'BUG:', 'Kernel panic', 'possible circular locking',
                           'sleeping function called', 'INFO: task worker blocked for more than'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                checked_control(report(True), control_log() + '\n' + diagnostic)
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                checked_cases(report(), 'musb-wake-dpm\n' + '\n'.join(CASES) + '\n' + diagnostic)


class RunnerAdmission(unittest.TestCase):
    @contextmanager
    def cached_runner(self, *, control=True, prior=('test.log', 'results.json'),
                      produced=(), failure='expected'):
        """Execute actual main with disposable inputs and an observed executor boundary."""
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            config_text = 'CONFIG_KUNIT=y\n'
            builder = dict(image='fixture-builder', platform='linux/amd64', jobs=1)
            metadata = dict(tree_sha256='a' * 64)
            lock = dict(linux=dict(tag='vfixture'), builder=builder)
            paths = ('tools/check-musb-wake-dpm-kunit.py', 'tools/musb_wake_dpm_kunit.py',
                     'tools/musb_restart_kunit.py', 'tools/musb_irq_checks.py',
                     'tools/kernel_sources.py', 'tools/kernel_candidates.py',
                     'tools/kernel_checks.py', 'tools/kernel-inputs.py',
                     'tools/managed_container.py', 'tools/docker-stage.py',
                     'tools/tests/test_musb_wake_dpm_kunit.py', 'Taskfile.yml',
                     'kernel/tests/musb-wake-dpm-kunit.c',
                     'kernel/tests/musb-wake-dpm-kunit.config', 'build/sources.lock.json')
            for name in paths:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture\n')
            (root / 'build/sources.lock.json').write_text(json.dumps(lock))
            (root / 'kernel/tests/musb-wake-dpm-kunit.config').write_text(config_text)
            (root / 'tools/kernel-inputs.py').write_text(
                'def patches(): return []\ndef apply_queue(*args): pass\n')
            work = root / '.local/build' / ('musb-wake-dpm-kunit' +
                    ('-callbacks-unregistered' if control else ''))
            key = hashlib.sha256((metadata['tree_sha256'] + config_text +
                                  builder['image']).encode()).hexdigest()[:16]
            scratch = work / ('kernel-' + key)
            output = scratch / 'output'
            output.mkdir(parents=True)
            (output / '.config').write_text(config_text)
            (output / 'linux').write_bytes(b'unchanged cached DPM binary')
            payload = {'test.log': (control_log() if control else
                       'musb-wake-dpm\n' + '\n'.join(CASES)).encode(),
                       'results.json': json.dumps(report(control)).encode()}
            targets = {'test.log': output / 'test.log', 'results.json': scratch / 'results.json'}
            for name in prior:
                targets[name].write_bytes(payload[name])
            identity = dict(schema=1, workspace='fixture-workspace',
                            stage='musb-wake-dpm-kunit', run='a' * 32)
            exit_code = 1 if control or failure == 'unexpected-positive' else 0
            terminal = dict(outcome='exited', exit_code=exit_code, returncode=exit_code,
                            stop_requested=False, job=identity,
                            state=dict(Running=False, Status='exited', ExitCode=exit_code,
                                       OOMKilled=False, Error=''))
            observed = copy.deepcopy(terminal)
            observed_identity = copy.deepcopy(identity)
            if failure == 'stopped':
                observed['stop_requested'] = True
            elif failure == 'oom':
                observed['state']['OOMKilled'] = True
            elif failure == 'running':
                observed['state']['Running'] = True
            elif failure == 'wrong-result':
                observed['job']['run'] = 'b' * 32
            elif failure == 'wrong-identity':
                observed_identity['run'] = 'b' * 32
            harness = SimpleNamespace(work=work, scratch=scratch, payload=payload,
                                      before_execution=None, result_observations=0)

            def execute(stage, arguments, attempt, *, timeout):
                attempt.mkdir(parents=True)
                harness.before_execution = {name: path.exists() for name, path in targets.items()}
                for name in produced:
                    targets[name].write_bytes(payload[name])
                if failure == 'unresolved':
                    raise RuntimeError('Managed DPM run remains unresolved')
                if exit_code:
                    raise runner.ManagedCommandFailure(identity, terminal)
                return terminal

            def result_for(receipt):
                harness.result_observations += 1
                return observed_identity, observed, root

            support = SimpleNamespace(__file__=str(root / 'tools/musb_wake_dpm_kunit.py'),
                test_patch=lambda *args, **kwargs: ('9999-fixture.patch', b'fixture'),
                checked_control=checked_control, checked_cases=checked_cases,
                CONTROL_CASE=CONTROL_CASE, CONTROL_ASSERTIONS=CONTROL_ASSERTIONS,
                LIMITS='host executor fixture')
            for name, value in (('ROOT', root),
                                ('__file__', str(root / 'tools/check-musb-wake-dpm-kunit.py')),
                                ('archive_for', lambda lock: root / 'archive'),
                                ('include_candidates', lambda *args: []),
                                ('ensure_source', lambda *args, **kwargs: (root / 'source', {}, metadata)),
                                ('execute', execute), ('result_for', result_for), ('support', support),
                                ('owns_active', lambda identity: failure == 'active-owner')):
                stack.enter_context(mock.patch.object(runner, name, value))
            args = ['runner', '--control', 'callbacks-unregistered'] if control else ['runner']
            stack.enter_context(mock.patch.object(sys, 'argv', args))
            stack.enter_context(redirect_stdout(io.StringIO()))
            yield harness

    def test_failed_rebuild_cannot_reuse_any_prior_result(self):
        for control in (False, True):
            for prior in (('test.log', 'results.json'), ('test.log',), ('results.json',)):
                with self.subTest(control=control, prior=prior), self.cached_runner(
                        control=control, prior=prior) as harness:
                    with self.assertRaisesRegex(RuntimeError, 'current-execution'):
                        runner.main()
                    self.assertEqual(harness.before_execution,
                                     {'test.log': False, 'results.json': False})
                    self.assertFalse(list(harness.work.glob('*evidence.json')))
                    retained = list((harness.scratch / 'previous-runs').iterdir())
                    self.assertEqual(len(retained), 1)
                    self.assertEqual({path.name for path in retained[0].iterdir()}, set(prior))
                    for name in prior:
                        self.assertEqual((retained[0] / name).read_bytes(), harness.payload[name])

    def test_partial_current_results_are_inconclusive(self):
        for produced in (('test.log',), ('results.json',)):
            with self.subTest(produced=produced), self.cached_runner(produced=produced) as harness:
                with self.assertRaisesRegex(RuntimeError, 'current-execution'):
                    runner.main()
                self.assertFalse(list(harness.work.glob('*evidence.json')))

    def test_identical_new_outputs_are_valid_on_positive_and_control_routes(self):
        for control in (False, True):
            with self.subTest(control=control), self.cached_runner(
                    control=control, produced=('test.log', 'results.json')) as harness:
                runner.main()
                self.assertEqual(harness.before_execution,
                                 {'test.log': False, 'results.json': False})
                name = 'control-evidence.json' if control else 'evidence.json'
                evidence = json.loads((harness.work / name).read_text())
                for artifact in ('test.log', 'results.json'):
                    self.assertEqual(evidence['artifacts'][artifact],
                                     hashlib.sha256(harness.payload[artifact]).hexdigest())

    def test_only_original_expected_failure_after_ownership_release_can_recover(self):
        for failure in ('unresolved', 'active-owner', 'stopped', 'oom', 'running',
                        'wrong-result', 'wrong-identity'):
            with self.subTest(failure=failure), self.cached_runner(
                    produced=('test.log', 'results.json'), failure=failure) as harness:
                with self.assertRaises(RuntimeError):
                    runner.main()
                self.assertFalse(list(harness.work.glob('*evidence.json')))
                if failure == 'unresolved':
                    self.assertEqual(harness.result_observations, 0)

    def test_positive_route_never_recovers_expected_nonzero(self):
        with self.cached_runner(control=False, produced=('test.log', 'results.json'),
                                failure='unexpected-positive') as harness:
            with self.assertRaises(runner.ManagedCommandFailure):
                runner.main()
            self.assertEqual(harness.result_observations, 0)
            self.assertFalse(list(harness.work.glob('*evidence.json')))


if __name__ == '__main__':
    unittest.main()
