"""Check keypad disconnect observation and bounded trace ownership/recovery."""
import errno
import json
from pathlib import Path
import select
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import keypad_pm as keypad

DEBUG_TEXT = ('drivers/usb/core/hub.c:3311 [usbcore]check_port_resume_type =_ "status"\n'
              'drivers/usb/core/hcd.c:2268 [usbcore]hcd_bus_suspend =mf "bus"\n'
              'drivers/usb/core/hub.c:6000 [usbcore]hub_event =p "unrelated"\n')


class InputHandles(unittest.TestCase):
    def test_dead_handle_is_not_confused_with_reused_event_path(self):
        info = dict(inputs=[dict(event='/dev/input/event1')])
        states = [dict(ioctl_errno=None), dict(ioctl_errno=errno.ENODEV), dict(ioctl_errno=None)]
        with patch.object(keypad, 'inspect', return_value=info), \
                patch.object(keypad.os, 'open', side_effect=[10, 11]), \
                patch.object(keypad.os, 'close') as close, \
                patch.object(keypad, 'handle_state', side_effect=states) as handle:
            result = {}
            with keypad.observe(result):
                pass
            self.assertEqual([call.args[0] for call in handle.call_args_list], [10, 10, 11])
            self.assertEqual(result['old_handle_after']['ioctl_errno'], errno.ENODEV)
            self.assertIsNone(result['new_handle_after']['ioctl_errno'])
            self.assertEqual([call.args[0] for call in close.call_args_list], [11, 10])

    def test_exception_closes_original_handle(self):
        with patch.object(keypad, 'inspect', return_value=dict(inputs=[dict(event='/dev/input/event1')])), \
                patch.object(keypad.os, 'open', return_value=10), \
                patch.object(keypad.os, 'close') as close, \
                patch.object(keypad, 'handle_state', return_value=dict(ioctl_errno=None)):
            with self.assertRaises(RuntimeError):
                with keypad.observe({}):
                    raise RuntimeError('PM failure')
            close.assert_called_once_with(10)

    def test_poll_and_ioctl_disconnect_evidence(self):
        poll = Mock()
        poll.poll.return_value = [(10, select.POLLERR | select.POLLHUP)]
        with patch.object(keypad.select, 'poll', return_value=poll), \
                patch.object(keypad.fcntl, 'ioctl', side_effect=OSError(errno.ENODEV, 'gone')):
            state = keypad.handle_state(10)
        self.assertTrue(state['hung_up'] and state['poll_error'] and state['disconnected'])
        self.assertIsNone(state['held_key_codes'])


