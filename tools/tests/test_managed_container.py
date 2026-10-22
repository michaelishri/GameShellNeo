"""Exercise durable result, timeout and successor-ownership boundaries."""
from contextlib import nullcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import managed_container as managed

spec = importlib.util.spec_from_file_location('managed_stage_tests', TOOLS / 'docker-stage.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class ManagedResults(unittest.TestCase):
    def exercise(self, mode):
        with tempfile.TemporaryDirectory() as temporary, patch.object(managed, 'ROOT', Path(temporary)):
            root = Path(temporary)
            destination = root / '.local/attempt'
            run = 'a' * 32
            identity = dict(schema=1, workspace=hashlib.sha256(str(root).encode()).hexdigest()[:20],
                            stage='fixture', run=run)
            directory = root / '.local/build/container-stages' / run
            active = root / '.local/build/container-active.json'
            commands = []

            def terminal(code, stopped=False):
                directory.mkdir(parents=True, exist_ok=True)
                (directory / 'container.log').write_bytes(b'original stdout and stderr\n')
                result = dict(job=identity, outcome='exited', exit_code=code, returncode=code,
                    stop_requested=stopped, state=dict(Running=False, Status='exited', ExitCode=code,
                                                     OOMKilled=False, Error=''),
                    log_sha256=hashlib.sha256((directory / 'container.log').read_bytes()).hexdigest())
                (directory / 'result.json').write_text(json.dumps(result))

            def command(argv, **kwargs):
                commands.append(argv)
                action = argv[2]
                if action == 'run':
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / 'managed-run.json').write_text(json.dumps(identity))
                    active.parent.mkdir(parents=True, exist_ok=True)
                    active.write_text(json.dumps(identity))
                    if mode in ('success', 'failure', 'removal_failed', 'corrupt_log'):
                        terminal(7 if mode == 'failure' else 0)
                        if mode != 'removal_failed':
                            active.unlink()
                        if mode == 'corrupt_log':
                            (directory / 'container.log').write_text('changed')
                        return subprocess.CompletedProcess(argv, 0 if mode == 'success' else 1)
                    if mode == 'successor':
                        active.write_text(json.dumps(dict(identity, run='b' * 32)))
                    raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
                if action == 'status':
                    return subprocess.CompletedProcess(argv, 0, json.dumps(dict(active=json.loads(active.read_text()),
                        container_state=dict(Running=True))), '')
                self.assertEqual(action, 'stop')
                self.assertEqual(argv[-2:], ['--run', run])
                if mode == 'successor':
                    return subprocess.CompletedProcess(argv, 1, '', 'Recorded run differs')
                terminal(137 if mode == 'timeout' else 0, stopped=mode == 'timeout')
                active.unlink()
                return subprocess.CompletedProcess(argv, 137 if mode == 'timeout' else 0, '', '')

            expected = {'success': None, 'failure': RuntimeError, 'timeout': subprocess.TimeoutExpired,
                        'successor': RuntimeError, 'removal_failed': RuntimeError, 'corrupt_log': ValueError}[mode]
            with patch.object(managed.subprocess, 'run', side_effect=command):
                if expected:
                    with self.assertRaises(expected):
                        managed.execute('fixture', ['image'], destination, timeout=1)
                else:
                    self.assertEqual(managed.execute('fixture', ['image'], destination, timeout=1)['exit_code'], 0)
            if mode in ('success', 'failure', 'timeout', 'removal_failed'):
                self.assertFalse(active.exists())
                result = json.loads((destination / 'managed-result.json').read_text())
                self.assertEqual(result['exit_code'], 137 if mode == 'timeout' else 7 if mode == 'failure' else 0)
                self.assertEqual((destination / 'container.log').read_bytes(), b'original stdout and stderr\n')
            if mode == 'successor':
                self.assertEqual(json.loads(active.read_text())['run'], 'b' * 32)
                self.assertTrue((destination / 'cleanup-pending.json').exists())
            if mode in ('timeout', 'successor', 'removal_failed'):
                self.assertTrue((destination / 'interrupted-state.json').exists())
                self.assertEqual([c[2] for c in commands], ['run', 'status', 'stop'])
            else:
                self.assertEqual([c[2] for c in commands], ['run'])

    def test_completion_failure_timeout_removal_retry_and_successor(self):
        for mode in ('success', 'failure', 'timeout', 'removal_failed', 'successor', 'corrupt_log'):
            with self.subTest(mode=mode):
                self.exercise(mode)

    def test_attempt_reuse_and_foreign_evidence_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(managed, 'ROOT', Path(temporary)):
            root = Path(temporary)
            destination = root / '.local/attempt'
            destination.mkdir(parents=True)
            (destination / 'original').write_text('preserve')
            with patch.object(managed.subprocess, 'run') as run:
                for path in (destination, root / 'foreign'):
                    with self.assertRaises(ValueError):
                        managed.execute('fixture', ['image'], path, timeout=1)
                run.assert_not_called()
            self.assertEqual((destination / 'original').read_text(), 'preserve')


