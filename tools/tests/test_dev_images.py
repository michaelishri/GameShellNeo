"""Offline imports retain OS metadata while separating development provenance."""
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dev_images as images


def digest(data):
    return hashlib.sha256(data).hexdigest()


def legacy(payload, kind, compression=0, load=0, entry=0):
    values = [0x27051956, 0, 0, len(payload), load, entry, zlib.crc32(payload),
              5, 2, kind, compression, b'fixture']
    header = struct.pack('>7I4B32s', *values)
    values[1] = zlib.crc32(header)
    return struct.pack('>7I4B32s', *values) + payload


def kernel_image(release):
    header = bytearray(64)
    struct.pack_into('<I', header, 36, 0x016f2818)
    payload = header + gzip.compress(b'Linux version ' + release.encode() + b' fixture\0', mtime=0)
    return legacy(payload, 2, load=0x40008000, entry=0x40008000)


def dtb():
    structure = struct.pack('>I', 1) + b'\0' * 4 + struct.pack('>II', 2, 9)
    size = 56 + len(structure)
    return struct.pack('>10I', 0xd00dfeed, size, 56, size, 40, 17, 16, 0, 0, len(structure)) + b'\0' * 16 + structure


class DevelopmentImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / 'source-root'
        self.boot = self.directory / 'source-boot'
        self.destination = self.directory / 'imported'
        self.initramfs = self.directory / 'uInitrd'
        self.kernel = '6.18.54-gameshellneo25'
        self.identity = dict(board='gameshellneo-cpi31', kernel=self.kernel,
                             hardware_qualified=False, version='diagnostic.26', root_partuuid='1234abcd-02',
                             sources=dict(linux=dict(tag='v6.18.54', localversion='-gameshellneo25')))
        self.fstab = (b'# keep this exact comment\nPARTUUID=1234abcd-02 / ext4 defaults 0 1\n'
                      b'UUID=boot /boot vfat defaults 0 2\n'
                      b'\ntmpfs /tmp tmpfs defaults,nosuid,size=64M 0 0\n')
        for name in ['etc/gameshellneo', 'usr/bin', 'usr/lib/modules/' + self.kernel,
                     'usr/lib/systemd', 'usr/sbin', 'home/cpi', 'var/lib', 'dev']:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.boot.mkdir()
        self.save_identity()
        (self.root / 'etc/fstab').write_bytes(self.fstab)
        (self.root / 'etc/independent.conf').write_bytes(b'private settings')
        (self.root / 'etc/independent.conf').chmod(0o640)
        (self.root / 'home/cpi/private-key').write_bytes(b'private identity')
        (self.root / 'home/cpi/private-key').chmod(0o600)
        (self.root / 'var/lib/state').write_bytes(b'mutable')
        self.module = self.root / 'usr/lib/modules' / self.kernel / 'example.ko'
        elf = bytearray(64)
        elf[:6] = b'\x7fELF\x01\x01'
        struct.pack_into('<H', elf, 18, 40)
        self.module.write_bytes(elf + b'\0vermagic=' + self.kernel.encode() + b' SMP\0')
        (self.root / 'usr/bin/tool').write_bytes(b'unchanged executable')
        (self.root / 'usr/bin/tool').chmod(0o755)
        os.link(self.root / 'usr/bin/tool', self.root / 'usr/bin/tool-hardlink')
        (self.root / 'usr/bin/tool-link').symlink_to('tool')
        (self.root / 'usr/lib/systemd/systemd').write_bytes(b'fixture init')
        (self.root / 'usr/sbin/init').symlink_to('/usr/lib/systemd/systemd')
        (self.root / 'sbin').symlink_to('usr/sbin')
        (self.root / 'lib').symlink_to('usr/lib')
        os.mkfifo(self.root / 'dev/fixture-fifo')
        (self.boot / 'uImage').write_bytes(kernel_image(self.kernel))
        (self.boot / images.DTB).write_bytes(dtb())
        self.initramfs.write_bytes(legacy(gzip.compress(b'070701 fixture initramfs', mtime=0), 3, 1))

    def save_identity(self):
        (self.root / images.IMAGE).write_bytes((json.dumps(self.identity) + '\n').encode())

    def imported(self, **kwargs):
        # Synthetic files belong to the real test user. Only the privilege gate
        # is mocked; real chown/chmod/xattr/link verification still runs. The
        # privileged saved builder separately exercises root/mixed-uid OS trees.
        with patch.object(images.os, 'geteuid', return_value=0):
            return images.import_release(self.root, self.boot, self.destination,
                slot='diagnostic-26', source_image_sha256='a' * 64,
                store_partuuid='1234abcd-03', initramfs=self.initramfs, **kwargs)

    def test_import_preserves_os_metadata_and_separates_identity(self):
        original_manifest = (self.root / images.IMAGE).read_bytes()
        result = self.imported()
        copied = self.destination / 'root'
        self.assertEqual((self.destination / 'source-image.json').read_bytes(), original_manifest)
        self.assertEqual((self.destination / 'source-fstab').read_bytes(), self.fstab)
        self.assertEqual((self.root / images.IMAGE).read_bytes(), original_manifest)
        self.assertEqual((self.root / 'etc/fstab').read_bytes(), self.fstab)
        self.assertEqual((copied / 'etc/fstab').read_bytes(),
            b'# keep this exact comment\n\ntmpfs /tmp tmpfs defaults,nosuid,size=64M 0 0\n')
        expected_marker = b'schema=1\nid=diagnostic-26\nkernel=6.18.54-gameshellneo25\n'
        self.assertEqual((copied / images.MARKER).read_bytes(), expected_marker)
        changed = json.loads((copied / images.IMAGE).read_text())
        self.assertEqual(changed['deployment'], 'development-directory')
        self.assertEqual(changed['root_partuuid'], '1234abcd-03')
        self.assertEqual(changed['source_image_sha256'], 'a' * 64)
        self.assertEqual(result['source_manifest_sha256'], digest(original_manifest))
        self.assertEqual(result['source_fstab_sha256'], digest(self.fstab))
        self.assertEqual(result['deployment_manifest_sha256'], digest((copied / images.IMAGE).read_bytes()))
        self.assertEqual(json.loads((self.destination / 'release.json').read_text()), result)
        for name in ['usr/bin/tool', 'etc/independent.conf', 'home/cpi/private-key', 'dev/fixture-fifo']:
            before, after = (self.root / name).lstat(), (copied / name).lstat()
            self.assertEqual((before.st_uid, before.st_gid, before.st_mode, before.st_mtime_ns),
                             (after.st_uid, after.st_gid, after.st_mode, after.st_mtime_ns))
        self.assertEqual((copied / 'usr/bin/tool').stat().st_ino,
                         (copied / 'usr/bin/tool-hardlink').stat().st_ino)
        self.assertNotEqual((copied / 'usr/bin/tool').stat().st_ino,
                            (self.root / 'usr/bin/tool').stat().st_ino)
        self.assertEqual(os.readlink(copied / 'usr/sbin/init'), '/usr/lib/systemd/systemd')
        self.assertEqual(os.readlink(copied / 'usr/bin/tool-link'), 'tool')
        self.assertIn('usr/bin/tool', result['immutable_files'])
        self.assertIn(str(images.MARKER), result['immutable_files'])
        self.assertNotIn('home/cpi/private-key', result['immutable_files'])
        self.assertNotIn('etc/independent.conf', result['immutable_files'])
        self.assertNotIn('var/lib/state', result['immutable_files'])
        self.assertFalse(any('private' in name for name in result['boot_files']))

    def test_inspect_source_needs_no_privilege_or_initramfs_and_retains_policy(self):
        self.identity['sources']['experiments'] = {'suspend_diagnostics': True}
        self.save_identity()
        original = (self.root / images.IMAGE).read_bytes()
        self.initramfs.unlink()
        with patch.object(images.os, 'geteuid', return_value=1000):
            inspected = images.inspect_source(self.root, self.boot)
        self.assertEqual(inspected['kernel'], self.kernel)
        self.assertTrue(inspected['suspend_diagnostics'])
        self.assertEqual(inspected['sources'], self.identity['sources'])
        self.assertEqual(inspected['source_manifest_sha256'], digest(original))
        self.assertEqual(inspected['source_fstab_sha256'], digest(self.fstab))
        self.assertEqual(set(inspected['boot_files']), {'uImage', images.DTB})
        self.assertEqual((self.root / images.IMAGE).read_bytes(), original)
        self.assertEqual((self.root / 'etc/fstab').read_bytes(), self.fstab)
        self.assertFalse(self.destination.exists())

    def test_inspect_source_rejects_boot_and_module_mismatch(self):
        (self.boot / 'uImage').write_bytes(kernel_image('different-kernel'))
        with self.assertRaisesRegex(ValueError, 'Boot kernel'):
            images.inspect_source(self.root, self.boot)
        (self.boot / 'uImage').write_bytes(kernel_image(self.kernel))
        self.module.write_bytes(self.module.read_bytes().replace(self.kernel.encode(), b'wrong'))
        with self.assertRaisesRegex(ValueError, 'vermagic'):
            images.inspect_source(self.root, self.boot)

    def test_legacy_usb_boot_policies_reject_instead_of_silently_changing(self):
        original = deepcopy(self.identity)
        for field, value in (('usb_absent_poll', True), ('usb_absent_poll', False),
                             ('usb_diagnostics', True), ('usb_diagnostics', False),
                             ('usb_poll_boot', {'initial_mode': 'stock'})):
            self.identity = deepcopy(original)
            if field == 'usb_poll_boot':
                self.identity[field] = value
            else:
                self.identity['sources']['experiments'] = {field: value}
            self.save_identity()
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, 'Legacy USB boot'):
                self.imported()
            self.assertFalse(self.destination.exists())
        self.identity = original
        # These are the retained diagnostic.25/.26 experiment shapes. Only
        # suspend_diagnostics changes their boot command line.
        for extra in ({}, {'clock_provenance': True}):
            self.identity['sources']['experiments'] = dict(suspend_diagnostics=True,
                keypad_supply_retention=True, cpi_wfi_s2idle=True, **extra)
            self.save_identity()
            self.assertTrue(images.inspect_source(self.root, self.boot)['suspend_diagnostics'])

    def test_import_preserves_exact_boolean_suspend_policy(self):
        for enabled in (True, False):
            self.identity['sources']['experiments'] = {'suspend_diagnostics': enabled}
            self.save_identity()
            result = self.imported()
            self.assertIs(result['suspend_diagnostics'], enabled)
            changed = json.loads((self.destination / 'root' / images.IMAGE).read_bytes())
            self.assertIs(changed['sources']['experiments']['suspend_diagnostics'], enabled)
            shutil.rmtree(self.destination)
        for malformed in (1, 'true', None):
            self.identity['sources']['experiments'] = {'suspend_diagnostics': malformed}
            self.save_identity()
            with self.subTest(malformed=malformed), self.assertRaisesRegex(ValueError, 'boolean'):
                self.imported()
            self.assertFalse(self.destination.exists())

    def test_symlink_targets_are_copied_without_reading_host_files(self):
        outside = self.directory / 'outside'
        outside.write_bytes(b'never imported')
        (self.root / 'usr/bin/outside-link').symlink_to(outside)
        result = self.imported()
        self.assertEqual(os.readlink(self.destination / 'root/usr/bin/outside-link'), str(outside))
        self.assertNotIn('usr/bin/outside-link', result['immutable_files'])
        self.assertEqual(outside.read_bytes(), b'never imported')

    def test_existing_destination_and_symlink_parents_are_rejected(self):
        self.destination.mkdir()
        with self.assertRaises(FileExistsError):
            self.imported()
        self.destination.rmdir()
        link = self.directory / 'linked-parent'
        link.symlink_to(self.directory)
        self.destination = link / 'imported'
        with self.assertRaises(ValueError):
            self.imported()
        self.assertFalse((self.directory / 'imported').exists())

    def test_non_root_actual_import_is_denied_before_creating_stage(self):
        with patch.object(images.os, 'geteuid', return_value=1000), self.assertRaises(PermissionError):
            images.import_release(self.root, self.boot, self.destination, slot='diagnostic-26',
                source_image_sha256='a' * 64, store_partuuid='1234abcd-03', initramfs=self.initramfs)
        self.assertFalse(self.destination.exists())

    def test_invalid_identity_kernel_and_modules_reject(self):
        original = deepcopy(self.identity)
        for key, value in [('board', 'other-board'), ('hardware_qualified', True),
                           ('kernel', 'wrong'), ('deployment', 'development-directory')]:
            self.identity = deepcopy(original)
            self.identity[key] = value
            self.save_identity()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.imported()
            self.assertFalse(self.destination.exists())
        self.identity = original
        self.save_identity()
        (self.boot / 'uImage').write_bytes(kernel_image('different-kernel'))
        with self.assertRaisesRegex(ValueError, 'Boot kernel'):
            self.imported()
        (self.boot / 'uImage').write_bytes(kernel_image(self.kernel))
        self.module.write_bytes(self.module.read_bytes().replace(self.kernel.encode(), b'wrong'))
        with self.assertRaisesRegex(ValueError, 'vermagic'):
            self.imported()

    def test_symlinked_metadata_or_modules_reject(self):
        image = self.root / images.IMAGE
        saved = image.read_bytes()
        alternate = self.directory / 'identity.json'
        alternate.write_bytes(saved)
        image.unlink()
        image.symlink_to(alternate)
        with self.assertRaises(ValueError):
            self.imported()
        image.unlink()
        image.write_bytes(saved)
        (self.module.parent / 'escaped.ko').symlink_to(self.module)
        with self.assertRaisesRegex(ValueError, 'Module paths'):
            self.imported()

    def test_source_overlap_and_dangling_optional_boot_link_reject(self):
        self.destination = self.root / 'would-mutate-source'
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.imported()
        self.assertFalse(self.destination.exists())
        self.destination = self.directory / 'imported'
        (self.boot / images.BASE_DTB).symlink_to('missing.dtb')
        with self.assertRaises(ValueError):
            self.imported()
        self.assertFalse(self.destination.exists())

    def test_corrupt_boot_assets_reject_without_publication(self):
        for path in [self.boot / 'uImage', self.boot / images.DTB, self.initramfs]:
            original = path.read_bytes()
            path.write_bytes(b'broken')
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                self.imported()
            path.write_bytes(original)
            self.assertFalse(self.destination.exists())
            self.assertFalse(list(self.directory.glob('.imported-import-*')))

    def test_bad_ramdisk_body_with_valid_crc_rejects(self):
        for payload in [b'not gzip', gzip.compress(b'not cpio')]:
            self.initramfs.write_bytes(legacy(payload, 3, 1))
            with self.assertRaises(ValueError):
                self.imported()
            self.assertFalse(self.destination.exists())

    def test_keypad_baseline_is_retained_and_hash_checked(self):
        base = self.boot / images.BASE_DTB
        base.write_bytes(dtb())
        self.identity['keypad_supply'] = dict(baseline_sha256=digest(base.read_bytes()),
                                              installed_sha256=digest((self.boot / images.DTB).read_bytes()))
        self.save_identity()
        result = self.imported()
        self.assertEqual(result['boot_files'][images.BASE_DTB], digest(base.read_bytes()))
        self.assertEqual((self.destination / 'boot' / images.BASE_DTB).read_bytes(), base.read_bytes())

    def test_failure_to_preserve_metadata_does_not_publish(self):
        with patch.object(images, '_metadata', side_effect=PermissionError('cannot retain uid')):
            with self.assertRaises(PermissionError):
                self.imported()
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.directory.glob('.imported-import-*')))

    def test_extended_attributes_are_preserved_or_import_fails(self):
        path = self.root / 'usr/bin/tool'
        os.setxattr(path, 'user.dev-import', b'retain exactly')
        self.imported()
        self.assertEqual(os.getxattr(self.destination / 'root/usr/bin/tool', 'user.dev-import'),
                         b'retain exactly')

    @unittest.skipUnless(os.geteuid() == 0, 'Actual mixed ownership/device copying requires root')
    def test_actual_mixed_ownership_and_device_node(self):
        path = self.root / 'home/cpi/private-key'
        os.chown(path, 1234, 2345)
        os.mknod(self.root / 'dev/fixture-null', stat.S_IFCHR | 0o600, os.makedev(1, 3))
        self.imported()
        copied = (self.destination / 'root/home/cpi/private-key').stat()
        self.assertEqual((copied.st_uid, copied.st_gid, stat.S_IMODE(copied.st_mode)), (1234, 2345, 0o600))
        self.assertEqual((self.destination / 'root/dev/fixture-null').lstat().st_rdev, os.makedev(1, 3))

    def test_late_destination_creation_is_never_replaced(self):
        publish = images._publish
        def collision(stage, destination):
            destination.mkdir()
            (destination / 'owner-file').write_bytes(b'preserve')
            publish(stage, destination)
        with patch.object(images, '_publish', side_effect=collision), self.assertRaises(FileExistsError):
            self.imported()
        self.assertEqual((self.destination / 'owner-file').read_bytes(), b'preserve')
        self.assertFalse(list(self.directory.glob('.imported-import-*')))

    def test_unsupported_live_socket_rejects(self):
        with socket.socket(socket.AF_UNIX) as stream:
            stream.bind(str(self.root / 'var/lib/live.sock'))
            with self.assertRaisesRegex(ValueError, 'Unsupported image file type'):
                self.imported()


if __name__ == '__main__':
    unittest.main()
