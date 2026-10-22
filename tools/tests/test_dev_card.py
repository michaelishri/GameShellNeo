import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev_card import admit_recovery, append_partition, fresh_output, layout, SOURCE_BYTES
import tempfile
from unittest.mock import patch


class DevelopmentCardLayout(unittest.TestCase):
    def test_append_preserves_bootloader_disk_identifier_and_existing_partition_bytes(self):
        original = bytearray(b'X' * 512)
        original[478:510] = bytes(32)
        original[510:] = b'\x55\xaa'
        source = {'disk_id': '1234abcd', 'bytes': SOURCE_BYTES,
                  'recovery_start_sector': 294912, 'recovery_sectors': 8093696}
        plan = layout(source, 32 * 1024 ** 3)
        changed = append_partition(bytes(original), plan)
        self.assertEqual(changed[:478], original[:478])
        self.assertEqual(changed[494:], original[494:])
        entry = struct.unpack('<B3sB3sII', changed[478:494])
        self.assertEqual((entry[0], entry[2], entry[4]), (0, 0x83, SOURCE_BYTES // 512))
        self.assertEqual((entry[4] + entry[5]) * 512, 32 * 1024 ** 3)
        self.assertEqual(plan['store_partuuid'], '1234abcd-03')

    def test_no_existing_partition_is_overwritten(self):
        original = bytearray(512)
        original[510:] = b'\x55\xaa'
        original[478] = 1
        with self.assertRaises(ValueError):
            append_partition(bytes(original), {'store_start_sector': 1, 'store_sectors': 1})

    def test_invalid_sizes_and_noninteger_values_reject(self):
        for size in (0, SOURCE_BYTES, 6 * 1024 ** 3 + 1, True, 3 * 1024 ** 4):
            with self.subTest(size=size), self.assertRaises(ValueError):
                layout({'disk_id': '1234abcd'}, size)

    def test_existing_receipt_or_symlink_never_gets_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'new.img'
            receipt = output.with_suffix('.json')
            receipt.write_text('original evidence')
            with self.assertRaises(FileExistsError):
                fresh_output(output)
            self.assertEqual(receipt.read_text(), 'original evidence')
            receipt.unlink()
            owner = Path(temporary) / 'owner'
            owner.write_text('preserved')
            receipt.symlink_to(owner)
            with self.assertRaises(FileExistsError):
                fresh_output(output)
            self.assertEqual(owner.read_text(), 'preserved')

    def test_recovery_partition_identity_cannot_diverge_from_manifest_or_fstab(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'etc').mkdir()
            fstab = root / 'etc/fstab'
            correct = b'PARTUUID=1234abcd-02 / ext4 defaults 0 1\n'
            fstab.write_bytes(correct)
            with patch('dev_images.inspect_source', return_value={'root_partuuid': '1234abcd-02'}):
                self.assertEqual(admit_recovery(root, root, '1234abcd-02')['root_partuuid'], '1234abcd-02')
                for text in (b'PARTUUID=9876fedc-02 / ext4 defaults 0 1\n', b'', correct + correct):
                    fstab.write_bytes(text)
                    with self.assertRaisesRegex(ValueError, 'Recovery manifest/fstab'):
                        admit_recovery(root, root, '1234abcd-02')
            fstab.write_bytes(correct)
            with patch('dev_images.inspect_source', return_value={'root_partuuid': '9876fedc-02'}), \
                    self.assertRaisesRegex(ValueError, 'Recovery manifest/fstab'):
                admit_recovery(root, root, '1234abcd-02')


if __name__ == '__main__':
    unittest.main()