class CompletedCommandFailures(unittest.TestCase):
    def test_only_original_clean_terminal_failure_with_released_ownership_is_typed(self):
        for mode in ('expected', 'unresolved', 'stopped', 'oom', 'running', 'wrong-returncode',
                     'wrong-original', 'changed-original'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary, \
                    patch.object(managed, 'ROOT', Path(temporary)):
                root = Path(temporary)
                destination = root / '.local/attempt'
                identity = dict(schema=1, workspace=hashlib.sha256(str(root).encode()).hexdigest()[:20],
                                stage='fixture', run='a' * 32)
                directory = root / '.local/build/container-stages' / identity['run']
                active = root / '.local/build/container-active.json'
                reads = 0
                original_result_for = managed.result_for

                def command(argv, **kwargs):
                    if argv[2] == 'run':
                        destination.mkdir(parents=True, exist_ok=True)
                        (destination / 'managed-run.json').write_text(json.dumps(identity))
                        directory.mkdir(parents=True)
                        (directory / 'container.log').write_bytes(b'actual original output\n')
                        job = dict(identity, run='b' * 32) if mode == 'wrong-original' else identity
                        result = dict(job=job, outcome='exited', exit_code=1, returncode=1,
                            stop_requested=mode == 'stopped',
                            state=dict(Running=mode == 'running', Status='exited', ExitCode=1,
                                       OOMKilled=mode == 'oom', Error=''),
                            log_sha256=hashlib.sha256((directory / 'container.log').read_bytes()).hexdigest())
                        (directory / 'result.json').write_text(json.dumps(result))
                        if mode == 'unresolved':
                            active.write_text(json.dumps(identity))
                        return subprocess.CompletedProcess(argv, 2 if mode == 'wrong-returncode' else 1)
                    if argv[2] == 'status':
                        return subprocess.CompletedProcess(argv, 0, 'original still owns cleanup', '')
                    self.assertEqual(argv[2], 'stop')
                    self.assertEqual(argv[-2:], ['--run', identity['run']])
                    # Terminal exit 1 is not sufficient: removal still failed.
                    return subprocess.CompletedProcess(argv, 1, '', 'removal failed')

                def result_for(receipt):
                    nonlocal reads
                    reads += 1
                    if mode == 'changed-original' and reads == 2:
                        path = directory / 'result.json'
                        changed = json.loads(path.read_text())
                        changed['different_observation'] = True
                        path.write_text(json.dumps(changed))
                    return original_result_for(receipt)

                expected = managed.ManagedCommandFailure if mode == 'expected' else ValueError if mode == 'wrong-original' else RuntimeError
                with patch.object(managed.subprocess, 'run', side_effect=command), \
                        patch.object(managed, 'result_for', side_effect=result_for):
                    with self.assertRaises(expected) as raised:
                        managed.execute('fixture', ['image'], destination, timeout=1)
                if mode == 'expected':
                    self.assertIsInstance(raised.exception, RuntimeError)
                    self.assertEqual(raised.exception.identity, identity)
                    self.assertEqual(raised.exception.result['exit_code'], 1)
                    self.assertFalse(active.exists())
                    self.assertTrue((destination / 'managed-result.json').is_file())
                else:
                    self.assertNotIsInstance(raised.exception, managed.ManagedCommandFailure)
                if mode == 'unresolved':
                    self.assertEqual(json.loads(active.read_text()), identity)
                    self.assertTrue((destination / 'cleanup-pending.json').is_file())


class StageReceipts(unittest.TestCase):
    def test_receipt_survives_failed_create_with_the_same_reserved_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build = root / '.local/build'
            receipt = root / '.local/attempt/identity.json'
            with patch.multiple(stage, ROOT=root, BUILD=build, ACTIVE=build / 'container-active.json'), \
                    patch.object(stage, 'recover_named', return_value=None), \
                    patch.object(stage, 'docker', side_effect=RuntimeError('create failed')):
                with self.assertRaises(RuntimeError):
                    stage.run('fixture', ['image'], receipt)
                identity = json.loads(receipt.read_text())
                job = json.loads(stage.ACTIVE.read_text())
                self.assertEqual(identity['run'], job['run'])
                self.assertEqual(stage.start_state(job), 'unrequested')
                with self.assertRaises(ValueError):
                    stage.run('fixture', ['image'], receipt)

    def test_pinned_stop_refuses_a_successor_before_inspection(self):
        with patch.object(stage, 'ownership', return_value=nullcontext()), \
                patch.object(stage, 'active', return_value={'run': 'b' * 32}), \
                patch.object(stage, 'inspect') as inspect, \
                patch.object(sys, 'argv', ['docker-stage.py', 'stop', '--run', 'a' * 32]):
            with self.assertRaises(RuntimeError):
                stage.main()
            inspect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
