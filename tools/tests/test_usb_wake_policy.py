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
            self.policy.write_text(initial + '\n')
            result = self.run_start()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.policy.read_text(), 'disabled\n')

    def test_missing_or_unexpected_control_fails_before_gadget_changes(self):
        for value in ('', 'unexpected'):
            self.policy.write_text(value)
            result = self.run_start()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Unexpected USB wake policy', result.stderr)
        self.policy.unlink()
        self.assertIn('Missing USB wake policy', self.run_start().stderr)

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
        self.assertIn('USB wake policy readback failed', result.stderr)


if __name__ == '__main__':
    unittest.main()
