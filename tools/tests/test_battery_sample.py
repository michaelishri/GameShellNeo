"""Sleep-inclusive observation age must survive transport and reach every consumer."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from awake_fixtures import clock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import battery_sample
import remote


def reading():
    return dict(schema_version=2, sample_clock='CLOCK_BOOTTIME', boot_id='boot',
                boottime_seconds=100, sample_monotonic_seconds=20,
                monitoring='valid', capacity_percent=80, status='Discharging')


def load(filename):
    spec = importlib.util.spec_from_file_location(filename.replace('-', '_'), TOOLS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BatteryAge(unittest.TestCase):
    def test_latched_clock_fault_rejects_even_fresh_recovered_sample(self):
        for fault in (None, {}, False, {'count': 1, 'first': {'reason': 'backwards'}}):
            sample = reading() | {'clock_fault': fault}
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, 'clock fault'):
                battery_sample.sample_age(sample, now=101, boot_id='boot')
            evidence = battery_sample.age_evidence(sample, now=101, boot_id='boot')
            self.assertIsNone(evidence['battery_age_seconds'])
            self.assertIn('clock fault', evidence['battery_age_error'])
            self.assertEqual(sample['clock_fault'], fault)
        self.assertEqual(battery_sample.age_evidence(reading(), now=101, boot_id='boot'),
                         {'battery_age_seconds': 1})

    def test_fault_aware_schema_uses_same_boottime_contract_without_legacy_clock_fallback(self):
        sample = reading() | {'schema_version': 3}
        self.assertEqual(battery_sample.sample_age(sample, now=3700, boot_id='boot'), 3600)
        for changed in ({'clock_fault': {'count': 1}}, {'boottime_seconds': None},
                        {'sample_clock': 'CLOCK_MONOTONIC'}, {'boot_id': 'other'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                battery_sample.sample_age(sample | changed, now=101, boot_id='boot')

    def test_offline_image_requires_the_clock_contract_and_exact_producer(self):
        verify = load('verify-rootfs.py')
        with tempfile.TemporaryDirectory() as directory:
            project, root = Path(directory) / 'project', Path(directory) / 'image'
            relative = Path('usr/local/lib/gameshellneo/battery_guard.py')
            for path in (project / 'runtime' / relative, root / relative):
                path.parent.mkdir(parents=True)
                path.write_bytes(b'expected producer')
            lock = dict(features={'battery_sample_clock': 'CLOCK_BOOTTIME'})
            verify.verify_battery(root, project, lock)
            for bad in ({}, {'features': {'battery_sample_clock': 'CLOCK_MONOTONIC'}}):
                with self.subTest(lock=bad), self.assertRaises(SystemExit):
                    verify.verify_battery(root, project, bad)
            (root / relative).write_bytes(b'old producer')
            with self.assertRaises(SystemExit):
                verify.verify_battery(root, project, lock)

    def test_age_includes_sleep_without_using_monotonic(self):
        with patch.object(battery_sample.time, 'clock_gettime', return_value=3700) as clock, \
                patch.object(battery_sample.time, 'monotonic', side_effect=AssertionError('wrong clock')):
            self.assertEqual(battery_sample.sample_age(reading(), boot_id='boot'), 3600)
        clock.assert_called_once_with(battery_sample.time.CLOCK_BOOTTIME)

    def test_unknown_clock_legacy_cross_boot_and_malformed_timestamps_reject(self):
        bad = [dict(monotonic_seconds=20), reading() | dict(schema_version=True),
               reading() | dict(schema_version=4), reading() | dict(sample_clock='CLOCK_MONOTONIC'),
               reading() | dict(boot_id='other')]
        bad += [reading() | dict(boottime_seconds=value)
                for value in (None, True, '100', -1, 102, float('nan'), float('inf'))]
        for sample in bad:
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                battery_sample.sample_age(sample, now=101, boot_id='boot')
        for now in (True, '101', -1, float('nan'), float('inf')):
            with self.subTest(now=now), self.assertRaises(ValueError):
                battery_sample.sample_age(reading(), now=now, boot_id='boot')

    def test_standalone_transport_contains_shared_helper_without_repo_import_path(self):
        for script in ('profile-power.py', 'sample-idle.py', 'compare-rsb.py'):
            # Run an import-only script in an unrelated cwd with no PYTHONPATH.
            program = ('scope={"__name__":"transport_test"}\nexec(' +
                       repr(remote.device_source(script)) + ', scope)\n' +
                       'assert scope["sample_age"](' + repr(reading()) +
                       ', now=3700, boot_id="boot") == 3600\n')
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                subprocess.run([sys.executable, '-I', '-c', program], cwd=directory, check=True)

    def test_all_live_age_consumers_reject_a_sleep_stale_reading(self):
        for filename, function in (('profile-power.py', 'health'), ('sample-idle.py', 'sample'),
                                   ('record-usb-detection.py', 'properties'), ('compare-rsb.py', 'cached_health')):
            module = load(filename)
            with self.subTest(consumer=filename), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                values = {
                    '/proc/sys/kernel/random/boot_id': 'boot', '/proc/sys/kernel/tainted': '0',
                    '/sys/devices/system/cpu/online': '0-3',
                    '/sys/class/backlight/ocp8178/brightness': '1',
                    '/sys/class/backlight/ocp8178/bl_power': '0',
                    '/sys/class/net/wlan0/carrier': '1',
                    '/sys/class/thermal/thermal_zone0/temp': '40000',
                    '/sys/class/udc/test/state': 'configured',
                    '/sys/module/workqueue/parameters/power_efficient': 'Y',
                    '/sys/devices/system/cpu/cpufreq/policy0/scaling_governor': 'schedutil',
                    '/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq': '240000',
                    '/sys/devices/system/cpu/cpufreq/policy0/scaling_min_freq': '240000',
                    '/sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq': '1008000',
                    '/sys/devices/system/cpu/cpufreq/policy0/schedutil/rate_limit_us': '2000',
                }
                for name, kind in (('axp20x-usb', 'USB'), ('axp22x-ac', 'Mains')):
                    values.update({f'/sys/class/power_supply/{name}/{key}': value
                                   for key, value in dict(type=kind, present='0', online='0').items()})
                values.update({f'/sys/class/power_supply/battery/{key}': value for key, value in
                               dict(capacity='80', status='Discharging', present='1',
                                    voltage_now='4000000', current_now='-100000').items()})
                sample = reading()
                if filename == 'compare-rsb.py':
                    sample['status'] = 'Full'
                values['/run/gameshellneo/battery.json'] = json.dumps(sample)
                for path, value in values.items():
                    output = root / path.lstrip('/')
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(value)

                def read(path):
                    key = str(path).removeprefix(str(root))
                    return values[key]

                def fake_path(path):
                    return root / str(path).lstrip('/')

                args = () if function != 'sample' else (fake_path('/sys/class/power_supply/battery'),
                    [fake_path('/sys/class/power_supply/axp20x-usb'), fake_path('/sys/class/power_supply/axp22x-ac')])
                with patch.object(module, 'read', read), patch.object(module, 'Path', fake_path), \
                        patch.object(module, 'observe', side_effect=clock(), create=True):
                    with patch.object(module, 'sample_age', lambda value: battery_sample.sample_age(
                            value, now=101, boot_id='boot')):
                        getattr(module, function)(*args)
                    with patch.object(module, 'sample_age', lambda value: battery_sample.sample_age(
                            value, now=3700, boot_id='boot')), self.assertRaises(ValueError):
                        getattr(module, function)(*args)
