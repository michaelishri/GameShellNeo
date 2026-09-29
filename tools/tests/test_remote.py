"""Mac transport selection must preserve the already trusted SSH identity."""
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote


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


if __name__ == '__main__':
    unittest.main()
