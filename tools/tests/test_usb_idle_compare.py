"""Reject unmatched settings, unobserved reboots and incomplete comparison windows."""
import copy
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from awake_fixtures import proof, window

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('usb_idle',
    Path(__file__).resolve().parents[1] / 'compare-usb-idle.py')
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


def state(boot='old'):
    return dict(health=dict(boot_id=boot, online_cpus='0-3', brightness=1, bl_power=0, governor='schedutil'),
                radio={'power_save': 'off', 'signal_dbm': -60},
                capabilities={'cpufreq_time_in_state': 'changing', 'schedutil_rate_limit_us': '366'},
                kernel='same kernel', firmware_sha256='same firmware', wifi_config_sha256='same network',
                radio_events={'firmware_crashes': 0, 'sdio_removals': 0})


class ComparisonTests(unittest.TestCase):
    def test_drift_is_recordable_but_setting_or_radio_reset_change_is_rejected(self):
        before = state()
        baseline = compare.fixed(before)
        after = copy.deepcopy(before)
        after['radio']['signal_dbm'] = -70
        after['capabilities']['cpufreq_time_in_state'] = 'later counts'
        compare.require_state(after, baseline, 'old', before['radio_events'])
        after['health']['brightness'] = 2
        with self.assertRaises(ValueError):
            compare.require_state(after, baseline, 'old')
        after['health']['brightness'] = 1
        after['radio_events']['firmware_crashes'] = 1
        with self.assertRaises(ValueError):
            compare.require_state(after, baseline, 'old', before['radio_events'])

    def test_reboot_must_produce_a_new_boot(self):
        with patch.object(compare, 'state', side_effect=[state(), state('new')]), \
                patch.object(compare.time, 'monotonic', side_effect=[0, 1, 2]), \
                patch.object(compare.time, 'sleep'):
            self.assertEqual(compare.wait_new_boot({}, 'old', compare.fixed(state()))['health']['boot_id'], 'new')
        with patch.object(compare, 'state', return_value=state()), \
                patch.object(compare.time, 'monotonic', side_effect=[0, 1, 181]), \
                patch.object(compare.time, 'sleep'):
            with self.assertRaises(TimeoutError):
                compare.wait_new_boot({}, 'old', compare.fixed(state()))

    def test_new_boot_with_changed_settings_is_not_accepted(self):
        fresh = state('new')
        fresh['health']['brightness'] = 2
        with patch.object(compare, 'state', return_value=fresh):
            with self.assertRaises(ValueError):
                compare.wait_new_boot({}, 'old', compare.fixed(state()))

    def test_reboot_radio_default_is_restored_before_measurement(self):
        fresh = state('new')
        fresh['radio']['power_save'] = 'on'
        with patch.object(compare, 'device', return_value=nullcontext('client')), \
                patch.object(compare, 'run') as run, patch.object(compare, 'state', return_value=state('new')):
            restored = compare.restore_radio({}, fresh, compare.fixed(state()))
            self.assertEqual(restored['radio']['power_save'], 'off')
            self.assertEqual(restored['restored_wifi_power_save_from'], 'on')
            run.assert_called_once_with('client', 'sudo -n /usr/sbin/iw dev wlan0 set power_save off', display=False)
            fresh['health']['brightness'] = 2
            run.reset_mock()
            with self.assertRaises(ValueError):
                compare.restore_radio({}, fresh, compare.fixed(state()))
            run.assert_not_called()

    def test_measurement_requires_final_complete_record(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory)
            capture = local / 'diagnostics/capture'
            capture.mkdir(parents=True)
            path = capture / 'idle-sample.jsonl'
            with patch.object(compare, 'LOCAL', local), \
                    patch.object(compare, 'task', return_value='Private capture: ' + str(capture) + '\n'):
                path.write_text(json.dumps({'event': 'sample'}) + '\n')
                with self.assertRaises(ValueError):
                    compare.measurement(capture, 'idle', [], path.name, 300)
                complete = dict(event='complete', passed=True, duration_seconds=300.01, awake_proof=proof(301))
                path.write_text(json.dumps(dict(event='ready', seconds=600)) + '\n' + json.dumps(complete) + '\n')
                with self.assertRaises(ValueError):
                    compare.measurement(capture, 'idle', [], path.name, 300)
                path.write_text(json.dumps(dict(event='ready', seconds=300)) + '\n' + json.dumps(complete) + '\n')
                self.assertTrue(compare.measurement(capture, 'idle', [], path.name, 300)['summary']['passed'])

    def test_nested_task_does_not_inherit_outer_task_defaults(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'NEO_IDLE_SECONDS': '600', 'NEO_USB_POLL_MODE': 'status'}), \
                patch.object(compare.subprocess, 'run') as run:
            run.return_value.returncode = 0
            compare.task(Path(directory), 'inner', ['device:usb-policy', 'MODE=stock'])
            environment = run.call_args.kwargs['env']
            self.assertFalse(any(key.startswith('NEO_') for key in environment))
            self.assertEqual(environment['PATH'], os.environ['PATH'])

    @unittest.skipUnless(shutil.which('task'), 'Requires the project Task runner')
    def test_real_task_resolves_explicit_duration_and_policy(self):
        # Exercise the actual project env mapping, without a remote/device command.
        prefix = (compare.ROOT / 'Taskfile.yml').read_text().split('\ntasks:', 1)[0]
        with tempfile.TemporaryDirectory(prefix='neo nested task ') as directory, \
                patch.dict(os.environ, {'NEO_IDLE_SECONDS': '600', 'NEO_PROFILE_SECONDS': '600',
                                        'NEO_USB_POLL_MODE': 'status', 'NEO_ROUTE': 'usb'}):
            root = Path(directory)
            (root / 'Taskfile.yml').write_text(prefix + '\ntasks:\n  probe:\n    cmds: [python3 probe.py]\n')
            (root / 'probe.py').write_text('import os,json\nprint(json.dumps({key: os.environ[key] for key in '
                '["NEO_IDLE_SECONDS", "NEO_PROFILE_SECONDS", "NEO_USB_POLL_MODE", "NEO_ROUTE"]}))\n')
            output = compare.task(root, 'resolved', ['--taskfile', str(root / 'Taskfile.yml'), 'probe',
                                                     'SECONDS=300', 'MODE=stock', 'ROUTE=wifi'])
            self.assertEqual(json.loads(output), dict(NEO_IDLE_SECONDS='300', NEO_PROFILE_SECONDS='300',
                                                     NEO_USB_POLL_MODE='stock', NEO_ROUTE='wifi'))

    def test_next_boot_selection_cannot_substitute_for_active_policy(self):
        value = dict(running_policy_verified=True, boot_source_matches=True,
                     running_requested='Y', next_boot='stock')
        with patch.object(compare, 'task', return_value=json.dumps(value)):
            compare.policy(Path('/unused'), 'selection', 'experimental', 'stock')
            with self.assertRaises(ValueError):
                compare.policy(Path('/unused'), 'verification', 'stock')

    def test_selection_receipt_is_not_interpreted_as_running_status(self):
        value = dict(running_policy_verified=True, boot_source_matches=True,
                     running_requested='Y', next_boot='stock')
        receipt = dict(previous_next_boot='experimental', next_boot='stock', reboot_performed=False)
        with patch.object(compare, 'task', side_effect=[json.dumps(receipt) + '\n' + json.dumps(value),
                                                       json.dumps(value)]) as task:
            self.assertEqual(compare.policy(Path('/unused'), 'select', 'experimental', 'stock'), value)
            self.assertEqual(task.call_args_list[-1].args[2], ['device:usb-policy', 'ROUTE=wifi', 'MODE=status'])

    def test_resume_accepts_only_recent_completed_unchanged_phases(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory)
            capture = local / 'diagnostics/comparison'
            capture.mkdir(parents=True)
            phase = dict(mode='experimental', boot_id='old', passed=True, before=state(), after=state())
            phase['before']['awake_window'] = window(0, boot='old')
            phase['after']['awake_window'] = window(600, boot='old')
            for kind, filename, seconds in (('idle', 'idle-sample.jsonl', 300), ('profile', 'power-profile.jsonl', 120)):
                child = local / 'diagnostics' / kind
                child.mkdir()
                ready = dict(event='ready', seconds=seconds, utc=datetime.now(timezone.utc).isoformat())
                complete = dict(event='complete', passed=True, duration_seconds=seconds, awake_proof=proof(seconds, boot='old'))
                (child / filename).write_text(json.dumps(ready) + '\n' + json.dumps(complete) + '\n')
                phase[kind] = dict(capture=str(child), summary=complete)
            value = dict(passed=False, phases=[phase], baseline=state())
            path = capture / 'comparison.json'
            path.write_text(json.dumps(value))
            with patch.object(compare, 'LOCAL', local):
                self.assertEqual(len(compare.resume_report(capture)['phases']), 1)
                value['phases'].append(dict(mode='stock', boot_id='failed-boot', passed=False))
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    compare.resume_report(capture)
                retried = compare.resume_report(capture, retry_incomplete=True)
                self.assertEqual(len(retried['phases']), 1)
                self.assertEqual(retried['discarded_phases'][0]['phase']['boot_id'], 'failed-boot')
                self.assertFalse(retried['passed'])
                value['phases'].pop()
                phase['passed'] = False
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    compare.resume_report(capture)
                phase['passed'] = True
                phase['idle']['summary']['duration_seconds'] = 600
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    compare.resume_report(capture)
                phase['idle']['summary']['duration_seconds'] = 300
                path.write_text(json.dumps(value))
                ready['utc'] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
                (child / filename).write_text(json.dumps(ready) + '\n' + json.dumps(complete) + '\n')
                with self.assertRaises(ValueError):
                    compare.resume_report(capture)


if __name__ == '__main__':
    unittest.main()
