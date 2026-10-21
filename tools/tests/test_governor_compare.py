"""Exercise rollback with filesystem stand-ins; never access real CPU controls."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('compare_governor', TOOLS / 'compare-governor.py')
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)
sys.path.insert(0, str(TOOLS))
from remote import governor_command


class GovernorRecovery(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='neo-governor-test-')
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.rate, self.state, self.boot = [root / name for name in ('rate', 'state.json', 'boot')]
        self.rate.write_text('366\n')
        self.boot.write_text('test-boot\n')
        for name, value in [('RATE_PATHS', (self.rate,)), ('STATE', self.state), ('BOOT_ID', self.boot)]:
            replacement = patch.object(compare, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_normal_return_restores_saved_value(self):
        with compare.saved_rate(10000) as (path, original):
            self.assertEqual(original, 366)
            self.assertEqual(self.rate.read_text().strip(), '366')
            self.assertEqual(json.loads(self.state.read_text())['original_us'], 366)
            self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
            compare.set_rate(path, 10000)
        self.assertEqual(self.rate.read_text().strip(), '366')
        self.assertFalse(self.state.exists())

    def test_exception_and_handled_signal_restore(self):
        for error in (ValueError('failed health check'), InterruptedError('SIGTERM')):
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                with compare.saved_rate(10000) as (path, _):
                    compare.set_rate(path, 10000)
                    raise error
            self.assertEqual(self.rate.read_text().strip(), '366')
            self.assertFalse(self.state.exists())

    def test_invalid_candidates_and_existing_state_do_not_write(self):
        for candidate in (0, 366, 999, 100001):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                with compare.saved_rate(candidate):
                    self.fail('Invalid candidate accepted')
        self.state.write_text('unfinished')
        with self.assertRaises(FileExistsError):
            with compare.saved_rate(10000):
                self.fail('Existing restoration state replaced')
        self.assertEqual(self.rate.read_text().strip(), '366')
        self.assertEqual(self.state.read_text(), 'unfinished')

    def test_readback_failure_and_failed_cleanup_keep_recovery_evidence(self):
        with patch.object(Path, 'write_text'), self.assertRaises(ValueError):
            compare.set_rate(self.rate, 10000)
        with self.assertRaises(OSError):
            with compare.saved_rate(10000) as (path, _):
                compare.set_rate(path, 10000)
                with patch.object(compare, 'set_rate', side_effect=OSError('read-only sysfs')):
                    compare.restore_pending()
                    # Unreachable: the context manager will retry outside this patch.
        self.assertEqual(self.rate.read_text().strip(), '366')
        # Test a failed independent stop hook, where the record must remain.
        self.state.write_text(json.dumps(dict(path=str(self.rate), original_us=366, boot_id='test-boot')))
        with patch.object(compare, 'set_rate', side_effect=OSError('unavailable')), self.assertRaises(OSError):
            compare.restore_pending()
        self.assertTrue(self.state.exists())
        compare.restore_pending()
        self.assertFalse(self.state.exists())

    def test_restore_rejects_wrong_boot_path_or_value(self):
        original = dict(path=str(self.rate), original_us=366, boot_id='test-boot')
        for invalid in (dict(boot_id='different-boot'), dict(path=str(self.boot)),
                        dict(original_us=-1), dict(original_us=True)):
            self.state.write_text(json.dumps(original | invalid))
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                compare.restore_pending()
            self.assertTrue(self.state.exists())
            self.assertEqual(self.rate.read_text().strip(), '366')

    def subprocess_setup(self):
        return ('import importlib.util, pathlib, sys, time\n'
                f'sys.path.insert(0, {str(TOOLS)!r})\n'
                f'spec = importlib.util.spec_from_file_location("compare", {str(TOOLS / "compare-governor.py")!r})\n'
                'm = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(m)\n'
                f'm.RATE_PATHS = (pathlib.Path({str(self.rate)!r}),)\n'
                f'm.STATE = pathlib.Path({str(self.state)!r})\n'
                f'm.BOOT_ID = pathlib.Path({str(self.boot)!r})\n')

    def test_fresh_process_restores_after_sigkill(self):
        source = self.subprocess_setup() + (
            'with m.saved_rate(10000) as (path, original):\n'
            ' m.set_rate(path, 10000)\n print("ready", flush=True)\n time.sleep(10)\n')
        with subprocess.Popen([sys.executable, '-B', '-u', '-c', source], stdout=subprocess.PIPE,
                              text=True) as process:
            try:
                self.assertEqual(process.stdout.readline().strip(), 'ready')
                process.kill()
                process.wait(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
        self.assertEqual(self.rate.read_text().strip(), '10000')
        self.assertTrue(self.state.exists())
        subprocess.run([sys.executable, '-B', '-c', self.subprocess_setup() + 'm.restore_pending()'],
                       check=True, timeout=5)
        self.assertEqual(self.rate.read_text().strip(), '366')
        self.assertFalse(self.state.exists())

    def test_remote_unit_has_independent_cleanup_and_bounded_runtime(self):
        args = governor_command('/tmp/gameshellneo-governor.abc123', 120, 10000)
        self.assertIn('--property=RuntimeMaxSec=510', args)
        self.assertIn('--property=ExecStopPost=/usr/bin/python3 -B '
                      '/tmp/gameshellneo-governor.abc123/compare-governor.py --restore', args)
        self.assertEqual(shlex.split(shlex.join(args)), args)
        for directory, seconds, rate in (('/tmp/unsafe;command', 120, 10000),
                                         ('/tmp/gameshellneo-governor.ok', 1, 10000),
                                         ('/tmp/gameshellneo-governor.ok', 120, 100001)):
            with self.assertRaises(ValueError):
                governor_command(directory, seconds, rate)

    @unittest.skipUnless(os.environ.get('NEO_SYSTEMD_TESTS') == '1', 'opt-in user-systemd recovery test')
    def test_systemd_exec_stop_post_restores_after_failure_kill_and_timeout(self):
        # A user unit and temporary files exercise real systemd lifecycle behavior without sudo/sysfs.
        worker = Path(self.directory.name) / 'worker.py'
        for mode in ('normal', 'error', 'term', 'kill', 'timeout'):
            with self.subTest(mode=mode):
                worker.write_text(self.subprocess_setup() +
                                  'if "--restore" in sys.argv:\n m.restore_pending(); sys.exit(0)\n'
                                  'with m.saved_rate(10000) as (path, original):\n'
                                  ' m.set_rate(path, 10000)\n'
                                  ' print("changed=10000", flush=True)\n'
                                  + {'normal': ' pass\n', 'error': ' raise ValueError("test failure")\n',
                                     'term': f' import os; os.kill(os.getpid(), {signal.SIGTERM})\n',
                                     'kill': f' import os; os.kill(os.getpid(), {signal.SIGKILL})\n',
                                     'timeout': ' time.sleep(15)\n'}[mode])
                args = ['systemd-run', '--user', '--quiet', '--wait', '--pipe', '--collect',
                        '--property=RuntimeMaxSec=2', '--property=TimeoutStopSec=5',
                        f'--property=ExecStopPost={sys.executable} -B {worker} --restore',
                        sys.executable, '-B', str(worker)]
                result = subprocess.run(args, capture_output=True, text=True, timeout=15)
                self.assertIn('changed=10000', result.stdout, result.stderr)
                # systemd treats an unhandled SIGTERM as a clean service exit.
                if mode in ('normal', 'term'):
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.rate.read_text().strip(), '366', result.stderr)
                self.assertFalse(self.state.exists(), result.stderr)


if __name__ == '__main__':
    unittest.main()
