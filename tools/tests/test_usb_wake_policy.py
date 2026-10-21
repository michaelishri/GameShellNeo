"""Run the real gadget startup script against isolated sysfs/configfs fixtures."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'runtime/usr/local/sbin/gameshellneo-usb'


class WakePolicy(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.udc = self.root / 'sys/class/udc'
        self.policy = self.udc / 'musb-hdrc.2.auto/device/power/wakeup'
        self.policy.parent.mkdir(parents=True)
        self.policy.write_text('enabled\n')
        self.supplies = [self.root / 'sys/class/power_supply' / name / 'power/wakeup'
                         for name in ('axp20x-usb', 'axp22x-ac')]
        for path in self.supplies:
            path.parent.mkdir(parents=True)
            path.write_text('enabled\n')
        self.controls = [self.policy, *self.supplies]
        self.pek = self.root / 'sys/devices/axp221-pek/power/wakeup'
        self.pek.parent.mkdir(parents=True)
        self.pek.write_text('enabled\n')
        gadget = self.root / 'sys/kernel/config/usb_gadget/gameshellneo'
        gadget.mkdir(parents=True)
        (gadget / 'UDC').write_text('musb-hdrc.2.auto\n')
        # All sysfs/configfs access is redirected. Reaching identity creation is
        # forbidden: this exercises repeated startup of an already bound gadget.
        self.script = SOURCE.read_text().replace('/sys/', str(self.root / 'sys') + '/')
        self.script = self.script.replace('identity=$(cat /etc/machine-id)',
                                          "echo 'UNEXPECTED identity creation' >&2; exit 99")

    def run_start(self, extra=''):
        shims = 'modprobe() { :; }; mountpoint() { return 0; };\n'
        return subprocess.run(['bash', '-c', shims + extra + self.script, 'test', 'start'],
                              capture_output=True, text=True, timeout=5)

    def test_already_bound_start_selects_and_checks_policy_every_time(self):
        for initial in ('enabled', 'disabled'):
            for path in self.controls:
                path.write_text(initial + '\n')
            result = self.run_start()
            self.assertEqual(result.returncode, 0, result.stderr)
            for path in self.controls:
                self.assertEqual(path.read_text(), 'disabled\n')
            self.assertEqual(self.pek.read_text(), 'enabled\n')

    def test_missing_or_unexpected_control_fails_before_gadget_changes(self):
        for value in ('', 'unexpected'):
            self.policy.write_text(value)
            result = self.run_start()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unexpected wake policy', result.stderr)
        self.policy.unlink()
        self.assertIn('Missing wake policy', self.run_start().stderr)

    def test_supply_registration_gap_fails_without_partial_writes_then_recovers(self):
        for path in self.supplies:
            for control in self.controls:
                control.write_text('enabled\n')
            path.unlink()  # device_add has happened, device_init_wakeup has not.
            result = self.run_start()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Missing wake policy control', result.stderr)
            for control in self.controls:
                if control.exists():
                    self.assertEqual(control.read_text(), 'enabled\n')
            path.write_text('enabled\n')
            self.assertEqual(self.run_start().returncode, 0)
            self.assertTrue(all(p.read_text() == 'disabled\n' for p in self.controls))

    def test_invalid_supply_policy_does_not_change_other_sources(self):
        for path in self.supplies:
            for control in self.controls:
                control.write_text('enabled\n')
            path.write_text('invalid\n')
            result = self.run_start()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unexpected wake policy', result.stderr)
            self.assertEqual(self.policy.read_text(), 'enabled\n')
            self.assertEqual(self.pek.read_text(), 'enabled\n')

    def test_ambiguous_or_missing_controller_is_not_selected(self):
        (self.udc / 'second').mkdir()
        self.assertIn('Expected one USB device controller', self.run_start().stderr)
        (self.udc / 'second').rmdir()
        self.policy.unlink()
        for path in (self.policy.parent, self.policy.parent.parent, self.policy.parent.parent.parent):
            path.rmdir()
        self.assertIn('Expected one USB device controller', self.run_start().stderr)

    def test_rejected_readback_stops(self):
        # A sysfs setter may accept the write while policy remains unchanged.
        result = self.run_start('cat() { if [[ $1 == */power/wakeup ]]; then '
                                'echo enabled; else command cat "$@"; fi; };\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Wake policy readback failed', result.stderr)

    def test_supply_setter_that_does_not_take_effect_fails_readback(self):
        for path in self.supplies:
            # Real setter boundary: the first read is enabled and the post-write
            # read must change. Never accept a write-only apparent success.
            result = self.run_start('cat() { if [[ $1 == "' + str(path) +
                                    '" ]]; then echo enabled; else command cat "$@"; fi; };\n')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Wake policy readback failed', result.stderr)


if __name__ == '__main__':
    unittest.main()
