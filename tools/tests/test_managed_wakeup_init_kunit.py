"""Reject stale, unrelated, incomplete and unresolved managed-wakeup results."""
from contextlib import contextmanager, ExitStack, redirect_stdout
import copy
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
from managed_wakeup_init_kunit import CASES, CONTROL_FAILURES, STEM, checked_cases, checked_control, test_patch
from managed_wakeup_init_source import PATCH
import managed_wakeup_init_kunit as support_module
from kernel_sources import digest, inventory

spec = importlib.util.spec_from_file_location('managed_wakeup_runner', TOOLS / 'check-managed-wakeup-init-kunit.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

spec = importlib.util.spec_from_file_location('managed_wakeup_object_runner', TOOLS / 'check-managed-wakeup-init.py')
object_runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(object_runner)


def report(control=False):
    counts = dict(tests=5, passed=3 if control else 5, failed=2 if control else 0,
                  crashed=0, skipped=0, errors=0)
    return dict(name='KUnit Test Group', arch='um', misc=counts, test_cases=[], sub_groups=[
        dict(name=STEM, arch='um', misc=counts.copy(), sub_groups=[], test_cases=[
            dict(name=name, status='FAIL' if control and name in CONTROL_FAILURES else 'PASS')
            for name in CASES])])


def log(control=False):
    # Predeclared exact rendering from pinned KUnit unary/binary formatters.
    # This is a validator fixture, not an executed-kernel receipt.
    lines = ['KTAP version 1', '# Subtest: ' + STEM]
    observations = (
        'result=0 source_hits=0 action_hits=0 created=1 freed=1',
        ('result=0 action=1 capable=0' if control else 'result=-12 action=0 capable=1') +
        ' source_hits=1 action_hits=0 created=0 freed=0',
        ('result=0 action=1 source=0 id=0 capable=0 source_hits=0 action_hits=0 created=2 freed=2' if control else
         'result=-17 action=0 source=1 id=1 capable=1 source_hits=0 action_hits=0 created=2 freed=1'),
        'result=-12 source_hits=0 action_hits=1 created=1 freed=1',
        'result=0 source_hits=0 action_hits=0 created=1 freed=1')
    for index, case in enumerate(CASES, 1):
        for name, actual, wanted in CONTROL_FAILURES.get(case, ()) if control else ():
            lines.append(f'# {case}: EXPECTATION FAILED at drivers/base/power/managed-wakeup-init-kunit.c:100')
            if name == 'result':
                lines.extend((f'Expected result == {wanted}, but', 'result == 0 (0x0)'))
            else:
                lines.append(f'Expected {name} to be {"true" if wanted else "false"}, '
                             f'but is {"true" if actual else "false"}')
        lines.extend((f'# {case}: ownership {observations[index - 1]}',
                      f'{"not ok" if control and case in CONTROL_FAILURES else "ok"} {index} {case}'))
    return '\n'.join(lines) + '\n'


class KernelOutcomeAdmission(unittest.TestCase):
    def test_five_successes_and_exact_eight_assertion_control_are_separate(self):
        self.assertEqual(len(checked_cases(report(), log())), 5)
        self.assertEqual(len(checked_control(report(True), log(True))), 5)
        with self.assertRaises(ValueError):
            checked_cases(report(True), log(True))
        with self.assertRaises(ValueError):
            checked_control(report(), log())

    def test_exact_assertion_format_values_boundaries_and_ownership(self):
        good = log(True)
        for bad in (good.replace('result == 0 (0x0)', 'result == -5 (0xfffffffffffffffb)', 1),
                    good.replace('result == 0 (0x0)', 'result == 0 (0x1)', 1),
                    good.replace('Expected result == -12', 'Expected result == -ENOMEM', 1),
                    good.replace('Expected action_present to be false', 'Expected different to be false', 1),
                    good.replace('but is true', 'but is false', 1),
                    good.replace('EXPECTATION FAILED', 'ASSERTION FAILED', 1),
                    good.replace('power/managed-wakeup-init-kunit.c:', 'power/other.c:', 1),
                    good.replace('source_hits=1', 'source_hits=0', 1),
                    good.replace('created=2 freed=2', 'created=2 freed=1', 1),
                    good + '# managed_wakeup_success_test: EXPECTATION FAILED at other.c:10\n',
                    good.replace('Expected action_present to be false, but is true\n', '', 1)):
            with self.subTest(log=bad[-120:]), self.assertRaises(ValueError):
                checked_control(report(True), bad)

    def test_missing_duplicate_reordered_skipped_or_extra_suite_is_inconclusive(self):
        for mode in ('missing', 'duplicate', 'reordered', 'skip', 'crashed', 'wrong-failure', 'extra-suite'):
            value = report(True)
            cases = value['sub_groups'][0]['test_cases']
            if mode == 'missing':
                cases.pop()
            elif mode == 'duplicate':
                cases[-1] = cases[0]
            elif mode == 'reordered':
                cases.reverse()
            elif mode == 'skip':
                cases[-1]['status'] = 'SKIP'
            elif mode == 'crashed':
                value['misc']['crashed'] = 1
            elif mode == 'wrong-failure':
                cases[0]['status'] = 'FAIL'
            else:
                value['sub_groups'].append(copy.deepcopy(value['sub_groups'][0]))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                checked_control(value, log(True))
        for diagnostic in ('WARNING:', 'BUG:', 'possible circular locking', 'suspicious RCU',
                           'sleeping function called', 'Kernel panic',
                           'INFO: task worker blocked for more than 120 seconds'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                checked_control(report(True), log(True) + diagnostic)

    def test_candidate_must_be_explicit_and_last_once(self):
        for queue in ([], [('other.patch', b'')], [(Path(PATCH).name, b'')] * 2,
                      [(Path(PATCH).name, b''), ('other.patch', b'')]):
            with self.subTest(queue=queue), self.assertRaisesRegex(ValueError, 'Exactly one'):
                test_patch(None, None, None, queue, None, None)


class VerifiedSourceAdmission(unittest.TestCase):
    @contextmanager
    def source(self):
        with tempfile.TemporaryDirectory() as temporary:
            spec = dict(schema=1, linux=dict(tag='fixture'), patches=[
                dict(name=f'{index}.patch', sha256='a' * 64) for index in range(35)])
            entry = Path(temporary) / ('source-' + digest(spec))
            source = entry / 'source'
            source.mkdir(parents=True)
            (source / 'body.c').write_text('actual fixture payload\n')
            metadata = entry / 'metadata.json'
            metadata.write_text(json.dumps(dict(spec=spec, tree_sha256=digest(inventory(source)))))
            with mock.patch.object(support_module, 'QUALIFIED_SOURCE_ID', digest(spec)):
                yield source, spec, metadata

    def test_matching_full_inventory_is_read_without_cache_mutation(self):
        with self.source() as (source, spec, metadata):
            before = metadata.read_bytes(), inventory(source), {p.name for p in source.parent.iterdir()}
            path, entries, observed = support_module.verified_source(source, spec)
            self.assertEqual(path, source)
            self.assertEqual(entries, before[1])
            self.assertEqual(observed, json.loads(before[0]))
            self.assertEqual((metadata.read_bytes(), inventory(source),
                              {p.name for p in source.parent.iterdir()}), before)

    def test_changed_body_spec_metadata_alias_and_extra_entries_fail_closed(self):
        for mode in ('body', 'spec', 'metadata', 'alias', 'extra', 'wrong-count'):
            with self.subTest(mode=mode), self.source() as (source, spec, metadata):
                path = source
                if mode == 'body':
                    (source / 'body.c').write_text('changed payload\n')
                elif mode == 'spec':
                    spec['linux']['tag'] = 'different'
                elif mode == 'metadata':
                    metadata.write_text('{}')
                elif mode == 'alias':
                    path = source.parent / 'alias'
                    path.symlink_to(source)
                elif mode == 'extra':
                    (source.parent / 'unexpected').write_text('not accepted')
                else:
                    spec['patches'].pop()
                before = metadata.read_bytes(), inventory(source)
                with self.assertRaises(ValueError):
                    support_module.verified_source(path, spec)
                self.assertEqual((metadata.read_bytes(), inventory(source)), before)

    def test_explicit_source_rejected_before_native_or_host_preparation(self):
        for flags in ([], ['--host-only']):
            with self.subTest(flags=flags), mock.patch.object(sys, 'argv',
                    ['runner', *flags, '--verified-source', '/unqualified/source']), \
                    mock.patch.object(object_runner, 'archive_for') as archive, \
                    redirect_stdout(io.StringIO()), mock.patch('sys.stderr', io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    object_runner.main()
                self.assertEqual(failure.exception.code, 2)
                archive.assert_not_called()


class RunnerAdmission(unittest.TestCase):
    @contextmanager
    def executor(self, *, prior=('test.log', 'results.json'), produced=(), outcome='expected'):
        """Drive real maintained main; model only source/executor boundaries."""
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            builder = dict(image='fixture-builder', platform='linux/amd64', jobs=1)
            metadata = dict(tree_sha256='b' * 64, spec=dict(patches=[]))
            config_text = 'CONFIG_KUNIT=y\n'
            paths = ('tools/check-managed-wakeup-init-kunit.py', 'tools/managed_wakeup_init_kunit.py',
                'tools/managed_wakeup_init_source.py', 'tools/musb_restart_kunit.py', 'tools/musb_irq_checks.py',
                'tools/kernel_checks.py', 'tools/kernel_sources.py', 'tools/kernel-inputs.py',
                'tools/kernel_candidates.py', 'tools/managed_container.py', 'tools/docker-stage.py',
                'tools/tests/test_managed_wakeup_init_kunit.py', 'build/sources.lock.json', 'Taskfile.yml',
                'kernel/tests/managed-wakeup-init-kunit.config', 'kernel/tests/managed-wakeup-init-kunit.c',
                'kernel/tests/managed-wakeup-init-kunit.h', PATCH)
            for name in paths:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture\n')
            (root / 'build/sources.lock.json').write_text(json.dumps(dict(linux=dict(tag='vfixture'), builder=builder)))
            (root / 'kernel/tests/managed-wakeup-init-kunit.config').write_text(config_text)
            base = root / '.local/build/managed-wakeup-init-kernel'
            key = hashlib.sha256((metadata['tree_sha256'] + config_text + builder['image']).encode()).hexdigest()[:16]
            scratch = base / ('uml-' + key)
            output = scratch / 'output'
            output.mkdir(parents=True)
            (output / '.config').write_text(config_text + 'CONFIG_NEO_MANAGED_WAKEUP_RETURN_IGNORED=y\n')
            (output / 'linux').write_bytes(b'fixture kernel')
            payload = {'test.log': log(True).encode(), 'results.json': json.dumps(report(True)).encode()}
            targets = {'test.log': output / 'test.log', 'results.json': scratch / 'results.json'}
            for name in prior:
                targets[name].write_bytes(payload[name])
            identity = dict(schema=1, workspace='fixture-workspace', stage=STEM + '-kunit', run='a' * 32)
            terminal = dict(outcome='exited', exit_code=1, returncode=1, stop_requested=False, job=identity,
                            state=dict(Running=False, Status='exited', ExitCode=1, OOMKilled=False, Error=''))
            observed = copy.deepcopy(terminal)
            if outcome == 'stopped':
                observed['stop_requested'] = True
            elif outcome == 'oom':
                observed['state']['OOMKilled'] = True
            elif outcome == 'running':
                observed['state']['Running'] = True
            elif outcome == 'wrong-result':
                observed['job']['run'] = 'b' * 32
            f = SimpleNamespace(base=base, scratch=scratch, payload=payload, before_execution=None)

            def execute(stage, arguments, attempt, *, timeout):
                self.assertIsNone(timeout)
                attempt.mkdir(parents=True)
                f.before_execution = {name: path.exists() for name, path in targets.items()}
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

            support = SimpleNamespace(__file__=str(root / 'tools/managed_wakeup_init_kunit.py'), STEM=STEM,
                kernel_source=lambda *args: (base, root / 'source', metadata), resources=lambda *args: {},
                production_pins=lambda *args: {},
                checked_control=checked_control, LIMITS='host runner fixture')
            for name, value in (('ROOT', root), ('__file__', str(root / 'tools/check-managed-wakeup-init-kunit.py')),
                ('archive_for', lambda lock: root / 'archive'), ('support', support), ('execute', execute),
                ('result_for', lambda receipt: (identity, observed, root)),
                ('owns_active', lambda identity: outcome == 'active-owner')):
                stack.enter_context(mock.patch.object(runner, name, value))
            stack.enter_context(mock.patch.object(sys, 'argv', ['runner', '--control', 'return-ignored']))
            stack.enter_context(redirect_stdout(io.StringIO()))
            yield f

    def test_stale_and_partial_cached_results_cannot_qualify_failed_rebuild(self):
        for prior in (('test.log', 'results.json'), ('test.log',), ('results.json',)):
            for produced in ((), ('test.log',), ('results.json',)):
                with self.subTest(prior=prior, produced=produced), self.executor(
                        prior=prior, produced=produced) as f:
                    with self.assertRaisesRegex(RuntimeError, 'current-execution'):
                        runner.main()
                    self.assertEqual(f.before_execution, {'test.log': False, 'results.json': False})
                    self.assertFalse((f.base / 'control-evidence.json').exists())
                    history = list((f.scratch / 'previous-runs').iterdir())
                    self.assertEqual(len(history), 1)
                    for name in prior:
                        self.assertEqual((history[0] / name).read_bytes(), f.payload[name])

    def test_fresh_outputs_and_exact_released_raw1_qualify(self):
        with self.executor(produced=('test.log', 'results.json')) as f:
            runner.main()
            self.assertEqual(f.before_execution, {'test.log': False, 'results.json': False})
            evidence = json.loads((f.base / 'control-evidence.json').read_text())
            self.assertEqual(evidence['managed_result']['exit_code'], 1)
            self.assertEqual(len(evidence['expected_assertions']), 2)
            for name in f.payload:
                self.assertEqual(evidence['artifacts'][name], hashlib.sha256(f.payload[name]).hexdigest())

    def test_normal_zero_unresolved_active_or_nonoriginal_result_refuses(self):
        for outcome in ('zero', 'unresolved', 'active-owner', 'stopped', 'oom', 'running', 'wrong-result'):
            with self.subTest(outcome=outcome), self.executor(
                    produced=('test.log', 'results.json'), outcome=outcome) as f:
                with self.assertRaises(RuntimeError):
                    runner.main()
                self.assertFalse((f.base / 'control-evidence.json').exists())


if __name__ == '__main__':
    unittest.main()
