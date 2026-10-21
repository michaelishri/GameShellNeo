"""Bounded capture preserves raw regressions without treating them as healthy PM."""
import copy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, TOOLS / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


recorder = module('clock_observer_test', 'observe-clocks.py')
host = module('clock_observer_host_test', 'check-clock-observation.py')


def sample(n=0, **changes):
    return dict(dict(cpu_before=0, cpu_after=0, raw_left=n, raw_right=n+8,
                     monotonic_left=n+1, monotonic_right=n+5, boottime=n+100), **changes)


class ClockObservationTests(unittest.TestCase):
    def test_exact_fixed_work_and_equal_ticks_are_accepted(self):
        read = Mock(return_value=sample(monotonic_right=1))
        pause = Mock()
        result = recorder.observe(read, pause, batches=2, per_batch=3)
        self.assertEqual(read.call_count, 6)
        self.assertEqual(pause.call_count, 2)
        self.assertEqual(result['samples'], 6)
        self.assertEqual(result['min_monotonic_bracket_ns'], 0)
        self.assertNotIn('monotonic_bracket', result['regressions'])

    def test_original_backward_bracket_is_preserved(self):
        bad = sample(20, monotonic_right=19, cpu_after=1)
        result = recorder.observe(iter([sample(), bad]).__next__, lambda _: None, 1, 2)
        self.assertEqual(result['regression_samples'], 1)
        self.assertEqual(result['regressions'], {'monotonic_bracket': 1})
        self.assertEqual(result['anomalies'][0]['sample'], bad)
        self.assertEqual(result['min_monotonic_bracket_ns'], -2)
        self.assertEqual(result['cpu_brackets_differ'], 1)

    def test_each_cross_call_source_regression_is_identified(self):
        before = sample(100)
        after = sample(200, monotonic_left=99, raw_left=99, boottime=99)
        self.assertEqual(set(recorder.regressions(before, after)),
                         {'monotonic_between', 'raw_between', 'boottime_between'})

    def test_cap_keeps_first_raw_events_and_total_counts(self):
        read = Mock(return_value=sample(monotonic_right=-1))
        result = recorder.observe(read, lambda _: None, 1, 40)
        self.assertEqual(len(result['anomalies']), 32)
        self.assertEqual(result['regression_samples'], 40)
        self.assertTrue(result['anomalies_truncated'])
        self.assertEqual(result['regressions']['monotonic_bracket'], 40)

    def test_reader_failure_propagates_without_retry(self):
        read = Mock(side_effect=OSError('clock read failed'))
        with self.assertRaises(OSError):
            recorder.observe(read, Mock(), 1, 5)
        self.assertEqual(read.call_count, 1)

    def test_host_rejects_missing_work_changed_state_and_forged_anomaly(self):
        before = {k: 'same' for k in ('boot_id', 'image', 'kernel', 'pm', 'stats',
            'services', 'backlight', 'usb', 'charger', 'cpu_policy', 'wifi_config_sha256',
            'taint', 'failed_units')}
        values = iter([sample(), sample(20, monotonic_right=19)])
        observation = recorder.observe(values.__next__, lambda _: None, 1, 2)
        observation['samples'] = 60000
        result = dict(schema=1, operation='awake-clock-observation', complete=True,
                      batches=300, per_batch=200, pause_seconds=0.1, boot_id='same',
                      observation=observation)
        def load(name, filename):
            if filename == 'observe-clocks.py':
                return recorder
            if filename == 'test-pm-stages.py':
                return SimpleNamespace(FAULTS=['BUG:'])
            return SimpleNamespace(delta=lambda a, b: '')
        with patch.object(host, 'load', side_effect=load):
            host.validate_result(result, before, before.copy())
            for mode in ('count', 'event', 'state', 'boot', 'bounds'):
                candidate = copy.deepcopy(result)
                after = before.copy()
                if mode == 'count':
                    candidate['observation']['samples'] = 59999
                elif mode == 'event':
                    candidate['observation']['anomalies'][0]['sample']['monotonic_right'] = 999
                elif mode == 'state':
                    after['stats'] = 'changed'
                elif mode == 'boot':
                    candidate['boot_id'] = 'other'
                else:
                    candidate['batches'] = 301
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    host.validate_result(candidate, before, after)


if __name__ == '__main__':
    unittest.main()
