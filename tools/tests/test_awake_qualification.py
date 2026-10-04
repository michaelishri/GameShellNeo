"""Fail-stop, timeout cleanup, evidence ownership and unchanged-state boundaries."""
from copy import deepcopy
import ast
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import remote

spec = importlib.util.spec_from_file_location('awake_qualification', TOOLS / 'qualify-awake.py')
awake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(awake)
BOOT = '12345678-1234-1234-1234-123456789abc'


def write(directory, name, value):
    (directory / name).write_text(json.dumps(value))


def lines(directory, name, values):
    (directory / name).write_text(''.join(json.dumps(v) + '\n' for v in values))


class Orchestration(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'build').mkdir()
        write(self.root / 'build', 'sources.lock.json', {'image_version': 'fixture',
                                                       'linux': {'tag': 'v6.18.1', 'localversion': '-test'}})
        self.enterContext(patch.object(awake, 'ROOT', self.root))
        self.enterContext(patch.object(awake, 'sources', return_value={'script': 'original'}))
        self.plan = (('first', ('fixture.py',), 1), ('second', ('fixture.py',), 1), ('third', ('fixture.py',), 1))
        self.enterContext(patch.object(awake, 'PLAN', self.plan))
        self.output = self.root / 'capture'
        self.output.mkdir()
        self.calls = []

    def execute(self, argv, directory, timeout, grace):
        progress = json.loads((self.output / 'progress.json').read_text())
        active = [s for s in progress['steps'] if s['status'] == 'running']
        self.assertEqual(len(active), 1)  # Persisted before any child starts.
        self.calls.append(active[0]['name'])
        (directory / 'controller.log').write_text('private fixture output')
        (directory / 'new-capture').mkdir()
        return 0

    def validate(self, name, directory, context, lock):
        context['boot_id'] = BOOT
        return {'passed': True}

    def test_success_serializes_all_steps_and_saves_report(self):
        record = awake.qualify(self.output, self.execute, self.validate)
        self.assertEqual(record['status'], 'passed')
        self.assertEqual(self.calls, ['first', 'second', 'third'])
        self.assertEqual(json.loads((self.output / 'progress.json').read_text()), record)
        self.assertIn('verified against the original', (self.output / 'report.md').read_text())
        self.assertEqual((self.output / 'progress.json').stat().st_mode & 0o777, 0o600)

    def test_nonzero_exit_missing_evidence_and_interruption_stop_following_steps(self):
        for mode in ('exit', 'evidence', 'interrupt', 'timeout'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(dir=self.root) as path:
                self.output = Path(path)
                self.calls = []
                def execute(argv, directory, timeout, grace):
                    result = self.execute(argv, directory, timeout, grace)
                    if self.calls[-1] == 'second':
                        if mode == 'exit':
                            return 7
                        if mode == 'evidence':
                            (directory / 'new-capture').rmdir()
                        if mode == 'interrupt':
                            raise KeyboardInterrupt()
                        if mode == 'timeout':
                            raise subprocess.TimeoutExpired(argv, timeout)
                    return result
                record = awake.qualify(self.output, execute, self.validate)
                self.assertEqual(self.calls, ['first', 'second'])
                self.assertEqual(record['steps'][2]['status'], 'skipped')
                self.assertNotEqual(record['status'], 'passed')
                self.assertIn('unverified', record['restoration'])

    def test_controller_success_cannot_override_bad_semantic_evidence(self):
        def invalid(*_):
            raise ValueError('Missing final restoration')
        record = awake.qualify(self.output, self.execute, invalid)
        self.assertEqual(self.calls, ['first'])
        self.assertEqual(record['status'], 'failed')

    def test_source_change_stops_before_next_step(self):
        original = self.execute
        def execute(*args):
            result = original(*args)
            awake.sources.return_value = {'script': 'changed'}
            return result
        record = awake.qualify(self.output, execute, self.validate)
        self.assertEqual(self.calls, ['first'])
        self.assertEqual(record['status'], 'failed')

    def test_existing_step_evidence_is_never_reused(self):
        (self.output / '00-first').mkdir()
        record = awake.qualify(self.output, self.execute, self.validate)
        self.assertFalse(self.calls)
        self.assertEqual(record['status'], 'failed')

    def test_report_is_offline_and_never_resumes(self):
        record = awake.qualify(self.output, self.execute, self.validate)
        record['status'] = 'running'
        write(self.output, 'progress.json', record)
        with patch.object(sys, 'argv', ['qualify-awake.py', '--report', str(self.output)]), \
                patch.object(awake, 'device') as connect, patch.object(awake, 'qualify') as qualify:
            self.assertEqual(awake.main(), 0)
        connect.assert_not_called()
        qualify.assert_not_called()
        self.assertIn('incomplete', awake.report_text(record))


class ProcessBounds(unittest.TestCase):
    def test_timeout_gives_controller_finally_a_chance_to_restore(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            (root / 'tools').mkdir()
            script = root / 'tools/fixture.py'
            script.write_text("import pathlib,time\ntry:\n time.sleep(30)\nfinally:\n pathlib.Path('restored').touch()\n")
            with patch.object(awake, 'ROOT', root):
                with self.assertRaises(subprocess.TimeoutExpired):
                    awake.execute(['fixture.py'], root, 0.5, 5)
            self.assertTrue((root / 'restored').exists())

    def test_unresponsive_controller_is_killed_after_grace(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            (root / 'tools').mkdir()
            (root / 'tools/fixture.py').write_text(
                "import os,pathlib,signal,time\nsignal.signal(signal.SIGINT,signal.SIG_IGN)\n"
                "pathlib.Path('pid').write_text(str(os.getpid()))\ntime.sleep(30)\n")
            with patch.object(awake, 'ROOT', root):
                with self.assertRaises(subprocess.TimeoutExpired):
                    awake.execute(['fixture.py'], root, 0.5, 0.1)
            with self.assertRaises(ProcessLookupError):
                os.kill(int((root / 'pid').read_text()), 0)

    def test_environment_cannot_turn_plan_into_physical_cycles_or_long_windows(self):
        with patch.dict(os.environ, {'NEO_BOOT_CYCLES': '4', 'NEO_PROFILE_SECONDS': '300', 'NEO_ROUTE': 'wifi'}):
            env = awake.child_environment(Path('/private/step'))
        self.assertEqual((env['NEO_BOOT_CYCLES'], env['NEO_PROFILE_SECONDS'], env['NEO_ROUTE']), ('0', '120', 'usb'))
        for _, argv, _ in awake.PLAN:
            self.assertNotIn('--test', argv)
            self.assertNotIn('--keypad-input', argv)
            if argv[0] == 'check-boot-cycles.py':
                self.assertEqual(argv, ('check-boot-cycles.py', '--cycles', '0'))


class Evidence(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.context = {'boot_id': BOOT}

    def test_guard_probes_persistent_lock_without_removing_it(self):
        # Execute the device-side function, including real Linux flock behavior.
        tree = ast.parse(awake.GUARD)
        tree.body = [node for node in tree.body if isinstance(node, (ast.Import, ast.FunctionDef))]
        namespace = {}
        exec(compile(tree, '<awake guard>', 'exec'), namespace)
        records = namespace['recovery_records']
        lock = self.directory / 'gameshellneo-pm-experiment.lock'
        self.assertEqual(records(self.directory), [])
        lock.touch()
        inode = lock.stat().st_ino
        self.assertEqual(records(self.directory), [])
        with lock.open('a') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(records(self.directory), [str(lock)])
        self.assertEqual(records(self.directory), [])
        self.assertEqual(lock.stat().st_ino, inode)
        recovery = self.directory / 'gameshellneo-power-key.json'
        recovery.write_text('{}')
        self.assertEqual(records(self.directory), [str(recovery)])

    def test_guard_rejects_invalid_lock_types_and_keeps_unknown_records(self):
        tree = ast.parse(awake.GUARD)
        tree.body = [node for node in tree.body if isinstance(node, (ast.Import, ast.FunctionDef))]
        namespace = {}
        exec(compile(tree, '<awake guard>', 'exec'), namespace)
        records = namespace['recovery_records']
        lock = self.directory / 'gameshellneo-pm-experiment.lock'
        target = self.directory / 'target'
        target.touch()
        lock.symlink_to(target)
        self.assertEqual(records(self.directory), [str(lock)])
        lock.unlink()
        lock.mkdir()
        self.assertEqual(records(self.directory), [str(lock)])
        lock.rmdir()
        os.mkfifo(lock)
        self.assertEqual(records(self.directory), [str(lock)])
        lock.unlink()
        unknown = self.directory / 'gameshellneo-future-experiment.lock'
        unknown.touch()
        self.assertEqual(records(self.directory), [str(unknown)])

    def test_guard_blocks_other_diagnostics_and_recovery_records(self):
        for field, value in (('active_diagnostics', ['gameshellneo-pm-test.service']),
                             ('recovery_records', ['/run/gameshellneo-wifi-recovery'])):
            record = {'boot_id': BOOT, 'active_diagnostics': [], 'recovery_records': [], field: value}
            write(self.directory, 'guard.json', record)
            with self.assertRaises(ValueError):
                awake.validate_step('guard-before', self.directory, self.context, {})

    def test_boot_change_fails_even_with_well_formed_success(self):
        with self.assertRaises(ValueError):
            awake.same_boot({'boot_id': '87654321-1234-1234-1234-123456789abc'}, self.context)

    def test_ambiguous_capture_and_symlinks_are_rejected(self):
        (self.directory / 'one').mkdir()
        self.assertEqual(awake.capture(self.directory), self.directory / 'one')
        (self.directory / 'two').mkdir()
        with self.assertRaises(ValueError):
            awake.capture(self.directory)
        (self.directory / 'two').rmdir()
        (self.directory / 'one').rmdir()
        (self.directory / 'link').symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(ValueError):
            awake.capture(self.directory)

    def test_evidence_root_rejects_escape_and_keeps_default_behavior(self):
        with patch.object(remote, 'LOCAL', self.directory):
            diagnostics = self.directory / 'diagnostics'
            diagnostics.mkdir()
            step = diagnostics / 'step'
            step.mkdir()
            with patch.dict(os.environ, {'NEO_EVIDENCE_ROOT': str(step)}):
                self.assertEqual(remote.evidence_directory().parent, step)
            with patch.dict(os.environ, {'NEO_EVIDENCE_ROOT': str(self.directory)}):
                with self.assertRaises(ValueError):
                    remote.evidence_directory()
            (diagnostics / 'escape').symlink_to(self.directory, target_is_directory=True)
            with patch.dict(os.environ, {'NEO_EVIDENCE_ROOT': str(diagnostics / 'escape')}):
                with self.assertRaises(ValueError):
                    remote.evidence_directory()
            with patch.dict(os.environ, {'NEO_EVIDENCE_ROOT': ''}):
                self.assertEqual(remote.evidence_directory().parent, diagnostics)

    def test_wifi_requires_restoration_all_checkpoints_and_full_windows(self):
        phases = awake.module('check-wifi-firmware.py').INSTALLED_PHASES
        events = [{'event': 'installed_window_complete', 'phase': p, 'duration_seconds': 120.1}
                  for p in ('unavailable_network', 'connected')]
        final = {'event': 'complete', 'passed': True, 'installed': True, 'connected': True,
                 'configuration_restored': True, 'health': {'identities': ['firmware'], 'faults': {'crash': 0}}}
        checkpoints = [{'phase': p, 'boot_id': BOOT, 'passed': True} for p in phases]
        lock = {'radio': {'firmware': {'runtime_identity': 'firmware'}}}
        for bad in ('none', 'restoration', 'checkpoint', 'window', 'reloaded', 'fault'):
            with self.subTest(bad=bad):
                e, f, c = deepcopy(events), deepcopy(final), deepcopy(checkpoints)
                if bad == 'restoration':
                    f['configuration_restored'] = False
                if bad == 'checkpoint':
                    c.pop()
                if bad == 'window':
                    e[0]['duration_seconds'] = 119
                if bad == 'reloaded':
                    f['health']['identities'].append('firmware')
                if bad == 'fault':
                    f['health']['faults']['crash'] = 1
                lines(self.directory, 'firmware-trial.jsonl', e + [f])
                lines(self.directory, 'wifi-ssh.jsonl', c)
                if bad == 'none':
                    self.assertTrue(awake.validate_step('wifi', self.directory, self.context, lock)['configuration_restored'])
                else:
                    with self.assertRaises(ValueError):
                        awake.validate_step('wifi', self.directory, self.context, lock)

    def test_stability_needs_same_boot_verified_storage_load_and_cleanup(self):
        events = [{'event': 'start', 'boot_id': BOOT},
                  {'event': 'sample', 'temperature_mc': 65000, 'kernel_taint': 0},
                  {'event': 'storage_passed', 'bytes': 134217728, 'direct_read': True, 'sha256': 'fixture'},
                  {'event': 'stress_result', 'exit_code': 0},
                  {'event': 'passed', 'boot_id': BOOT, 'temporary_files_removed': True}]
        for index, field, value in ((1, 'temperature_mc', 80000), (1, 'kernel_taint', 1),
                                    (2, 'direct_read', False), (3, 'exit_code', 1),
                                    (4, 'temporary_files_removed', False)):
            changed = deepcopy(events)
            changed[index][field] = value
            lines(self.directory, 'stability.jsonl', changed)
            with self.assertRaises(ValueError):
                awake.validate_step('stability', self.directory, self.context, {})
        lines(self.directory, 'stability.jsonl', events)
        self.assertEqual(awake.validate_step('stability', self.directory, self.context, {})['maximum_temperature_c'], 65)

    def test_empty_or_partial_integration_and_battery_output_cannot_pass(self):
        for value in ({}, {'country': {'passed': True}}):
            write(self.directory, 'integration.json', value)
            with self.assertRaises(ValueError):
                awake.validate_step('integration', self.directory, self.context, {})
        for output in ('OK', 'Ran 9 tests in 0.1s\nFAILED', 'Ran 0 tests in 0.1s\nOK'):
            (self.directory / 'battery-policy.txt').write_text(output)
            with self.assertRaises(ValueError):
                awake.validate_step('battery', self.directory, self.context, {})

    def test_pm_comparison_rejects_changed_policy_and_suspend_counters(self):
        pm = awake.module('test-pm-stages.py')
        lock = {'experiments': {'suspend_diagnostics': True, 'keypad_supply_retention': True},
                'image_version': 'fixture', 'linux': {'tag': 'v6.18.1', 'localversion': '-test'},
                'radio': {'firmware': {'sha256': 'fw', 'runtime_identity': 'Firmware: expected'},
                          'nvram': {'sha256': 'nv'}}}
        before = dict(boot_id=BOOT, image={'board': 'gameshellneo-cpi31', 'version': 'fixture', 'sources': lock},
            kernel='6.18.1-test', firmware_sha256='fw', nvram_sha256='nv',
            kernel_config='CONFIG_SUSPEND=y\nCONFIG_PM_SLEEP_DEBUG=y\nCONFIG_PM_ADVANCED_DEBUG=y\n',
            journal='brcmf_c_preinit_dcmds: Firmware: expected\n',
            pm={'pm_test': '[none] freezer devices', 'mem_sleep': '[s2idle]', 'state': 'freeze mem', 'pm_async': '1'},
            pm_test_delay='5', masks={n: '/dev/null' for n in pm.MASKS}, sleep_config='AllowSuspend=no',
            usb_experiments={'gameshellneo_slow_poll': 'N', 'gameshellneo_diagnostics': 'N'},
            sdio_retains_power=True, keypad_retains_supply=True, cmdline='', taint='0', failed_units='',
            usb=['configured'], wifi='wpa_state=COMPLETED\n',
            battery={'monitoring': 'valid', 'status': 'Full', 'capacity_percent': 100}, battery_age_seconds=2,
            external_power={'axp20x-usb': {'type': 'USB', 'present': '1', 'online': '1'}},
            services={n: {'ActiveState': 'active', 'NRestarts': '0'} for n in pm.SERVICES},
            stats={'success': '0', 'fail': '0'}, wifi_config_sha256='config', wifi_power_save='off',
            charger={'voltage_max': '4200000'}, cpu_policy={'scaling_governor': 'schedutil'},
            backlight={'brightness': '1', 'bl_power': '0'})
        write(self.directory, 'inspection.json', before)
        awake.validate_step('pm-before', self.directory, self.context, lock)
        awake.validate_step('pm-after', self.directory, self.context, lock)
        for field, value in (('stats', {'success': '1', 'fail': '0'}), ('wifi_config_sha256', 'changed'),
                             ('charger', {'voltage_max': '4350000'}), ('backlight', {'brightness': '9'}),
                             ('cpu_policy', {'scaling_governor': 'performance'}), ('wifi_power_save', 'on'),
                             ('journal', 'rotated\nbrcmf_c_preinit_dcmds: Firmware: expected\n')):
            with self.subTest(field=field):
                write(self.directory, 'inspection.json', before | {field: value})
                with self.assertRaises(ValueError):
                    awake.validate_step('pm-after', self.directory, self.context, lock)

    def test_keypad_reenumeration_and_audio_changes_fail(self):
        keypad = {'usb': {'power': {'control': 'on', 'persist': '1'}, 'attributes': {'devnum': '2'}},
                  'inputs': ['event1'], 'regulators': {'supply': 'enabled'}, 'port_quirks': {'value': 0}}
        write(self.directory, 'keypad.json', keypad)
        awake.validate_step('keypad-before', self.directory, self.context, {})
        awake.validate_step('keypad-after', self.directory, self.context, {})
        keypad['usb']['attributes']['devnum'] = '3'
        write(self.directory, 'keypad.json', keypad)
        with self.assertRaises(ValueError):
            awake.validate_step('keypad-after', self.directory, self.context, {})
        audio = {'boot_id': BOOT, 'pcm_status': {'pcm': 'closed\n'},
                 'amplifiers': {'speaker': 'Off'}, 'controls': 'quiet'}
        write(self.directory, 'audio.json', audio)
        awake.validate_step('audio-before', self.directory, self.context, {})
        awake.validate_step('audio-after', self.directory, self.context, {})
        for changes in ({'pcm_status': {'pcm': 'running'}}, {'amplifiers': {'speaker': 'On'}}, {'controls': 'loud'}):
            write(self.directory, 'audio.json', audio | changes)
            with self.assertRaises(ValueError):
                awake.validate_step('audio-after', self.directory, self.context, {})


if __name__ == '__main__':
    unittest.main()
