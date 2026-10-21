"""Observer ownership/barrier/lifecycle regressions without hardware PM."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tcp_supervisor as supervisor

TOKEN = 'a'*32
CGROUP = '0::/system.slice/gameshellneo-sleep-test.service\n'


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root/'tcp_metadata.py').write_bytes(b'recorder-source')
        self.source = hashlib.sha256(b'recorder-source').hexdigest()
        self.supervisor_source = hashlib.sha256(Path(supervisor.__file__).read_bytes()).hexdigest()
        self.recorder = Mock(pid=123); self.recorder.poll.return_value = None
        self.operation = Mock(); self.operation.poll.return_value = None
        self.enterContext(patch.object(supervisor, 'cgroup', return_value=CGROUP))
        self.ready = dict(run_id=TOKEN, source_sha256=self.source, ready=True, pid=123,
                          interface='usb0', address='192.0.2.1')
        self.factory = self.enterContext(patch.object(supervisor.subprocess, 'Popen', side_effect=self.launch))
        self.command = ['/usr/bin/systemd-inhibit', '/bin/true']

    def launch(self, args, **kwargs):
        if 'capture' in args:
            (self.root/'ready.json').write_text(json.dumps(self.ready))
            return self.recorder
        self.assertTrue((self.root/'ready.json').exists())
        self.assertEqual(args, self.command)
        return self.operation

    def finish_command(self, timeout):
        self.operation.poll.return_value = 0
        return 0

    def finish_capture(self, timeout):
        self.recorder.poll.return_value = 0
        (self.root/'result.json').write_text(json.dumps(dict(run_id=TOKEN, passed=True)))
        return 0

    def run_supervisor(self):
        return supervisor.supervise(self.root, TOKEN, self.source, self.supervisor_source,
                                    '192.0.2.1', self.command)

    def test_ready_then_single_command_then_record_collection(self):
        self.operation.wait.side_effect = self.finish_command
        self.recorder.wait.side_effect = self.finish_capture
        self.assertEqual(self.run_supervisor(), 0)
        record = json.loads((self.root/'supervisor.json').read_text())
        self.assertTrue(record['passed']); self.assertTrue(record['command_started'])
        self.assertEqual(self.factory.call_count, 2)
        self.assertFalse(self.factory.call_args_list[0].kwargs.get('start_new_session', False))
        self.operation.terminate.assert_not_called(); self.recorder.terminate.assert_not_called()

    def test_wrong_readiness_never_starts_command(self):
        for field, value in [('run_id', 'b'*32), ('source_sha256', '0'*64), ('pid', 999),
                             ('interface', 'en0'), ('address', '192.0.2.2'), ('ready', False)]:
            with self.subTest(field=field):
                for file in self.root.glob('*.json'): file.unlink()
                original = self.ready[field]; self.ready[field] = value
                self.factory.reset_mock(); self.recorder.terminate.reset_mock()
                with self.assertRaisesRegex(ValueError, 'readiness'):
                    self.run_supervisor()
                self.assertEqual(self.factory.call_count, 1)
                self.recorder.terminate.assert_called_once()
                self.assertFalse(json.loads((self.root/'supervisor.json').read_text())['command_started'])
                self.ready[field] = original

    def test_dead_recorder_never_starts_command(self):
        self.recorder.poll.return_value = 1
        with self.assertRaisesRegex(ValueError, 'readiness'): self.run_supervisor()
        self.assertEqual(self.factory.call_count, 1)

    def test_source_mismatch_and_existing_artifact_never_launch(self):
        self.source = '0'*64
        with self.assertRaisesRegex(ValueError, 'source'): self.run_supervisor()
        self.factory.assert_not_called()
        self.source = hashlib.sha256(b'recorder-source').hexdigest()
        (self.root/'ready.json').touch()
        with self.assertRaisesRegex(ValueError, 'already exist'): self.run_supervisor()
        self.factory.assert_not_called()

    def test_command_failure_is_preserved_and_never_resubmitted(self):
        self.operation.wait.return_value = 7; self.operation.poll.return_value = 7
        self.recorder.wait.side_effect = self.finish_capture
        self.assertEqual(self.run_supervisor(), 1)
        record = json.loads((self.root/'supervisor.json').read_text())
        self.assertEqual(record['command_returncode'], 7); self.assertFalse(record['passed'])
        self.assertEqual(self.factory.call_count, 2)

    def test_command_timeout_cleans_both_children_without_retry(self):
        self.operation.wait.side_effect = [subprocess.TimeoutExpired('operation', 170), 0]
        with self.assertRaises(subprocess.TimeoutExpired): self.run_supervisor()
        self.operation.terminate.assert_called_once(); self.recorder.terminate.assert_called_once()
        self.assertEqual(self.factory.call_count, 2)

    def test_control_symlink_is_not_followed(self):
        target = self.root/'original'; target.write_text('{}')
        link = self.root/'link'; link.symlink_to(target)
        with self.assertRaises(OSError): supervisor.read_json(link)

    def test_cleanup_failure_does_not_skip_other_child_or_replace_primary(self):
        original = InterruptedError('unit stopped')
        self.operation.wait.side_effect = original
        with patch.object(supervisor, 'terminate', side_effect=[OSError('cleanup'), None]) as cleanup:
            with self.assertRaises(InterruptedError) as caught:
                self.run_supervisor()
        self.assertIs(caught.exception, original)
        self.assertEqual(cleanup.call_count, 2)
        record = json.loads((self.root/'supervisor.json').read_text())
        self.assertEqual(record['cleanup_errors'], ['OSError'])
        self.assertFalse(record['passed'])

    def test_foreign_cgroup_rejected(self):
        with patch.object(Path, 'read_text', return_value='0::/system.slice/other.service\n'):
            # setUp mocks the public function; execute its actual implementation.
            spec = importlib.util.spec_from_file_location('real_supervisor', supervisor.__file__)
            real = importlib.util.module_from_spec(spec); spec.loader.exec_module(real)
            with self.assertRaisesRegex(ValueError, 'existing sleep'): real.cgroup(1)


class HostIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('observed_sleep_host', Path(supervisor.__file__).with_name('check-sleep-rtc.py'))
        cls.host = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.host)

    def test_observer_wraps_same_inhibited_command_and_keeps_recovery(self):
        description = dict(directory='/tmp/gameshellneo-tcp.test', run_id=TOKEN,
                           source_sha256='1'*64, supervisor_sha256='2'*64, address='192.0.2.1')
        plain = self.host.service('/tmp/gameshellneo-sleep.test', 'b'*32, 'rtc-wake', 'c'*32)
        observed = self.host.service('/tmp/gameshellneo-sleep.test', 'b'*32, 'rtc-wake', 'c'*32,
                                     observer=description)
        original_index = plain.index('/usr/bin/systemd-inhibit')
        start = observed.index('/usr/bin/systemd-inhibit')
        self.assertEqual(observed[start:], plain[original_index:])
        self.assertEqual(observed[:original_index], plain[:original_index])
        self.assertEqual(observed[original_index:start], supervisor.prefix(description))
        self.assertEqual(sum(x.startswith('--unit=') for x in observed), 1)
        with self.assertRaisesRegex(ValueError, 'connected-USB'):
            self.host.service('/tmp/gameshellneo-sleep.test', 'b'*32, 'rehearse', '', observer=description)
        with self.assertRaisesRegex(ValueError, 'connected-USB'):
            self.host.service('/tmp/gameshellneo-sleep.test', 'b'*32, 'rtc-wake', 'c'*32,
                              connection='battery', observer=description)

    def test_invalid_observer_description_cannot_construct_command(self):
        for description in ({}, dict(directory='/tmp/foreign', run_id=TOKEN, source_sha256='a'*64,
                                     supervisor_sha256='b'*64, address='192.0.2.1')):
            with self.assertRaises(ValueError):
                self.host.service('/tmp/gameshellneo-sleep.test', TOKEN, 'rtc-wake', 'b'*32,
                                  observer=description)


if __name__ == '__main__': unittest.main()
