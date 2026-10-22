"""Development selection never overwrites another system or reboots the host."""
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dev_systems as systems


def image(payload, kind):
    fields = [0x27051956, 0, 0, len(payload), 0, 0, zlib.crc32(payload),
              5, 2, kind, 0, b'fixture']
    header = struct.pack('>7I4B32s', *fields)
    fields[1] = zlib.crc32(header)
    return struct.pack('>7I4B32s', *fields) + payload


class DevelopmentSystems(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.boot, self.store = self.base / 'boot', self.base / 'store'
        self.boot.mkdir()
        self.store.mkdir()
        self.recovery = self.base / 'recovery'
        self.recovery.mkdir()
        self.assets(self.recovery)
        (self.boot / 'boot.scr').write_bytes(b'previous executable')
        self.prepare('diag26')
        self.prepare('diag27')
        systems.initialize(self.boot, self.store, recovery_partuuid='1234abcd-02',
                           recovery_boot=self.recovery, releases=['diag26', 'diag27'])
        self.card = systems.Card(self.boot, self.store)

    def assets(self, directory):
        (directory / 'uImage').write_bytes(image(b'fixture Linux payload', 2))
        (directory / 'uInitrd').write_bytes(image(b'fixture initramfs', 3))
        (directory / 'sun8i-r16-clockworkpi-cpi3.dtb').write_bytes(
            struct.pack('>10I', 0xd00dfeed, 40, 40, 40, 40, 17, 16, 0, 0, 0))

    def prepare(self, name):
        directory = self.store / 'systems' / name
        root, boot = directory / 'root', directory / 'boot'
        (root / 'etc/gameshellneo').mkdir(parents=True)
        (root / 'usr/bin').mkdir(parents=True)
        (root / 'usr/bin/fixture').write_bytes(b'unchanged application')
        marker = f'schema=1\nid={name}\nkernel=6.18.54-test\n'
        (root / 'etc/gameshellneo/development-slot').write_text(marker)
        (root / 'etc/gameshellneo/image.json').write_text('{"development": true}\n')
        boot.mkdir()
        self.assets(boot)
        record = {'schema': 1, 'board': systems.BOARD, 'slot': name,
                  'kernel': '6.18.54-test', 'store_partuuid': '1234abcd-03',
                  'source_image_sha256': '1' * 64,
                  'boot_files': systems.boot_bundle(boot, True),
                  'immutable_files': {str(p.relative_to(root)): systems.sha(p)
                                      for p in root.rglob('*') if p.is_file()}}
        (directory / 'release.json').write_bytes(systems.json_bytes(record))
        return directory

    def test_initial_recovery_and_trial_leave_confirmed_descriptor_untouched(self):
        before = (self.boot / 'good.scr').read_bytes()
        self.assertEqual(self.card.status()['confirmed_system'], 'recovery')
        self.card.select('diag26')
        status = self.card.status()
        self.assertEqual(status['next_system'], 'diag26')
        self.assertTrue(status['trial_pending'])
        self.assertEqual((self.boot / 'good.scr').read_bytes(), before)
        self.assertFalse(status['reboot_performed'])

    def test_case_insensitive_reads_cannot_admit_uppercase_flag_entries(self):
        # Model FAT's ability to read lower paths while enumeration preserves
        # uppercase on-disk names. The legacy writer cannot replace those names.
        entries = list(self.boot.iterdir())
        before = {p.name: p.read_bytes() for p in entries if p.name in systems.FLAGS}
        iterdir = Path.iterdir

        def presented(path):
            if path == self.boot:
                return iter(p.with_name(p.name.upper()) if p.name in systems.FLAGS else p
                            for p in entries)
            return iterdir(path)

        with patch.object(Path, 'iterdir', presented), self.assertRaisesRegex(ValueError, 'lowercase'):
            systems.Card(self.boot, self.store)
        self.assertEqual({name: (self.boot / name).read_bytes() for name in before}, before)

    def test_mount_options_cannot_disguise_incompatible_short_names(self):
        before = (self.boot / 'next.scr').read_bytes()
        for options in ('rw,shortname=lower', 'rw,shortname=win95', 'rw'):
            device = self.boot.stat().st_dev
            record = {'filesystems': [{'fstype': 'vfat', 'options': options,
                       'maj:min': f'{os.major(device)}:{os.minor(device)}'}]}
            with patch.object(systems.subprocess, 'check_output', return_value=json.dumps(record)), \
                    self.assertRaisesRegex(ValueError, 'shortname=mixed'):
                systems.Card(self.boot, self.store)
        self.assertEqual((self.boot / 'next.scr').read_bytes(), before)

    def test_alias_or_case_change_after_construction_cannot_change_selection(self):
        before = (self.boot / 'next.scr').read_bytes()
        alias = self.boot / 'NEXT.SCR'
        alias.write_bytes(before)
        with self.assertRaisesRegex(ValueError, 'unique lowercase'):
            self.card.select('diag26')
        self.assertEqual((self.boot / 'next.scr').read_bytes(), before)
        alias.unlink()
        (self.boot / 'next.scr').rename(alias)
        with self.assertRaisesRegex(ValueError, 'unique lowercase'):
            self.card.select('diag26')
        self.assertEqual(alias.read_bytes(), before)

    def test_changed_root_rejects_selection_before_state_write(self):
        before = (self.boot / 'next.scr').read_bytes()
        (self.store / 'systems/diag26/root/usr/bin/fixture').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'system input changed'):
            self.card.select('diag26')
        self.assertEqual((self.boot / 'next.scr').read_bytes(), before)

    def test_changed_kernel_rejects_selection_before_state_write(self):
        before = (self.boot / 'next.scr').read_bytes()
        (self.boot / 'systems/diag26/uImage').write_bytes(b'damaged')
        with self.assertRaises(ValueError):
            self.card.select('diag26')
        self.assertEqual((self.boot / 'next.scr').read_bytes(), before)

    def test_source_root_symlink_cannot_redirect_hashing_to_host(self):
        target = self.store / 'systems/diag26/root/usr'
        target.rename(target.with_name('saved-usr'))
        target.symlink_to(self.base / 'outside', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.card.select('diag26')

    def test_explicit_confirmation_checks_actual_root_and_running_kernel(self):
        root = self.store / 'systems/diag26/root'
        runtime = self.base / 'runtime-marker'
        runtime.write_bytes((root / 'etc/gameshellneo/development-slot').read_bytes())
        with patch.object(systems.os, 'uname', return_value=types.SimpleNamespace(release='6.18.54-test')):
            with self.assertRaisesRegex(ValueError, 'not the running root'):
                self.card.confirm('diag26', running_root=self.store / 'systems/diag27/root',
                                  runtime_record=runtime)
            self.card.confirm('diag26', running_root=root, runtime_record=runtime)
        self.assertEqual(self.card.status()['confirmed_system'], 'diag26')
        self.assertFalse(self.card.status()['trial_pending'])

    def test_kernel_mismatch_preserves_default(self):
        root = self.store / 'systems/diag26/root'
        runtime = self.base / 'runtime-marker'
        runtime.write_bytes((root / 'etc/gameshellneo/development-slot').read_bytes())
        before = (self.boot / 'good.scr').read_bytes()
        with self.assertRaisesRegex(ValueError, 'kernel/early-userspace'):
            self.card.confirm('diag26', running_root=root, runtime_record=runtime)
        self.assertEqual((self.boot / 'good.scr').read_bytes(), before)

    def test_register_additional_release_does_not_change_selection(self):
        before = (self.boot / 'next.scr').read_bytes()
        self.prepare('diag28')
        self.card.register('diag28')
        new_card = systems.Card(self.boot, self.store)
        self.assertIn('diag28', new_card.status()['systems'])
        self.assertEqual((self.boot / 'next.scr').read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'immutable'):
            new_card.register('diag28')

    def test_card_pair_mismatch_rejects_without_state_write(self):
        record = json.loads((self.store / systems.CARD_FILE).read_text())
        record['store_partuuid'] = '00000000-03'
        (self.store / systems.CARD_FILE).write_bytes(systems.json_bytes(record))
        with self.assertRaises(ValueError):
            systems.Card(self.boot, self.store)

    def test_two_preconstructed_registrars_preserve_each_others_new_versions(self):
        second = systems.Card(self.boot, self.store)
        self.prepare('diag28')
        self.prepare('diag29')
        self.card.register('diag28')
        second.register('diag29')
        self.assertEqual(set(systems.Card(self.boot, self.store).status()['systems']),
                         {'diag26', 'diag27', 'diag28', 'diag29'})

    def test_fixed_recovery_cannot_be_replaced_by_a_registered_version(self):
        with self.assertRaisesRegex(ValueError, 'reserved'):
            self.card.register('recovery')
        old = (self.boot / 'recover.scr').read_bytes()
        self.card.select('diag26')
        self.card.select_recovery()
        self.assertEqual((self.boot / 'next.scr').read_bytes(), old)

    def test_invalid_identifier_and_unprepared_card_are_rejected(self):
        for value in ('../outside', 'diag;reset', 'a' * 49, 'UPPER', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.card.select(value)
        with self.assertRaises((ValueError, FileNotFoundError)):
            systems.Card(self.base, self.store)


if __name__ == '__main__':
    unittest.main()
