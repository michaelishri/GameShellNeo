import importlib.util
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch
from awake_fixtures import window

source = Path(__file__).resolve().parents[1] / 'sample-idle.py'
spec = importlib.util.spec_from_file_location('idle_sample', source)
idle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(idle)


class IdleUnits(unittest.TestCase):
    @staticmethod
    def reading(seconds, current_ua):
        return dict(monotonic_seconds=seconds, awake_window=window(seconds), current_ua=current_ua, voltage_uv=4000000,
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


class BacklightRestoration(unittest.TestCase):
    def test_restore_after_success_failure_or_termination(self):
        for outcome in ('success', 'failure', 'termination'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for name, value in dict(brightness='1', max_brightness='31', bl_power='0').items():
                    (root / name).write_text(value)
                # Model hardware that immediately reports the requested brightness.
                (root / 'actual_brightness').symlink_to(root / 'brightness')
                with patch.object(idle, 'emit'), patch('speaker_audio.warn_screen'):
                    try:
                        with idle.backlight_mode('off', root):
                            self.assertEqual((root / 'brightness').read_text().strip(), '0')
                            if outcome == 'failure':
                                raise OSError('Lost sampling input')
                            if outcome == 'termination':
                                idle.interrupted(signal.SIGTERM, None)
                    except OSError:
                        self.assertNotEqual(outcome, 'success')
                self.assertEqual((root / 'brightness').read_text().strip(), '1')

    def test_failed_off_readback_restores_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, value in dict(brightness='1', actual_brightness='1',
                                    max_brightness='31', bl_power='0').items():
                (root / name).write_text(value)
            with patch.object(idle, 'emit'), patch('speaker_audio.warn_screen'), \
                    self.assertRaisesRegex(ValueError, 'did not report off'):
                with idle.backlight_mode('off', root):
                    self.fail('Must not begin measurement after failed off readback')
            self.assertEqual((root / 'brightness').read_text().strip(), '1')

    def test_failed_warning_keeps_display_lit_and_skips_measurement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, value in dict(brightness='1', max_brightness='31', bl_power='0').items():
                (root/name).write_text(value)
            with patch('speaker_audio.warn_screen', side_effect=RuntimeError('speaker')), \
                    self.assertRaisesRegex(RuntimeError, 'speaker'):
                with idle.backlight_mode('off', root):
                    self.fail('Cannot begin a blank-screen measurement after a failed warning')
            self.assertEqual((root/'brightness').read_text(), '1')
