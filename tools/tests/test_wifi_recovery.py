"""Installed-radio trials keep rollback independent of the host connection."""
from contextlib import ExitStack
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), TOOLS / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


fw = module('test-wifi-firmware')
host = module('check-wifi-firmware')
IDENTITY = 'Firmware: BCM43430/0 test identity'
LOG = 'brcmfmac: brcmf_c_preinit_dcmds: ' + IDENTITY


class InstalledRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.paths = {}
        for name, content in {
            '/proc/sys/kernel/random/boot_id': 'boot', '/proc/sys/kernel/tainted': '0',
            '/etc/gameshellneo/image.json': json.dumps({'board': 'gameshellneo-cpi31', 'version': 'test'}),
        }.items():
            target = self.root / name.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            self.paths[name] = target
        udc = self.root / 'udc/controller'
        udc.mkdir(parents=True)
        (udc / 'state').write_text('configured')
        self.paths['/sys/class/udc'] = udc.parent
        self.files = {}
        for name, content in (('FIRMWARE', b'installed firmware'), ('NVRAM', b'board data'),
                              ('WIFI_CONFIG', b'persistent private config')):
            target = self.root / name
            target.write_bytes(content)
            self.files[name] = target
            self.stack.enter_context(patch.object(fw, name, target))
        self.state = self.root / 'recovery'
        self.stack.enter_context(patch.object(fw, 'INSTALLED_STATE', self.state))
        self.stack.enter_context(patch.object(fw, 'STATE', self.root / 'old-trial'))
        self.stack.enter_context(patch.object(fw, 'Path', side_effect=lambda p: self.paths.get(str(p), Path(p))))
        self.stack.enter_context(patch.object(fw.os, 'uname', return_value=SimpleNamespace(release='1-test')))
        self.command = self.stack.enter_context(patch.object(fw, 'command', side_effect=self.control))
        self.stack.enter_context(patch.object(fw, 'kernel', return_value=LOG))
        self.stack.enter_context(patch.object(fw.time, 'sleep'))
        self.stack.enter_context(patch.object(fw, 'emit'))
        self.stack.enter_context(patch.object(fw, 'wifi_address', return_value='192.0.2.2'))
        self.status = self.stack.enter_context(patch.object(fw, 'wifi_status', return_value={
            'wpa_state': 'COMPLETED', 'ssid': 'original'}))
        self.lock = {'image_version': 'test', 'linux': {'tag': 'v1', 'localversion': '-test'},
                     'radio': {'firmware': {'runtime_identity': IDENTITY,
                                           'sha256': fw.digest(self.files['FIRMWARE'].read_bytes())},
                               'nvram': {'sha256': fw.digest(self.files['NVRAM'].read_bytes())}}}
        self.saved = {'boot_id': 'boot', 'config_sha256': fw.digest(self.files['WIFI_CONFIG'].read_bytes()),
                      'ssid_sha256': fw.digest(b'original')}

    @staticmethod
    def control(*args):
        if args[-1] == 'list_networks':
            return 'network id / ssid / bssid / flags\n0\toriginal\tany\t[CURRENT]'
        if args[-2:] == ('get', 'disable_scan_offload'):
            return '0'
        if args[-1] == 'add_network':
            return '1'
        return 'OK'

    def make_state(self):
        self.state.mkdir()
        (self.state / 'state.json').write_text(json.dumps(self.saved))

    def test_installed_health_requires_single_pinned_identity_and_no_faults(self):
        self.assertEqual(fw.installed_health(self.lock, self.saved)['identities'], [IDENTITY])
        for log in ('', LOG.replace('/0 ', '/1 '), LOG + '\n' + LOG,
                    LOG + '\nbrcmf_fw_crashed: Firmware has halted or crashed',
                    LOG + '\nmmc1: card 0001 removed',
                    LOG + '\nRuntime PM usage count underflow!'):
            with self.subTest(log=log), patch.object(fw, 'kernel', return_value=log):
                with self.assertRaises(ValueError):
                    fw.installed_health(self.lock, self.saved)

    def test_health_rejects_changed_persistent_inputs_or_lost_usb(self):
        for name in self.files:
            with self.subTest(name=name):
                path = self.files[name]
                original = path.read_bytes()
                path.write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    fw.installed_health(self.lock, self.saved)
                path.write_bytes(original)
        (self.paths['/sys/class/udc'] / 'controller/state').write_text('not attached')
        with self.assertRaises(ValueError):
            fw.installed_health(self.lock, self.saved)

    def test_offline_window_requires_scanning_and_rejects_association(self):
        with self.assertRaises(ValueError):
            fw.installed_observe(self.lock, self.saved, 60, offline=True)
        self.status.return_value = {'wpa_state': 'DISCONNECTED'}
        with self.assertRaisesRegex(ValueError, 'No scanning'):
            fw.installed_observe(self.lock, self.saved, 60, offline=True)
        self.status.return_value = {'wpa_state': 'SCANNING'}
        fw.installed_observe(self.lock, self.saved, 60, offline=True)
        with self.assertRaises(ValueError):
            fw.installed_observe(self.lock, self.saved, 60)

    def test_restore_reloads_only_runtime_config_then_is_idempotent(self):
        self.make_state()
        before = {name: path.read_bytes() for name, path in self.files.items()}
        fw.restore_installed()
        self.assertFalse(self.state.exists())
        calls = self.command.call_args_list[:]
        fw.restore_installed()
        self.assertEqual(self.command.call_args_list, calls)
        for name, path in self.files.items():
            self.assertEqual(path.read_bytes(), before[name])
        self.assertEqual([c.args[-1] for c in calls[:2]], ['reconfigure', 'reconnect'])

    def test_changed_config_or_boot_keeps_record_and_refuses_restore_mutation(self):
        self.make_state()
        for path in (self.files['WIFI_CONFIG'], self.paths['/proc/sys/kernel/random/boot_id']):
            with self.subTest(path=path):
                original = path.read_bytes()
                path.write_text('changed')
                with self.assertRaises(ValueError):
                    fw.restore_installed()
                self.command.assert_not_called()
                self.assertTrue((self.state / 'state.json').exists())
                path.write_bytes(original)

    def test_failed_restoration_retains_record_for_retry(self):
        self.make_state()
        with patch.object(fw.time, 'monotonic', side_effect=[0, 61]):
            with self.assertRaisesRegex(ValueError, 'did not recover'):
                fw.restore_installed()
        self.assertTrue((self.state / 'state.json').exists())
        fw.restore_installed()
        self.assertFalse(self.state.exists())

    def test_interrupted_unavailable_window_restores_network_without_firmware_swap(self):
        self.status.side_effect = [{'wpa_state': 'COMPLETED', 'ssid': 'original'},
                                   {'wpa_state': 'SCANNING'},
                                   {'wpa_state': 'COMPLETED', 'ssid': 'original'}]
        before = {name: path.read_bytes() for name, path in self.files.items()}
        with patch.object(fw, 'wifi_checkpoint'), patch.object(fw, 'reconnect'), \
                patch.object(fw, 'installed_observe', side_effect=InterruptedError('lost observer')), \
                patch.object(fw, 'reload') as reload:
            with self.assertRaises(InterruptedError):
                fw.installed_trial(self.lock, 60)
            reload.assert_not_called()
        self.assertFalse(self.state.exists())
        for name, path in self.files.items():
            self.assertEqual(path.read_bytes(), before[name])
        operations = [call.args[3] for call in self.command.call_args_list]
        self.assertIn('select_network', operations)
        self.assertIn('reconfigure', operations)
        self.assertNotIn('save_config', operations)

    def test_preflight_failure_never_claims_state_or_creates_network(self):
        self.status.return_value = {'wpa_state': 'SCANNING'}
        with self.assertRaises(ValueError):
            fw.installed_trial(self.lock, 60)
        self.assertFalse(self.state.exists())
        self.assertNotIn('add_network', [c.args[-1] for c in self.command.call_args_list])


