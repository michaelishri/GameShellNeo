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
    def test_guest_failure_uses_managed_identity_and_retains_original_artifacts(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, 'ROOT', Path(directory)):
            scratch = Path(directory) / 'scratch'
            kernel = scratch / 'output/arch/arm/boot/zImage'
            kernel.parent.mkdir(parents=True)
            kernel.write_bytes(b'original kernel')
            (scratch / 'output/.config').write_text('CONFIG_SMP=y\n')
            (scratch / 'output/test.log').write_text('incomplete original guest log\n')
            def execute(stage, arguments, destination, *, timeout):
                self.assertEqual(stage, 'callback-smp')
                self.assertFalse(any(arg.startswith('--name') for arg in arguments))
                self.assertIn('--network=none', arguments)
                self.assertIn('--entrypoint=timeout', arguments)
                self.assertEqual(timeout, 3660)
                raise subprocess.TimeoutExpired(arguments, timeout)
            with patch.object(runner, 'run_managed', side_effect=execute):
                with self.assertRaises(subprocess.TimeoutExpired):
                    runner.execute('sha256:' + 'a' * 64, Path(directory) / 'source', scratch,
                                   dict(cross_compile='arm-linux-gnueabihf-', jobs=1))
            attempt, = (scratch / 'attempts').iterdir()
            artifacts = json.loads((attempt / 'available-artifacts.json').read_text())
            self.assertEqual(set(artifacts), {'zImage', 'config', 'test.log'})
            kernel.write_bytes(b'next attempt kernel')
            self.assertEqual((attempt / 'zImage').read_bytes(), b'original kernel')
            self.assertEqual(artifacts['zImage'], runner.sha256(attempt / 'zImage'))
            self.assertFalse((scratch / 'evidence.json').exists())


if __name__ == '__main__':
    unittest.main()