class TraceRecovery(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, path in (('TRACE', root/'tracing'), ('DEBUG', root/'debug'), ('OWNED', root/'owned.json')):
            self.enterContext(patch.object(keypad, name, path))
        (keypad.TRACE / 'instances').mkdir(parents=True)
        for name in keypad.EVENTS:
            p = keypad.TRACE / 'events' / name
            p.mkdir(parents=True)
            (p / 'enable').write_text('0')
        keypad.DEBUG.write_text(DEBUG_TEXT)
        self.instance = keypad.TRACE / 'instances' / keypad.INSTANCE
        self.enterContext(patch.object(keypad, 'optional', return_value='boot-one'))
        self.commands = []
        real_set = keypad.set_site
        self.enterContext(patch.object(keypad, 'set_site', side_effect=lambda s, f: (
            self.commands.append((s['file'], s['line'], f)), real_set(s, f))[-1]))
        real_mkdir = Path.mkdir
        def create(path, *args, **kwargs):
            result = real_mkdir(path, *args, **kwargs)
            if path == self.instance:
                for name in keypad.EVENTS:
                    (path / 'events' / name).mkdir(parents=True)
                    (path / 'events' / name / 'enable').write_text('0')
                (path / 'trace').write_text('keypad trace\n')
                (path / 'per_cpu/cpu0').mkdir(parents=True)
                (path / 'per_cpu/cpu0/stats').write_text('overrun: 0\ndropped events: 0\n')
            return result
        self.enterContext(patch.object(Path, 'mkdir', create))
        real_rmdir = Path.rmdir
        self.enterContext(patch.object(Path, 'rmdir', lambda p: shutil.rmtree(p) if p == self.instance else real_rmdir(p)))

    def test_normal_and_interrupted_capture_restore_only_selected_sites(self):
        for fail in (False, True):
            keypad.DEBUG.write_text(DEBUG_TEXT)
            result = {}
            try:
                with keypad.trace(result):
                    self.assertEqual((self.instance / 'tracing_on').read_text(), '1\n')
                    self.assertEqual((self.instance / 'events/regulator/regulator_disable/filter').read_text(),
                                     'name == "keypad-vbus"\n')
                    if fail:
                        raise RuntimeError('interrupted')
            except RuntimeError:
                self.assertTrue(fail)
            self.assertFalse(keypad.OWNED.exists() or self.instance.exists())
            self.assertFalse(result['trace_overrun'])
            self.assertTrue(result['trace_restored'])
            self.assertEqual(result['trace'], 'keypad trace\n')
            self.assertEqual([s[2] for s in self.commands[-4:]], ['p', 'mfp', '_', 'mf'])
            self.assertTrue(all(s[1] != 6000 for s in self.commands))

    def test_missing_events_or_existing_owner_do_not_enable_anything(self):
        event = keypad.TRACE / 'events' / keypad.EVENTS[0] / 'enable'
        event.unlink()
        with self.assertRaises(ValueError):
            with keypad.trace({}):
                self.fail('missing event accepted')
        self.assertFalse(keypad.OWNED.exists())
        event.write_text('0')
        keypad.OWNED.write_text('existing')
        with self.assertRaises(FileExistsError):
            with keypad.trace({}):
                self.fail('existing owner accepted')
        self.assertEqual(keypad.OWNED.read_text(), 'existing')
        self.assertFalse(self.commands)

    def test_fresh_restore_rejects_other_boot_and_retains_failed_cleanup(self):
        saved = dict(boot_id='other', sites=keypad.sites(DEBUG_TEXT))
        keypad.OWNED.write_text(json.dumps(saved))
        with self.assertRaises(ValueError):
            keypad.restore_trace()
        self.assertTrue(keypad.OWNED.exists())
        saved['boot_id'] = 'boot-one'
        keypad.OWNED.write_text(json.dumps(saved))
        with patch.object(keypad, 'set_site', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                keypad.restore_trace()
        self.assertTrue(keypad.OWNED.exists())
        keypad.restore_trace()
        self.assertFalse(keypad.OWNED.exists())

    def test_overflow_is_recorded(self):
        result = {}
        with keypad.trace(result):
            (self.instance / 'per_cpu/cpu0/stats').write_text('overrun: 12\ndropped events: 0\n')
        self.assertTrue(result['trace_overrun'])

    def test_commit_overrun_or_missing_cpu_stats_cannot_pass(self):
        for missing in (False, True):
            keypad.DEBUG.write_text(DEBUG_TEXT)
            result = {}
            with keypad.trace(result):
                stats = self.instance / 'per_cpu/cpu0/stats'
                if missing:
                    stats.unlink()
                else:
                    stats.write_text('overrun: 0\ncommit overrun: 1\ndropped events: 0\n')
            self.assertTrue(result['trace_overrun'])

    def test_selector_injection_is_rejected(self):
        for site in (dict(file='drivers/usb/core/hub.c; +p', line=1, flags='_'),
                     dict(file='drivers/usb/core/hub.c', line=-1, flags='_'),
                     dict(file='drivers/usb/core/hub.c', line=1, flags='_\n+p')):
            with self.assertRaises(ValueError):
                keypad.set_site(site, site['flags'])

    def test_absolute_source_paths_select_the_same_bounded_sites(self):
        self.assertEqual(keypad.sites(DEBUG_TEXT), keypad.sites(DEBUG_TEXT.replace('drivers/', '/build/linux/drivers/')))


if __name__ == '__main__':
    unittest.main()