class InstalledHostTests(unittest.TestCase):
    def test_service_installed_mode_restores_config_without_candidate_argument(self):
        script = '/tmp/gameshellneo-firmware.abcdefgh/test-wifi-firmware.py'
        argv = host.service_command(script, 120, installed=True)
        self.assertNotIn('--candidate', argv)
        self.assertIn('--installed', argv)
        self.assertIn('--property=RuntimeMaxSec=1740', argv)
        self.assertIn('--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore --installed', argv)
        for path, seconds, connected in ((script, 59, False), (script, 120, True),
                                         ('/tmp/x; reboot', 120, False)):
            with self.assertRaises(ValueError):
                host.service_command(path, seconds, connected=connected, installed=True)

    def test_all_installed_checkpoints_need_independent_wifi_before_ack(self):
        sink = host.ConnectedCapture(io.BytesIO(), io.StringIO(), MagicMock(), {}, 'boot',
                                     '/tmp/helper.py', host.INSTALLED_PHASES)
        events = []
        with patch.object(host, 'verify_wifi', side_effect=lambda *a: events.append('wifi')), \
                patch.object(host, 'run', side_effect=lambda *a, **k: events.append('ack')):
            for phase in host.INSTALLED_PHASES:
                sink.write((json.dumps(dict(event='wifi_ready', phase=phase, boot_id='boot',
                                           address='192.0.2.2', token='a' * 32)) + '\n').encode())
        self.assertEqual(events, ['wifi', 'ack'] * 7)
        self.assertEqual(sink.phases, host.INSTALLED_PHASES)


if __name__ == '__main__':
    unittest.main()
