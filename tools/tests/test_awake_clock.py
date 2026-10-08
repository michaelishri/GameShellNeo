"""Sleep detection, measurement admission and cleanup without touching devices."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import awake_clock as awake
import remote
from awake_fixtures import observation, window, proof


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), TOOLS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ClockContract(unittest.TestCase):
    def test_normal_elapsed_time_and_existing_sleep_offset_are_allowed(self):
        result = awake.validate([observation(10, sleep_ns=3600_000_000_000),
                                 observation(3610, sleep_ns=3600_000_000_000)])
        self.assertEqual(result['observation_count'], 2)
        self.assertEqual(result['max_bracket_ns'], 100)
        self.assertEqual(result['offset_upper_ns'] - result['offset_lower_ns'], 100)

    def test_sleep_between_reads_and_pm_activity_without_clock_freeze_reject(self):
        for change in (dict(sleep_ns=1_000_000), dict(sleep_ns=3600_000_000_000),
                       dict(success=1), dict(fail=1), dict(boot='another')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                awake.validate([observation(10), observation(20, **change)])

    def test_small_successive_changes_cannot_hide_in_pairwise_overlap(self):
        # Adjacent bounds overlap, but the full sequence admits no common offset.
        values = [observation(10), observation(20, sleep_ns=75), observation(30, sleep_ns=150)]
        awake.validate(values[:2])
        awake.validate(values[1:])
        with self.assertRaisesRegex(ValueError, 'Sleep or clock'):
            awake.validate(values)

    def test_uncertainty_invalid_fields_reordering_and_missing_data_reject(self):
        bad = [None, {}, observation() | dict(schema_version=True), observation() | dict(boot_id=''),
               observation(width_ns=awake.MAX_BRACKET_NS + 1),
               observation() | dict(pm_counts={'success': True, 'fail': 0}),
               observation() | dict(pm_counts={'success': 0}),
               observation(10) | dict(boottime_ns=1)]
        for key in ('monotonic_before_ns', 'boottime_ns', 'monotonic_after_ns'):
            bad += [observation() | {key: value} for value in (None, True, '0', -1, float('nan'), float('inf'))]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                awake.validate([value])
        for values in ([], None, [observation(10), observation(9)]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                awake.validate(values)
        with self.assertRaises(ValueError):
            awake.windows([dict(boot_id='other', awake_window=window())])
        for value in (float('nan'), True, -1, 20):
            with self.subTest(timestamp=value), self.assertRaises(ValueError):
                awake.windows([dict(monotonic_seconds=value, awake_window=window(10))])

    def test_clock_collection_detects_pm_change_and_missing_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            boot = Path(directory) / 'boot'; boot.write_text('boot\n')
            with patch.object(awake, 'BOOT', boot), \
                    patch.object(awake, 'pm_counts', side_effect=[dict(success=0, fail=0), dict(success=1, fail=0)]), \
                    patch.object(awake.time, 'monotonic_ns', side_effect=[1000, 1100]), \
                    patch.object(awake.time, 'clock_gettime_ns', return_value=1050), \
                    self.assertRaisesRegex(ValueError, 'System PM changed'):
                awake.observe()

    def test_actual_collector_reads_boottime_and_detects_frozen_monotonic(self):
        with tempfile.TemporaryDirectory() as directory:
            boot = Path(directory) / 'boot'; boot.write_text('boot\n')
            with patch.object(awake, 'BOOT', boot), \
                    patch.object(awake, 'pm_counts', return_value=dict(success=0, fail=0)), \
                    patch.object(awake.time, 'monotonic_ns', side_effect=[0, 100, 10_000_000_000, 10_000_000_100]), \
                    patch.object(awake.time, 'clock_gettime_ns', side_effect=[50, 3610_000_000_050]) as clock:
                run = awake.AwakeRun()
                with self.assertRaisesRegex(ValueError, 'Sleep or clock'):
                    run.check()
                self.assertEqual(clock.call_count, 2)
                self.assertTrue(all(call.args == (awake.time.CLOCK_BOOTTIME,) for call in clock.call_args_list))
            with patch.object(awake, 'BOOT', boot), patch.object(awake, 'STATS', Path(directory)), \
                    self.assertRaises(FileNotFoundError):
                awake.observe()

    def test_saved_claims_cannot_override_bad_evidence_or_short_coverage(self):
        awake.checked_proof(proof(300), seconds=300, boot_id='boot')
        for value in (None, proof(300) | dict(schema_version=True), proof(30),
                      proof(300, boot='other')):
            with self.subTest(proof=value), self.assertRaises(ValueError):
                awake.checked_proof(value, seconds=300, boot_id='boot')
        value = proof(300)
        value['observations'][-1]['pm_counts']['success'] += 1
        value['validation'] = dict(passed=True, observation_count=2)
        with self.assertRaises(ValueError):
            awake.checked_proof(value)


class MeasurementAdmission(unittest.TestCase):
    def test_read_only_recorder_produces_bounded_observations_without_settings(self):
        recorder = load('record-awake-clock')
        values = [observation(index) for index in range(21)]
        with patch.object(awake, 'observe', side_effect=values), patch.object(recorder.time, 'sleep') as sleep, \
                patch('builtins.print') as output:
            recorder.main()
        result = json.loads(output.call_args.args[0])
        self.assertTrue(result['passed'])
        self.assertEqual(awake.checked_proof(result['awake_proof'])['observation_count'], 21)
        self.assertEqual(sleep.call_count, 19)

    def test_all_three_numeric_summaries_reject_sleep_before_calculating_rates(self):
        for script in ('sample-idle', 'profile-power', 'compare-rsb'):
            module = load(script)
            for changes in (dict(sleep_ns=1_000_000_000), dict(success=1), dict(fail=1)):
                before, after = dict(awake_window=window(0)), dict(awake_window=window(60, **changes))
                args = ([before, after],) if script == 'sample-idle' else (before, after)
                if script == 'profile-power':
                    args += (100,)
                with self.subTest(script=script, change=changes), self.assertRaisesRegex(ValueError, 'Sleep|system PM'):
                    module.summarize(*args)

    def test_idle_sleep_during_settling_restores_backlight(self):
        idle = load('sample-idle')
        state = dict(boot_id='boot', brightness=0, bl_power=0, governor='schedutil')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in dict(brightness='1', bl_power='0', max_brightness='31').items():
                (root / name).write_text(value)
            (root / 'actual_brightness').symlink_to(root / 'brightness')
            with patch.object(awake, 'observe', side_effect=[observation(0), observation(10, sleep_ns=1_000_000_000)]), \
                    patch.object(idle, 'sample', return_value=state), patch.object(idle, 'wifi_signal', return_value=-60), \
                    patch.object(idle, 'emit') as emit, patch.object(idle.time, 'sleep'), self.assertRaises(ValueError):
                with idle.backlight_mode('off', root):
                    idle.measure(root, [], 60, 'off')
            self.assertEqual((root / 'brightness').read_text().strip(), '1')
            self.assertFalse(any(call.args[0] == 'complete' for call in emit.call_args_list))

    def test_real_governor_comparison_restores_after_sleep_in_changed_phase(self):
        compare = load('compare-governor')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rate, state, boot = (root / name for name in ('rate', 'state', 'boot'))
            rate.write_text('366\n'); boot.write_text('boot\n')
            supplies = root / 'supplies'
            for name, kind in (('battery', 'Battery'), ('usb', 'USB')):
                path = supplies / name; path.mkdir(parents=True)
                (path / 'type').write_text(kind); (path / 'online').write_text('0')
            def path(value):
                return supplies if str(value) == '/sys/class/power_supply' else Path(value)
            index = 0
            def clock():
                nonlocal index
                index += 1
                return observation(index, success=int(rate.read_text().strip() == '10000'))
            health = dict(boot_id='boot', online_cpus='0-3', brightness=1, bl_power=0, governor='schedutil')
            events = []
            profile = SimpleNamespace(health=lambda: health,
                capabilities=lambda: dict(schedutil_rate_limit_us=int(rate.read_text())),
                radio=lambda: dict(power_save='off'), snapshot=lambda: {}, summarize=lambda *args: {},
                emit=lambda event, **kwargs: events.append(event))
            idle = SimpleNamespace(sample=lambda *args: dict(monotonic_seconds=0), summarize=lambda *args: {})
            with patch.object(compare, 'RATE_PATHS', (rate,)), patch.object(compare, 'STATE', state), \
                    patch.object(compare, 'BOOT_ID', boot), patch.object(compare, 'Path', path), \
                    patch.object(compare, 'helper', side_effect=[profile, idle]), \
                    patch.object(compare.time, 'sleep'), patch.object(awake, 'observe', side_effect=clock), \
                    self.assertRaisesRegex(ValueError, 'system PM'):
                compare.compare(60, 10000)
            self.assertEqual(rate.read_text().strip(), '366')
            self.assertFalse(state.exists())
            self.assertEqual(events.count('phase'), 2)
            self.assertNotIn('complete', events)

    def test_rsb_setting_restores_on_clock_rejection(self):
        compare = load('compare-rsb')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delay, state, boot = (root / name for name in ('delay', 'state', 'boot'))
            delay.write_text('1000\n'); boot.write_text('boot\n')
            with patch.object(compare, 'DELAY', delay), patch.object(compare, 'STATE', state), \
                    patch.object(compare, 'BOOT', boot), \
                    patch.object(awake, 'observe', side_effect=[observation(0), observation(10, fail=1)]), \
                    self.assertRaises(ValueError):
                run = awake.AwakeRun()
                with compare.saved_delay(100):
                    compare.set_delay(100)
                    run.check()
            self.assertEqual(delay.read_text().strip(), '1000')
            self.assertFalse(state.exists())

    def test_real_rsb_comparison_rejects_sleep_after_changing_delay(self):
        compare = load('compare-rsb')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            delay, state, boot = (root / name for name in ('delay', 'state', 'boot'))
            delay.write_text('1000\n'); boot.write_text('boot\n')
            original_read = compare.read
            def read(path):
                if path == compare.BUS / 'power/control': return 'auto'
                if str(path).startswith('/proc/'): return ''
                return original_read(path)
            index = 0
            def clock():
                nonlocal index
                index += 1
                return observation(index, success=int(delay.read_text().strip() == '100'))
            health = dict(boot_id='boot', fixed={}, schedutil_rate_us='366', guard={})
            boundary = dict(health=health, charging={}, wifi_config_sha256='same',
                            scan_offload='same', wifi_power_save='same', journal='unchanged')
            profile = SimpleNamespace(processes=lambda: {}, interrupts=lambda _: {}, proc_stat=lambda _: {},
                                      process_rates=lambda *args: [], interrupt_rates=lambda *args: [])
            spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _: None))
            with patch.object(compare, 'DELAY', delay), patch.object(compare, 'STATE', state), \
                    patch.object(compare, 'BOOT', boot), patch.object(compare, 'read', side_effect=read), \
                    patch.object(compare, 'boundary_health', return_value=boundary), \
                    patch.object(compare, 'cached_health', return_value=health), \
                    patch.object(compare, 'residency', return_value={}), \
                    patch.object(compare, 'summarize', return_value={'seconds': 60}), \
                    patch.object(compare, 'emit') as emit, patch.object(compare.time, 'sleep'), \
                    patch.object(compare.importlib.util, 'spec_from_file_location', return_value=spec), \
                    patch.object(compare.importlib.util, 'module_from_spec', return_value=profile), \
                    patch.object(awake, 'observe', side_effect=clock), self.assertRaisesRegex(ValueError, 'system PM'):
                compare.compare({}, 60, 100)
            self.assertEqual(delay.read_text().strip(), '1000')
            self.assertFalse(state.exists())
            self.assertEqual(sum(call.args[0] == 'phase' for call in emit.call_args_list), 2)
            self.assertFalse(any(call.args[0] == 'complete' for call in emit.call_args_list))

    def test_perf_recorder_is_terminated_when_awake_check_fails(self):
        governor = load('profile-governor')
        health = dict(boot_id='boot', online_cpus='0-3', brightness=1, bl_power=0, governor='schedutil')
        events = []
        profile = SimpleNamespace(health=lambda: health, capabilities=lambda: {}, radio=lambda: dict(power_save='off'),
            processes=lambda: {'42': dict(pid=42, comm='sugov:0', start_ticks=1)},
            emit=lambda event, **kwargs: events.append(event))
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _: None))
        process = MagicMock()
        process.__enter__.return_value = process
        process.poll.return_value = None
        process.terminate.side_effect = lambda: setattr(process.poll, 'return_value', 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); symbols = root / 'symbols'; symbols.write_text('')
            def path(value):
                return symbols if str(value) == '/proc/kallsyms' else Path(value)
            with patch.object(governor, '__file__', str(root / 'profile-governor.py')), \
                    patch.object(governor, 'Path', side_effect=path), \
                    patch.object(governor.importlib.util, 'spec_from_file_location', return_value=spec), \
                    patch.object(governor.importlib.util, 'module_from_spec', return_value=profile), \
                    patch.object(governor.subprocess, 'check_output', return_value='perf test'), \
                    patch.object(governor.subprocess, 'Popen', return_value=process), \
                    patch.object(sys, 'argv', ['profile-governor.py', '--seconds', '10']), \
                    patch.object(awake, 'observe', side_effect=[observation(0), observation(2, success=1)]), \
                    self.assertRaisesRegex(ValueError, 'system PM'):
                governor.main()
            process.terminate.assert_called_once()
            process.wait.assert_called_once_with(timeout=5)
            self.assertEqual(events, ['ready'])

    def test_power_profile_sleep_during_settling_cannot_emit_success(self):
        profile = load('profile-power')
        state = dict(boot_id='boot', online_cpus='0-3', brightness=1, bl_power=0, governor='schedutil')
        with patch.object(profile, 'health', return_value=state), patch.object(profile, 'capabilities', return_value={}), \
                patch.object(profile, 'emit') as emit, patch.object(profile.time, 'sleep'), \
                patch.object(sys, 'argv', ['profile-power.py', '--seconds', '30']), \
                patch.object(awake, 'observe', side_effect=[observation(0), observation(30, success=1)]), \
                self.assertRaises(ValueError):
            profile.main()
        self.assertEqual([call.args[0] for call in emit.call_args_list], ['ready'])

    def test_standalone_bundle_runs_clock_validation_without_repo_imports(self):
        for script in ('profile-power.py', 'sample-idle.py', 'compare-rsb.py', 'record-awake-clock.py'):
            program = ('scope={"__name__":"transport_test"}\nexec(' + repr(remote.device_source(script)) + ',scope)\n'
                       'import awake_clock\nawake_clock.checked_proof(' + repr(proof(300)) + ', seconds=300)\n')
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                subprocess.run([sys.executable, '-I', '-c', program], cwd=directory, check=True)

    def test_usb_admission_rejects_legacy_and_changed_sleep_proof_without_rewriting(self):
        compare = load('compare-usb-idle')
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory); capture = local / 'diagnostics/capture'; capture.mkdir(parents=True)
            path = capture / 'idle-sample.jsonl'
            for value in (None, proof(30), proof(300)):
                complete = dict(event='complete', passed=True, duration_seconds=300)
                if value is not None:
                    complete['awake_proof'] = copy.deepcopy(value)
                    if value['observations'][-1]['monotonic_before_ns'] > 100_000_000_000:
                        complete['awake_proof']['observations'][-1]['pm_counts']['success'] = 1
                text = '\n'.join(json.dumps(row) for row in [dict(event='ready', seconds=300), complete]) + '\n'
                path.write_text(text)
                with self.subTest(value=value), patch.object(compare, 'LOCAL', local), self.assertRaises(ValueError):
                    compare.checked_capture(capture, path.name, 300)
                self.assertEqual(path.read_text(), text)
