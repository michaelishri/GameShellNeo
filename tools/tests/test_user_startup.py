"""Unix98 terminal behavior, result parsing and failed-channel cleanup."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('user_startup', Path(__file__).resolve().parents[1]/'check-user-startup.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class Terminals(unittest.TestCase):
    def test_real_unix98_bidirectional_io_and_resize(self):
        self.assertEqual(module.pty_smoke(), dict(unix98=True, both_directions=True, resize=True))

    def test_timeout_closes_both_owned_descriptors(self):
        opened = []
        original = os.openpty
        def allocate():
            pair = original(); opened.extend(pair); return pair
        with patch.object(module.os, 'openpty', side_effect=allocate), \
                patch.object(module.select, 'select', return_value=([], [], [])), self.assertRaises(TimeoutError):
            module.pty_smoke()
        for fd in opened:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_ssh_requests_terminal_and_checks_unix98_path(self):
        client = MagicMock(); channel = client.get_transport.return_value.open_session.return_value
        channel.recv.side_effect = [b'/dev/pts/2\r\n', b'']; channel.recv_exit_status.return_value = 0
        self.assertTrue(module.ssh_pty(client))
        channel.get_pty.assert_called_once_with(term='vt100', width=80, height=24)
        channel.exec_command.assert_called_once_with('tty'); channel.close.assert_called_once()

    def test_failed_ssh_pty_request_closes_without_exec_or_retry(self):
        client = MagicMock(); channel = client.get_transport.return_value.open_session.return_value
        channel.get_pty.side_effect = RuntimeError('refused')
        with self.assertRaises(RuntimeError):
            module.ssh_pty(client)
        channel.close.assert_called_once(); channel.exec_command.assert_not_called()
        client.get_transport.return_value.open_session.assert_called_once()


class Inventory(unittest.TestCase):
    def setUp(self):
        self.dump = '\n'.join('→ Unit '+name+':' for name in (
            'dev-ttyp0.device', 'sys-devices-virtual-tty-ttyp0.device',
            'dev-ttye0.device', 'dev-ttyS0.device', 'default.target'))
        self.properties = '\n'.join(key+'='+str(value) for key, value in zip(module.TIMESTAMPS,
            (1000000, 1050000, 1170000, 1170100, 4570100, 4925000)))

    def test_counts_legacy_aliases_and_separates_enumeration_interval(self):
        value = module.summarize_manager(self.dump, self.properties)
        self.assertEqual(value['legacy_device_units'], 3)
        self.assertEqual(value['types'], dict(device=4, target=1))
        self.assertEqual(value['unit_load_seconds'], 3.4)
        self.assertEqual(value['startup_seconds'], 3.925)
        self.assertEqual(value['generators_seconds'], 0.12)

    def test_missing_or_unordered_clock_and_invalid_dump_rejected(self):
        for dump, props in ((self.dump, self.properties.replace('4570100', '100')),
                            (self.dump, self.properties.replace('4925000', '0')),
                            (self.dump+'\n→ Unit default.target:', self.properties),
                            ('', self.properties)):
            with self.subTest(dump=dump, props=props), self.assertRaises(ValueError):
                module.summarize_manager(dump, props)

    def test_wrong_expectation_rejected_before_device_reads(self):
        with patch.object(module, 'health') as health, self.assertRaises(ValueError):
            module.inspect('typo')
        health.assert_not_called()


if __name__ == '__main__':
    unittest.main()
