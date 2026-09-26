import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

source = Path(__file__).resolve().parents[2] / 'tools/provision.py'
sys.path.insert(0, str(source.parent))
spec = importlib.util.spec_from_file_location('provision', source)
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)


class ProvisionTests(unittest.TestCase):
    def test_private_identity_is_stable_and_credentials_are_encoded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ssid = 'Network "quoted"'
            (root / 'ssid').write_text(ssid + '\n')
            (root / 'wicd').write_text('[ap]\nessid=' + ssid + '\nenctype=wpa-psk\napsk=private password\n')
            key = root / 'development'
            subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
            args = ['python3', str(source), '--wicd', str(root / 'wicd'), '--ssid-file',
                    str(root / 'ssid'), '--authorized-key', str(key) + '.pub', '--output', str(root / 'device')]
            subprocess.run(args, check=True, stdout=subprocess.DEVNULL)
            before = (root / 'device/identity.json').read_bytes()
            subprocess.run(args, check=True, stdout=subprocess.DEVNULL)
            self.assertEqual(before, (root / 'device/identity.json').read_bytes())
            wifi = (root / 'device/wpa_supplicant-wlan0.conf').read_text()
            self.assertIn('ssid=' + ssid.encode().hex(), wifi)
            self.assertNotIn('private password', wifi)
            self.assertEqual((root / 'device/ssh_host_ed25519_key').stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / 'device/wpa_supplicant-wlan0.conf').stat().st_mode & 0o777, 0o600)

    def test_conflicting_profiles_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wicd'
            path.write_text('[a]\nessid=ssid\nenctype=wpa-psk\napsk=password1\n'
                            '[b]\nessid=ssid\nenctype=wpa-psk\napsk=password2\n')
            with self.assertRaises(ValueError):
                provision.wifi_config(path, 'ssid')

    def test_env_provisioning_matches_legacy_wifi_without_printing_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = 'private # literal $(no-command)'
            env = root / '.env'
            env.write_text('GAMESHELL_WIFI_SSID="example network"\nGAMESHELL_WIFI_PSK=' + repr(secret) + '\n')
            key = root / 'key'
            subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
            result = subprocess.run(['python3', str(source), '--env', str(env), '--authorized-key',
                                     str(key) + '.pub', '--output', str(root / 'device')],
                                    check=True, capture_output=True, text=True)
            self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertEqual((root / 'device/wpa_supplicant-wlan0.conf').read_text(),
                             provision.wifi_config_from_key('example network', secret))


if __name__ == '__main__':
    unittest.main()
