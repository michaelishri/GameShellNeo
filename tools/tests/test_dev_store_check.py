"""Complete-root metadata stays stable across development administration."""
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location('development_store_compatibility', TOOLS / 'check-dev-store.py')
compatibility = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compatibility)


class CompleteRootMetadata(unittest.TestCase):
    def setUp(self):
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = self.base / 'complete root'
        self.outside = self.base / 'outside'
        self.outside.write_bytes(b'outside data must never be followed')
        self.populate(self.root)

    def populate(self, root):
        root.mkdir(mode=0o755)
        (root / 'bin').mkdir(mode=0o755)
        (root / 'empty').mkdir(mode=0o755)
        tool = root / 'bin/tool'
        tool.write_bytes(b'unchanged fixture content')
        tool.chmod(0o751)
        os.setxattr(tool, 'user.metadata-fixture', b'opaque\0\xff value')
        os.link(tool, root / 'bin/alias')
        (root / 'link').symlink_to(self.outside)
        os.mkfifo(root / 'pipe', 0o640)
        for path in (root / 'bin/tool', root / 'bin/alias', root / 'link', root / 'pipe',
                     root / 'bin', root / 'empty', root):
            os.utime(path, ns=(1700000000123456789, 1700000000987654321), follow_symlinks=False)

    def test_deterministic_summary_covers_every_entry_without_following_symlinks(self):
        original_scandir = os.scandir
        visited = []
        def scanning(path):
            visited.append(Path(path))
            self.assertTrue(Path(path).is_relative_to(self.root))
            return original_scandir(path)
        with patch.object(compatibility.os, 'scandir', side_effect=scanning):
            first = compatibility.root_metadata(self.root)
        self.assertEqual(set(visited), {self.root, self.root / 'bin', self.root / 'empty'})
        self.assertEqual(first, compatibility.root_metadata(self.root))
        self.assertEqual(first['entries']['link']['symlink'], str(self.outside))
        self.assertEqual(first['entries']['bin/tool']['xattrs']['user.metadata-fixture'], b'opaque\0\xff value'.hex())
        summary = compatibility.metadata_summary(first)
        self.assertEqual({name: summary[name] for name in ('entries', 'directories', 'regular_files',
                          'symlinks', 'special_files', 'hardlink_groups')},
                         dict(entries=7, directories=3, regular_files=2, symlinks=1,
                              special_files=1, hardlink_groups=1))
        self.assertEqual(first['hardlink_groups'], [['bin/alias', 'bin/tool']])
        self.assertEqual(len(summary['sha256']), 64)

    def test_independent_inode_numbers_and_read_induced_atime_do_not_change_metadata(self):
        before = compatibility.root_metadata(self.root)
        clone = self.base / 'independent root'
        self.populate(clone)
        self.assertNotEqual((self.root / 'bin/tool').stat().st_ino, (clone / 'bin/tool').stat().st_ino)
        self.assertEqual(before, compatibility.root_metadata(clone))
        tool = self.root / 'bin/tool'
        details = tool.stat()
        os.utime(tool, ns=(details.st_atime_ns + 9000000000, details.st_mtime_ns))
        after = compatibility.root_metadata(self.root)
        compatibility.verify_root_metadata(before, after)
        self.assertEqual(compatibility.metadata_summary(before), compatibility.metadata_summary(after))

    def test_mode_and_nanosecond_mtime_changes_fail_equality(self):
        tool = self.root / 'bin/tool'
        before = compatibility.root_metadata(self.root)
        tool.chmod(0o750)
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            compatibility.verify_root_metadata(before, compatibility.root_metadata(self.root))
        tool.chmod(0o751)
        details = tool.stat()
        os.utime(tool, ns=(details.st_atime_ns, details.st_mtime_ns + 1))
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            compatibility.verify_root_metadata(before, compatibility.root_metadata(self.root))

    def test_symlink_text_change_fails_even_when_mode_and_mtime_are_preserved(self):
        before = compatibility.root_metadata(self.root)
        link, root_details = self.root / 'link', self.root.stat()
        details = link.lstat()
        link.unlink()
        link.symlink_to('different relative target')
        os.utime(link, ns=(details.st_atime_ns, details.st_mtime_ns), follow_symlinks=False)
        os.utime(self.root, ns=(root_details.st_atime_ns, root_details.st_mtime_ns))
        after = compatibility.root_metadata(self.root)
        self.assertEqual(before['entries']['link']['mode'], after['entries']['link']['mode'])
        self.assertEqual(before['entries']['link']['mtime_ns'], after['entries']['link']['mtime_ns'])
        with self.assertRaisesRegex(ValueError, 'link'):
            compatibility.verify_root_metadata(before, after)

    def test_broken_hardlink_group_fails_even_when_file_metadata_is_copied(self):
        before = compatibility.root_metadata(self.root)
        alias = self.root / 'bin/alias'
        directory_details = alias.parent.stat()
        temporary = alias.with_name('replacement')
        shutil.copy2(alias, temporary)
        temporary.replace(alias)
        os.utime(alias.parent, ns=(directory_details.st_atime_ns, directory_details.st_mtime_ns))
        after = compatibility.root_metadata(self.root)
        self.assertEqual(after['hardlink_groups'], [])
        self.assertEqual(before['entries']['bin/alias']['mtime_ns'], after['entries']['bin/alias']['mtime_ns'])
        self.assertEqual(before['entries']['bin/alias']['xattrs'], after['entries']['bin/alias']['xattrs'])
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            compatibility.verify_root_metadata(before, after)

    def test_xattr_value_changes_fail_equality(self):
        tool = self.root / 'bin/tool'
        before = compatibility.root_metadata(self.root)
        os.setxattr(tool, 'user.metadata-fixture', b'different opaque value')
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            compatibility.verify_root_metadata(before, compatibility.root_metadata(self.root))

    def test_posix_acl_values_are_captured_and_compared(self):
        tool = self.root / 'bin/tool'
        before = compatibility.root_metadata(self.root)
        acl = struct.pack('<I', 2) + b''.join(struct.pack('<HHI', *entry) for entry in (
            (1, 7, 0xffffffff), (2, 4, 12345), (4, 5, 0xffffffff),
            (16, 5, 0xffffffff), (32, 1, 0xffffffff)))
        try:
            os.setxattr(tool, 'system.posix_acl_access', acl)
        except OSError as error:
            if os.geteuid() == 0:
                raise
            self.skipTest('Host filesystem cannot create POSIX ACLs: ' + str(error))
        after = compatibility.root_metadata(self.root)
        self.assertEqual(after['entries']['bin/tool']['xattrs']['system.posix_acl_access'], acl.hex())
        self.assertGreater(compatibility.metadata_summary(after)['acls'], 0)
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            compatibility.verify_root_metadata(before, after)

    def test_nested_mounts_filesystems_and_symlinked_root_are_rejected(self):
        mountinfo = self.base / 'mountinfo'
        escaped = str(self.root).replace(' ', '\\040')
        mountinfo.write_text('1 0 0:1 / ' + escaped + ' rw - ext4 /dev/fixture rw\n')
        compatibility.reject_nested_mounts(self.root, mountinfo)
        mountinfo.write_text('2 1 0:1 / ' + escaped + '/empty rw - ext4 /dev/fixture rw\n')
        with self.assertRaisesRegex(ValueError, 'Nested mount'):
            compatibility.reject_nested_mounts(self.root, mountinfo)
        original_lstat = Path.lstat
        def details(path):
            observed = original_lstat(path)
            if path == self.root / 'empty':
                return types.SimpleNamespace(st_dev=observed.st_dev + 1)
            return observed
        with patch.object(Path, 'lstat', new=details), self.assertRaisesRegex(ValueError, 'Nested filesystem'):
            compatibility.root_metadata(self.root)
        link = self.base / 'root alias'
        link.symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, 'real complete'):
            compatibility.root_metadata(link)

    @unittest.skipUnless(os.geteuid() == 0, 'mixed ownership requires the saved root test Task')
    def test_native_owner_changes_fail_equality(self):
        before = compatibility.root_metadata(self.root)
        os.chown(self.root / 'bin/tool', 12345, 23456)
        after = compatibility.root_metadata(self.root)
        self.assertEqual((after['entries']['bin/tool']['uid'], after['entries']['bin/tool']['gid']), (12345, 23456))
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            compatibility.verify_root_metadata(before, after)

    @unittest.skipUnless(os.geteuid() == 0, 'security capabilities require the saved root test Task')
    def test_native_capability_bytes_are_captured_and_compared(self):
        tool = self.root / 'bin/tool'
        original = struct.pack('<5I', 0x02000001, 1 << 13, 0, 0, 0)
        os.setxattr(tool, 'security.capability', original)
        before = compatibility.root_metadata(self.root)
        self.assertEqual(before['entries']['bin/tool']['xattrs']['security.capability'], original.hex())
        os.setxattr(tool, 'security.capability', struct.pack('<5I', 0x02000001, 1 << 7, 0, 0, 0))
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            compatibility.verify_root_metadata(before, compatibility.root_metadata(self.root))

    @unittest.skipUnless(os.geteuid() == 0, 'device metadata requires the saved root test Task')
    def test_native_device_identity_changes_fail_equality(self):
        node = self.root / 'device'
        os.mknod(node, stat.S_IFCHR | 0o640, os.makedev(1, 3))
        before = compatibility.root_metadata(self.root)
        details, root_details = node.stat(), self.root.stat()
        node.unlink()
        os.mknod(node, stat.S_IFCHR | 0o640, os.makedev(1, 5))
        os.utime(node, ns=(details.st_atime_ns, details.st_mtime_ns))
        os.utime(self.root, ns=(root_details.st_atime_ns, root_details.st_mtime_ns))
        after = compatibility.root_metadata(self.root)
        self.assertEqual(after['entries']['device']['rdev'], os.makedev(1, 5))
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            compatibility.verify_root_metadata(before, after)


if __name__ == '__main__':
    unittest.main()
