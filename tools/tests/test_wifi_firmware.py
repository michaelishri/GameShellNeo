"""Firmware trials must reject stale identity and preserve valid rollback bytes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('wifi_firmware',
    Path(__file__).resolve().parents[1] / 'test-wifi-firmware.py')
fw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fw)


class FirmwareTrialTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
