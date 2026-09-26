import importlib.util
from pathlib import Path
import tempfile
import unittest

source = Path(__file__).resolve().parents[1] / 'usr/local/lib/gameshellneo/battery_guard.py'
spec = importlib.util.spec_from_file_location('battery', source)
battery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(battery)


class BatteryTests(unittest.TestCase):
    def test_three_consecutive_low_readings(self):
        guard = battery.Guard()
        sample = {'status': 'Discharging', 'capacity_percent': 10}
        self.assertFalse(guard.update(sample, 0))
        self.assertFalse(guard.update(sample, 10))
        self.assertTrue(guard.update(sample, 20))

    def test_invalid_charging_recovery_and_gap_reset(self):
        low = {'status': 'Discharging', 'capacity_percent': 0}
        for reset in (None, {'status': 'Charging', 'capacity_percent': 0},
                      {'status': 'Discharging', 'capacity_percent': 11}):
            guard = battery.Guard()
            guard.update(low, 0)
            guard.update(low, 10)
            self.assertFalse(guard.update(reset, 20))
            self.assertFalse(guard.update(low, 30))
        guard = battery.Guard()
        guard.update(low, 0)
        guard.update(low, 10)
        self.assertFalse(guard.update(low, 40))
        self.assertFalse(guard.update(low, 40.1))

    def test_sysfs_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supply = root / 'axp-battery'
            supply.mkdir()
            valid = dict(type='Battery', present='1', capacity='10',
                         status='Discharging', voltage_now='3600000')
            for name, value in valid.items():
                (supply / name).write_text(value + '\n')
            self.assertEqual(battery.read_sample(root)['capacity_percent'], 10)
            for name, value in (('present', '0'), ('capacity', '-1'), ('capacity', '101'),
                                ('capacity', 'oops'), ('status', 'Unknown'), ('voltage_now', '0')):
                (supply / name).write_text(value)
                with self.assertRaises(ValueError):
                    battery.read_sample(root)
                (supply / name).write_text(valid[name])
            (supply / 'capacity').unlink()
            with self.assertRaises(OSError):
                battery.read_sample(root)


if __name__ == '__main__':
    unittest.main()
