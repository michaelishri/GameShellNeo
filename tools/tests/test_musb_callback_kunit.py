"""Reject a superficially green result with missing SMP callback evidence."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from musb_callback_kunit import CASES, checked_cases

spec = importlib.util.spec_from_file_location('callback_runner',
    Path(__file__).resolve().parents[1] / 'check-musb-callback-kunit.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CallbackEvidenceTest(unittest.TestCase):
    def setUp(self):
        counts = dict(tests=len(CASES), passed=len(CASES), failed=0, crashed=0, skipped=0, errors=0)
        self.report = dict(name='KUnit Test Group', arch='arm', misc=counts, test_cases=[],
            sub_groups=[dict(name='musb-callback-smp', arch='arm', misc=counts.copy(), sub_groups=[],
                             test_cases=[dict(name=name, status='PASS') for name in CASES])])
        self.log = '\n'.join(f'SMP callback=1 unbind=2 observer=0 online=4 kind={kind} context={context} drained=0 completions=1'
                             for kind in range(5) for context in range(3))
        self.log += ('\nSMP callback=1 unbind=2 observer=0 online=4 kind=0 context=3 drained=0 completions=1'
                     '\nSecond callback CPU=3 remaining after first=1'
                     '\nRebind cycles=4 admitted callbacks=20'
                     '\nUnstarted actor: cleanup unregister=0')
        self.log += '\nmusb-callback-smp\n' + '\n'.join(
            f'ok {index} {name}' for index, name in enumerate(CASES, 1))

    def test_complete_contract(self):
        self.assertEqual(len(checked_cases(self.report, self.log)), 18)

    def test_missing_duplicate_failed_or_wrong_arch(self):
        changes = [lambda r: r.update(arch='um'),
                   lambda r: r['misc'].update(skipped=1),
                   lambda r: r['sub_groups'][0]['test_cases'].pop(),
                   lambda r: r['sub_groups'][0]['test_cases'][0].update(status='SKIP'),
                   lambda r: r['sub_groups'][0]['test_cases'][0].update(name=CASES[1]),
                   lambda r: r['sub_groups'][0].update(arch='um')]
        for change in changes:
            report = copy.deepcopy(self.report)
            change(report)
            with self.assertRaises(ValueError):
                checked_cases(report, self.log)

    def test_missing_or_false_concurrency_and_kernel_failures(self):
        logs = [self.log.replace('unbind=2', 'unbind=1', 1),
                self.log.replace('online=4', 'online=1', 1),
                self.log.replace('drained=0', 'drained=1', 1),
                self.log.replace('context=2', 'context=1', 1),
                self.log.replace('completions=1', 'completions=0', 1),
                self.log.replace('remaining after first=1', 'remaining after first=0'),
                self.log.replace('admitted callbacks=20', 'admitted callbacks=0'),
                self.log.replace('Unstarted actor: cleanup unregister=0', ''),
                self.log.replace('ok 1 resume_irq', ''),
                '\n'.join(self.log.splitlines()[1:]),
                self.log + '\n' + self.log.splitlines()[0],
                self.log + '\nBUG: KASAN: slab-use-after-free',
                self.log + '\nWARNING: possible circular locking dependency detected',
                self.log + '\nnot ok 1 resume_irq']
        for log in logs:
            with self.assertRaises(ValueError):
                checked_cases(self.report, log)


class CallbackRunnerCleanupTest(unittest.TestCase):
    def test_guest_timeout_retires_only_owned_container(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, 'ROOT', Path(directory)):
            scratch = Path(directory) / 'scratch'
            scratch.mkdir()
            kernel = scratch / 'output/arch/arm/boot/zImage'
            kernel.parent.mkdir(parents=True)
            kernel.write_bytes(b'original kernel')
            (scratch / 'output/.config').write_text('CONFIG_SMP=y\n')
            (scratch / 'output/test.log').write_text('incomplete original guest log\n')
            commands = []

            def run(command, **kwargs):
                commands.append(command)
                if command[1] == 'run':
                    raise subprocess.TimeoutExpired(command, 3660)
                if command[1] == 'inspect':
                    return subprocess.CompletedProcess(command, 0,
                        json.dumps(dict(Running=len(commands) == 2,
                                        Status='running' if len(commands) == 2 else 'exited')), '')
                return subprocess.CompletedProcess(command, 0, '', '')

            with patch.object(runner.subprocess, 'run', side_effect=run):
                with self.assertRaises(subprocess.TimeoutExpired):
                    runner.execute('sha256:' + 'a' * 64, Path(directory) / 'source', scratch,
                                   dict(cross_compile='arm-linux-gnueabihf-', jobs=1))
            attempt, = (scratch / 'attempts').iterdir()
            identity = json.loads((attempt / 'container.json').read_text())['name']
            self.assertEqual([c[1] for c in commands], ['run', 'inspect', 'stop', 'inspect', 'rm'])
            self.assertTrue(all(c[-1] == identity for c in commands[1:]))
            self.assertTrue(json.loads((attempt / 'cleanup.json').read_text())['removed'])
            observed = json.loads((attempt / 'interrupted-state.json').read_text())
            self.assertTrue(json.loads(observed['stdout'])['Running'])
            artifacts = json.loads((attempt / 'available-artifacts.json').read_text())
            self.assertEqual(set(artifacts), {'zImage', 'config', 'test.log'})
            kernel.write_bytes(b'next attempt kernel')
            self.assertEqual((attempt / 'zImage').read_bytes(), b'original kernel')
            self.assertEqual(artifacts['zImage'], runner.sha256(attempt / 'zImage'))
            self.assertFalse((scratch / 'evidence.json').exists())

    def test_unknown_or_running_container_is_not_removed(self):
        for result in (subprocess.CompletedProcess([], 1, '', 'unavailable'),
                       subprocess.CompletedProcess([], 0, '{"Running": true}', '')):
            with tempfile.TemporaryDirectory() as directory, patch.object(runner, 'ROOT', Path(directory)):
                scratch = Path(directory) / 'scratch'
                scratch.mkdir()
                commands = []

                def run(command, **kwargs):
                    commands.append(command)
                    if command[1] == 'run':
                        raise subprocess.TimeoutExpired(command, 3660)
                    if command[1] == 'stop':
                        raise subprocess.TimeoutExpired(command, 10)
                    if command[1] == 'inspect':
                        return result
                    self.fail('Unknown or live container was removed')

                with patch.object(runner.subprocess, 'run', side_effect=run):
                    with self.assertRaises(RuntimeError):
                        runner.execute('sha256:' + 'a' * 64, Path(directory) / 'source', scratch,
                                       dict(cross_compile='arm-linux-gnueabihf-', jobs=1))
                attempt, = (scratch / 'attempts').iterdir()
                self.assertEqual([c[1] for c in commands], ['run', 'inspect', 'stop', 'inspect'])
                self.assertFalse(json.loads((attempt / 'cleanup.json').read_text())['removed'])


if __name__ == '__main__':
    unittest.main()
