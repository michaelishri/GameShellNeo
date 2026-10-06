"""Prevent power transitions, sleep gaps and incomplete traces from passing."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, TOOLS/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sampler = load('charge_sampler', 'sample-charge.py')
host = load('charge_baseline_host', 'check-charge-baseline.py')


def checkpoint(now, offset=1_000_000_000):
    return dict(boot_id='fixture', pm={'success': '11', 'fail': '0'},
        clock=dict(monotonic_before_ns=now, monotonic_after_ns=now+100,
                   boottime_ns=now+offset+50, offset_low_ns=offset-50,
                   offset_high_ns=offset+50))


def sample(index, current=300000):
    now = 100_000_000_000+index*10_000_000_000
    return dict(index=index, before=checkpoint(now), after=checkpoint(now+10_000_000),
        supplies={
            'axp20x-battery': dict(type='Battery', present='1', health='Good', status='Charging',
                capacity='80', current_now=str(current), voltage_now='4100000', voltage_max='4200000',
                constant_charge_current='1200000', constant_charge_current_max='1200000'),
            'axp20x-usb': dict(type='USB', present='1', online='1', input_current_limit='900000'),
            'axp22x-ac': dict(type='Mains', present='1', online='1')},
        state=dict(brightness='1', bl_power='0', temperature_millic='45000', taint='0'))


class Baseline(unittest.TestCase):
    def test_constant_and_varying_currents_use_elapsed_time_and_uah_units(self):
        samples = [sample(i) for i in range(7)]
        result = sampler.summary(samples, 60)
        self.assertEqual(result['sampled_net_charge_estimate_uah'], 5000)
        self.assertEqual(result['elapsed_seconds'], 60)
        self.assertFalse(result['sleep_charge_measured'])
        samples = [sample(i, i*100000) for i in range(7)]
        self.assertEqual(sampler.summary(samples, 60)['sampled_net_charge_estimate_uah'], 5000)

    def test_unplug_bad_health_invalid_number_low_battery_and_discharge_stop(self):
        modifications = [
            ('axp20x-usb', 'present', '0'), ('axp22x-ac', 'online', '0'),
            ('axp20x-battery', 'present', '0'), ('axp20x-battery', 'health', 'Unknown'),
            ('axp20x-battery', 'capacity', '20'), ('axp20x-battery', 'capacity', '101'),
            ('axp20x-battery', 'current_now', '-1000'), ('axp20x-battery', 'current_now', 'NaN'),
            ('axp20x-battery', 'voltage_now', '-1'), ('axp20x-battery', 'status', 'Discharging')]
        for supply, field, value in modifications:
            s = sample(0); s['supplies'][supply][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                sampler.validate(s)

    def test_display_temperature_and_charger_changes_stop_without_writes(self):
        for field, value in [('brightness', '2'), ('bl_power', '4'), ('taint', '1'),
                             ('temperature_millic', '80000')]:
            s = sample(1); s['state'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                sampler.validate(s, sample(0))
        for field in ('constant_charge_current', 'constant_charge_current_max', 'voltage_max'):
            s = sample(1); s['supplies']['axp20x-battery'][field] = '1'
            with self.subTest(field=field), self.assertRaises(ValueError):
                sampler.validate(s, sample(0))
        s = sample(1); s['supplies']['axp20x-usb']['input_current_limit'] = '100000'
        with self.assertRaises(ValueError):
            sampler.validate(s, sample(0))

    def test_sleep_during_read_and_between_samples_cannot_be_integrated(self):
        for point in ('before', 'after'):
            s = sample(1)
            s[point] = checkpoint(s[point]['clock']['monotonic_before_ns'], offset=31_000_000_000)
            with self.subTest(point=point), self.assertRaises(ValueError):
                sampler.validate(s, sample(0))
        s = sample(1)
        s['before']['pm']['success'] = s['after']['pm']['success'] = '12'
        with self.assertRaises(ValueError):
            sampler.validate(s, sample(0))

    def test_slow_missing_duplicate_and_boot_changed_samples_fail(self):
        before = sample(0)
        slow = sample(1); slow['after'] = checkpoint(114_000_000_000)
        missing = sample(2); missing['index'] = 1
        reboot = sample(1); reboot['before']['boot_id'] = 'other'
        for s in (slow, missing, sample(0), reboot):
            with self.subTest(sample=s), self.assertRaises(ValueError):
                sampler.validate(s, before)
        with self.assertRaises(ValueError):
            sampler.summary([sample(i) for i in range(6)], 60)

    def test_whole_sequence_duration_must_match_despite_individually_allowed_gaps(self):
        samples = [sample(i) for i in range(7)]
        for i, s in enumerate(samples):
            for point in ('before','after'):
                s[point] = checkpoint(s[point]['clock']['monotonic_before_ns']+i*1_000_000_000)
        with self.assertRaisesRegex(ValueError, 'duration'):
            sampler.summary(samples, 60)

    def test_rejected_observation_saved_and_no_following_sample_runs(self):
        captures = [sample(0), sample(1), sample(2)]
        captures[-1]['supplies']['axp20x-usb']['online'] = '0'
        output = io.StringIO()
        with patch.object(sampler, 'capture', side_effect=captures) as capture, \
                patch.object(sampler.time, 'monotonic_ns', side_effect=[0, 0, 10**10, 2*10**10]), \
                patch.object(sampler.time, 'sleep') as sleep, contextlib.redirect_stdout(output):
            with self.assertRaises(ValueError):
                sampler.collect(60)
        self.assertEqual(capture.call_count, 3)
        sleep.assert_not_called()
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]['sample']['supplies']['axp20x-usb']['online'], '0')

    def test_full_battery_zero_current_is_recorded_without_charge_claim(self):
        samples = [sample(i, 0) for i in range(7)]
        for s in samples:
            s['supplies']['axp20x-battery'].update(capacity='100', status='Full')
        result = sampler.summary(samples, 60)
        self.assertEqual(result['sampled_net_charge_estimate_uah'], 0)
        self.assertFalse(result['sleep_charge_measured'])


class Transport(unittest.TestCase):
    def test_composed_source_runs_outside_checkout_and_retains_helper_hashes(self):
        source, hashes = host.payload()
        self.assertEqual(set(hashes), {'sample_charge', 'charge_inventory'})
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, '-B', '-', '--help'], input=source,
                cwd=temporary, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'--seconds', result.stdout)

    def test_invalid_duration_rejected_before_device_or_inventory_access(self):
        for seconds in ('0', '59', '61', '610', '1000000'):
            with self.subTest(seconds=seconds), patch.dict(host.os.environ, NEO_CHARGE_SECONDS=seconds), \
                    patch.object(host, 'device') as device:
                with self.assertRaises(ValueError):
                    host.main()
                device.assert_not_called()

    def test_termination_records_failure_not_a_partial_pass(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['sample-charge.py', '--kernel', 'test', '--image', 'test']), \
                patch.object(sampler.signal, 'signal'), \
                patch.object(sampler.inventory, 'inspect'), \
                patch.object(sampler, 'collect', side_effect=InterruptedError('interrupted')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(sampler.main(), 1)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[-1]['event'], 'failed')
        self.assertFalse(rows[-1]['passed'])
        self.assertNotIn('completed', [r['event'] for r in rows])


if __name__ == '__main__':
    unittest.main()
