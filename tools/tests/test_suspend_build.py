"""Separate staged suspend support from unqualified USB experiment combinations."""
import importlib.util
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import usb_poll_boot
import keypad_supply

spec = importlib.util.spec_from_file_location('kernel_config', TOOLS / 'check-kernel-config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class SuspendBuildTests(unittest.TestCase):
    def test_retention_is_explicit_and_isolated(self):
        self.assertFalse(keypad_supply.enabled({}))
        self.assertTrue(keypad_supply.enabled({'experiments': {
            'suspend_diagnostics': True, 'keypad_supply_retention': True}}))
        for experiments in ({'keypad_supply_retention': True},
                            {'suspend_diagnostics': 1, 'keypad_supply_retention': True},
                            {'suspend_diagnostics': True, 'keypad_supply_retention': False},
                            {'suspend_diagnostics': True, 'keypad_supply_retention': 1},
                            {'suspend_diagnostics': True, 'keypad_supply_retention': True,
                             'usb_absent_poll': False}):
            with self.assertRaises(ValueError):
                config.requirements({}, {'experiments': experiments})

    def test_sleep_image_requires_debug_gates_and_excludes_automatic_sleep(self):
        required = config.requirements({}, {'experiments': {'suspend_diagnostics': True}})
        for option in ('CONFIG_SUSPEND', 'CONFIG_SUSPEND_FREEZER', 'CONFIG_FREEZER',
                       'CONFIG_PM_SLEEP', 'CONFIG_PM_DEBUG', 'CONFIG_PM_SLEEP_DEBUG'):
            self.assertEqual(required[option], 'y')
        for option in ('CONFIG_HIBERNATION', 'CONFIG_PM_AUTOSLEEP', 'CONFIG_PM_WAKELOCKS',
                       'CONFIG_ARM_PSCI_CPUIDLE', 'CONFIG_PM_TEST_SUSPEND'):
            self.assertEqual(required[option], 'n')

    def test_usb_experiments_retain_no_sleep_requirement(self):
        for mode in (True, False):
            required = config.requirements({}, {'experiments': {'usb_absent_poll': mode}})
            self.assertEqual(required['CONFIG_PM_SLEEP'], 'n')
            self.assertEqual(required['CONFIG_USB_MUSB_GADGET'], 'y')

    def test_mixed_or_malformed_opt_ins_fail_before_build(self):
        for extra in ({'usb_absent_poll': False}, {'usb_absent_poll': True}, {'usb_diagnostics': False}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                config.requirements({}, {'experiments': {'suspend_diagnostics': True} | extra})
        for value in ('true', 1, None):
            with self.assertRaises(ValueError):
                config.requirements({}, {'experiments': {'suspend_diagnostics': value}})

    def test_sleep_boot_defaults_to_s2idle_without_usb_opt_ins(self):
        source = usb_poll_boot.boot_script('1234abcd-02', suspend_tests=True)
        self.assertIn(b'mem_sleep_default=s2idle', source)
        self.assertNotIn(b'gameshellneo_slow_poll=', source)
        self.assertNotIn(b'gameshellneo_diagnostics=', source)
        self.assertNotIn(b'test_suspend=', source)
        self.assertNotIn(b'mem_sleep_default', usb_poll_boot.boot_script('1234abcd-02'))
        for mode, diagnostics in (('stock', False), ('experimental', False), (None, True)):
            with self.assertRaises(ValueError):
                usb_poll_boot.boot_script('1234abcd-02', mode, diagnostics, suspend_tests=True)


if __name__ == '__main__':
    unittest.main()
