"""Boot-policy integrity and interrupted-selection checks without card access."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usb_poll_boot as policy


def compiled(source):
    payload = struct.pack('>2I', len(source), 0) + source
    header = struct.pack('>7I4B32s', 0x27051956, 0, 0, len(payload), 0, 0,
                         zlib.crc32(payload), 5, 2, 6, 0, b'GameShellNeo')
    return header[:4] + struct.pack('>I', zlib.crc32(header)) + header[8:] + payload


class BootPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.boot = Path(self.temp.name)
        self.identity = {'root_partuuid': '1234abcd-02', 'usb_poll_boot': {'files': {}}}
        for mode in policy.MODES:
            source = policy.boot_script(self.identity['root_partuuid'], mode)
            for suffix, data in [('cmd', source), ('scr', compiled(source))]:
                name = f'boot-usb-{mode}.{suffix}'
                (self.boot / name).write_bytes(data)
                self.identity['usb_poll_boot']['files'][name] = policy.sha(data)
                if mode == 'stock':
                    (self.boot / f'boot.{suffix}').write_bytes(data)

    def test_both_selections_verify_and_are_repeatable(self):
        for mode in ('experimental', 'stock', 'stock'):
            result = policy.select(self.boot, self.identity, mode)
            self.assertEqual(result['next_boot'], mode)
            self.assertFalse(result['reboot_performed'])
            self.assertEqual(policy.verify_scripts(self.boot, self.identity)[1], mode)
            self.assertEqual(policy.script_source((self.boot / 'boot.scr').read_bytes()),
                             (self.boot / 'boot.cmd').read_bytes())

    def test_bad_variant_blocks_any_write(self):
        previous = (self.boot / 'boot.scr').read_bytes()
        (self.boot / 'boot-usb-experimental.scr').write_bytes(b'corrupted')
        with self.assertRaises(ValueError):
            policy.select(self.boot, self.identity, 'experimental')
        self.assertEqual((self.boot / 'boot.scr').read_bytes(), previous)

    def test_diagnostics_opt_in_matches_both_modes_and_image_manifest(self):
        self.identity['sources'] = {'experiments': {'usb_diagnostics': True}}
        for mode in policy.MODES:
            source = policy.boot_script(self.identity['root_partuuid'], mode, True)
            self.assertIn((policy.DIAGNOSTIC_PARAMETER + '=1').encode(), source)
            for suffix, data in [('cmd', source), ('scr', compiled(source))]:
                name = f'boot-usb-{mode}.{suffix}'
                (self.boot / name).write_bytes(data)
                self.identity['usb_poll_boot']['files'][name] = policy.sha(data)
                if mode == 'stock':
                    (self.boot / f'boot.{suffix}').write_bytes(data)
        policy.select(self.boot, self.identity, 'experimental')
        self.identity['sources']['experiments']['usb_diagnostics'] = False
        with self.assertRaises(ValueError):
            policy.verify_scripts(self.boot, self.identity)

    def test_hash_alone_cannot_bless_wrong_script(self):
        for content in (b'corrupt CRC', compiled(b'boot an unexpected kernel\n')):
            name = 'boot-usb-experimental.scr'
            (self.boot / name).write_bytes(content)
            self.identity['usb_poll_boot']['files'][name] = policy.sha(content)
            with self.assertRaises(ValueError):
                policy.select(self.boot, self.identity, 'experimental')

    def test_unknown_current_boot_is_not_overwritten(self):
        (self.boot / 'boot.scr').write_bytes(b'custom user boot script')
        with self.assertRaises(ValueError):
            policy.select(self.boot, self.identity, 'stock')
        self.assertEqual((self.boot / 'boot.scr').read_bytes(), b'custom user boot script')

    def test_interruption_before_executable_replace_keeps_previous_bootable(self):
        previous = (self.boot / 'boot.scr').read_bytes()
        original = policy.atomic_write

        def interrupted(path, data):
            if path.name == 'boot.scr':
                raise OSError('simulated interruption')
            original(path, data)

        with patch.object(policy, 'atomic_write', side_effect=interrupted):
            with self.assertRaises(OSError):
                policy.select(self.boot, self.identity, 'experimental')
        self.assertEqual((self.boot / 'boot.scr').read_bytes(), previous)
        self.assertEqual(policy.verify_scripts(self.boot, self.identity)[1], 'stock')
        # A later explicit selection also repairs the informational source file.
        policy.select(self.boot, self.identity, 'stock')
        self.assertEqual(policy.script_source(previous), (self.boot / 'boot.cmd').read_bytes())

    def test_failed_replace_cleans_temporary_file(self):
        previous = (self.boot / 'boot.scr').read_bytes()
        with patch.object(policy.os, 'replace', side_effect=OSError('failed rename')):
            with self.assertRaises(OSError):
                policy.atomic_write(self.boot / 'boot.scr', b'new')
        self.assertEqual((self.boot / 'boot.scr').read_bytes(), previous)
        self.assertFalse(list(self.boot.glob('.usb-policy-*')))

    def test_unexpected_manifest_names_and_symlinks_rejected(self):
        for name in ('../boot.scr', 'unexpected'):
            bad = json.loads(json.dumps(self.identity))
            bad['usb_poll_boot']['files'][name] = '0' * 64
            with self.assertRaises(ValueError):
                policy.verify_scripts(self.boot, bad)
        path = self.boot / 'boot-usb-stock.cmd'
        path.unlink()
        path.symlink_to(self.boot / 'boot.cmd')
        with self.assertRaises(ValueError):
            policy.verify_scripts(self.boot, self.identity)

    def test_invalid_selection_and_partuuid_rejected(self):
        for mode in ('', 'experimental; reboot', None):
            with self.assertRaises(ValueError):
                policy.select(self.boot, self.identity, mode)
        with self.assertRaises(ValueError):
            policy.boot_script('1234abcd-02; reset', 'stock')


if __name__ == '__main__':
    unittest.main()
