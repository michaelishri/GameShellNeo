"""Bounded-duration admission and endpoint failures, without live PM or networks."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_sleep_rtc as existing
import test_sleep_chain as chain
import test_sleep_cable_batch as cable_batch_tests
import sleep_window as window

sleep, host = existing.sleep, existing.host


def endpoint(start=100, connection='battery'):
    online = int(connection == 'usb')
    return dict(boot_id='boot', boottime_before=start, boottime_after=start+.2,
        present=1, capacity_percent=80, voltage_uv=3920000, current_ua=-265000,
        status='Charging' if online else 'Discharging', temperature_millic=44000,
        external={name: dict(present=online, online=online) for name in ('axp20x-usb', 'axp22x-ac')},
        guard=dict(schema_version=2, sample_clock='CLOCK_BOOTTIME', boot_id='boot',
                   boottime_seconds=start-1, monitoring='valid'))


def extended():
    record = existing.Evidence().delivery_record()
    record.update(alarm_seconds=60, connection='battery', before={'boot_id': 'boot'})
    record['returned'] = existing.Evidence.clock(161, 161)
    record['keypad'] = existing.Evidence.sleep_trace(end=160)
    record['rtc'].update(before={'rtc_time': sleep.rtc.rtc_time(1000)},
        requested=[1, 0]+sleep.rtc.rtc_time(1060), margin_seconds=59, entry_margin_seconds=59,
        after_delivery={'rtc_time': sleep.rtc.rtc_time(1061)})
    record['battery_window'] = dict(admission=endpoint(100), entry=endpoint(101.3), returned=endpoint(161.1))
    return record


class Duration(unittest.TestCase):
    def test_uploaded_source_bundle_imports_without_the_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in sleep.SOURCES:
                shutil.copy2(existing.TOOLS/(name+'.py'), root/(name+'.py'))
            result = subprocess.run([sys.executable, '-B', str(root/'sleep_rtc.py'), '--help'],
                cwd=root, env={'PATH': os.defpath}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--alarm-seconds', result.stdout)

    def test_only_two_integer_durations_and_fixed_connection_extensions(self):
        for seconds in (30, 60):
            for connection in ('usb', 'battery'):
                self.assertEqual(window.duration(seconds, connection), seconds)
        for seconds in (True, False, 30.0, 60.0, '60', None, 0, -30, 31, 61, 300, float('nan')):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError): window.duration(seconds)
        for connection in ('usb-remove', 'usb-attach'):
            self.assertEqual(window.duration(30, connection), 30)
            with self.assertRaises(ValueError): window.duration(60, connection)

    def test_service_and_collection_budgets_preserve_existing_recovery_allowance(self):
        for seconds, service, collection in ((30, 180, 210), (60, 210, 240)):
            self.assertEqual(window.budget(seconds), dict(service_seconds=service, collection_seconds=collection))
            command = host.service('/tmp/gameshellneo-sleep.test', existing.TOKEN, 'rtc-wake',
                                   chain.REHEARSAL, seconds=seconds)
            self.assertIn('--property=RuntimeMaxSec='+str(service), command)
            self.assertEqual(command[command.index('--alarm-seconds')+1], str(seconds))
            self.assertIn('--attended', command)
        with self.assertRaises(ValueError):
            host.service('/tmp/gameshellneo-sleep.test', existing.TOKEN, 'rtc-wake',
                         chain.REHEARSAL, observer={}, seconds=60)

    def test_unsupported_host_requests_fail_before_credentials_or_device_access(self):
        cases = [('--rehearse', 'usb', '300'), ('--rtc-batch', 'usb', '60'),
                 ('--rehearse', 'usb-attach', '60'), ('--rtc-wake', 'usb-remove', '60'),
                 ('--collect', 'usb', '60'), ('--clock-inspect', 'usb', '60')]
        for mode, connection, seconds in cases:
            with self.subTest(mode=mode, connection=connection, seconds=seconds), \
                    patch.object(sys, 'argv', ['check', mode, '--connection', connection]), \
                    patch.dict(os.environ, NEO_SLEEP_ALARM_SECONDS=seconds), \
                    patch.object(host, 'load_env') as load, self.assertRaises(SystemExit):
                host.main()
            load.assert_not_called()
        with patch.object(sys, 'argv', ['device', '--rtc-wake', '--alarm-seconds', '300']), \
                patch.object(sleep, 'pm_module') as pm, self.assertRaises(SystemExit):
            sleep.main()
        pm.assert_not_called()

    def test_cable_batch_does_not_silently_ignore_an_extended_duration(self):
        cable = cable_batch_tests.guided
        for mode in ('--start', '--next'):
            with patch.object(sys, 'argv', ['batch', mode]), \
                    patch.dict(os.environ, NEO_SLEEP_ALARM_SECONDS='60'), \
                    patch.object(cable, 'load_env') as load, self.assertRaises(SystemExit):
                cable.main()
            load.assert_not_called()

    def test_qualification_rehearsal_history_and_returned_duration_must_match(self):
        pm = Mock()
        with self.assertRaisesRegex(ValueError, 'receipt.*duration'):
            sleep.admission(pm, {}, {}, {'alarm_seconds': 30}, seconds=60)
        pm.validate.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'CPI WFI'):
            sleep.admission(pm, {}, {}, {'alarm_seconds': 60}, seconds=60)
        pm.validate.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root/chain.REHEARSAL/'result.json'; path.parent.mkdir()
            path.write_text(json.dumps({'alarm_seconds': 30}))
            with patch.object(sleep, 'RESULTS', root), patch.object(sleep, 'completed_result') as check, \
                    self.assertRaisesRegex(ValueError, 'rehearsal.*duration'):
                sleep.rehearsal_for_chain(pm, {}, {}, dict(sleep_runs=[], alarm_seconds=60), chain.REHEARSAL)
            check.assert_not_called()
        debug, records, current = chain.chain(1)
        with self.assertRaisesRegex(ValueError, 'history changed alarm duration'):
            sleep.history(pm, debug, records, current, {}, seconds=60)
        with patch.object(host.diagnostic, 'completed_result') as check, \
                self.assertRaisesRegex(ValueError, 'result.*duration'):
            host.validate_result({'alarm_seconds': 30}, '', {}, 'rtc-wake', seconds=60)
        check.assert_not_called()


class Endpoints(unittest.TestCase):
    def test_actual_sysfs_reads_are_bracketed_and_guard_is_not_the_endpoint(self):
        expected = endpoint()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {'proc/sys/kernel/random/boot_id': 'boot',
                     'sys/class/thermal/thermal_zone0/temp': '44000',
                     'run/gameshellneo/battery.json': json.dumps(expected['guard'])}
            battery = 'sys/class/power_supply/axp20x-battery/'
            for name, field in (('present', 'present'), ('status', 'status'), ('capacity', 'capacity_percent'),
                                ('voltage_now', 'voltage_uv'), ('current_now', 'current_ua')):
                files[battery+name] = str(expected[field])
            for name, values in expected['external'].items():
                for field, value in values.items(): files['sys/class/power_supply/'+name+'/'+field] = str(value)
            for name, value in files.items():
                p = root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
            with patch.object(window.time, 'clock_gettime', side_effect=[100, 100.2]):
                self.assertEqual(window.observe(root), expected)
            (root/(battery+'voltage_now')).write_text('bad')
            with self.assertRaises(ValueError): window.observe(root)

    def test_reserve_type_temperature_power_and_stale_guard_failures(self):
        good = endpoint()
        window.validate(good, 'boot', 'battery', admission=True)
        mutations = [lambda v: v.update(capacity_percent=50), lambda v: v.update(voltage_uv=3799999),
                     lambda v: v.update(capacity_percent=True), lambda v: v.update(current_ua=-500001),
                     lambda v: v.update(temperature_millic=60000), lambda v: v.update(voltage_uv=4300001),
                     lambda v: v.update(present=0), lambda v: v.update(status='Charging'),
                     lambda v: v.update(current_ua=1), lambda v: v.update(boot_id='other'),
                     lambda v: v.update(boottime_after=106), lambda v: v.update(boottime_before=float('nan')),
                     lambda v: v['external']['axp22x-ac'].update(online=1),
                     lambda v: v['guard'].update(monitoring='degraded'),
                     lambda v: v['guard'].update(boottime_seconds=74),
                     lambda v: v['guard'].update(boot_id='other'),
                     lambda v: v['guard'].update(sample_clock='CLOCK_MONOTONIC')]
        for change in mutations:
            bad = deepcopy(good); change(bad)
            with self.subTest(change=change), self.assertRaises(ValueError):
                window.validate(bad, 'boot', 'battery', admission=True)
        returned = endpoint(161); returned['guard'] = good['guard']
        window.validate(returned, 'boot', 'battery')  # Frozen guard cache is expected immediately after wake.
        with self.assertRaises(ValueError): window.validate(returned, 'boot', 'battery', admission=True)
        with self.assertRaises(ValueError): window.fresh(good, 106)

    def test_endpoint_assessment_has_no_integrated_energy_and_rejects_late_or_reordered_reads(self):
        record = extended()
        result = window.assess(record)
        self.assertFalse(result['energy_qualified']); self.assertFalse(result['calibrated'])
        self.assertNotIn('power_mw', result); self.assertNotIn('charge_mah', result)
        mutations = [lambda r: r['battery_window'].update(entry=endpoint(95)),
                     lambda r: r['battery_window'].update(returned=endpoint(167)),
                     lambda r: r['battery_window'].update(returned=endpoint(160)),
                     lambda r: r['battery_window'].update(admission=endpoint(105)),
                     lambda r: r['entry_clock'].update(boot=110)]
        for change in mutations:
            bad = deepcopy(record); change(bad)
            with self.subTest(change=change), self.assertRaises(ValueError): window.assess(bad)


class Alarm(unittest.TestCase):
    setUp = existing.Alarm.setUp

    def test_sixty_second_target_is_written_once_and_owned_restoration_survives_failure(self):
        target = [1, 0]+sleep.rtc.rtc_time(1060)
        with patch.object(sleep.rtc, 'alarm', return_value=target):
            with self.assertRaisesRegex(RuntimeError, 'test interruption'):
                with sleep.deadline({}, lambda: None, existing.TOKEN, 60) as (_, requested):
                    self.assertEqual(requested, target)
                    self.assertEqual(json.loads(sleep.rtc.OWNED.read_text())['requested'], target)
                    raise RuntimeError('test interruption')
        self.ioctl.assert_called_once(); self.restore.assert_called_once()

    def test_longer_entry_cannot_consume_more_setup_allowance(self):
        target = [1, 0]+sleep.rtc.rtc_time(1060)
        for now, accepted in ((1000, True), (1015, True), (1016, False), (999, False)):
            current = self.before | {'alarm': target, 'rtc_time': sleep.rtc.rtc_time(now)}
            with patch.object(sleep.rtc, 'snapshot', return_value=current):
                if accepted: self.assertEqual(sleep.margin(10, target, 60), 1060-now)
                else:
                    with self.assertRaises(ValueError): sleep.margin(10, target, 60)


class Entry(unittest.TestCase):
    setUp = existing.Entry.setUp
    enter = existing.Entry.enter

    def prepare_extended(self):
        self.record.update(alarm_seconds=60, before={'boot_id': 'boot'}, connection='usb',
                           battery_window={'admission': endpoint(98, 'usb')})
        self.margin.return_value = 59
        self.observed = self.enterContext(patch.object(window, 'observe', side_effect=[endpoint(100, 'usb'), endpoint(161, 'usb')]))
        self.enterContext(patch.object(sleep, 'clock_pair', side_effect=[existing.Evidence.clock(101, 101),
                                                                       existing.Evidence.clock(161, 106)]))

    def test_invalid_entry_battery_never_submits_and_lost_guard_does_not_pass(self):
        self.prepare_extended()
        point = endpoint(100, 'usb'); point['capacity_percent'] = 10
        self.observed.side_effect = [point]
        with self.assertRaises(ValueError): self.enter()
        self.write.assert_not_called()

    def test_endpoints_are_saved_before_recovery_and_an_early_wake_stays_failed(self):
        self.prepare_extended()
        persisted = []
        def early(fd, timeout):
            self.assertEqual((fd, timeout), (10, 0))
            self.assertEqual(self.observed.call_count, 1)  # No post-return work can defer this check.
            raise ValueError('early/unrelated wake')
        self.delivery.side_effect = early
        with self.assertRaisesRegex(ValueError, 'early'):
            self.enter(persist=lambda: persisted.append(deepcopy(self.record)))
        self.assertEqual([c.args[0].name for c in self.write.call_args_list], ['wakeup_count', 'state'])
        self.assertEqual(persisted[-1]['battery_window']['returned'], endpoint(161, 'usb'))
        self.assertIn('early/unrelated wake', persisted[-1]['rtc']['delivery_error'])
        self.delivery.assert_called_once_with(10, 0)

    def test_disk_delay_makes_endpoint_stale_and_prevents_sleep(self):
        self.prepare_extended()
        with patch.object(sleep, 'clock_pair', return_value=existing.Evidence.clock(110, 110)), \
                self.assertRaisesRegex(ValueError, 'stale'):
            self.enter()
        self.assertEqual([c.args[0].name for c in self.write.call_args_list], ['wakeup_count'])

    def test_extended_awake_rehearsal_waits_for_matching_alarm_without_pm_writes(self):
        self.prepare_extended()
        with patch.object(sleep, 'clock_pair', return_value=existing.Evidence.clock(161, 161)), \
                patch.object(sleep.time, 'clock_gettime', return_value=101):
            self.enter('rehearse')
        self.write.assert_not_called(); self.delivery.assert_called_once_with(10, 65000)
        self.assertIn('returned', self.record['battery_window'])


class Evidence(unittest.TestCase):
    def test_offline_report_recomputes_endpoints_and_preserves_the_original_result(self):
        record = extended() | dict(run_id=existing.TOKEN, event='complete', passed=True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'result.json'
            for delayed in (False, True):
                if delayed: record['battery_window']['returned'] = endpoint(170)
                path.write_text(json.dumps(record))
                raw = path.read_bytes()
                result = existing.report.assess(path)
                self.assertEqual(result['measurement_checks_passed'], not delayed)
                self.assertFalse(result['overall_requalified'])
                self.assertEqual(path.read_bytes(), raw)
                if not delayed: self.assertFalse(result['battery_observation']['energy_qualified'])

    def test_full_interval_passes_but_early_wake_forged_target_or_setup_margin_does_not(self):
        record = extended()
        result = sleep.validate_delivery(record)
        self.assertEqual(result['alarm_elapsed_seconds'], 60)
        self.assertFalse(result['energy_qualified'])
        mutations = [lambda r: r.update(returned=existing.Evidence.clock(131, 131)),
                     lambda r: r['rtc'].update(entry_margin_seconds=44),
                     lambda r: r['rtc'].update(requested=[1, 0]+sleep.rtc.rtc_time(1030)),
                     lambda r: r['rtc'].update(interrupt=None),
                     lambda r: r.update(alarm_seconds=300)]
        for change in mutations:
            bad = deepcopy(record); change(bad)
            with self.subTest(change=change), self.assertRaises(ValueError): sleep.validate_delivery(bad)
        # An old default-duration record remains assessable as 30 seconds only.
        self.assertEqual(sleep.validate_delivery(existing.Evidence().delivery_record())['alarm_elapsed_seconds'], 30)


class Transport(unittest.TestCase):
    setUp = chain.Transport.setUp

    def test_sixty_second_submission_keeps_one_id_and_duration_specific_deadline(self):
        self.complete['alarm_seconds'] = 60
        with patch.object(host, 'collect', return_value=self.complete):
            host.experiment({}, self.root, self.root/'qualification', 'rtc-wake', chain.REHEARSAL, seconds=60)
        self.assertEqual(len(self.submissions), 1)
        self.assertIn('--alarm-seconds 60', self.submissions[0])
        self.assertIn('--property=RuntimeMaxSec=210', self.submissions[0])
        saved = json.loads((self.root/'run.json').read_text())
        self.assertEqual(saved['alarm_seconds'], 60)
        self.assertEqual(saved['budgets']['collection_seconds'], 240)

    def test_extended_host_expiry_preserves_original_identity_without_resubmission(self):
        with patch.object(host.time, 'monotonic', side_effect=[0, 241]), patch.object(host, 'collect') as collect:
            with self.assertRaisesRegex(TimeoutError, self.token):
                host.experiment({}, self.root, self.root/'qualification', 'rtc-wake', chain.REHEARSAL, seconds=60)
        collect.assert_not_called(); self.assertEqual(len(self.submissions), 1)
        self.assertEqual(json.loads((self.root/'run.json').read_text())['run_id'], self.token)


if __name__ == '__main__':
    unittest.main()
