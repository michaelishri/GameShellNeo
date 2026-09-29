"""Counter interpretation and rollback without kernel or device access."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), TOOLS / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


probe = module('test-usb-diagnostics')
runner = module('check-usb-diagnostics')


def counters(**changes):
    value = dict(version=1, entries=0, completed=0, success=0, real_errors=0,
                 injected_errors=0, inflight=0, budget=0, enabled=1, generation=1,
                 synthetic_requests=0, monotonic_ns=1_000_000_000, experimental=1,
                 events=[], status=48)
    value.update(changes)
    return value


class UsbDiagnosticTests(unittest.TestCase):
    def test_other_active_observers_are_rejected(self):
        with patch.object(probe.subprocess, 'check_output', return_value='gameshellneo-power-profile.service loaded active running\n'):
            with self.assertRaises(ValueError):
                probe.check_observers()
        with patch.object(probe.subprocess, 'check_output', return_value=''):
            probe.check_observers()

    def test_interrupted_measurement_disables_controls_and_clears_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {
                '/etc/gameshellneo/image.json': json.dumps(dict(board='gameshellneo-cpi31', kernel='test', version='test',
                                                               sources={'experiments': {'usb_diagnostics': True}})),
                '/proc/sys/kernel/tainted': '0',
                '/boot-id': 'one\n',
            }
            for name, content in files.items():
                path = root / name.lstrip('/')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            state = root / 'state'
            with patch.object(probe, 'STATE', state), patch.object(probe, 'BOOT', root / 'boot-id'), \
                 patch.object(probe, 'Path', side_effect=lambda value: root / value.lstrip('/')), \
                 patch.object(probe.os, 'uname', return_value=SimpleNamespace(release='test')), \
                 patch.object(probe, 'snapshot', return_value=counters(enabled=0)), \
                 patch.object(probe, 'quiet_snapshot', side_effect=[counters(), counters(enabled=0)]), \
                 patch.object(probe, 'command') as command, patch.object(probe, 'check_observers'), \
                 patch.object(probe, 'emit'), patch.object(probe.time, 'sleep', side_effect=InterruptedError('lost observer')):
                with self.assertRaises(InterruptedError):
                    probe.execute('count', 60, 1)
            self.assertEqual([call.args[0] for call in command.call_args_list], ['enable', 'disable'])
            self.assertFalse(state.exists())

    def test_natural_counts_use_elapsed_time_and_reject_contamination(self):
        before = counters()
        after = counters(entries=240, completed=240, success=240, monotonic_ns=61_000_000_000)
        self.assertEqual(probe.count_result(before, after)['callbacks_per_second'], 4)
        for changes in ({'generation': 2}, {'experimental': 0}, {'monotonic_ns': 1},
                        {'synthetic_requests': 1}, {'enabled': 0}, {'entries': 241},
                        {'success': 239, 'real_errors': 1}, {'inflight': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                probe.count_result(before, dict(after, **changes))

    def test_experimental_and_stock_online_recovery_differ(self):
        for policy in (0, 1):
            before = counters(experimental=policy)
            amount = 4 if policy else 1
            events = [dict(result=-5, status=48, retry_ms=50 if policy else 0, injected=1)] * amount
            if policy:
                events += [dict(result=0, status=48, retry_ms=0, injected=0)]
            after = counters(experimental=policy, synthetic_requests=1,
                             entries=amount + policy, completed=amount + policy, success=policy,
                             injected_errors=amount, events=events)
            result = probe.error_result(before, after, 4, 48)
            self.assertEqual(result['successful_real_read_observed'], bool(policy))
            for changes in ({'budget': 1}, {'status': 0}, {'events': []}, {'generation': 2}, {'enabled': 0}):
                with self.subTest(policy=policy, changes=changes), self.assertRaises(ValueError):
                    probe.error_result(before, dict(after, **changes), 4, 48)

    def test_restore_is_idempotent_and_checks_boot_and_disabled_readback(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / 'state'
            boot = Path(temporary) / 'boot'
            boot.write_text('one\n')
            with patch.object(probe, 'STATE', state), patch.object(probe, 'BOOT', boot), \
                 patch.object(probe, 'command') as command, \
                 patch.object(probe, 'quiet_snapshot', return_value=counters(enabled=0)) as snapshot:
                probe.restore()
                command.assert_not_called()
                state.write_text(json.dumps({'boot_id': 'two'}))
                with self.assertRaises(ValueError):
                    probe.restore()
                command.assert_not_called()
                state.write_text(json.dumps({'boot_id': 'one'}))
                snapshot.return_value = counters(enabled=1)
                with self.assertRaises(ValueError):
                    probe.restore()
                self.assertTrue(state.exists())
                snapshot.return_value = counters(enabled=0)
                probe.restore()
                command.assert_called_with('disable')
                self.assertFalse(state.exists())

    def test_service_keeps_recovery_independent_of_host(self):
        script = '/tmp/gameshellneo-usb-diag.abcdefgh/test-usb-diagnostics.py'
        command = runner.service_command(script, 'errors', 60, 4)
        self.assertIn('--property=RuntimeMaxSec=90', command)
        self.assertIn('--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore', command)
        for path, mode, seconds, errors in ((script, 'bad', 60, 1), (script, 'errors', 60, 5),
                                           (script, 'count', 301, 1), ('/tmp/x; reboot', 'count', 60, 1)):
            with self.assertRaises(ValueError):
                runner.service_command(path, mode, seconds, errors)


if __name__ == '__main__':
    unittest.main()
