"""Destructive-operation guards; no real disk access."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('flash_macos', Path(__file__).parents[1] / 'flash-macos.py')
flash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash)


class TargetSafety(unittest.TestCase):
    def setUp(self):
        self.expected = {'device': 'disk16', 'partition': 'disk16s1',
                         'volume_uuid': 'owner-confirmed-volume', 'TotalSize': 64013467648,
                         'DeviceBlockSize': 512, 'MediaName': 'Micro SD/M2',
                         'DeviceTreePath': 'inspected-usb-port'}
        self.disk = dict(self.expected, WholeDisk=True, Internal=False,
                         VirtualOrPhysical='Physical', BusProtocol='USB', Writable=True,
                         RemovableMediaOrExternalDevice=True)
        self.partition = {'ParentWholeDisk': 'disk16', 'VolumeUUID': 'owner-confirmed-volume'}

    def validate(self, disk=None, partition=None, size=4294967296):
        with patch.object(flash, 'disk_info', side_effect=[disk or self.disk, partition or self.partition]):
            return flash.validate_target(self.expected, size)

    def test_identified_external_card(self):
        self.assertEqual(self.validate(), '/dev/rdisk16')

    def test_refuses_internal_virtual_readonly_and_changed_disks(self):
        for key, value in [('Internal', True), ('WholeDisk', False),
                           ('VirtualOrPhysical', 'Virtual'), ('BusProtocol', 'PCI-Express'),
                           ('Writable', False), ('TotalSize', 16000000000),
                           ('DeviceTreePath', 'another-port')]:
            with self.subTest(key=key):
                disk = copy.deepcopy(self.disk)
                disk[key] = value
                with self.assertRaises(RuntimeError):
                    self.validate(disk=disk)

    def test_refuses_reused_disk_number_with_different_card(self):
        with self.assertRaises(RuntimeError):
            self.validate(partition={'ParentWholeDisk': 'disk16', 'VolumeUUID': 'different-card'})

    def test_refuses_wrong_parent_and_unaligned_or_oversized_images(self):
        with self.assertRaises(RuntimeError):
            self.validate(partition={'ParentWholeDisk': 'disk17', 'VolumeUUID': 'owner-confirmed-volume'})
        for size in (0, 513, 128 * 1024**3):
            with self.subTest(size=size), self.assertRaises(RuntimeError):
                self.validate(size=size)

    def test_bad_identifier_never_reaches_diskutil(self):
        for device in ('disk0', '/dev/disk16', 'disk16s1', 'disk16; anything'):
            self.expected['device'] = device
            with patch.object(flash, 'disk_info') as query, self.assertRaises(RuntimeError):
                flash.validate_target(self.expected, 4294967296)
            query.assert_not_called()


if __name__ == '__main__':
    unittest.main()
