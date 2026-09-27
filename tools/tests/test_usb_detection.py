import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), TOOLS / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


recorder = module('record-usb-detection')
host = module('check-usb-detection')


def snapshot(sequence, state, seconds, plugin=0, removal=0):
    attached = int(state == 'configured')
    return dict(event='snapshot', sequence=sequence, boot_id='boot-a', monotonic=seconds,
                start=seconds, state=state,
                irqs=dict(cpus=['CPU0'], counts=dict(VBUS_PLUGIN=plugin, VBUS_REMOVAL=removal)),
                power=dict(supplies={'axp20x-usb': dict(present=attached, online=attached)}))


class RecorderTests(unittest.TestCase):
    def test_irq_mapping_uses_pmic_resources_not_linux_irq_numbers(self):
        text = (' CPU0 CPU1\n'
                ' 172: 1 2 axp22x_irq_chip 5 Edge axp20x-usb-power-supply\n'
                ' 173: 4 5 axp22x_irq_chip 6 Edge axp20x-usb-power-supply\n'
                ' 26: 9 9 GICv2 30 Level arch_timer\nErr: 0\n')
        result = recorder.irq_counts(text)
        self.assertEqual(result['counts'], dict(VBUS_PLUGIN=3, VBUS_REMOVAL=9))
        with self.assertRaises(ValueError):
            recorder.irq_counts(text.replace('axp22x_irq_chip 6', 'another-chip 6'))
        with self.assertRaises(ValueError):
            recorder.irq_counts(text + '174: 1 0 axp22x_irq_chip 5 Edge duplicate\n')

    def test_counter_reset_or_cpu_change_is_rejected(self):
        before = dict(cpus=['CPU0'], counts={'VBUS_PLUGIN': 2})
        for after in (dict(cpus=['CPU0'], counts={'VBUS_PLUGIN': 1}),
                      dict(cpus=['CPU1'], counts={'VBUS_PLUGIN': 3})):
            with self.assertRaises(ValueError):
                recorder.check_counts(before, after)

    def test_targeted_register_reads_skip_irq_status_and_never_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'range').write_text('0-e6\n')
            (directory / 'registers').write_text(''.join(f'{i:02x}: {i:02x}\n' for i in range(0xe7)))
            real_pread = recorder.os.pread
            with patch.object(recorder.os, 'pread', wraps=real_pread) as reads:
                result = recorder.pmic_configuration(directory)
            self.assertEqual([call.args[1:] for call in reads.call_args_list],
                             [(7, address * 7) for address in (0, 0x30, 0x40, 0x8f)])
            self.assertEqual(result['registers']['8f'], 0x8f)
            self.assertTrue(result['control_values_may_be_cached'])
            (directory / 'range').write_text('0-20\n30-e6\n')
            with self.assertRaises(ValueError):
                recorder.pmic_configuration(directory)

    def test_register_read_error_is_not_a_zero_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'range').write_text('0-e6\n')
            (directory / 'registers').write_text('00: XX\n')
            with self.assertRaises(ValueError):
                recorder.pmic_configuration(directory)

    def test_netlink_filters_sender_supply_and_fields(self):
        data = (b'change@/devices/foo\0ACTION=change\0SUBSYSTEM=power_supply\0'
                b'POWER_SUPPLY_NAME=axp20x-usb\0POWER_SUPPLY_ONLINE=1\0SEQNUM=42\0SECRET=x\0')
        parsed = recorder.parse_uevent(data, 0)
        self.assertEqual(parsed['POWER_SUPPLY_ONLINE'], '1')
        self.assertNotIn('SECRET', parsed)
        self.assertIsNone(recorder.parse_uevent(data, 123))
        self.assertIsNone(recorder.parse_uevent(data.replace(b'axp20x-usb', b'other'), 0))
        with self.assertRaises(ValueError):
            recorder.parse_uevent(data, 0, socket.MSG_TRUNC)


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.ready = dict(event='ready', sequence=0, boot_id='boot-a', monotonic=1)
        self.baseline = snapshot(1, 'not attached', 2)

    def encode(self, records):
        return ''.join(json.dumps(row) + '\n' for row in records).encode()

    def test_partial_live_tail_is_ignored_but_final_tail_fails(self):
        data = self.encode([self.ready, self.baseline]) + b'{"event":'
        self.assertEqual(len(host.trace_records(data)), 2)
        with self.assertRaises(ValueError):
            host.trace_records(data, final=True)

    def test_missing_sequence_changed_boot_and_clock_are_rejected(self):
        for replacement in (dict(sequence=3), dict(boot_id='boot-b'), dict(monotonic=0)):
            record = dict(self.baseline, **replacement)
            with self.assertRaises(ValueError):
                host.trace_records(self.encode([self.ready, record]))

    def test_failed_or_unfinished_capture_cannot_pass(self):
        failed = dict(event='failed', sequence=2, boot_id='boot-a', monotonic=3, error='ENOBUFS')
        with self.assertRaises(ValueError):
            host.trace_records(self.encode([self.ready, self.baseline, failed]))
        with self.assertRaises(ValueError):
            host.trace_records(self.encode([self.ready, self.baseline]), final=True)
        complete = dict(failed, event='complete')
        self.assertEqual(len(host.trace_records(self.encode([self.ready, self.baseline, complete]), final=True)), 3)

    def test_initial_connection_and_unverified_cycles_do_not_count(self):
        tracker = host.Cycles()
        with self.assertRaises(ValueError):
            tracker.consume(snapshot(1, 'configured', 2))
        tracker.consume(self.baseline)
        tracker.consume(snapshot(2, 'configured', 3, 1))
        with self.assertRaises(ValueError):
            tracker.consume(snapshot(3, 'not attached', 4, 1, 1))

    def test_cycle_waits_for_late_irq_and_stable_removal(self):
        tracker = host.Cycles()
        tracker.consume(self.baseline)
        tracker.consume(snapshot(2, 'configured', 3, 1))
        tracker.pending['usb_ssh'] = {'verified': True}
        tracker.consume(snapshot(3, 'not attached', 4, 1, 0))
        self.assertEqual(tracker.completed, [])
        tracker.consume(snapshot(4, 'not attached', 4.02, 1, 1))
        self.assertEqual(tracker.completed, [])
        tracker.consume(snapshot(5, 'not attached', 5.1, 1, 1))
        self.assertEqual(tracker.completed[0]['irq_delta'], dict(VBUS_PLUGIN=1, VBUS_REMOVAL=1))
        tracker.consume(snapshot(6, 'not attached', 6, 1, 1))
        self.assertEqual(len(tracker.completed), 1)

    def test_rapid_reconnect_during_settle_is_not_silently_merged(self):
        tracker = host.Cycles()
        tracker.consume(self.baseline)
        tracker.consume(snapshot(2, 'configured', 3, 1))
        tracker.pending['usb_ssh'] = {'verified': True}
        tracker.consume(snapshot(3, 'not attached', 4, 1, 1))
        with self.assertRaises(ValueError):
            tracker.consume(snapshot(4, 'configured', 4.2, 2, 1))

    def test_failure_stops_owned_recorder_and_preserves_diagnostics(self):
        commands = []
        checks = 0
        failed = dict(event='failed', sequence=2, boot_id='boot-a', monotonic=3, error='read failed')
        data = self.encode([self.ready, self.baseline, failed])

        def run(_client, command, **_kwargs):
            nonlocal checks
            commands.append(command)
            if 'LoadState' in command:
                checks += 1
                return b'not-found\n' if checks == 1 else b'loaded\n'
            if 'mktemp' in command:
                return b'/tmp/gameshellneo-usb-detection.ABC12345\n'
            if 'cat ' in command:
                return data
            if 'journalctl' in command:
                return b'recorder diagnostic\n'
            return b''

        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(host, 'device', return_value=MagicMock()), \
                patch.object(host, 'upload'), patch.object(host, 'run', side_effect=run), \
                patch.object(host.WifiObserver, 'trace_since', side_effect=[data, b'']):
            events = []
            with self.assertRaisesRegex(ValueError, 'read failed'):
                host.observe({}, 4, 5, Path(temporary), lambda event, **kw: events.append(event))
            self.assertIn('sudo -n systemctl stop ' + host.UNIT, commands)
            self.assertIn('cleanup_pending', events)
            self.assertTrue((Path(temporary) / 'recorder-journal.txt').is_file())
            self.assertFalse(any(command.startswith('sudo -n rm ') for command in commands))

    def test_existing_unit_is_not_stopped_or_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(host, 'device', return_value=MagicMock()), \
                patch.object(host, 'run', return_value=b'loaded\n') as run:
            with self.assertRaisesRegex(ValueError, 'already exists'):
                host.observe({}, 4, 5, Path(temporary), lambda *args, **kwargs: None)
            self.assertEqual(run.call_count, 1)

    def test_stale_wifi_transport_reconnects_once_without_losing_trace(self):
        events = []
        with patch.object(host, 'device', return_value=MagicMock()) as connect, \
                patch.object(host, 'run', side_effect=[TimeoutError('stale'), b'trace']) as run:
            with host.WifiObserver({}, lambda event, **kw: events.append(event)) as observer:
                self.assertEqual(observer.query('read capture'), b'trace')
            self.assertEqual(connect.call_count, 2)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(events, ['wifi_reconnecting', 'wifi_reconnected'])

    def test_failed_wifi_recovery_is_bounded_and_remote_errors_are_not_replayed(self):
        for failures, attempts in (([TimeoutError('old'), TimeoutError('new')], 2),
                                   ([RuntimeError('remote failed')], 1)):
            with patch.object(host, 'device', return_value=MagicMock()) as connect, \
                    patch.object(host, 'run', side_effect=failures):
                with host.WifiObserver({}, lambda *args, **kw: None) as observer:
                    with self.assertRaises((TimeoutError, RuntimeError)):
                        observer.query('read capture')
                self.assertEqual(connect.call_count, attempts)

    def test_trace_download_is_bounded_and_resumes_at_last_byte(self):
        client = MagicMock()
        sftp = client.open_sftp.return_value.__enter__.return_value
        sftp.stat.return_value.st_size = 100
        source = sftp.open.return_value.__enter__.return_value
        source.read.return_value = b'new bytes'
        observer = host.WifiObserver({}, lambda *args, **kwargs: None)
        observer.client = client
        self.assertEqual(observer.trace_since('/tmp/trace', 77), b'new bytes')
        source.seek.assert_called_once_with(77)
        source.read.assert_called_once_with(32768)
        sftp.stat.return_value.st_size = 70
        with self.assertRaisesRegex(ValueError, 'truncated'):
            observer.trace_since('/tmp/trace', 77)


if __name__ == '__main__':
    unittest.main()
