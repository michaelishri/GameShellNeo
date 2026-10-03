"""Exercise rejection, restoration and evidence boundaries without suspending a host."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, TOOLS / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pm = load('pm_stages', 'test-pm-stages.py')
host = load('pm_stage_host', 'check-pm-stages.py')


class Controls(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for key, name in (('POWER', 'power'), ('BOOT', 'boot'), ('STATE', 'owned.json')):
            value = self.root / name
            self.enterContext(patch.object(pm, key, value))
        pm.POWER.mkdir()
        pm.BOOT.write_text('boot-one')
        (pm.POWER / 'pm_test').write_text('[none] freezer devices')
        (pm.POWER / 'pm_async').write_text('1')
        (pm.POWER / 'state').write_text('untouched')
        actual = pm.read
        def read(path):
            if str(path) == '/sys/module/suspend/parameters/pm_test_delay':
                return '5'
            value = actual(path)
            if Path(path) == pm.POWER / 'pm_test' and '[' not in value:
                return '[' + value + ']'
            return value
        self.enterContext(patch.object(pm, 'read', side_effect=read))

    def test_success_and_failure_restore_both_controls(self):
        for fail in (False, True):
            try:
                with pm.stage_controls('devices'):
                    self.assertEqual((pm.POWER / 'pm_async').read_text().strip(), '0')
                    pm.enter_stage('devices')
                    self.assertEqual((pm.POWER / 'state').read_text().strip(), 'freeze')
                    if fail:
                        raise InterruptedError('signal')
            except InterruptedError:
                pass
            self.assertEqual(pm.selected(pm.read(pm.POWER / 'pm_test')), 'none')
            self.assertEqual(pm.read(pm.POWER / 'pm_async'), '1')
            self.assertFalse(pm.STATE.exists())

    def test_unsafe_stages_cannot_write_state_or_claim_controls(self):
        for stage in ('none', 'platform', 'processors', 'core', 's2idle', ''):
            with self.assertRaises(ValueError):
                with pm.stage_controls(stage):
                    self.fail('Unsafe stage accepted')
            with self.assertRaises(ValueError):
                pm.enter_stage(stage)
        self.assertFalse(pm.STATE.exists())
        self.assertEqual(pm.read(pm.POWER / 'state'), 'untouched')

    def test_readback_race_refuses_entry(self):
        with pm.stage_controls('freezer'):
            (pm.POWER / 'pm_test').write_text('[none] freezer devices')
            with self.assertRaises(ValueError):
                pm.enter_stage('freezer')
        self.assertEqual(pm.read(pm.POWER / 'state'), 'untouched')

    def test_existing_owner_wrong_boot_or_bad_record_are_preserved(self):
        saved = dict(boot_id='boot-one', pm_test='none', pm_async='1')
        pm.STATE.write_text(json.dumps(saved))
        with self.assertRaises(FileExistsError):
            with pm.stage_controls('devices'):
                self.fail('Second owner accepted')
        for change in ({'boot_id': 'other'}, {'pm_test': 'devices'}, {'pm_async': '2'}):
            pm.STATE.write_text(json.dumps(saved | change))
            with self.assertRaises(ValueError):
                pm.restore()
            self.assertTrue(pm.STATE.exists())
        pm.STATE.write_text(json.dumps(saved))
        pm.restore()
        pm.restore()
        self.assertFalse(pm.STATE.exists())

    def test_failed_restore_retains_evidence(self):
        pm.STATE.write_text(json.dumps(dict(boot_id='boot-one', pm_test='none', pm_async='1')))
        with patch.object(Path, 'write_text', side_effect=OSError('sysfs error')):
            with self.assertRaises(OSError):
                pm.restore()
        self.assertTrue(pm.STATE.exists())
        pm.restore()

    def test_trace_restore_failure_still_restores_pm_controls(self):
        pm.STATE.write_text(json.dumps(dict(boot_id='boot-one', pm_test='none', pm_async='1')))
        (pm.POWER / 'pm_test').write_text('devices')
        (pm.POWER / 'pm_async').write_text('0')
        with patch.object(sys, 'argv', ['pm-test', '--restore']), \
                patch('keypad_pm.restore_trace', side_effect=OSError('trace cleanup failure')):
            with self.assertRaises(OSError):
                pm.main()
        self.assertFalse(pm.STATE.exists())
        self.assertEqual(pm.selected(pm.read(pm.POWER / 'pm_test')), 'none')
        self.assertEqual(pm.read(pm.POWER / 'pm_async'), '1')

    def test_persistence_and_trace_errors_still_restore_pm_controls(self):
        pm.STATE.write_text(json.dumps(dict(boot_id='boot-one', pm_test='none', pm_async='1')))
        (pm.POWER / 'pm_test').write_text('devices')
        with patch.object(sys, 'argv', ['pm-test', '--restore']), \
                patch('keypad_pm.restore_trace', side_effect=OSError('trace failure')), \
                patch('keypad_pm.restore_persistence', side_effect=OSError('persistence failure')) as recover:
            with self.assertRaises(OSError):
                pm.main()
        recover.assert_called_once_with()
        self.assertFalse(pm.STATE.exists())
        self.assertEqual(pm.selected(pm.read(pm.POWER / 'pm_test')), 'none')

    def test_killed_worker_can_be_restored_from_a_fresh_process(self):
        program = '''
import runpy, sys, time
from pathlib import Path
scope = runpy.run_path(sys.argv[1], run_name='pm_worker')
fn = scope['stage_controls'] if sys.argv[3] == 'start' else scope['restore']
g = scope['restore'].__globals__
root = Path(sys.argv[2])
g.update(POWER=root/'power', BOOT=root/'boot', STATE=root/'owned.json')
actual = g['read']
def read(path):
    value = actual(path)
    return '['+value+']' if Path(path).name == 'pm_test' and '[' not in value else value
g['read'] = read
if sys.argv[3] == 'start':
    with fn('devices'):
        (root/'ready').touch()
        time.sleep(60)
else:
    fn()
'''
        args = [sys.executable, '-c', program, str(TOOLS / 'test-pm-stages.py'), str(self.root)]
        worker = subprocess.Popen(args + ['start'])
        try:
            deadline = time.monotonic() + 5
            while not (self.root / 'ready').exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue((self.root / 'ready').exists())
            worker.kill()
            worker.wait(timeout=5)
            self.assertTrue(pm.STATE.exists())
            subprocess.run(args + ['restore'], check=True, timeout=5)
            self.assertFalse(pm.STATE.exists())
            self.assertEqual(pm.read(pm.POWER / 'pm_async'), '1')
            self.assertEqual(pm.selected(pm.read(pm.POWER / 'pm_test')), 'none')
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait(timeout=5)


class Evidence(unittest.TestCase):
    def test_rejected_preflight_is_saved_without_entering_pm(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(pm, 'result_dir', return_value=Path(temporary)/'run'), \
                patch.object(pm, 'snapshot', return_value={'fixture': 'rejected snapshot'}), \
                patch.object(pm, 'validate', side_effect=ValueError('rejected health gate')), \
                patch.object(pm, 'command') as command, patch.object(pm, 'enter_stage') as enter:
            with self.assertRaisesRegex(ValueError, 'rejected health gate'):
                pm.test_stage({}, 'devices', 'a'*32)
            record = json.loads((Path(temporary)/'run/result.json').read_text())
            self.assertEqual(record['before'], {'fixture': 'rejected snapshot'})
            self.assertFalse(record['passed'])
            self.assertEqual(record['event'], 'failed')
            self.assertNotIn('stage_seconds', record)
            self.assertFalse((Path(temporary)/'run/started.json').exists())
            command.assert_not_called()
            enter.assert_not_called()

    def test_preflight_accepts_only_the_isolated_healthy_image(self):
        lock = dict(experiments={'suspend_diagnostics': True}, image_version='diagnostic-test',
                    linux={'tag': 'v6.18.54', 'localversion': '-test'},
                    radio={'firmware': {'sha256': 'fw', 'runtime_identity': 'Firmware: expected'},
                           'nvram': {'sha256': 'nv'}})
        good = dict(image={'board': 'gameshellneo-cpi31', 'version': 'diagnostic-test', 'sources': lock},
                    kernel='6.18.54-test', firmware_sha256='fw', nvram_sha256='nv',
                    kernel_config='CONFIG_SUSPEND=y\nCONFIG_PM_SLEEP_DEBUG=y\nCONFIG_PM_ADVANCED_DEBUG=y\n',
                    journal='brcmf_c_preinit_dcmds: Firmware: expected\n',
                    pm={'pm_test': '[none] freezer devices', 'mem_sleep': '[s2idle]', 'state': 'freeze mem'},
                    pm_test_delay='5', masks={n: '/dev/null' for n in pm.MASKS}, sleep_config='AllowSuspend=no',
                    usb_experiments={'gameshellneo_slow_poll': 'N', 'gameshellneo_diagnostics': 'N'},
                    sdio_retains_power=True, keypad_retains_supply=False, cmdline='mem_sleep_default=s2idle',
                    taint='0', failed_units='', usb=['configured'], wifi='wpa_state=COMPLETED\n',
                    battery={'monitoring': 'valid', 'status': 'Charging', 'capacity_percent': 70},
                    battery_age_seconds=2,
                    external_power={'axp20x-usb': {'type': 'USB', 'present': '1', 'online': '1'},
                                    'axp22x-ac': {'type': 'Mains', 'present': '1', 'online': '1'}},
                    services={n: {'ActiveState': 'active', 'NRestarts': '0'} for n in pm.SERVICES})
        pm.validate(good, lock)
        wake_lock = deepcopy(lock)
        wake_lock['features'] = {'usb_system_wakeup': False}
        wake_good = deepcopy(good)
        wake_good['image']['sources'] = wake_lock
        wake_good['usb_system_wakeup'] = ['disabled']
        pm.validate(wake_good, wake_lock)
        for policy in ([], ['enabled'], [None], ['disabled', 'disabled']):
            with self.assertRaisesRegex(ValueError, 'USB system wake policy'):
                pm.validate(wake_good | {'usb_system_wakeup': policy}, wake_lock)
        for policy in (True, 0, None):
            invalid_lock = deepcopy(wake_lock)
            invalid_lock['features']['usb_system_wakeup'] = policy
            with self.assertRaisesRegex(ValueError, 'USB system wake policy'):
                pm.validate(wake_good, invalid_lock)
        # Battery current direction is independent of external input availability.
        for status in ('Charging', 'Discharging', 'Full', 'Not charging'):
            with self.subTest(status=status):
                pm.validate(good | {'battery': good['battery'] | {'status': status}}, lock)
        for power in ({}, {'axp22x-ac': good['external_power']['axp22x-ac']},
                      *[{'axp20x-usb': good['external_power']['axp20x-usb'] | change}
                        for change in ({'present': '0'}, {'online': '0'}, {'online': None},
                                       {'present': 'invalid'}, {'type': 'Battery'})]):
            with self.subTest(power=power), self.assertRaisesRegex(ValueError, 'usb_external_power'):
                pm.validate(good | {'external_power': power}, lock)
        missing_power = deepcopy(good)
        del missing_power['external_power']
        with self.assertRaisesRegex(ValueError, 'usb_external_power'):
            pm.validate(missing_power, lock)
        for change in ({'status': 'Unknown'}, {'monitoring': 'degraded'}, {'capacity_percent': 20}):
            with self.subTest(battery=change), self.assertRaises(ValueError):
                pm.validate(good | {'battery': good['battery'] | change}, lock)
        with self.assertRaisesRegex(ValueError, 'failed: usb_configured, battery_freshness'):
            pm.validate(good | dict(usb=['suspended'], battery_age_seconds=26), lock)
        retained = deepcopy(good)
        retained_lock = deepcopy(lock)
        retained_lock['experiments']['keypad_supply_retention'] = True
        retained['image']['sources'] = retained_lock
        retained['keypad_retains_supply'] = True
        pm.validate(retained, retained_lock)
        with self.assertRaises(ValueError):
            pm.validate(retained | {'keypad_retains_supply': False}, retained_lock)
        changes = [dict(kernel='wrong'), dict(firmware_sha256='other'), dict(sdio_retains_power=False),
                   dict(keypad_retains_supply=True),
                   dict(pm_test_delay='0'), dict(usb=['not attached']), dict(battery_age_seconds=40),
                   dict(kernel_config=good['kernel_config']+'CONFIG_PM_AUTOSLEEP=y\n'),
                   dict(masks={n: '/lib/systemd/system/' + n for n in pm.MASKS}),
                   dict(pm=good['pm'] | {'mem_sleep': 's2idle [deep]'}),
                   dict(usb_experiments=good['usb_experiments'] | {'gameshellneo_slow_poll': 'Y'}),
                   dict(journal=good['journal']+'Failed to set pm_flags 1\n')]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                pm.validate(good | change, lock)

    def snapshots(self):
        before = dict(boot_id='one', journal='boot\n', stats={'success': '2', 'fail': '0', 'failed_suspend': '0'},
                      backlight={'brightness': '1'}, inputs=['keys'], pm={'pm_async': '1'},
                      wifi='ssid=fixture\nid=0\n', wifi_config_sha256='fixture', wifi_power_save='on',
                      charger={'voltage_max': '4200000'}, cpu_policy={'scaling_governor': 'schedutil'})
        after = deepcopy(before)
        after['stats']['success'] = '3'
        after['journal'] += 'PM: suspend debug: Waiting for 5 second(s).\n'
        return before, after

    def test_only_one_bounded_cycle_without_faults_passes(self):
        before, after = self.snapshots()
        pm.check_result(before, after, 'devices', True)
        bad_cases = [dict(boot_id='other'), dict(journal='rotated'),
                     dict(journal=after['journal'] + 'WARNING: fault\n'),
                     dict(journal=after['journal'] + 'brcmfmac: error while changing bus sleep state -5\n'),
                     dict(journal=after['journal'] + 'brcmfmac: HT Avail timeout\n'),
                     dict(journal=after['journal'] + 'sunxi-musb does not have ULPI bus control register\n'),
                     dict(journal=after['journal'] + 'musb-hdrc: gadget work resume failed: -5\n'),
                     dict(journal=after['journal'] + 'musb-hdrc: resume work failed with -19\n'),
                     dict(stats=after['stats'] | {'success': '4'}),
                     dict(stats=after['stats'] | {'failed_suspend': '1'}),
                     dict(backlight={}), dict(inputs=[]), dict(pm={'pm_async': '0'}),
                     dict(charger={'voltage_max': '4300000'}), dict(cpu_policy={}),
                     dict(wifi_config_sha256='changed'), dict(wifi_power_save='off'), dict(wifi='ssid=other\nid=0\n')]
        for change in bad_cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                pm.check_result(before, after | change, 'devices', True)
        with self.assertRaises(ValueError):
            pm.check_result(before, after, 'freezer', False)

    def test_normal_lock_cannot_enable_tests(self):
        for experiments in ({}, {'usb_absent_poll': True},
                            {'suspend_diagnostics': True, 'usb_diagnostics': False},
                            {'suspend_diagnostics': True, 'keypad_supply_retention': False},
                            {'suspend_diagnostics': True, 'keypad_supply_retention': 1},
                            {'suspend_diagnostics': 1}):
            with self.assertRaises(ValueError):
                pm.validate({}, {'experiments': experiments})

    def test_async_service_has_independent_restore_and_inhibitor(self):
        args = host.service_command('/tmp/gameshellneo-pm.good', 'devices', 'a' * 32)
        self.assertNotIn('--pipe', args)
        self.assertNotIn('--wait', args)
        self.assertIn('--property=RuntimeMaxSec=120', args)
        self.assertIn('--property=ExecStopPost=/usr/bin/python3 -B /tmp/gameshellneo-pm.good/test-pm-stages.py --restore', args)
        self.assertIn('--what=handle-power-key:sleep:idle', args)
        for directory, stage, run_id in (('/tmp/escape;id', 'devices', 'a' * 32),
                                         ('/tmp/gameshellneo-pm.good', 'none', 'a' * 32),
                                         ('/tmp/gameshellneo-pm.good', 'devices', '../escape')):
            with self.assertRaises(ValueError):
                host.service_command(directory, stage, run_id)
        with self.assertRaises(ValueError):
            pm.result_dir('../escape')

    def test_wifi_trace_is_opt_in_and_does_not_weaken_service_bounds(self):
        args = host.service_command('/tmp/gameshellneo-pm.good', 'devices', 'a' * 32, wifi_trace=True)
        self.assertIn('--wifi-trace', args)
        self.assertIn('--property=RuntimeMaxSec=120', args)
        self.assertIn('--property=ExecStopPost=/usr/bin/python3 -B /tmp/gameshellneo-pm.good/test-pm-stages.py --restore', args)
        for options in ({'stage': 'freezer', 'wifi_trace': True},
                        {'stage': 'devices', 'wifi_trace': True, 'keypad_input': True, 'keypad_trace': True},
                        {'stage': 'devices', 'wifi_trace': True, 'keypad_quirk': 'old-scheme', 'keypad_trace': True}):
            with self.assertRaises(ValueError):
                host.service_command('/tmp/gameshellneo-pm.good', run_id='a'*32, **options)
        with self.assertRaises(ValueError):
            pm.test_stage({}, 'freezer', 'a'*32, wifi_trace=True)

    def test_wifi_restore_failure_does_not_prevent_pm_restoration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            boot, state, power = root/'boot', root/'state', root/'power'
            boot.write_text('same')
            power.mkdir()
            (power/'pm_test').write_text('devices')
            (power/'pm_async').write_text('0')
            state.write_text(json.dumps(dict(boot_id='same', pm_test='none', pm_async='1')))
            actual = pm.read
            def read(path):
                value = actual(path)
                return '['+value+']' if Path(path).name == 'pm_test' else value
            with patch.object(pm, 'BOOT', boot), patch.object(pm, 'STATE', state), \
                    patch.object(pm, 'POWER', power), patch.object(pm, 'read', side_effect=read), \
                    patch.object(sys, 'argv', ['pm-test', '--restore']), \
                    patch('wifi_trace.restore', side_effect=OSError('radio cleanup failed')):
                with self.assertRaises(OSError):
                    pm.main()
            self.assertFalse(state.exists())
            self.assertEqual((power/'pm_test').read_text().strip(), 'none')
            self.assertEqual((power/'pm_async').read_text().strip(), '1')


class HostRecovery(unittest.TestCase):
    def test_ambiguous_submission_and_collection_disconnect_do_not_resubmit(self):
        run_id = 'a' * 32
        before = {'boot_id': 'same', 'wifi': 'fixture'}
        result = dict(event='complete', passed=True, run_id=run_id, before=before, after=before)
        submissions = []
        def remote_run(_client, command, **_kwargs):
            if 'systemctl show' in command:
                return b'not-found\n'
            if 'mktemp' in command:
                return b'/tmp/gameshellneo-pm.fixture\n'
            if 'systemd-run' in command:
                submissions.append(command)
                raise RuntimeError('Remote command failed (exit -1)')
            if command == 'cat /proc/sys/kernel/random/boot_id':
                return b'same\n'
            self.fail('Unexpected command: ' + command)
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(host, 'device', return_value=MagicMock()), \
                patch.object(host, 'inline', return_value=json.dumps(before)), \
                patch.object(host, 'module', return_value=SimpleNamespace(validate=lambda *a: None)), \
                patch.object(host, 'wifi_proof') as wifi, patch.object(host, 'upload'), \
                patch.object(host, 'run', side_effect=remote_run), \
                patch.object(host.uuid, 'uuid4', return_value=SimpleNamespace(hex=run_id)), \
                patch.object(host.time, 'sleep'), patch.object(host.time, 'monotonic', return_value=0), \
                patch.object(host, 'collect', side_effect=[RuntimeError('lost SSH'), result]) as collect:
            capture = Path(temporary)
            host.cycle({}, capture, {}, 'devices')
            saved = json.loads((capture / 'result.json').read_text())
            self.assertTrue(saved['usb_ssh_verified'] and saved['wifi_ssh_verified'])
            self.assertEqual(len(submissions), 1)
            self.assertEqual(collect.call_count, 2)
            self.assertEqual(wifi.call_count, 2)
            self.assertTrue((capture / 'collection-errors.txt').exists())


if __name__ == '__main__':
    unittest.main()
