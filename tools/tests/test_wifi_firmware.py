"""Firmware trials must reject stale identity and preserve valid rollback bytes."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

spec = importlib.util.spec_from_file_location('wifi_firmware',
    Path(__file__).resolve().parents[1] / 'test-wifi-firmware.py')
fw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fw)
host_spec = importlib.util.spec_from_file_location('wifi_firmware_host',
    Path(__file__).resolve().parents[1] / 'check-wifi-firmware.py')
host = importlib.util.module_from_spec(host_spec)
host_spec.loader.exec_module(host)


class FirmwareTrialTests(unittest.TestCase):
    def test_candidate_association_failure_restores_bytes_and_loaded_identity(self):
        real_path = Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            firmware, board, config = root / 'firmware', root / 'board', root / 'wifi'
            firmware.write_bytes(b'original')
            board.write_bytes(b'board')
            config.write_bytes(b'private config')
            candidate = root / 'candidate'
            candidate.write_bytes(b'candidate')
            (root / 'image').write_text(json.dumps({'board': 'gameshellneo-cpi31'}))
            (root / 'module').mkdir()
            (root / 'udc/controller').mkdir(parents=True)
            (root / 'udc/controller/state').write_text('configured')
            (root / 'boot').write_text('same-boot')
            paths = {'/etc/gameshellneo/image.json': root / 'image',
                     '/sys/module/brcmfmac': root / 'module', '/sys/class/udc': root / 'udc',
                     '/proc/sys/kernel/random/boot_id': root / 'boot'}
            old_identity = 'original FWID 01-e2c3069b'
            def reload(data, mode):
                fw.write(firmware, data, mode)
                return 1
            with patch.object(fw, 'Path', side_effect=lambda value: paths.get(str(value), real_path(value))), \
                    patch.object(fw, 'FIRMWARE', firmware), patch.object(fw, 'NVRAM', board), \
                    patch.object(fw, 'WIFI_CONFIG', config), patch.object(fw, 'STATE', root / 'recovery'), \
                    patch.object(fw, 'ORIGINAL', fw.digest(b'original')), patch.object(fw, 'BOARD_DATA', fw.digest(b'board')), \
                    patch.object(fw, 'identity', return_value=old_identity), patch.object(fw, 'command', return_value='0'), \
                    patch.object(fw, 'counts', return_value={'firmware_crashes': 0, 'sdio_removals': 0}), \
                    patch.object(fw, 'reload', side_effect=reload) as loader, \
                    patch.object(fw, 'wait_identity', side_effect=lambda expected, _count: expected), \
                    patch.object(fw, 'wifi_checkpoint', side_effect=[None, ValueError('candidate unavailable')]), \
                    patch.object(fw, 'emit') as emit:
                with self.assertRaisesRegex(ValueError, 'candidate unavailable'):
                    fw.trial(candidate, {'sha256': fw.digest(b'candidate'), 'size_bytes': 9,
                                         'runtime_identity': 'candidate'}, 60, connected=True)
            self.assertEqual(firmware.read_bytes(), b'original')
            self.assertFalse((root / 'recovery').exists())
            self.assertEqual([call.args[0] for call in loader.call_args_list], [b'candidate', b'original'])
            self.assertEqual([call.args[0] for call in emit.call_args_list], ['candidate_loaded', 'restored'])

    def test_acknowledgement_rejects_an_old_token(self):
        with tempfile.TemporaryDirectory() as directory:
            request, ack = Path(directory) / 'request', Path(directory) / 'ack'
            request.write_text(json.dumps({'token': 'a' * 32}))
            with patch.object(fw, 'WIFI_REQUEST', request), patch.object(fw, 'WIFI_ACK', ack):
                with self.assertRaises(ValueError):
                    fw.acknowledge('b' * 32)
                self.assertFalse(ack.exists())
                fw.acknowledge('a' * 32)
                self.assertEqual(ack.read_text(), 'a' * 32)

    def test_reconnection_requires_observed_disconnection(self):
        with patch.object(fw, 'command', return_value='OK'), \
                patch.object(fw, 'wifi_status', return_value={'wpa_state': 'COMPLETED'}), \
                patch.object(fw.time, 'monotonic', side_effect=[0, 11]), \
                patch.object(fw, 'wifi_checkpoint') as checkpoint:
            with self.assertRaisesRegex(ValueError, 'disconnection was not observed'):
                fw.reconnect(1, 'boot', 'identity')
            checkpoint.assert_not_called()

    def test_reconnection_is_not_verified_until_after_reconnect_request(self):
        calls = []
        with patch.object(fw, 'command', side_effect=lambda *args: calls.append(args[-1]) or 'OK'), \
                patch.object(fw, 'wifi_status', side_effect=[{'wpa_state': 'COMPLETED'}, {'wpa_state': 'DISCONNECTED'}]), \
                patch.object(fw.time, 'sleep'), patch.object(fw, 'emit'), \
                patch.object(fw, 'wifi_checkpoint', side_effect=lambda *args: calls.append(args)):
            fw.reconnect(2, 'boot', 'identity')
        self.assertEqual(calls, ['disconnect', 'reconnect', ('candidate_reconnect_2', 'boot', 'identity')])

    def test_pinned_runtime_identity_is_distinct_from_binary_footer(self):
        metadata = json.loads((Path(__file__).resolve().parents[2] /
                               'build/wifi-firmware-candidate.json').read_text())
        observed = ('brcmfmac: brcmf_c_preinit_dcmds: Firmware: BCM43430/0 wl0: '
                    'May 29 2017 00:03:43 version 7.13.53.9 (r664949) FWID 01-130000')
        self.assertNotIn(metadata['fwid'], observed)
        with patch.object(fw, 'identities', return_value=['old', observed]):
            self.assertEqual(fw.wait_identity(metadata['runtime_identity'], 1), observed)
        with patch.object(fw, 'identities', return_value=['old', observed.replace('/0 ', '/1 ')]), \
                patch.object(fw.time, 'sleep'):
            with self.assertRaises(ValueError):
                fw.wait_identity(metadata['runtime_identity'], 1)

    def test_identity_requires_new_load_message(self):
        with patch.object(fw, 'identities', return_value=['expected']), patch.object(fw.time, 'sleep'):
            with self.assertRaises(ValueError):
                fw.wait_identity('expected', 1)
        with patch.object(fw, 'identities', return_value=['old', 'new expected']):
            self.assertEqual(fw.wait_identity('expected', 1), 'new expected')

    def test_restore_verifies_backup_nvram_and_loaded_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, live, nvram = root / 'state', root / 'firmware', root / 'board.txt'
            state.mkdir()
            (state / 'original.bin').write_bytes(b'original')
            (state / 'state.json').write_text(json.dumps({'mode': 0o644, 'identity': 'old identity'}))
            live.write_bytes(b'candidate')
            nvram.write_bytes(b'board')
            def reload(data, mode):
                fw.write(live, data, mode)
                return 5
            with patch.object(fw, 'STATE', state), patch.object(fw, 'FIRMWARE', live), \
                    patch.object(fw, 'NVRAM', nvram), patch.object(fw, 'ORIGINAL', fw.digest(b'original')), \
                    patch.object(fw, 'BOARD_DATA', fw.digest(b'board')), \
                    patch.object(fw, 'reload', side_effect=reload) as loader, \
                    patch.object(fw, 'wait_identity', return_value='old identity') as wait:
                self.assertEqual(fw.restore(), 'old identity')
                self.assertEqual(live.read_bytes(), b'original')
                self.assertEqual(live.stat().st_mode & 0o777, 0o644)
                wait.assert_called_once_with('old identity', 5)
                self.assertFalse(state.exists())
                fw.restore()
                loader.assert_called_once()

    def test_bad_backup_never_writes_firmware(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'original.bin').write_bytes(b'wrong')
            (state / 'state.json').write_text(json.dumps({'mode': 0o644, 'identity': 'old'}))
            with patch.object(fw, 'STATE', state), patch.object(fw, 'reload') as reload:
                with self.assertRaises(ValueError):
                    fw.restore()
                reload.assert_not_called()
                self.assertTrue((state / 'state.json').exists())

    def test_failed_radio_restore_keeps_recovery_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'original.bin').write_bytes(b'original')
            (state / 'board.txt').write_bytes(b'board')
            (state / 'state.json').write_text(json.dumps({'mode': 0o644, 'identity': 'old'}))
            with patch.object(fw, 'STATE', state), patch.object(fw, 'NVRAM', state / 'board.txt'), \
                    patch.object(fw, 'ORIGINAL', fw.digest(b'original')), \
                    patch.object(fw, 'BOARD_DATA', fw.digest(b'board')), \
                    patch.object(fw, 'reload', side_effect=RuntimeError('reload failed')):
                with self.assertRaises(RuntimeError):
                    fw.restore()
                self.assertTrue((state / 'state.json').exists())
                self.assertEqual((state / 'original.bin').read_bytes(), b'original')


class ConnectedHostTests(unittest.TestCase):
    def make_sink(self):
        return host.ConnectedCapture(io.BytesIO(), io.StringIO(), MagicMock(), {}, 'boot', '/tmp/helper.py')

    def event(self, **changes):
        values = dict(event='wifi_ready', phase='original_before', token='a' * 32,
                      boot_id='boot', address='192.0.2.42')
        values.update(changes)
        return (json.dumps(values) + '\n').encode()

    def test_split_event_verifies_wifi_before_acknowledging_over_usb(self):
        sink, calls = self.make_sink(), []
        with patch.object(host, 'verify_wifi', side_effect=lambda *args: calls.append(('wifi', args))), \
                patch.object(host, 'run', side_effect=lambda *args, **kwargs: calls.append(('ack', args[1]))):
            event = self.event()
            sink.write(event[:20])
            self.assertEqual(calls, [])
            sink.write(event[20:])
        self.assertEqual([call[0] for call in calls], ['wifi', 'ack'])
        self.assertEqual(sink.phases, ['original_before'])
        self.assertTrue(json.loads(sink.evidence.getvalue())['passed'])
        self.assertEqual(sink.output.getvalue(), event)

    def test_wrong_boot_usb_endpoint_or_phase_never_gets_acknowledged(self):
        for changes in ({'boot_id': 'other'}, {'address': '192.168.10.1'},
                        {'phase': 'candidate_initial'}, {'token': 'bad'}):
            with self.subTest(changes=changes), patch.object(host, 'verify_wifi') as verify, \
                    patch.object(host, 'run') as run:
                with self.assertRaises(ValueError):
                    self.make_sink().write(self.event(**changes))
                verify.assert_not_called()
                run.assert_not_called()

    def test_failed_wifi_never_acknowledges_or_marks_a_phase_passed(self):
        sink = self.make_sink()
        with patch.object(host, 'verify_wifi', side_effect=host.paramiko.SSHException('unreachable')), \
                patch.object(host, 'run') as run, patch.object(host.time, 'sleep'):
            with self.assertRaises(host.paramiko.SSHException):
                sink.write(self.event())
            run.assert_not_called()
        self.assertEqual(sink.phases, [])
        self.assertEqual(sink.evidence.getvalue(), '')

    def test_fresh_wifi_session_must_match_boot_and_endpoint(self):
        for output in (b'other\n192.0.2.1 45000 192.0.2.42 22\n',
                       b'boot\n192.0.2.1 45000 192.168.10.1 22\n'):
            with patch.object(host, 'device') as device, patch.object(host, 'run', return_value=output):
                with self.assertRaises(ValueError):
                    host.verify_wifi({}, 'boot', '192.0.2.42')
                device.assert_called_once_with({'GAMESHELL_IP': '192.0.2.42'}, 'wifi')


if __name__ == '__main__':
    unittest.main()
