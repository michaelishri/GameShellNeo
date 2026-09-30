"""Keep a successful recorder distinct from positive keypad continuity evidence."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('retention_host', TOOLS/'check-pm-stages.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class RetentionTests(unittest.TestCase):
    def fixture(self):
        info = dict(usb=dict(power=dict(persist='1', control='on', wakeup=None),
                             attributes=dict(devnum='2')), inputs=[dict(sysfs='/input/input1/event1')])
        return dict(before=dict(keypad_retains_supply=True), after=dict(keypad_retains_supply=True),
                    run_id='a'*32, stage_seconds=5.5, keypad_ready_after_stage=dict(seconds=0.01),
                    journal_delta='', keypad=dict(before=info, after=deepcopy(info),
                    old_handle_after=dict(ioctl_errno=None, disconnected=False),
                    trace_overrun=False, trace_restored=True, trace='bounded trace'))

    def test_healthy_and_reenumerated_results_are_distinguished(self):
        result = self.fixture()
        self.assertTrue(host.retention_result(result)['original_handle_healthy'])
        result['keypad']['old_handle_after'] = dict(ioctl_errno=19, disconnected=True)
        result['keypad']['after']['usb']['attributes']['devnum'] = '3'
        result['journal_delta'] = 'usb 1-1: USB disconnect, device number 2\n'
        summary = host.retention_result(result)
        self.assertFalse(summary['original_handle_healthy'])
        self.assertFalse(summary['usb_device_number_unchanged'])
        self.assertEqual(summary['keypad_disconnects'], 1)

    def test_missing_retention_lost_trace_or_supply_disable_is_rejected(self):
        for key, value in (('trace_overrun', True), ('trace_restored', False),
                           ('trace', '0.42: regulator_disable: name=keypad-vbus'),
                           ('trace', '0.42: regulator_disable_complete: name=keypad-vbus')):
            result = self.fixture()
            result['keypad'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                host.retention_result(result)
        result = self.fixture()
        result['after']['keypad_retains_supply'] = False
        with self.assertRaises(ValueError):
            host.retention_result(result)

    def test_persistence_comparison_refuses_retention_image(self):
        with self.assertRaises(ValueError):
            host.compare_keypad({}, None, {'experiments': {'keypad_supply_retention': True}})


if __name__ == '__main__':
    unittest.main()
