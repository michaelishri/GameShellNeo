"""Separate staged suspend support from unqualified USB experiment combinations."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import usb_poll_boot
import keypad_supply

spec = importlib.util.spec_from_file_location('kernel_config', TOOLS / 'check-kernel-config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class SuspendBuildTests(unittest.TestCase):
    def test_checker_rejects_missing_or_disabled_ext4_security_without_fragment_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'kernel').mkdir()
            (root / 'build').mkdir()
            (root / 'kernel/gameshellneo.config').write_text('CONFIG_EXT4_FS=y\n')
            (root / 'build/sources.lock.json').write_text('{}\n')
            resolved = root / 'resolved.config'
            base = ''.join(key + '=y\n' for key in (
                'CONFIG_EXT4_FS', 'CONFIG_MMC_BLOCK', 'CONFIG_BLK_DEV_SD',
                'CONFIG_SERIAL_8250_CONSOLE', 'CONFIG_UNIX', 'CONFIG_INET',
                'CONFIG_PROC_FS', 'CONFIG_SYSFS'))
            with patch.object(config, 'ROOT', root), \
                    patch.object(sys, 'argv', ['check-kernel-config.py', str(resolved)]):
                for option in ('', 'CONFIG_EXT4_FS_SECURITY=n\n'):
                    resolved.write_text(base + option)
                    with self.subTest(option=option), self.assertRaisesRegex(
                            SystemExit, 'CONFIG_EXT4_FS_SECURITY: requested y, resolved n'):
                        config.main()
                resolved.write_text(base + 'CONFIG_EXT4_FS_SECURITY=y\n')
                with patch('builtins.print'):
                    config.main()

    def test_ext4_security_attributes_are_required_without_lsms_or_experiments(self):
        for lock, variant in (({}, None), ({}, 'enabled'), ({}, 'disabled'),
                              ({'experiments': {'suspend_diagnostics': True}}, None)):
            with self.subTest(lock=lock, variant=variant):
                required = config.requirements({'CONFIG_EXT4_FS_SECURITY': 'n'}, lock,
                                               clock_diagnostics_test=variant)
                self.assertEqual(required['CONFIG_EXT4_FS_SECURITY'], 'y')
                self.assertNotIn('CONFIG_SECURITY', required)

    def test_current_image_composition_and_unknown_experiments(self):
        import json
        lock = json.loads((TOOLS.parent / 'build/sources.lock.json').read_text())
        required = config.requirements({}, lock)
        self.assertEqual(required['CONFIG_NEO_CLOCK_DIAG'], 'y')
        self.assertTrue(keypad_supply.enabled(lock))
        for value in (True, False):
            variant = dict(lock, experiments=lock['experiments'] | {'clock_provenance': value})
            self.assertTrue(keypad_supply.enabled(variant))
        for extra in ({'clock_provenance': 1}, {'clock_provenance': 'true'},
                      {'unqualified_experiment': True}, {'usb_absent_poll': False}):
            variant = dict(lock, experiments=lock['experiments'] | extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                config.requirements({}, variant)

    def test_clock_diagnostic_opt_in_and_object_test_do_not_drop_other_gates(self):
        lock = {'experiments': {'suspend_diagnostics': True, 'clock_provenance': True}}
        requested = dict(CONFIG_USB_MUSB_GADGET='y', CONFIG_NEO_CLOCK_DIAG='y',
                         CONFIG_NEO_CLOCK_DIAG_KUNIT_TEST='y')
        required = config.requirements(requested, lock)
        self.assertEqual(required['CONFIG_NEO_CLOCK_DIAG'], 'y')
        self.assertEqual(required['CONFIG_NEO_CLOCK_DIAG_KUNIT_TEST'], 'n')
        for key in ('CONFIG_ARM_ARCH_TIMER', 'CONFIG_DEBUG_FS', 'CONFIG_IKCONFIG_PROC',
                    'CONFIG_POSIX_TIMERS', 'CONFIG_AEABI'):
            self.assertEqual(required[key], 'y')
        # The disabled test may change only the recorder, including when the
        # fragment relies on the selector to assert its dependencies.
        disabled = config.requirements(requested, lock, clock_diagnostics_test='disabled')
        self.assertEqual(disabled, required | {'CONFIG_NEO_CLOCK_DIAG': 'n'})
        self.assertEqual(config.requirements({}, {})['CONFIG_NEO_CLOCK_DIAG'], 'n')
        self.assertEqual(config.requirements({}, {}, clock_diagnostics_test='enabled')
                         ['CONFIG_NEO_CLOCK_DIAG'], 'y')
        for value in ('true', 1, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.requirements({}, {'experiments': {'clock_provenance': value}})
        with self.assertRaises(ValueError):
            config.requirements({}, lock, clock_diagnostics_test='anything')

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
