"""RSB experiments must restore their delay and report only measured counters."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from awake_fixtures import window, clock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), TOOLS / (name + '.py'))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


compare = module('compare-rsb')
host = module('check-rsb-runtime')


def counter(**changes):
    result = dict(control='auto', autosuspend_delay_ms=100, started_ns=1_000_000_000,
                  finished_ns=1_001_000_000, runtime_active_time=1000, runtime_suspended_time=0)
    result.update(changes)
    result['awake_window'] = window(result['started_ns'] / 1e9)
    return result


class RsbTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.delay, self.state, self.boot = [self.root / name for name in ('delay', 'state', 'boot')]
        self.delay.write_text('1000\n')
        self.boot.write_text('boot\n')
        for name, value in (('DELAY', self.delay), ('STATE', self.state), ('BOOT', self.boot)):
            replacement = patch.object(compare, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_normal_and_interrupted_exits_restore_exact_original(self):
        for error in (None, ValueError('health'), InterruptedError('SIGTERM')):
            with self.subTest(error=error):
                try:
                    with compare.saved_delay(100) as original:
                        self.assertEqual(original, 1000)
                        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
                        compare.set_delay(100)
                        if error:
                            raise error
                except (ValueError, InterruptedError) as caught:
                    self.assertIs(caught, error)
                self.assertEqual(self.delay.read_text().strip(), '1000')
                self.assertFalse(self.state.exists())

    def test_invalid_candidate_or_existing_state_never_changes_delay(self):
        for value in (True, 0, 9, 501, 1000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                with compare.saved_delay(value):
                    self.fail('Invalid candidate accepted')
        self.state.write_text('unfinished')
        with self.assertRaises(FileExistsError):
            with compare.saved_delay(100):
                self.fail('Unfinished state replaced')
        self.assertEqual(self.delay.read_text().strip(), '1000')
        self.assertEqual(self.state.read_text(), 'unfinished')

    def test_failed_readback_or_restore_keeps_recovery_record(self):
        with patch.object(Path, 'write_text'), self.assertRaises(ValueError):
            compare.set_delay(100)
        record = dict(path=str(self.delay), original_ms=1000, boot_id='boot')
        self.state.write_text(json.dumps(record))
        with patch.object(compare, 'set_delay', side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):
                compare.restore()
        self.assertTrue(self.state.exists())
        compare.restore()
        compare.restore()
        self.assertFalse(self.state.exists())

    def test_restore_rejects_foreign_path_boot_and_invalid_original(self):
        base = dict(path=str(self.delay), original_ms=1000, boot_id='boot')
        for change in ({'path': str(self.boot)}, {'boot_id': 'other'},
                       {'original_ms': True}, {'original_ms': -1}, {'original_ms': 60001}):
            with self.subTest(change=change):
                self.state.write_text(json.dumps(base | change))
                with self.assertRaises(ValueError):
                    compare.restore()
                self.assertTrue(self.state.exists())
                self.assertEqual(self.delay.read_text().strip(), '1000')

    def test_fresh_process_recovers_after_killed_worker(self):
        setup = ('import importlib.util, pathlib, sys, time\n'
                 f'sys.path.insert(0, {str(TOOLS)!r})\n'
                 f's = importlib.util.spec_from_file_location("rsb", {str(TOOLS / "compare-rsb.py")!r})\n'
                 'm = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n'
                 f'm.DELAY = pathlib.Path({str(self.delay)!r})\n'
                 f'm.STATE = pathlib.Path({str(self.state)!r})\n'
                 f'm.BOOT = pathlib.Path({str(self.boot)!r})\n')
        worker = setup + ('with m.saved_delay(100):\n m.set_delay(100)\n'
                          ' print("changed", flush=True)\n time.sleep(30)\n')
        with subprocess.Popen([sys.executable, '-u', '-c', worker], stdout=subprocess.PIPE, text=True) as process:
            try:
                self.assertEqual(process.stdout.readline().strip(), 'changed')
            finally:
                process.kill()
                process.wait(timeout=5)
        self.assertEqual(self.delay.read_text().strip(), '100')
        subprocess.run([sys.executable, '-c', setup + 'm.restore()'], check=True, timeout=5)
        self.assertEqual(self.delay.read_text().strip(), '1000')
        self.assertFalse(self.state.exists())

    def test_residency_uses_counter_deltas_without_inventing_resume_counts(self):
        before = counter()
        after = counter(started_ns=61_000_000_000, finished_ns=61_001_000_000,
                        runtime_active_time=16000, runtime_suspended_time=45000)
        result = compare.summarize(before, after)
        self.assertEqual(result['suspended_percent'], 75)
        self.assertEqual(result['counter_coverage_percent'], 100)
        self.assertEqual(result['seconds'], 60)
        self.assertIsNone(result['resume_count'])
        for change in ({'runtime_active_time': 0}, {'runtime_suspended_time': 1000},
                       {'control': 'on'}, {'autosuspend_delay_ms': 1000}, {'started_ns': 0}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                compare.summarize(before, after | change)

    def test_runtime_control_and_error_states_are_not_measurements(self):
        with patch.object(compare, 'BUS', self.root), patch.object(compare, 'observe', side_effect=clock()):
            power = self.root / 'power'
            power.mkdir()
            for name, value in counter().items():
                if name not in ('started_ns', 'finished_ns', 'awake_window'):
                    (power / name).write_text(str(value))
            (power / 'runtime_status').write_text('suspended')
            self.assertEqual(compare.residency()['runtime_status'], 'suspended')
            for name, value in (('runtime_status', 'error'), ('control', 'on')):
                with self.subTest(name=name):
                    original = (power / name).read_text()
                    (power / name).write_text(value)
                    with self.assertRaises(ValueError):
                        compare.residency()
                    (power / name).write_text(original)

    def test_service_has_independent_restoration_and_runtime_bound(self):
        directory = '/tmp/gameshellneo-rsb.abcdefgh'
        argv = host.service_command(directory, 120, 100)
        self.assertIn('--property=RuntimeMaxSec=495', argv)
        self.assertIn('--property=ExecStopPost=/usr/bin/python3 -B ' + directory + '/compare-rsb.py --restore', argv)
        for path, seconds, delay in (('/tmp/x;reboot', 120, 100), (directory, 1, 100),
                                     (directory, 120, 0), (directory, 120, 1000)):
            with self.assertRaises(ValueError):
                host.service_command(path, seconds, delay)


if __name__ == '__main__':
    unittest.main()
