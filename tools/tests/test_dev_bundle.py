"""Real GNU pax metadata round trips and archive admission before extraction."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dev_bundle as bundles


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DevelopmentBundle(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.version = self.base / 'diagnostic-26'
        self.root = self.version / 'root'
        for relative in ('usr/bin', 'etc/gameshellneo', 'dev', 'var/lib'):
            (self.root / relative).mkdir(parents=True)
        self.file = self.root / 'usr/bin/tool'
        self.file.write_bytes(b'unchanged application\n')
        self.file.chmod(0o751)
        os.link(self.file, self.file.with_name('hardlink'))
        (self.root / 'sbin').symlink_to('/usr/bin')
        (self.root / 'etc/relative-link').symlink_to('../usr/bin/tool')
        os.mkfifo(self.root / 'dev/pipe', 0o640)
        self.mutable = self.root / 'var/lib/settings'
        self.mutable.write_bytes(b'independent settings')
        self.mutable.chmod(0o600)
        (self.version / 'boot').mkdir()
        for filename in ('uImage', 'sun8i-r16-clockworkpi-cpi3.dtb', 'uInitrd'):
            (self.version / 'boot' / filename).write_bytes(b'fixture ' + filename.encode())
        self.source_image = self.version / 'source-image.json'
        self.source_image.write_text('{"original": true}\n')
        self.source_fstab = self.version / 'source-fstab'
        self.source_fstab.write_text('PARTUUID=1234abcd-02 / ext4 defaults 0 1\n')
        marker = self.root / 'etc/gameshellneo/development-slot'
        marker.write_text('schema=1\nid=diagnostic-26\nkernel=6.18.54-gameshellneo25\n')
        identity = self.root / 'etc/gameshellneo/image.json'
        identity.write_text('{"deployment": "development-directory"}\n')
        self.manifest = dict(schema=1, board=bundles.BOARD, slot=self.version.name,
            kernel='6.18.54-gameshellneo25', store_partuuid='1234abcd-03',
            source_image_sha256='a' * 64, source_manifest_sha256=sha(self.source_image),
            source_fstab_sha256=sha(self.source_fstab), deployment_manifest_sha256=sha(identity),
            boot_files={path.name: sha(path) for path in (self.version / 'boot').iterdir()},
            immutable_files={str(path.relative_to(self.root)): sha(path)
                             for path in (marker, identity, self.file)})
        self.save_manifest()
        self.archive = self.base / 'bundle.tar'
        self.systems = self.base / 'systems'
        self.systems.mkdir()
        self.destination = self.systems / self.version.name
        os.utime(self.file, ns=(1700000000123456789, 1700000010987654321))

    def save_manifest(self):
        (self.version / 'release.json').write_text(json.dumps(self.manifest) + '\n')

    def unpack(self, **kwargs):
        # Ordinary fixtures retain the real caller's ownership. The root gate
        # alone is mocked here; GNU tar and metadata verification execute fully.
        with patch.object(bundles.os, 'geteuid', return_value=0):
            return bundles.unpack_release(self.archive, self.destination,
                expected_hash=kwargs.pop('expected_hash', sha(self.archive)),
                store_partuuid=kwargs.pop('store_partuuid', '1234abcd-03'), **kwargs)

    def crafted(self, additions=(), *, mutate=None):
        with tarfile.open(self.archive, 'w', format=tarfile.PAX_FORMAT) as archive:
            archive.add(self.version, arcname=self.version.name, filter=mutate)
            for member, data in additions:
                archive.addfile(member, io.BytesIO(data) if data else None)

    def assert_not_published(self):
        self.assertFalse(self.destination.exists())
        logs = list(self.systems.glob('.diagnostic-26-bundle-*/operation.log'))
        self.assertTrue(logs)
        self.assertTrue(any(path.stat().st_size for path in logs))

    def test_real_gnu_round_trip_preserves_data_metadata_links_and_selection(self):
        selection = self.base / 'NEXT.SCR'
        selection.write_bytes(b'original selection')
        os.setxattr(self.file, 'user.bundle-test', b'opaque\0\xff metadata')
        before = self.file.stat()
        result = bundles.pack_release(self.version, self.archive)
        self.assertEqual(result['sha256'], sha(self.archive))
        self.assertEqual(result['bytes'], self.archive.stat().st_size)
        self.assertEqual(result['slot'], self.version.name)
        self.assertEqual(result['source_image_sha256'], 'a' * 64)
        self.assertEqual(self.unpack(), self.manifest)
        target = self.destination / 'root/usr/bin/tool'
        after = target.stat()
        self.assertEqual(target.read_bytes(), b'unchanged application\n')
        self.assertEqual((before.st_uid, before.st_gid, before.st_mode, before.st_mtime_ns),
                         (after.st_uid, after.st_gid, after.st_mode, after.st_mtime_ns))
        self.assertEqual(before.st_atime_ns, after.st_atime_ns)
        self.assertEqual(os.getxattr(target, 'user.bundle-test'), b'opaque\0\xff metadata')
        self.assertEqual(target.stat().st_ino, target.with_name('hardlink').stat().st_ino)
        self.assertNotEqual(target.stat().st_ino, self.file.stat().st_ino)
        self.assertEqual(os.readlink(self.destination / 'root/sbin'), '/usr/bin')
        self.assertEqual(os.readlink(self.destination / 'root/etc/relative-link'), '../usr/bin/tool')
        self.assertTrue(stat.S_ISFIFO((self.destination / 'root/dev/pipe').stat().st_mode))
        self.assertEqual((self.destination / 'root/var/lib/settings').read_bytes(), b'independent settings')
        self.assertEqual(selection.read_bytes(), b'original selection')
        self.assertFalse(list(self.systems.glob('.diagnostic-26-bundle-*/archive.tar')))
        self.assertFalse(self.archive.with_suffix('.json').exists())

    def test_named_user_acl_round_trip(self):
        # Named-user ACL, independent of a setfacl executable or root privileges.
        acl = struct.pack('<I', 2) + b''.join(struct.pack('<HHI', *entry) for entry in
            ((1, 7, 0xffffffff), (2, 4, 12345), (4, 5, 0xffffffff),
             (16, 5, 0xffffffff), (32, 1, 0xffffffff)))
        try:
            os.setxattr(self.file, 'system.posix_acl_access', acl)
        except OSError as error:
            if os.geteuid() == 0:
                raise
            self.skipTest('Host filesystem cannot create POSIX ACLs: ' + str(error))
        bundles.pack_release(self.version, self.archive)
        self.unpack()
        self.assertEqual(os.getxattr(self.destination / 'root/usr/bin/tool',
                                   'system.posix_acl_access'), acl)

    def test_tar_options_cannot_change_the_fixed_packing_command(self):
        with patch.dict(os.environ, {'TAR_OPTIONS': '--transform=s/diagnostic-26/other/'}):
            bundles.pack_release(self.version, self.archive)
            self.assertEqual(self.unpack()['slot'], 'diagnostic-26')

    def test_existing_artifact_and_destination_are_never_replaced(self):
        self.archive.write_bytes(b'original archive')
        with self.assertRaises(FileExistsError):
            bundles.pack_release(self.version, self.archive)
        self.assertEqual(self.archive.read_bytes(), b'original archive')
        self.archive.unlink()
        bundles.pack_release(self.version, self.archive)
        self.destination.mkdir()
        marker = self.destination / 'original'
        marker.write_bytes(b'preserved')
        with self.assertRaises(FileExistsError):
            self.unpack()
        self.assertEqual(marker.read_bytes(), b'preserved')

    def test_hash_wrong_card_and_wrong_version_reject_before_publication(self):
        bundles.pack_release(self.version, self.archive)
        for arguments in ({'expected_hash': '0' * 64}, {'store_partuuid': '9876fedc-03'}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.unpack(**arguments)
            self.assert_not_published()
        with patch.object(bundles.os, 'geteuid', return_value=0), self.assertRaises(ValueError):
            bundles.unpack_release(self.archive, self.systems / 'another-version',
                expected_hash=sha(self.archive), store_partuuid='1234abcd-03')
        self.assertFalse((self.systems / 'another-version').exists())

    def test_missing_and_inconsistent_source_metadata_reject(self):
        self.source_fstab.write_bytes(b'changed source metadata')
        with self.assertRaisesRegex(ValueError, 'source metadata'):
            bundles.pack_release(self.version, self.archive)
        self.crafted()
        with self.assertRaisesRegex(ValueError, 'source metadata'):
            self.unpack()
        self.assert_not_published()

    def test_path_traversal_duplicates_and_unsupported_types_never_extract(self):
        for name, kind in (('/absolute-escape', tarfile.REGTYPE),
                           ('diagnostic-26/root/../../escape', tarfile.REGTYPE),
                           ('diagnostic-26//root/file', tarfile.REGTYPE),
                           ('diagnostic-26/root/./file', tarfile.REGTYPE),
                           ('diagnostic-26/release.json', tarfile.REGTYPE),
                           ('diagnostic-26/root/sparse', tarfile.GNUTYPE_SPARSE)):
            with self.subTest(name=name):
                member = tarfile.TarInfo(name)
                member.type = kind
                self.crafted([(member, b'')])
                with patch.object(bundles, '_execute') as extraction, self.assertRaises(ValueError):
                    self.unpack()
                extraction.assert_not_called()
                self.assert_not_published()

    def test_symlink_ancestors_reject_regardless_of_archive_order(self):
        for order in (False, True):
            with self.subTest(child_first=order):
                link = tarfile.TarInfo('diagnostic-26/root/redirect')
                link.type, link.linkname = tarfile.SYMTYPE, str(self.base)
                child = tarfile.TarInfo('diagnostic-26/root/redirect/escape')
                additions = [(link, b''), (child, b'')]
                self.crafted(reversed(additions) if order else additions)
                with patch.object(bundles, '_execute') as extraction, self.assertRaisesRegex(ValueError, 'ancestor'):
                    self.unpack()
                extraction.assert_not_called()
                self.assertFalse((self.base / 'escape').exists())

    def test_hardlinks_must_target_a_regular_member_inside_the_version(self):
        for target in ('/etc/passwd', '../outside', 'other/root/file',
                       'diagnostic-26/root/sbin', 'diagnostic-26/root/missing',
                       'diagnostic-26/root/usr'):
            with self.subTest(target=target):
                link = tarfile.TarInfo('diagnostic-26/root/hard-escape')
                link.type, link.linkname = tarfile.LNKTYPE, target
                self.crafted([(link, b'')])
                with patch.object(bundles, '_execute') as extraction, self.assertRaises(ValueError):
                    self.unpack()
                extraction.assert_not_called()

    def test_pax_overrides_and_appended_archives_cannot_hide_members(self):
        member = tarfile.TarInfo('diagnostic-26/root/safe')
        member.pax_headers = {'path': '../escape'}
        self.crafted([(member, b'')])
        with patch.object(bundles, '_execute') as extraction, self.assertRaises(ValueError):
            self.unpack()
        extraction.assert_not_called()
        self.crafted()
        with self.archive.open('ab') as stream:
            stream.write(b'not permitted after TAR ending')
        with patch.object(bundles, '_execute') as extraction, self.assertRaises(ValueError):
            self.unpack()
        extraction.assert_not_called()
        with self.assertRaises(ValueError):
            bundles._pax(b'10 path=a\n10 path=b\n')
        with self.assertRaises(ValueError):
            bundles._pax(b'22 GNU.sparse.name=x\n')

    def test_failed_extraction_retains_snapshot_log_and_preserves_existing_systems(self):
        bundles.pack_release(self.version, self.archive)
        existing = self.systems / 'older-version'
        existing.mkdir()
        (existing / 'original').write_bytes(b'preserved')
        with patch.object(bundles, '_execute', side_effect=RuntimeError('original extraction failure')):
            with self.assertRaisesRegex(RuntimeError, 'original extraction failure'):
                self.unpack()
        self.assert_not_published()
        self.assertEqual((existing / 'original').read_bytes(), b'preserved')
        self.assertTrue(list(self.systems.glob('.diagnostic-26-bundle-*/archive.tar')))

    def test_root_required_reserved_name_and_nonregular_archive_reject(self):
        with patch.object(bundles.os, 'geteuid', return_value=1000), self.assertRaises(PermissionError):
            bundles.unpack_release(self.archive, self.destination, expected_hash='0' * 64,
                                   store_partuuid='1234abcd-03')
        with patch.object(bundles.os, 'geteuid', return_value=0), self.assertRaises(ValueError):
            bundles.unpack_release(self.archive, self.systems / 'recovery', expected_hash='0' * 64,
                                   store_partuuid='1234abcd-03')
        self.archive.symlink_to(self.source_image)
        with self.assertRaises(OSError):
            self.unpack()

    @unittest.skipUnless(os.geteuid() == 0, 'mixed ownership/device nodes require the saved root builder')
    def test_root_round_trip_preserves_mixed_uid_gid_and_device_nodes(self):
        os.chown(self.file, 12345, 23456)
        node = self.root / 'dev/null-fixture'
        os.mknod(node, stat.S_IFCHR | 0o640, os.makedev(1, 3))
        os.chown(node, 12346, 23457)
        bundles.pack_release(self.version, self.archive)
        self.unpack()
        target = self.destination / 'root/usr/bin/tool'
        self.assertEqual((target.stat().st_uid, target.stat().st_gid), (12345, 23456))
        actual = (self.destination / 'root/dev/null-fixture').stat()
        self.assertTrue(stat.S_ISCHR(actual.st_mode))
        self.assertEqual((actual.st_uid, actual.st_gid, actual.st_rdev), (12346, 23457, os.makedev(1, 3)))


if __name__ == '__main__':
    unittest.main()
