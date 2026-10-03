import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

source = (Path(os.environ['NEO_BATTERY_MODULE']) if 'NEO_BATTERY_MODULE' in os.environ
          else Path(__file__).resolve().parents[1] / 'usr/local/lib/gameshellneo/battery_guard.py')
digest = hashlib.sha256(source.read_bytes()).hexdigest()
if os.environ.get('NEO_BATTERY_SHA256', digest) != digest:
    raise RuntimeError('Installed battery guard differs from the expected source')
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


class SimulationComplete(Exception):
    """End a finite input sequence without altering the guard's control flow."""


class BatteryLoopTests(unittest.TestCase):
    """Run the actual main loop with fake sysfs, time and shutdown delivery."""

    def simulate(self, samples, times=None, returns=(0,), monotonic_times=None,
                 read_seconds=None, read_sleep=None):
        times = times if times is not None else [10 * i for i in range(len(samples))]
        monotonic_times = monotonic_times if monotonic_times is not None else times
        read_seconds = read_seconds if read_seconds is not None else [0] * len(samples)
        read_sleep = read_sleep if read_sleep is not None else [0] * len(samples)
        self.assertEqual(len(samples), len(times))
        states, requests = [], []
        tick = 0
        read_finished = False
        reader = battery.read_sample
        with tempfile.TemporaryDirectory(prefix='gameshellneo-battery-test.') as directory:
            root = Path(directory)
            supplies = root / 'supplies'
            supply = supplies / 'battery'
            supply.mkdir(parents=True)
            output = root / 'state'
            boot_file = root / 'boot-id'
            boot_file.write_text('test-boot\n')

            def sample():
                nonlocal read_finished
                values = dict(type='Battery', present='1', capacity='10',
                              status='Discharging', voltage_now='3600000')
                values.update(samples[tick])
                for name, value in values.items():
                    path = supply / name
                    if value is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_text(str(value) + '\n')
                try:
                    return reader(supplies)
                finally:
                    read_finished = True

            def monotonic_ns():
                return round((monotonic_times[tick] + (read_seconds[tick] if read_finished else 0)) * 1e9)

            def boottime_ns(clock):
                self.assertEqual(clock, 7)
                return round((times[tick] + (read_seconds[tick] + read_sleep[tick] if read_finished else 0)) * 1e9)

            def sleep(seconds):
                nonlocal tick, read_finished
                self.assertEqual(seconds, 10)
                tick += 1
                read_finished = False
                if tick == len(samples):
                    raise SimulationComplete()

            def state_directory(path):
                if path == '/proc/sys/kernel/random/boot_id':
                    return boot_file
                self.assertEqual(path, '/run/gameshellneo')
                return output

            def publish(src, dst):
                self.assertEqual(src, output / 'battery.json.tmp')
                self.assertEqual(dst, output / 'battery.json')
                os.replace(src, dst)
                states.append(json.loads(dst.read_text()))

            def poweroff(args, *, check):
                self.assertEqual(args, ['systemctl', '--no-block', 'poweroff'])
                self.assertFalse(check)
                self.assertLess(len(requests), len(returns), 'Unexpected shutdown retry')
                code = returns[len(requests)]
                requests.append({'time': times[tick], 'returncode': code})
                return SimpleNamespace(returncode=code)

            # Replace module references only in this test process. The real service,
            # /sys and /run/gameshellneo are never written or stopped by the tests.
            with patch.object(battery, 'Path', state_directory), \
                    patch.object(battery, 'read_sample', sample), \
                    patch.object(battery, 'time', SimpleNamespace(
                        monotonic_ns=monotonic_ns, clock_gettime_ns=boottime_ns,
                        CLOCK_BOOTTIME=7, sleep=sleep)), \
                    patch.object(battery, 'os', SimpleNamespace(replace=publish)), \
                    patch.object(battery, 'subprocess', SimpleNamespace(run=poweroff)), \
                    patch.object(battery, 'logging', Mock(INFO=20)):
                try:
                    battery.main()
                except SimulationComplete:
                    pass
            self.assertEqual(len(states), len(samples), 'Guard exited before the expected sample')
            self.assertFalse((output / 'battery.json.tmp').exists())
        return states, requests

    def test_boundary_requests_once_after_three_valid_samples(self):
        states, requests = self.simulate([{}, {}, {}])
        self.assertEqual([s['consecutive_low_samples'] for s in states], [1, 2, 3])
        self.assertEqual(requests, [{'time': 20, 'returncode': 0}])
        self.assertTrue(all(s['monitoring'] == 'valid' for s in states))
        self.assertTrue(all(s['schema_version'] == 2 and s['sample_clock'] == 'CLOCK_BOOTTIME'
                            and s['boot_id'] == 'test-boot' for s in states))
        self.assertEqual([s['boottime_seconds'] for s in states], [0, 10, 20])
        self.assertTrue(all('monotonic_seconds' not in s for s in states))

    def test_sleep_breaks_consecutive_window_with_monotonic_frozen(self):
        for boot, mono in (([0, 10, 3610, 3620, 3630], [0, 10, 20, 30, 40]),
                           ([0, 10, 20, 30, 40], [0, 10, 19, 29, 39])):
            with self.subTest(boottime=boot):
                states, requests = self.simulate([{}] * 5, times=boot, monotonic_times=mono)
                self.assertEqual([s['consecutive_low_samples'] for s in states], [1, 2, 1, 2, 3])
                self.assertEqual(requests, [{'time': boot[-1], 'returncode': 0}])
                self.assertEqual([s['sample_monotonic_seconds'] for s in states], mono)

    def test_slow_or_suspended_sysfs_read_is_degraded_and_cannot_power_off(self):
        for duration, sleep_gap in ((3, 0), (0, 0.1), (0, 10)):
            boot = [0, 10, 20, 30 + sleep_gap, 40 + sleep_gap, 50 + sleep_gap]
            with self.subTest(duration=duration, sleep=sleep_gap):
                states, requests = self.simulate([{}] * 6, times=boot,
                    monotonic_times=[0, 10, 20, 30, 40, 50],
                    read_seconds=[0, 0, duration, 0, 0, 0], read_sleep=[0, 0, sleep_gap, 0, 0, 0])
                self.assertEqual([s['consecutive_low_samples'] for s in states], [1, 2, 0, 1, 2, 3])
                self.assertEqual(states[2]['monitoring'], 'degraded')
                self.assertNotIn('capacity_percent', states[2])
                self.assertEqual(states[2]['boottime_seconds'], 20)
                self.assertEqual(requests, [{'time': boot[-1], 'returncode': 0}])

    def test_clock_bracketing_does_not_confuse_syscall_latency_with_sleep(self):
        with patch.object(battery.time, 'monotonic_ns', side_effect=[10, 14]), \
                patch.object(battery.time, 'clock_gettime_ns', return_value=20):
            value = battery.clocks()
        self.assertEqual(value['gap_low'], 6)
        self.assertEqual(value['gap_high'], 10)
        self.assertFalse(battery.crossed_suspend(value, dict(gap_low=9, gap_high=12)))
        self.assertTrue(battery.crossed_suspend(value, dict(gap_low=11, gap_high=12)))

    def test_above_threshold_and_external_power_do_not_request_shutdown(self):
        for reading in ({'capacity': '11'}, {'status': 'Charging', 'capacity': '0'},
                        {'status': 'Full', 'capacity': '0'},
                        {'status': 'Not charging', 'capacity': '0'}):
            with self.subTest(reading=reading):
                states, requests = self.simulate([reading] * 3)
                self.assertEqual(requests, [])
                self.assertTrue(all(s['consecutive_low_samples'] == 0 for s in states))

    def test_invalid_input_publishes_degraded_and_restarts_observation(self):
        for invalid in ({'capacity': 'oops'}, {'capacity': None}, {'present': '0'},
                        {'status': 'Unknown'}, {'voltage_now': '0'}):
            with self.subTest(invalid=invalid):
                states, requests = self.simulate([{}, {}, invalid, {}, {}, {}])
                self.assertEqual([s['consecutive_low_samples'] for s in states], [1, 2, 0, 1, 2, 3])
                self.assertEqual(states[2]['monitoring'], 'degraded')
                self.assertIn('reason', states[2])
                self.assertNotIn('capacity_percent', states[2])
                self.assertEqual(requests, [{'time': 50, 'returncode': 0}])

    def test_charging_or_recovered_capacity_cancels_pending_shutdown(self):
        for reset in ({'status': 'Charging'}, {'capacity': '11'}):
            with self.subTest(reset=reset):
                states, requests = self.simulate([{}, {}, reset, {}, {}, {}])
                self.assertEqual([s['consecutive_low_samples'] for s in states], [1, 2, 0, 1, 2, 3])
                self.assertEqual(requests, [{'time': 50, 'returncode': 0}])

    def test_delayed_and_too_fast_samples_restart_observation(self):
        for times in ([0, 10, 40, 50, 60], [0, 10, 10.1, 20.1, 30.1]):
            with self.subTest(times=times):
                states, requests = self.simulate([{}] * 5, times=times)
                self.assertEqual([s['consecutive_low_samples'] for s in states], [1, 2, 1, 2, 3])
                self.assertEqual(requests, [{'time': times[-1], 'returncode': 0}])

    def test_rejected_poweroff_is_retried_on_the_next_valid_sample(self):
        states, requests = self.simulate([{}] * 4, returns=(1, 0))
        self.assertEqual(requests, [{'time': 20, 'returncode': 1}, {'time': 30, 'returncode': 0}])
        self.assertEqual(states[-1]['consecutive_low_samples'], 4)


if __name__ == '__main__':
    print('Battery guard under test:', source, 'SHA-256:', digest, flush=True)
    unittest.main()
