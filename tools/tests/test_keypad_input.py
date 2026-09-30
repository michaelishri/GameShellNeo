"""Physical edges, held-key continuity, loss rejection and bounded cleanup."""
from contextlib import contextmanager
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import keypad_input as keys


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


host = load('input_host', 'check-pm-stages.py')
pm = load('input_pm', 'test-pm-stages.py')


def event(code, value, kind=1):
    return keys.EVENT.pack(123, 456, kind, code, value)


def state(down=()):
    return dict(ioctl_errno=None, hung_up=False, poll_error=False,
                disconnected=False, held_key_codes=sorted(down))


class EventEvidence(unittest.TestCase):
    def test_native_abi_and_ordered_press_repeat_release(self):
        self.assertIn(keys.EVENT.size, (16, 24))
        record = {}
        log = keys.EventLog(record)
        log.feed(event(36, 1) + event(36, 2))
        self.assertEqual(log.state()[0], {36})
        log.feed(event(36, 0))
        self.assertFalse(log.state()[0])
        self.assertEqual(record['events'][0]['seconds'], 123.000456)

    def test_queue_loss_bad_edges_and_partial_records_cannot_pass(self):
        for data in (event(3, 0, 0), event(36, 0), event(36, 2),
                     event(36, 1) * 2, event(36, 9), b'', event(36, 1)[:-1]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                keys.EventLog({}).feed(data)
        with patch.object(keys, 'MAX_EVENTS', 1), self.assertRaises(ValueError):
            keys.EventLog({}).feed(event(36, 1) + event(36, 0))

    def test_reader_keeps_one_fd_across_two_event_windows(self):
        read_fd, write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        record = {}
        session = keys.Session(read_fd, record)
        session.thread.start()
        try:
            for value, count in ((1, 1), (0, 2)):
                os.write(write_fd, event(36, value))
                deadline = time.monotonic() + 1
                while session.log.state()[1] < count and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(session.log.state()[1], count)
            self.assertEqual([e['value'] for e in record['events']], [1, 0])
        finally:
            session.stop.set()
            session.thread.join(1)
            os.close(write_fd)
            os.close(read_fd)

    def test_wrong_button_and_timeout_stop_the_sequence(self):
        session = keys.Session(-1, {})
        session.log.feed(event(37, 1))
        with self.assertRaisesRegex(ValueError, 'Unexpected button'):
            session.wait_edges(0, 36, [1])
        with patch.object(keys.time, 'monotonic', side_effect=[0, 20]), self.assertRaises(TimeoutError):
            session.wait_edges(1, 36, [0])

    def simulate(self):
        record = {}
        session = keys.Session(17, record)
        original = session.prompt
        def prompt(phase, *lines):
            original(phase, *lines)
            for label, code in keys.BUTTONS:
                if phase in ('before-' + label, 'after-' + label):
                    session.log.feed(event(code, 1) + event(code, 0))
            if phase == 'hold':
                session.log.feed(event(36, 1))
            if phase == 'release':
                session.log.feed(event(36, 0))
        return record, session, prompt

    def test_complete_sequence_and_held_bitmap_on_original_fd(self):
        record, session, prompt = self.simulate()
        with patch.object(session, 'prompt', side_effect=prompt), \
                patch.object(Path, 'write_text'), patch.object(keys.time, 'sleep'), \
                patch.object(keys, 'handle_state', side_effect=lambda fd: state(session.log.state()[0])) as handle:
            session.before_stage()
            session.verify_hold('immediately-before-entry')
            session.log.feed(event(36, 2))  # Normal repeat does not invalidate a hold.
            session.after_stage()
            session.checkpoint('final', [])
        self.assertTrue(record['passed'])
        self.assertTrue(all(c.args[0] == 17 for c in handle.call_args_list))
        record.update(grab_released=True, console_restored=True)
        retention = dict(original_handle_healthy=True, usb_device_number_unchanged=True,
                         input_sysfs_unchanged=True, keypad_disconnects=0)
        result = dict(physical_input=record, keypad={'old_handle_after': state()})
        host.validate_physical_result(result, retention)
        record['events'].append(dict(type=1, code=36, value=1))
        with self.assertRaisesRegex(ValueError, 'complete ordered sequence'):
            host.validate_physical_result(result, retention)

    def test_release_repress_during_pm_is_not_continuous_hold(self):
        record, session, prompt = self.simulate()
        with patch.object(session, 'prompt', side_effect=prompt), \
                patch.object(Path, 'write_text'), patch.object(keys.time, 'sleep'), \
                patch.object(keys, 'handle_state', side_effect=lambda fd: state(session.log.state()[0])):
            session.before_stage()
            session.log.feed(event(36, 0) + event(36, 1))
            with self.assertRaisesRegex(ValueError, 'hold interrupted'):
                session.after_stage()
        self.assertFalse(record['passed'])


class Cleanup(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name, path in (('CONSOLE_OWNED', 'owner.json'), ('SCREEN', 'screen'), ('TTY', 'tty')):
            self.enterContext(patch.object(keys, name, self.root / path))
        self.screen = bytes([2, 4, 1, 1]) + b'x\x07' * 8
        keys.SCREEN.write_bytes(self.screen)
        self.enterContext(patch.object(keys, 'optional', side_effect=lambda path:
            'tty1' if path.endswith('/active') else 'boot-one'))

    def test_console_restores_after_failure_and_fresh_recovery(self):
        with self.assertRaises(RuntimeError):
            with keys.console():
                keys.SCREEN.write_bytes(self.screen[:4] + b'y\x07' * 8)
                raise RuntimeError('failed')
        self.assertEqual(keys.SCREEN.read_bytes(), self.screen)
        self.assertFalse(keys.CONSOLE_OWNED.exists())
        keys.CONSOLE_OWNED.write_text(json.dumps(dict(boot_id='boot-one',
            screen=base64.b64encode(self.screen).decode())))
        keys.restore_console()
        self.assertFalse(keys.CONSOLE_OWNED.exists())

    def test_other_boot_or_geometry_keeps_ownership_for_inspection(self):
        for boot, data in (('other', self.screen), ('boot-one', bytes([3, 4, 0, 0]) + b'x\x07' * 12)):
            keys.CONSOLE_OWNED.write_text(json.dumps(dict(boot_id=boot, screen=base64.b64encode(data).decode())))
            with self.assertRaises(ValueError):
                keys.restore_console()
            self.assertTrue(keys.CONSOLE_OWNED.exists())
        self.assertEqual(keys.SCREEN.read_bytes(), self.screen)

    def test_failed_sequence_releases_grab_and_restores_console(self):
        record = {}
        with patch.object(keys, 'handle_state', return_value=state()), \
                patch.object(keys.fcntl, 'ioctl') as ioctl, \
                patch.object(keys.Session, 'read_events'), patch.object(keys.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'injected failure'):
                with keys.capture(record, 17):
                    raise RuntimeError('injected failure')
        self.assertFalse(record['passed'])
        self.assertTrue(record['grab_released'] and record['console_restored'])
        self.assertEqual(ioctl.call_args_list[0].args, (17, keys.EVIOCGRAB, 1))
        self.assertEqual(ioctl.call_args_list[-1].args, (17, keys.EVIOCGRAB, 0))
        self.assertEqual(keys.SCREEN.read_bytes(), self.screen)

    def test_console_restore_failure_cannot_prevent_pm_restore(self):
        with patch.object(sys, 'argv', ['test', '--restore']), \
                patch('keypad_pm.restore_trace'), patch('keypad_pm.restore_persistence'), \
                patch.object(keys, 'restore_console', side_effect=OSError('console error')), \
                patch.object(pm, 'restore') as restore:
            with self.assertRaises(OSError):
                pm.main()
            restore.assert_called_once_with()


class EntryGuards(unittest.TestCase):
    def test_input_mode_cannot_widen_pm_scope(self):
        for stage, trace, persist, lock in (
                ('devices', True, None, {}), ('freezer', True, None, {}),
                ('devices', False, None, {}), ('devices', True, '0', {})):
            with patch.object(pm, 'result_dir') as directory, self.assertRaises(ValueError):
                pm.test_stage(lock, stage, 'a'*32, trace, persist, True)
            directory.assert_not_called()
        args = host.service_command('/tmp/gameshellneo-pm.test', 'devices', 'a'*32, True, None, True)
        self.assertIn('--property=RuntimeMaxSec=240', args)
        self.assertIn('--keypad-input', args)
        self.assertTrue(any(a.startswith('--property=ExecStopPost=') for a in args))

    def test_failed_physical_preparation_never_enters_pm(self):
        @contextmanager
        def observe(record, tracing=False):
            record['before'] = {'fixture': 'keypad'}
            yield 17
        @contextmanager
        def capture(record, fd):
            class Input:
                def before_stage(self):
                    raise ValueError('physical sequence rejected')
            yield Input()
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(pm, 'result_dir', return_value=Path(temporary)/'run'), \
                patch.object(pm, 'snapshot', return_value={}), patch.object(pm, 'validate'), \
                patch.object(pm, 'command', return_value=''), patch('keypad_pm.observe', observe), \
                patch('keypad_pm.keypad_identity'), patch.object(keys, 'capture', capture), \
                patch.object(pm, 'enter_stage') as enter:
            with self.assertRaisesRegex(ValueError, 'physical sequence rejected'):
                pm.test_stage({'experiments': {'keypad_supply_retention': True}},
                              'devices', 'a'*32, True, None, True)
            enter.assert_not_called()
            result = json.loads((Path(temporary)/'run/result.json').read_text())
            self.assertEqual(result['event'], 'failed')
            self.assertNotIn('stage_seconds', result)


if __name__ == '__main__':
    unittest.main()
