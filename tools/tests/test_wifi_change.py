"""Wi-Fi updates preserve credentials and recover unless the host verifies access."""
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import MagicMock, patch
from paramiko.file import BufferedFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


apply = module('apply_wifi', 'apply-wifi.py')
host = module('change_wifi', 'change-wifi.py')


class WifiTransactionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.target = self.root / 'live.conf'
        self.target.write_bytes(b'previous secret\n')
        self.directory = self.root / 'transaction'
        self.directory.mkdir()
        (self.directory / 'candidate.conf').write_bytes(b'new secret\n')
        for name, value in [('TARGET', self.target), ('restart', None), ('address', None)]:
            mocked = patch.object(apply, name, value) if name == 'TARGET' else patch.object(apply, name)
            setattr(self, name, mocked.start())
            self.addCleanup(mocked.stop)
        self.address.return_value = '192.0.2.9'
        self.sleep = patch.object(apply.time, 'sleep').start()
        self.addCleanup(patch.stopall)

    def test_missing_host_commit_restores_previous_config(self):
        with self.assertRaises(TimeoutError):
            apply.apply(self.directory, seconds=0)
        self.assertEqual(self.target.read_bytes(), b'previous secret\n')
        self.assertEqual(self.restart.call_count, 2)
        self.assertEqual(json.loads((self.directory / 'status.json').read_text())['phase'], 'restored')
        apply.restore(self.directory)
        self.assertEqual(self.restart.call_count, 2)

    def test_commit_keeps_candidate_and_restoration_hook_is_noop(self):
        (self.directory / 'commit').write_text('192.0.2.9\n')
        apply.apply(self.directory)
        apply.restore(self.directory)
        self.assertEqual(self.target.read_bytes(), b'new secret\n')
        self.restart.assert_called_once()
        self.assertTrue(json.loads((self.directory / 'status.json').read_text())['passed'])
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)

    def test_changed_address_does_not_accept_stale_commit(self):
        (self.directory / 'commit').write_text('192.0.2.10\n')
        with patch.object(apply.time, 'monotonic', side_effect=[0, 0, 121]):
            with self.assertRaises(TimeoutError):
                apply.apply(self.directory)
        self.assertEqual(self.target.read_bytes(), b'previous secret\n')

    def test_service_failure_restores_previous_config(self):
        self.restart.side_effect = [RuntimeError('restart failed'), None]
        with self.assertRaises(RuntimeError):
            apply.apply(self.directory)
        self.assertEqual(self.target.read_bytes(), b'previous secret\n')
        self.assertTrue((self.directory / 'restored').exists())

    def test_independent_hook_repairs_interrupted_transaction(self):
        (self.directory / 'previous.conf').write_bytes(b'previous secret\n')
        self.target.write_bytes(b'new secret\n')
        apply.restore(self.directory)
        self.assertEqual(self.target.read_bytes(), b'previous secret\n')
        self.restart.assert_called_once()

    def test_failed_restoration_can_be_retried(self):
        (self.directory / 'previous.conf').write_bytes(b'previous secret\n')
        self.restart.side_effect = [RuntimeError('failed'), None]
        with self.assertRaises(RuntimeError):
            apply.restore(self.directory)
        self.assertFalse((self.directory / 'restored').exists())
        apply.restore(self.directory)
        self.assertTrue((self.directory / 'restored').exists())

    def test_env_preserves_secrets_and_rejects_concurrent_edit(self):
        env = self.root / '.env'
        original = b'# keep\nGAMESHELL_WIFI_PSK="a $(literal) secret"\nGAMESHELL_IP=192.0.2.1\n'
        env.write_bytes(original)
        host.update_address(env, original, '192.0.2.9')
        self.assertEqual(env.read_bytes(), original.replace(b'GAMESHELL_IP=192.0.2.1', b'GAMESHELL_IP=192.0.2.9'))
        changed = env.read_bytes()
        with self.assertRaises(ValueError):
            host.update_address(env, original, '192.0.2.10')
        self.assertEqual(env.read_bytes(), changed)

    def test_env_rejects_duplicate_address_and_invalid_ip(self):
        env = self.root / '.env'
        original = b'GAMESHELL_IP=192.0.2.1\nexport GAMESHELL_IP=192.0.2.2\n'
        env.write_bytes(original)
        for address in ('192.0.2.9', 'not-an-address'):
            with self.assertRaises(ValueError):
                host.update_address(env, original, address)
        self.assertEqual(env.read_bytes(), original)

    def test_private_sftp_staging_is_exclusively_writable_and_read_back(self):
        sftp = MagicMock()
        stream = sftp.open.return_value.__enter__.return_value
        stream.read.side_effect = [b'new secret\n', b'{"phase":"queued","passed":false}\n']
        with patch.object(host, 'upload'):
            host.stage(sftp, '/tmp/example', b'new secret\n')
        modes = [call.args[1] for call in sftp.open.call_args_list]
        self.assertEqual(modes, ['wx', 'rb', 'wx', 'rb'])
        for mode in modes[::2]:
            file = BufferedFile()
            file._set_mode(mode)
            self.assertTrue(file.writable())
        self.assertEqual([call.args[1] for call in sftp.chmod.call_args_list], [0o600, 0o600])


if __name__ == '__main__':
    unittest.main()
