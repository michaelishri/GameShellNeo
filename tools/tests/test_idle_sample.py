import importlib.util
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[1] / 'sample-idle.py'
spec = importlib.util.spec_from_file_location('idle_sample', source)
idle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(idle)


class IdleUnits(unittest.TestCase):
    @staticmethod
    def reading(seconds, current_ua):
        return dict(monotonic_seconds=seconds, current_ua=current_ua, voltage_uv=4000000,
                    capacity_percent=80, frequency_khz=120000, temperature_millic=40000)

    def test_one_amp_hour_at_four_volts(self):
        result = idle.summarize([self.reading(0, -1000000), self.reading(3600, -1000000)])
        self.assertEqual(result['estimated_charge_mah'], 1000)
        self.assertEqual(result['estimated_energy_mwh'], 4000)
        self.assertEqual(result['time_weighted_current_ma'], 1000)
        self.assertEqual(result['time_weighted_power_mw'], 4000)

    def test_nonuniform_samples_use_elapsed_time(self):
        # 100 mA for ten seconds, then a linear rise to 300 mA over twenty seconds.
        result = idle.summarize([self.reading(0, -100000), self.reading(10, -100000),
                                 self.reading(30, -300000)])
        self.assertAlmostEqual(result['estimated_charge_mah'], 1.3888888889)
        self.assertAlmostEqual(result['estimated_energy_mwh'], 5.5555555556)
        self.assertAlmostEqual(result['time_weighted_current_ma'], 166.6666666667)

    def test_nonincreasing_time_is_rejected(self):
        with self.assertRaises(ValueError):
            idle.summarize([self.reading(10, -100000), self.reading(10, -100000)])
