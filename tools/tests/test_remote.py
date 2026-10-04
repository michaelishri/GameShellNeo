"""Mac transport selection must preserve the already trusted SSH identity."""
from pathlib import Path
import io
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote


class PythonTransportTests(unittest.TestCase):
    def test_real_interpreter_preserves_source_and_literal_arguments(self):
        source = 'import json, sys\nprint(json.dumps(sys.argv[1:]))\n# café \' " $() `literal`\n'
        arguments = ('--inspect', 'spaces and quotes \' "', '$(must-not-run)', '--flag=é')
        payload = remote.python_command(source, *arguments)
        argv = shlex.split(payload['command'])
        self.assertEqual(argv[:5], ['sudo', '-n', 'python3', '-B', '-'])
        self.assertNotIn(source, payload['command'])
        process = subprocess.run([sys.executable, *argv[3:]], input=payload['input_data'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        self.assertEqual(json.loads(process.stdout), list(arguments))

    def test_full_pm_helper_stays_out_of_audited_command(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('stdin_pm_host', remote.ROOT/'tools/check-pm-stages.py')
        host = importlib.util.module_from_spec(spec); spec.loader.exec_module(host)
        with patch.object(host, 'run') as run:
            host.inline(object(), '--help')
        kwargs = run.call_args.kwargs
        self.assertGreater(len(kwargs['input_data']), 50000)
        self.assertLess(len(kwargs['command']), 100)
        argv = shlex.split(kwargs['command'])
        process = subprocess.run([sys.executable, *argv[3:]], input=kwargs['input_data'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        self.assertIn(b'--stage', process.stdout)

    def client(self):
        client = MagicMock()
        channel = client.get_transport.return_value.open_session.return_value
        channel.recv.side_effect = [b'first\n', b'last\n', b'']
        channel.recv_exit_status.return_value = 0
        return client, channel

    def test_source_sent_once_before_eof_and_output_retained(self):
        client, channel = self.client(); output = io.BytesIO()
        source = '# marker\n' * 20000 + 'print("done")\n'
        result = remote.run(client, **remote.python_command(source), output=output, display=False)
        channel.sendall.assert_called_once_with(source.encode())
        names = [c[0] for c in channel.method_calls]
        self.assertLess(names.index('sendall'), names.index('shutdown_write'))
        self.assertLess(names.index('shutdown_write'), names.index('recv'))
        self.assertEqual(result, b'first\nlast\n'); self.assertEqual(output.getvalue(), result)
        channel.close.assert_called_once()

    def test_uncertain_send_or_read_failure_closes_without_resubmission(self):
        for method in ('sendall', 'recv'):
            with self.subTest(method=method):
                client, channel = self.client()
                getattr(channel, method).side_effect = TimeoutError('interrupted')
                with self.assertRaises(TimeoutError):
                    remote.run(client, **remote.python_command('print(1)'), display=False)
                channel.exec_command.assert_called_once()
                channel.sendall.assert_called_once()
                channel.close.assert_called_once()

    def test_nonzero_exit_preserves_output_and_reports_failure(self):
        client, channel = self.client(); channel.recv_exit_status.return_value = 7
        output = io.BytesIO()
        with self.assertRaisesRegex(RuntimeError, 'exit 7'):
            remote.run(client, **remote.python_command('raise SystemExit(7)'), output=output, display=False)
        self.assertEqual(output.getvalue(), b'first\nlast\n')
        channel.close.assert_called_once()

    def test_invalid_input_rejected_before_opening_channel(self):
        for payload, password in [('text', None), (b'x' * (1024 * 1024 + 1), None), (b'x', 'secret')]:
            client, channel = self.client()
            with self.assertRaises(ValueError):
                remote.run(client, 'unused', input_data=payload, password=password)
            channel.exec_command.assert_not_called()
            client.get_transport.return_value.open_session.assert_not_called()
        for source in ('', ' ', 'x\0y', 'é' * (512 * 1024 + 1), None):
            with self.assertRaises(ValueError):
                remote.python_command(source)


class MacConnectionTests(unittest.TestCase):
    def setUp(self):
        self.config = {'M2_MACBOOK_AIR_IP': '192.0.2.1',
                       'M2_MACBOOK_AIR_USERNAME': 'developer'}
        factory = patch.object(remote.paramiko, 'SSHClient')
        self.client = factory.start().return_value
        self.addCleanup(factory.stop)
        connector = patch.object(remote.socket, 'create_connection')
        self.socket = connector.start()
        self.addCleanup(connector.stop)

    def test_lan_without_tailnet_retains_normal_connection(self):
        self.assertIs(remote.connect_mac(self.config), self.client)
        self.socket.assert_not_called()
        self.assertEqual(self.client.connect.call_args.args, ('192.0.2.1',))
        self.assertIsNone(self.client.connect.call_args.kwargs['sock'])
        self.assertIsInstance(self.client.set_missing_host_key_policy.call_args.args[0],
                              paramiko.RejectPolicy)

    def test_tailnet_transport_keeps_existing_host_key_identity(self):
        self.config.update(M2_MACBOOK_AIR_TAILNET='100.64.0.1',
                           M2_MACBOOK_AIR_PASSWORD='test password')
        self.assertIs(remote.connect_mac(self.config), self.client)
        self.socket.assert_called_once_with(('100.64.0.1', 22), timeout=10)
        self.assertEqual(self.client.connect.call_args.args, ('192.0.2.1',))
        self.assertIs(self.client.connect.call_args.kwargs['sock'], self.socket.return_value)
        self.assertEqual(self.client.connect.call_args.kwargs['password'], 'test password')
        self.assertIsInstance(self.client.set_missing_host_key_policy.call_args.args[0],
                              paramiko.RejectPolicy)
        self.client.load_system_host_keys.assert_called_once_with()
        self.client.close.assert_not_called()

    def test_tailnet_only_requires_its_own_host_key_identity(self):
        self.config.pop('M2_MACBOOK_AIR_IP')
        self.config['M2_MACBOOK_AIR_TAILNET'] = '100.64.0.1'
        remote.connect_mac(self.config)
        self.socket.assert_not_called()
        self.assertEqual(self.client.connect.call_args.args, ('100.64.0.1',))
        self.assertIsInstance(self.client.set_missing_host_key_policy.call_args.args[0],
                              paramiko.RejectPolicy)

    def test_unreachable_tailnet_never_retries_lan(self):
        self.config['M2_MACBOOK_AIR_TAILNET'] = '100.64.0.1'
        self.socket.side_effect = TimeoutError('unreachable')
        with self.assertRaises(TimeoutError):
            remote.connect_mac(self.config)
        self.socket.assert_called_once()
        self.client.connect.assert_not_called()
        self.client.close.assert_called_once()

    def test_host_key_mismatch_propagates_and_closes_transport(self):
        self.config['M2_MACBOOK_AIR_TAILNET'] = '100.64.0.1'
        error = paramiko.BadHostKeyException('192.0.2.1', MagicMock(), MagicMock())
        self.client.connect.side_effect = error
        with self.assertRaises(paramiko.BadHostKeyException):
            remote.connect_mac(self.config)
        self.client.connect.assert_called_once()
        self.client.close.assert_called_once()
        self.socket.return_value.close.assert_called_once()

    def test_missing_address_fails_before_connecting(self):
        self.config.pop('M2_MACBOOK_AIR_IP')
        with self.assertRaises(ValueError):
            remote.connect_mac(self.config)
        self.socket.assert_not_called()
        self.client.connect.assert_not_called()


class DeviceRouteTests(unittest.TestCase):
    def setUp(self):
        self.config = {'GAMESHELL_IP': '192.0.2.20'}
        for name in ('connect_mac', 'private_path'):
            mock = patch.object(remote, name)
            setattr(self, name, mock.start())
            self.addCleanup(mock.stop)
        self.private_path.return_value.read_text.return_value = 'ssh-ed25519 AA== fixture'
        factory = patch.object(remote.paramiko, 'SSHClient')
        self.client = factory.start().return_value.__enter__.return_value
        self.addCleanup(factory.stop)
        key = patch.object(remote.paramiko, 'Ed25519Key')
        self.key = key.start().return_value
        self.addCleanup(key.stop)
        self.mac = self.connect_mac.return_value.__enter__.return_value
        self.forward = self.mac.get_transport.return_value.open_channel

    def check_route(self, route, expected, bridged):
        with remote.device(self.config, route) as client:
            self.assertIs(client, self.client)
            self.client.get_host_keys.return_value.add.assert_called_once_with(
                expected, 'ssh-ed25519', self.key)
            self.assertEqual(self.client.connect.call_args.args, (expected,))
            self.assertIsInstance(self.client.set_missing_host_key_policy.call_args.args[0],
                                  paramiko.RejectPolicy)
            if bridged:
                self.forward.assert_called_once_with('direct-tcpip', (expected, 22),
                                                     ('127.0.0.1', 0), timeout=10)
                self.assertIs(self.client.connect.call_args.kwargs['sock'], self.forward.return_value)
            else:
                self.connect_mac.assert_not_called()
                self.assertIsNone(self.client.connect.call_args.kwargs['sock'])
        if bridged:
            self.forward.return_value.close.assert_called_once()
            self.connect_mac.return_value.__exit__.assert_called_once()

    def test_default_wifi_is_direct(self):
        self.check_route('wifi', '192.0.2.20', False)

    def test_remote_wifi_uses_its_wifi_address_through_mac(self):
        self.config['GAMESHELL_WIFI_VIA_MAC'] = '1'
        self.check_route('wifi', '192.0.2.20', True)

    def test_usb_stays_on_separate_usb_address(self):
        self.config['GAMESHELL_WIFI_VIA_MAC'] = '1'
        self.config['GAMESHELL_USB_IP'] = '192.0.2.30'
        self.check_route('usb', '192.0.2.30', True)

    def test_remote_connection_failure_closes_bridge_without_fallback(self):
        self.config['GAMESHELL_WIFI_VIA_MAC'] = '1'
        self.client.connect.side_effect = paramiko.SSHException('failed authentication')
        with self.assertRaises(paramiko.SSHException):
            with remote.device(self.config, 'wifi'):
                self.fail('Unexpected connected session')
        self.client.connect.assert_called_once()
        self.forward.return_value.close.assert_called_once()
        self.connect_mac.return_value.__exit__.assert_called_once()

    def test_invalid_route_configuration_fails_before_connection(self):
        for route, flag in (('wifi', 'typo'), ('other', '0')):
            with self.subTest(route=route, flag=flag):
                self.config['GAMESHELL_WIFI_VIA_MAC'] = flag
                with self.assertRaises(ValueError):
                    with remote.device(self.config, route):
                        self.fail('Unexpected connected session')
        self.connect_mac.assert_not_called()
        self.client.connect.assert_not_called()


class ScanRecoveryTests(unittest.TestCase):
    def test_recovery_waits_for_running_comparison_before_restoring(self):
        commands = []
        def run(_client, command, **_kwargs):
            commands.append(command)
            return b'loaded\n' if 'LoadState' in command else b''
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(remote, 'device'), \
                patch.object(remote, 'evidence_directory', return_value=Path(directory)), \
                patch.object(remote, 'run', side_effect=run):
            remote.device_action({}, 'wifi-scan-restore', 'usb')
        self.assertEqual(len(commands), 3)
        self.assertIn('systemctl stop gameshellneo-scan-test', commands[1])
        self.assertTrue(commands[2].endswith('--restore'))

    def test_failed_stop_does_not_race_the_active_comparison(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(remote, 'device'), \
                patch.object(remote, 'evidence_directory', return_value=Path(directory)), \
                patch.object(remote, 'run', side_effect=[b'loaded\n', RuntimeError('stop failed')]) as run:
            with self.assertRaises(RuntimeError):
                remote.device_action({}, 'wifi-scan-restore', 'usb')
        self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
