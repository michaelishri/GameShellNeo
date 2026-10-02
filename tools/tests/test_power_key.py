"""Guard event continuity, inhibitor identity and bounded handoff without hardware."""
import sys
from pathlib import Path
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import power_key as key


def event(code=116, value=1, kind=1, seconds=10):
    return key.EVENT.pack(seconds, 0, kind, code, value)


def state(**changes):
    return dict(ioctl_errno=None, hung_up=False, poll_error=False, held_key_codes=[]) | changes


class Inhibition(unittest.TestCase):
    def test_own_ancestor_low_level_inhibitor_is_required(self):
        good = ['idle:sleep:handle-power-key', key.WHO, 'test', 'block', 0, 42]
        def doc(row):
            return dict(type='a(ssssuu)', data=[[row]])
        self.assertEqual(key.validate_inhibitors(doc(good), {42})['pid'], 42)
        for index, value in ((0, 'sleep:idle'), (1, 'other'), (3, 'delay'), (4, 1000), (5, 43)):
            row = good.copy(); row[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                key.validate_inhibitors(doc(row), {42})
        with self.assertRaises(ValueError):
            key.validate_inhibitors(dict(type='unexpected', data=[]), {42})


class Events(unittest.TestCase):
    def test_waking_press_is_consumed_until_release(self):
        record = {}; c = key.Consumer(record); c.resumed = 9
        c.feed(event())
        self.assertFalse(c.released(state()))
        c.feed(event(value=2))
        self.assertFalse(c.released(state()))
        c.feed(event(value=0, seconds=12))
        self.assertTrue(c.released(state()))
        self.assertEqual(len(record['events']), 3)
        self.assertFalse(c.released(state(held_key_codes=[116])))

    def test_suspend_logical_clear_is_not_physical_release_claim(self):
        record = {}; c = key.Consumer(record); c.resumed = 20
        c.feed(event() + event(value=0, seconds=11))
        self.assertTrue(record['pre_resume_release_seen'])
        self.assertNotIn('physical_release_verified', record)

    def test_loss_disconnect_and_bad_events_cannot_pass(self):
        for data in (b'', b'x', event(kind=0, code=3, value=0), event(code=42), event(value=2)):
            with self.subTest(data=data):
                c = key.Consumer({})
                with self.assertRaises(ValueError):
                    c.feed(data)
                self.assertFalse(c.released(state()))
        for change in (dict(ioctl_errno=19), dict(hung_up=True), dict(poll_error=True)):
            self.assertFalse(key.Consumer({}).released(state(**change)))

    def test_held_key_timeout_is_bounded_and_not_handed_back(self):
        record = {}; guard = key.Guard(10, record, Mock())
        guard.consumer.feed(event())
        with patch.object(guard, 'drain'), patch.object(key.time, 'monotonic', side_effect=[0, 0, 9]), \
                patch.object(key, 'handle_state', return_value=state(held_key_codes=[116])):
            with self.assertRaises(TimeoutError):
                guard.finish()
        self.assertFalse(record['handed_back'])

    def test_entry_rechecks_inhibitor_and_refuses_touched_key(self):
        guard = key.Guard(10, {}, Mock())
        with patch.object(guard, 'drain'), patch.object(key, 'verify_inhibitor', return_value={}), \
                patch.object(key, 'handle_state', return_value=state()):
            guard.before_entry()
            guard.consumer.feed(event() + event(value=0))
            with self.assertRaises(ValueError):
                guard.before_entry()
        with patch.object(key, 'verify_inhibitor', side_effect=ValueError('lost inhibitor')):
            with self.assertRaisesRegex(ValueError, 'lost inhibitor'):
                guard.before_entry()

    def test_handoff_rechecks_inhibition_before_accepting(self):
        guard = key.Guard(10, {}, Mock()); guard.consumer.last_event = -1
        with patch.object(guard, 'drain'), patch.object(key.time, 'monotonic', return_value=0), \
                patch.object(key, 'handle_state', return_value=state()), \
                patch.object(key, 'verify_inhibitor', side_effect=ValueError('lost inhibitor')):
            with self.assertRaisesRegex(ValueError, 'lost inhibitor'):
                guard.finish()
            self.assertNotIn('logical_release_verified', guard.record)


class Ownership(unittest.TestCase):
    def test_cleanup_and_abnormal_records(self):
        for cleanup_error in (None, TimeoutError('held')):
            with self.subTest(cleanup_error=cleanup_error), tempfile.TemporaryDirectory() as temporary:
                owned = Path(temporary)/'owner'
                boot = Path(temporary)/'boot'; boot.write_text('boot')
                record = {}
                def save(_data, path):
                    path.write_text('owned')
                with patch.object(key, 'OWNED', owned), patch.object(key, 'BOOT', boot), \
                        patch.object(key, 'verify_inhibitor', return_value={}), \
                        patch.object(key, 'identity', return_value=dict(node='/dev/fixture', dev='13:64')), \
                        patch.object(key.os, 'open', return_value=10), patch.object(key.os, 'close') as close, \
                        patch.object(key.os, 'fstat', return_value=SimpleNamespace(st_mode=0o020600, st_rdev=key.os.makedev(13,64))), \
                        patch.object(key.fcntl, 'ioctl') as ioctl, patch.object(key, 'save_owned', side_effect=save), \
                        patch.object(key, 'handle_state', return_value=state()), \
                        patch.object(key.Guard, 'finish', side_effect=cleanup_error):
                    if cleanup_error:
                        with self.assertRaises(TimeoutError):
                            with key.own(record, Mock()):
                                pass
                        self.assertTrue(owned.exists())
                        self.assertFalse(record['handed_back'])
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'PM rejected'):
                            with key.own(record, Mock()):
                                raise RuntimeError('PM rejected')
                        self.assertFalse(owned.exists())
                        self.assertTrue(record['handed_back'])
                        ioctl.assert_any_call(10, 0x40044590, 0)
                    close.assert_called_once_with(10)
                    self.assertTrue(record['descriptor_closed'])

    def test_stale_owner_blocks_another_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            owned = Path(temporary)/'owner'; owned.touch()
            with patch.object(key, 'OWNED', owned), patch.object(key, 'verify_inhibitor') as verify:
                with self.assertRaises(ValueError):
                    with key.own({}, Mock()):
                        self.fail('stale owner accepted')
                verify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
