"""Destructive-operation guards; no real disk access."""
import copy
import hashlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

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

    def test_source_only_cannot_reach_a_disk(self):
        with patch.object(flash.sys, 'argv', ['flash-macos.py', '--source-only', '--write',
                                            '--image', 'image.gz', '--manifest', 'transfer.json',
                                            '--target', 'target.json']), \
             patch.object(flash.sys, 'platform', 'darwin'), \
             patch.object(flash, 'disk_info') as query, self.assertRaises(RuntimeError):
            flash.main()
        query.assert_not_called()


class CardComparison(unittest.TestCase):
    def setUp(self):
        progress = patch.object(flash, 'progress', return_value=0)
        progress.start()
        self.addCleanup(progress.stop)

    def test_matching_full_region_and_digest(self):
        data = bytes(range(256)) * 16
        result = flash.compare_streams(io.BytesIO(data), io.BytesIO(data + b'unused card tail'), len(data))
        self.assertTrue(result['matched'])
        self.assertEqual(result['actual_sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(result['different_ranges'], [])

    def test_sector_ranges_merge_across_chunk_boundaries(self):
        data = bytes(4096)
        changed = bytearray(data)
        changed[513] = changed[1034] = changed[3073] = 1
        with patch.object(flash, 'CHUNK', 1024):
            result = flash.compare_streams(io.BytesIO(data), io.BytesIO(changed), len(data))
        self.assertFalse(result['matched'])
        self.assertEqual(result['different_sectors'], 3)
        self.assertEqual(result['different_ranges'], [{'offset': 512, 'bytes': 1024},
                                                       {'offset': 3072, 'bytes': 512}])
        self.assertEqual(result['actual_sha256'], hashlib.sha256(changed).hexdigest())

    def test_difference_report_is_bounded_but_hash_covers_all_data(self):
        data = bytes(4096)
        changed = bytearray(data)
        changed[0] = changed[1024] = changed[2048] = 1
        result = flash.compare_streams(io.BytesIO(data), io.BytesIO(changed), len(data), range_limit=2)
        self.assertEqual(len(result['different_ranges']), 2)
        self.assertTrue(result['ranges_truncated'])
        self.assertEqual(result['different_sectors'], 3)
        self.assertEqual(result['first_difference_sector_start'], 0)
        self.assertEqual(result['last_difference_sector_end'], 2559)
        self.assertEqual(result['actual_sha256'], hashlib.sha256(changed).hexdigest())

    def test_short_card_reads_are_accumulated(self):
        class ShortReads(io.BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 7))
        data = bytes(range(256)) * 4
        self.assertTrue(flash.compare_streams(io.BytesIO(data), ShortReads(data), len(data))['matched'])

    def test_truncated_or_oversized_source_and_short_card_fail(self):
        for source, target in ((bytes(512), bytes(1024)),
                               (bytes(1025), bytes(1024)),
                               (bytes(1024), bytes(512))):
            with self.subTest(source=len(source), target=len(target)):
                with self.assertRaises(RuntimeError):
                    flash.compare_streams(io.BytesIO(source), io.BytesIO(target), 1024)

    def test_compare_cannot_be_combined_with_write_or_source_only(self):
        for flag in ('--write', '--source-only'):
            with patch.object(flash.sys, 'argv', ['flash-macos.py', '--compare-card', flag,
                                                '--image', 'image.gz', '--manifest', 'transfer.json',
                                                '--target', 'target.json']), \
                 patch.object(flash.sys, 'platform', 'darwin'), \
                 patch.object(flash, 'disk_info') as query, self.assertRaises(RuntimeError):
                flash.main()
            query.assert_not_called()


class MountSuppression(unittest.TestCase):
    def setUp(self):
        self.guard = flash.MountGuard('disk16')
        self.guard.process = MagicMock()
        self.guard.process.poll.return_value = None
        self.guard.wait_line = MagicMock()
        runner = patch.object(flash.subprocess, 'run')
        self.run = runner.start()
        self.run.return_value.returncode = 1
        self.addCleanup(runner.stop)
        info = patch.object(flash, 'disk_info', return_value={})
        self.info = info.start()
        self.addCleanup(info.stop)

    def test_requires_actual_matching_veto(self):
        self.guard.verify_veto('disk16s1')
        self.guard.wait_line.assert_called_once_with('BLOCKED disk16s1', 10)
        self.info.assert_called_once_with('disk16s1')

    def test_successful_mount_refuses_to_proceed(self):
        self.run.return_value.returncode = 0
        with self.assertRaises(RuntimeError):
            self.guard.verify_veto('disk16s1')
        self.guard.wait_line.assert_not_called()

    def test_other_mount_failure_is_not_a_guard_pass(self):
        self.guard.wait_line.side_effect = RuntimeError('No actual veto received')
        with self.assertRaises(RuntimeError):
            self.guard.verify_veto('disk16s1')

    def test_dead_guard_refuses_to_proceed(self):
        self.guard.process.poll.return_value = 3
        with self.assertRaises(RuntimeError):
            self.guard.verify_veto('disk16s1')
        self.run.assert_not_called()

    def test_unrelated_partition_is_never_mounted(self):
        with self.assertRaises(RuntimeError):
            self.guard.verify_veto('disk160s1')
        self.run.assert_not_called()

    def test_still_mounted_volume_refuses_to_proceed(self):
        self.info.return_value = {'MountPoint': '/Volumes/armbi_boot'}
        with self.assertRaises(RuntimeError):
            self.guard.verify_veto('disk16s1')


if __name__ == '__main__':
    unittest.main()
