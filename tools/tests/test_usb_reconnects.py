"""Cycle accounting and fast-sampling selection without real USB/SSH access."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


host = module('usb_reconnects', 'check-usb-reconnects.py')
recorder = module('usb_states', 'record-usb-states.py')


def events(*states):
    return [{'sequence': i, 'state': state} for i, state in enumerate(states)]


class CycleAccounting(unittest.TestCase):
    def test_initial_attachment_and_empty_capture_do_not_count(self):
        self.assertFalse(host.cycle_complete([], 'configured'))
        self.assertFalse(host.cycle_complete(events('powered', 'configured'), 'configured'))

    def test_one_removal_and_reconfiguration_counts(self):
        self.assertTrue(host.cycle_complete(events('not attached', 'powered', 'configured'),
                                            'configured'))

    def test_pending_or_stale_configuration_does_not_count(self):
        self.assertFalse(host.cycle_complete(events('not attached', 'powered'), 'powered'))
        self.assertFalse(host.cycle_complete(events('not attached', 'configured'), 'not attached'))
        self.assertFalse(host.cycle_complete(events('configured', 'not attached'), 'configured'))

    def test_multiple_unchecked_removals_fail(self):
        with self.assertRaisesRegex(RuntimeError, 'Multiple removals'):
            host.cycle_complete(events('not attached', 'configured', 'not attached', 'configured'),
                                'configured')

    def test_configuration_must_follow_removal_in_sequence(self):
        invalid = [{'sequence': 3, 'state': 'not attached'},
                   {'sequence': 2, 'state': 'configured'}]
        with self.assertRaisesRegex(ValueError, 'No configured state'):
            host.cycle_complete(invalid, 'configured')

    def test_cli_selects_and_records_interval_without_changing_default(self):
        for flags, milliseconds, mode in (([], 250, 'standard'), (['--rapid'], 20, 'rapid')):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                def complete(_config, cycles, _timeout, emit, _directory, sample_ms):
                    self.assertEqual(sample_ms, milliseconds)
                    emit('verified', cycle=cycles)
                with patch.object(host.sys, 'argv', ['check-usb-reconnects.py'] + flags), \
                     patch.object(host, 'LOCAL', root), \
                     patch.object(host, 'evidence_directory', return_value=root), \
                     patch.object(host, 'load_env', return_value={}), \
                     patch.object(host, 'observe', side_effect=complete), redirect_stdout(io.StringIO()):
                    self.assertEqual(host.main(), 0)
                result = json.loads((root / 'summary.json').read_text())
                self.assertEqual(result['mode'], mode)
                self.assertEqual(result['sample_interval_ms'], milliseconds)
                self.assertEqual(result['verified_cycles'], 4)
                self.assertFalse(result['physical_timing_qualified'])


class RecorderSampling(unittest.TestCase):
    def test_both_intervals_keep_changes_ordered_and_record_monotonic_observations(self):
        for flags, milliseconds in (([], 250), (['--sample-ms', '20'], 20)):
            with self.subTest(milliseconds=milliseconds):
                state = MagicMock()
                state.read_text.side_effect = ['configured', 'configured', 'not attached', 'configured']
                controller = MagicMock()
                controller.glob.return_value = [state]
                boot = MagicMock()
                boot.read_text.return_value = 'test-boot\n'
                output = io.StringIO()
                with patch.object(recorder, 'Path', side_effect=[controller, boot]), \
                     patch('sys.argv', ['record-usb-states.py'] + flags), \
                     patch.object(recorder.time, 'monotonic', side_effect=[10, 10.02, 10.04, 10.06]), \
                     patch.object(recorder.time, 'sleep', side_effect=[None, None, None, StopIteration]) as sleep, \
                     redirect_stdout(output), self.assertRaises(StopIteration):
                    recorder.main()
                captured = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual([e['state'] for e in captured],
                                 ['configured', 'not attached', 'configured'])
                self.assertEqual([e['sequence'] for e in captured], [0, 1, 2])
                self.assertEqual([e['monotonic'] for e in captured], [10, 10.04, 10.06])
                self.assertTrue(all(e['sample_interval_ms'] == milliseconds for e in captured))
                self.assertTrue(all(e['boot_id'] == 'test-boot' for e in captured))
                self.assertEqual([c.args for c in sleep.call_args_list], [(milliseconds / 1000,)] * 4)

    def test_unsupported_interval_is_rejected_before_sysfs_access(self):
        with patch('sys.argv', ['record-usb-states.py', '--sample-ms', '0']), \
             patch.object(recorder, 'Path') as paths, redirect_stderr(io.StringIO()), \
             self.assertRaises(SystemExit):
            recorder.main()
        paths.assert_not_called()


if __name__ == '__main__':
    unittest.main()
