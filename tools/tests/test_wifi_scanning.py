"""Runtime scan controls fail closed and retain restoration state on failure."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('wifi_scanning',
    Path(__file__).resolve().parents[1] / 'test-wifi-scanning.py')
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)


class ScanControlTests(unittest.TestCase):
    def test_set_requires_ack_and_readback_before_reassociation(self):
        for responses in (['FAIL'], ['OK', '0']):
            with patch.object(scan, 'wpa', side_effect=responses) as wpa:
                with self.assertRaises(ValueError):
                    scan.set_value(1)
                self.assertNotIn(('reassociate',), [call.args for call in wpa.call_args_list])
        with patch.object(scan, 'wpa', side_effect=['OK', '1', 'OK']) as wpa:
            scan.set_value(1)
            self.assertEqual(wpa.call_args_list[-1].args, ('reassociate',))

    def test_invalid_get_is_not_treated_as_disabled(self):
        for response in ('FAIL', '', 'UNKNOWN COMMAND'):
            with patch.object(scan, 'wpa', return_value=response):
                with self.assertRaises(ValueError):
                    scan.setting()

    def test_temporarily_disabled_interface_does_not_hide_successful_flag_write(self):
        with patch.object(scan, 'wpa', side_effect=['OK', '0', 'FAIL']):
            self.assertFalse(scan.set_value(0))

    def test_interface_removal_during_sysfs_read_is_recorded(self):
        def read(path):
            if path.name == 'ifindex':
                raise OSError(22, 'Invalid argument')
            return 'test-boot'
        with patch.object(scan.Path, 'read_text', read), patch.object(scan, 'setting', return_value=0), \
                patch.object(scan, 'wpa', return_value='wpa_state=INTERFACE_DISABLED'):
            value = scan.snapshot()
        self.assertIsNone(value['ifindex'])
        self.assertEqual(value['ifindex_error'], 22)
        self.assertEqual(value['wpa_state'], 'INTERFACE_DISABLED')

    def test_restore_keeps_record_until_success_then_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            state.write_text(json.dumps({'original': 0}))
            with patch.object(scan, 'STATE', state), patch.object(scan, 'set_value') as setter:
                setter.side_effect = RuntimeError('offline')
                with self.assertRaises(RuntimeError):
                    scan.restore()
                self.assertTrue(state.exists())
                setter.side_effect = None
                scan.restore()
                self.assertFalse(state.exists())
                scan.restore()
                self.assertEqual(setter.call_count, 2)

    def test_interrupted_measurement_restores_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            with patch.object(scan, 'STATE', state), patch.object(scan, 'setting', return_value=0), \
                    patch.object(scan, 'set_value') as setter, patch.object(scan, 'emit'), \
                    patch.object(scan.time, 'sleep', side_effect=InterruptedError):
                with self.assertRaises(InterruptedError):
                    scan.measure(60)
                self.assertEqual([call.args for call in setter.call_args_list], [(0,), (0,)])
                self.assertFalse(state.exists())

    def test_counts_distinguish_firmware_crash_and_bus_removal(self):
        log = ('ieee80211 phy1: brcmf_fw_crashed: Firmware has halted or crashed\n'
               'mmc1: card 0001 removed\nnormal message\n')
        with patch.object(scan, 'command', return_value=log):
            self.assertEqual(scan.kernel_counts(), {'firmware_crashes': 1, 'sdio_removals': 1})


if __name__ == '__main__':
    unittest.main()
