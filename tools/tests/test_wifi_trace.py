"""Trace privacy, loss rejection and independent cleanup without using a radio."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wifi_trace as trace


def journal(*messages):
    return '\n'.join(json.dumps({'__MONOTONIC_TIMESTAMP': str(1000000 + i), 'MESSAGE': message})
                     for i, message in enumerate(messages))


class Parsing(unittest.TestCase):
    def test_allowlist_preserves_steps_without_network_identity_or_payload(self):
        rows = journal(
            'wlan0: State: ASSOCIATED -> 4WAY_HANDSHAKE',
            'WPA: RX message 1 of 4-Way Handshake from aa:bb:cc:dd:ee:ff',
            'WPA: Sending EAPOL-Key 2/4',
            'wlan0: RX EAPOL from aa:bb:cc:dd:ee:ff',
            'wlan0: Setting authentication timeout: 10 sec 0 usec',
            'wlan0: Authentication with aa:bb:cc:dd:ee:ff timed out.',
            'CTRL-EVENT-ASSOC-REJECT bssid=aa:bb:cc:dd:ee:ff status_code=16',
            'CTRL-EVENT-SSID-TEMP-DISABLED id=0 ssid="private-network" auth_failures=2 duration=20 reason=CONN_FAILED',
            'WPA: Key negotiation completed with aa:bb:cc:dd:ee:ff [PTK=CCMP GTK=CCMP]',
            'SSID - hexdump_ascii(len=15): private-network',
            'WPA: PTK - hexdump(len=32): secret-key-material',
            'wlan0: State: PRIVATE_NETWORK -> INACTIVE')
        result = trace.summarize_journal(rows)
        encoded = json.dumps(result)
        for secret in ('aa:bb:cc:dd:ee:ff', 'private-network', 'secret-key-material', 'PRIVATE_NETWORK'):
            self.assertNotIn(secret, encoded)
        self.assertEqual(len(result['events']), 9)
        self.assertEqual(result['events'][0]['after'], '4WAY_HANDSHAKE')
        self.assertEqual(result['events'][6]['status_code'], 16)
        self.assertEqual(result['events'][7]['duration'], 20)

    def test_missing_time_overlong_capture_and_unknown_loss_reject(self):
        with self.assertRaises(ValueError):
            trace.summarize_journal(json.dumps({'MESSAGE': 'CTRL-EVENT-CONNECTED'}))
        with patch.object(trace, 'LIMIT', 1), self.assertRaises(ValueError):
            trace.summarize_journal(journal('ignored', 'ignored'))
        clean = 'overrun: 0\ncommit overrun: 0\ndropped events: 0\n'
        self.assertFalse(trace.trace_lost({'cpu0': clean}))
        for value in ({}, {'cpu0': ''}, {'cpu0': clean.replace('overrun: 0', 'overrun: 1', 1)},
                      {'cpu0': clean, 'cpu1': 'overrun: 0'}):
            self.assertTrue(trace.trace_lost(value))


class Capture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for key, value in (('TRACE', root / 'tracing'), ('OWNED', root / 'owned.json'), ('BOOT', root / 'boot')):
            self.enterContext(patch.object(trace, key, value))
        trace.BOOT.write_text('same-boot')
        (trace.TRACE / 'instances').mkdir(parents=True)
        for name in trace.EVENTS:
            event = trace.TRACE / 'events' / name
            event.mkdir(parents=True)
            (event / 'enable').write_text('0')
            (event / 'format').write_text('char[] name; u16 protocol; unsigned int len;')
        self.level = dict(level='INFO', timestamp='0')
        self.level_writes = []
        self.pid = dict(pid='123', start_ticks='1000')
        self.enterContext(patch.object(trace, 'identity', side_effect=lambda: self.pid))
        self.enterContext(patch.object(trace, 'log_level', side_effect=lambda: self.level.copy()))
        self.enterContext(patch.object(trace, 'set_level', side_effect=self.set_level))
        self.enterContext(patch.object(trace, 'journal_cursor', return_value='cursor-one'))
        self.enterContext(patch.object(trace, 'command', return_value=journal('WPA: Key negotiation completed')))
        self.instance = trace.TRACE / 'instances' / trace.INSTANCE
        original_mkdir, original_rmdir = Path.mkdir, Path.rmdir

        def mkdir(path, *args, **kwargs):
            original_mkdir(path, *args, **kwargs)
            if path == self.instance:
                for name in trace.EVENTS:
                    original_mkdir(path / 'events' / name, parents=True)
                    (path / 'events' / name / 'enable').write_text('0')
                    (path / 'events' / name / 'filter').write_text('none')
                original_mkdir(path / 'per_cpu/cpu0', parents=True)
                (path / 'per_cpu/cpu0/stats').write_text('overrun: 0\ncommit overrun: 0\ndropped events: 0\n')
                (path / 'trace').write_text('netif_rx_entry: name=wlan0 protocol=0x888e\n'
                                          'net_dev_start_xmit: name=wlan0 protocol=0x888e\n')

        def rmdir(path, *args, **kwargs):
            if path == self.instance:
                # tracefs virtual entries disappear with their instance.
                for child in sorted(path.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                    original_rmdir(child) if child.is_dir() else child.unlink()
            original_rmdir(path, *args, **kwargs)

        self.enterContext(patch.object(Path, 'mkdir', new=mkdir))
        self.enterContext(patch.object(Path, 'rmdir', new=rmdir))

    def set_level(self, value):
        self.level_writes.append(value.copy())
        self.level = value.copy()

    def assert_restored(self, record):
        self.assertEqual(self.level, dict(level='INFO', timestamp='0'))
        self.assertFalse(trace.OWNED.exists())
        self.assertFalse(self.instance.exists())
        self.assertTrue(record['restored'])

    def test_success_and_body_failure_restore_and_capture(self):
        for fail in (False, True):
            record = {}
            try:
                with trace.capture(record):
                    self.assertEqual(self.level['level'], 'DEBUG')
                    self.assertEqual(trace.OWNED.stat().st_mode & 0o777, 0o600)
                    for name in trace.EVENTS[:2]:
                        self.assertEqual((self.instance / 'events' / name / 'filter').read_text(),
                                         'name == "wlan0" && protocol == 34958\n')
                    if fail:
                        raise InterruptedError('test body stopped')
            except InterruptedError:
                pass
            self.assert_restored(record)
            self.assertEqual((record['eapol_rx'], record['eapol_tx']), (1, 1))
            self.assertFalse(record['trace_lost'])

    def test_setup_failure_and_capture_failure_restore(self):
        original_write = Path.write_text
        def write(path, value, *args, **kwargs):
            if path.name == 'filter' and 'protocol' in value:
                raise OSError('filter rejected')
            return original_write(path, value, *args, **kwargs)
        for setup in (False, True):
            record = {}
            if setup:
                with patch.object(Path, 'write_text', new=write), self.assertRaises(OSError):
                    with trace.capture(record):
                        self.fail('Bad setup entered the body')
            else:
                with patch.object(trace, 'summarize_journal', side_effect=ValueError('truncated')), \
                        self.assertRaises(ValueError):
                    with trace.capture(record):
                        pass
            self.assert_restored(record)

    def test_trace_loss_rejects_after_cleanup(self):
        record = {}
        with self.assertRaises(ValueError):
            with trace.capture(record):
                (self.instance / 'per_cpu/cpu0/stats').write_text('overrun: 1\n')
        self.assert_restored(record)
        self.assertTrue(record['trace_lost'])

    def test_independent_restore_and_foreign_state_are_protected(self):
        owner = dict(boot_id='same-boot', process=self.pid.copy(), logging=self.level.copy())
        trace.OWNED.write_text(json.dumps(owner))
        self.level['level'] = 'DEBUG'
        with self.assertRaises(ValueError):
            with trace.capture({}):
                self.fail('Second recorder entered')
        trace.restore()
        self.assertEqual(self.level['level'], 'INFO')
        trace.OWNED.write_text(json.dumps(owner | {'boot_id': 'other'}))
        with self.assertRaises(ValueError):
            trace.restore()
        self.assertTrue(trace.OWNED.exists())
        trace.OWNED.write_text(json.dumps(owner))
        self.pid = dict(pid='124', start_ticks='1001')
        with self.assertRaises(ValueError):
            trace.restore()
        self.assertTrue(trace.OWNED.exists())

    def test_trace_cleanup_failure_still_restores_logging_and_keeps_owner(self):
        with patch.object(Path, 'rmdir', side_effect=OSError('busy trace instance')), self.assertRaises(OSError):
            with trace.capture({}):
                pass
        self.assertEqual(self.level['level'], 'INFO')
        self.assertTrue(trace.OWNED.exists())
        trace.restore()
        self.assertFalse(trace.OWNED.exists())

    def test_unqualified_logging_or_format_rejected_before_changes(self):
        self.level['level'] = 'MSGDUMP'
        with self.assertRaises(ValueError):
            with trace.capture({}):
                self.fail('Existing debugger accepted')
        self.level['level'] = 'INFO'
        (trace.TRACE / 'events/net/netif_rx_entry/format').write_text('unknown')
        with self.assertRaises(ValueError):
            with trace.capture({}):
                self.fail('Unknown format accepted')
        self.assertFalse(trace.OWNED.exists())
        self.assertEqual(self.level_writes, [])


if __name__ == '__main__':
    unittest.main()
