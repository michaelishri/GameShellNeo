"""Attribute transport failures without leaking payloads or changing retries."""
from contextlib import nullcontext
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import host_timing as timing
import remote

BOOT = '12345678-1234-1234-1234-123456789abc'
SECRET = 'private password 192.0.2.3 command payload'


class Timing(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def records(self):
        return [json.loads(line) for line in (self.root/'host-timing.jsonl').read_text().splitlines()]

    def test_nested_clock_brackets_and_exclusive_private_capture(self):
        with timing.capture_timing(self.root):
            with timing.phase('clock.sample'):
                timing.clock_sample(dict(boot_id=BOOT, boottime_ns=123))
        records = self.records()
        clock = next(r for r in records if r['event'] == 'device_clock')
        bounds = [r for r in records if r.get('span') == clock['span'] and r['event'] in ('begin', 'end')]
        self.assertLessEqual(bounds[0]['host_monotonic_ns'], clock['host_monotonic_ns'])
        self.assertLessEqual(clock['host_monotonic_ns'], bounds[1]['host_monotonic_ns'])
        self.assertEqual(bounds[0]['parent'], records[0]['span'])
        self.assertEqual(records[-1]['phase'], 'capture')
        self.assertEqual(records[-1]['outcome'], 'ok')
        summary = timing.summarize(self.root)
        self.assertEqual(summary['capture_outcome'], 'ok')
        self.assertEqual(next(r for r in summary['phases'] if r['phase'] == 'clock.sample')['count'], 1)
        self.assertEqual(stat.S_IMODE((self.root/'host-timing.jsonl').stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            with timing.capture_timing(self.root):
                self.fail('Must not overwrite timing')
        (self.root/'host-timing.jsonl').unlink()
        target = self.root/'target'; target.write_text('original')
        (self.root/'host-timing.jsonl').symlink_to(target)
        with self.assertRaises(OSError):
            with timing.capture_timing(self.root):
                self.fail('Must not follow symlink')
        self.assertEqual(target.read_text(), 'original')

    def test_payload_and_error_details_absent_but_failed_phase_retained(self):
        client = MagicMock()
        channel = client.get_transport.return_value.open_session.return_value
        error = TimeoutError(SECRET)
        channel.recv.side_effect = error
        with timing.capture_timing(self.root), self.assertRaises(TimeoutError) as caught:
            remote.run(client, SECRET, input_data=SECRET.encode(), display=False)
        self.assertIs(caught.exception, error)
        self.assertNotIn(SECRET, (self.root/'host-timing.jsonl').read_text())
        failures = [r for r in self.records() if r['event'] == 'failure']
        self.assertEqual(failures[0]['phase'], 'command.response')
        self.assertEqual(failures[0]['category'], 'timeout')
        channel.exec_command.assert_called_once_with(SECRET)
        channel.close.assert_called_once()

    def test_setup_failure_closes_command_channel(self):
        client = MagicMock()
        channel = client.get_transport.return_value.open_session.return_value
        channel.settimeout.side_effect = OSError(SECRET)
        with timing.capture_timing(self.root), self.assertRaises(OSError):
            remote.run(client, SECRET, display=False)
        channel.close.assert_called_once()
        channel.exec_command.assert_not_called()
        self.assertIn('command.request', [r['phase'] for r in self.records() if r['event'] == 'failure'])

    def test_tunnel_failure_is_not_mislabeled_as_device_handshake(self):
        mac = MagicMock()
        mac.get_transport.return_value.open_channel.side_effect = remote.paramiko.ChannelException(2, SECRET)
        with timing.capture_timing(self.root), patch.object(remote, 'connect_mac', return_value=nullcontext(mac)), \
                self.assertRaises(remote.paramiko.ChannelException):
            with remote.device({}, 'usb'):
                self.fail('No device connection')
        failures = [r for r in self.records() if r['event'] == 'failure']
        self.assertEqual(failures[0]['phase'], 'device.tunnel')
        self.assertEqual(failures[0]['code'], 2)
        self.assertNotIn('device.ssh', [r.get('phase') for r in self.records()])
        self.assertNotIn(SECRET, (self.root/'host-timing.jsonl').read_text())
        mac.get_transport.return_value.open_channel.assert_called_once()

    def test_mac_tcp_failure_keeps_identity_and_closes_without_ssh_retry(self):
        config = dict(M2_MACBOOK_AIR_IP='192.0.2.1', M2_MACBOOK_AIR_TAILNET='100.64.0.1')
        with timing.capture_timing(self.root), patch.object(remote.paramiko, 'SSHClient') as factory, \
                patch.object(remote.socket, 'create_connection', side_effect=TimeoutError(SECRET)) as connect, \
                self.assertRaises(TimeoutError):
            remote.connect_mac(config)
        connect.assert_called_once()
        factory.return_value.close.assert_called_once()
        factory.return_value.connect.assert_not_called()
        self.assertEqual([r['phase'] for r in self.records() if r['event'] == 'failure'], ['mac.tcp'])

    def test_recording_failure_cannot_mask_primary_error_or_interrupt_operation(self):
        error = RuntimeError(SECRET)
        stream = MagicMock(); stream.write.side_effect = OSError('disk full')
        recorder = timing.Recorder(stream)
        token = timing._active.set(recorder)
        stderr = MagicMock(); stderr.write.side_effect = OSError('same full disk')
        try:
            with patch.object(sys, 'stderr', stderr), self.assertRaises(RuntimeError) as caught:
                with timing.phase('pm.submit'):
                    raise error
            self.assertIs(caught.exception, error)
            self.assertTrue(recorder.failed)
            stream.write.assert_called_once()
        finally:
            timing._active.reset(token)

    def test_event_cap_and_fixed_labels_bound_private_output(self):
        with patch.object(timing, 'MAX_EVENTS', 3), patch.object(sys, 'stderr', io.StringIO()), \
                timing.capture_timing(self.root) as recorder:
            for _ in range(10):
                with timing.phase('awake.probe'):
                    pass
        self.assertTrue(recorder.failed)
        self.assertEqual(len(self.records()), 3)
        with self.assertRaises(ValueError):
            timing.summarize(self.root)
        with self.assertRaises(ValueError):
            with timing.phase(SECRET):
                pass
        for value in (dict(boot_id=SECRET, boottime_ns=1), dict(boot_id=BOOT, boottime_ns=True),
                      dict(boot_id=BOOT, boottime_ns=1, payload=SECRET)):
            with self.assertRaises(ValueError):
                timing.clock_sample(value)

    def test_short_write_is_incomplete_and_does_not_interrupt_operation(self):
        stream = MagicMock(); stream.write.return_value = 1
        recorder = timing.Recorder(stream)
        with patch.object(sys, 'stderr', io.StringIO()):
            recorder.emit(event='begin', phase='capture', span=1, parent=None)
        self.assertTrue(recorder.failed)

    def test_summary_groups_nested_routes_and_rejects_broken_nesting(self):
        with timing.capture_timing(self.root):
            for route in ('usb', 'wifi'):
                with timing.phase('route.'+route), timing.phase('device.ssh'):
                    pass
        summary = timing.summarize(self.root)
        self.assertEqual({r['route'] for r in summary['phases'] if r['phase'] == 'device.ssh'}, {'usb', 'wifi'})
        records = self.records()
        records[2]['parent'] = 999
        (self.root/'host-timing.jsonl').write_text('\n'.join(json.dumps(r) for r in records)+'\n')
        with self.assertRaises(ValueError):
            timing.summarize(self.root)


class AwakeProbe(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('awake_ssh_probe', remote.ROOT/'tools/check-ssh-timing.py')
        self.probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.probe)
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.connections = self.enterContext(patch.object(self.probe, 'device', side_effect=lambda *a: nullcontext(object())))
        self.enterContext(patch.object(self.probe.time, 'sleep'))
        self.value = dict(clock=dict(boot_id=BOOT, boottime_ns=1000), pm=dict(success=13, fail=0))

    def test_fresh_distinct_routes_same_boot_and_pm_counts(self):
        with patch.object(self.probe, 'run', side_effect=[b'ip_address=192.0.2.20\n']+[json.dumps(self.value).encode()]*4):
            result = self.probe.probe({}, self.root, 2)
        self.assertTrue(result['passed'])
        self.assertEqual([v['route'] for v in result['samples']], ['usb', 'wifi']*2)
        self.assertEqual([c.args[1] for c in self.connections.call_args_list], ['usb', 'usb', 'wifi', 'usb', 'wifi'])
        self.assertEqual(self.connections.call_args_list[-1].args[0]['GAMESHELL_IP'], '192.0.2.20')

    def test_fail_stops_without_retry_and_preserves_first_observation(self):
        changed = dict(self.value, pm=dict(success=14, fail=0))
        with patch.object(self.probe, 'run', side_effect=[b'ip_address=192.0.2.20\n',
                json.dumps(self.value).encode(), json.dumps(changed).encode()]) as run, self.assertRaises(ValueError):
            self.probe.probe({}, self.root, 4)
        run.assert_called(); self.assertEqual(run.call_count, 3)
        summary = json.loads((self.root/'awake-ssh.json').read_text())
        self.assertFalse(summary['passed']); self.assertEqual(len(summary['samples']), 1)

    def test_unconnected_or_same_route_rejected_before_measurements(self):
        with patch.object(self.probe, 'run', return_value=b'ip_address=192.168.10.1\n') as run, \
                self.assertRaises(ValueError):
            self.probe.probe({}, self.root, 1)
        run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
