#!/usr/bin/env python3
"""Verify, then explicitly write a private image to an identified external card.

Run on macOS. Without --write this only checks the image and disk identity.
The target JSON records a previously inspected disk, partition UUID and size;
it must be prepared after the owner identifies the card to erase.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import select
import stat
import subprocess
import sys
import time

CHUNK = 4 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class MountGuard:
    """Veto mounts of this card until the verified image has been ejected."""
    def __init__(self, disk):
        self.disk, self.process = disk, None

    def __enter__(self):
        source = Path(__file__).with_name('macos-mount-guard.c')
        binary = source.with_suffix('')
        temporary = binary.with_suffix('.part')
        try:
            subprocess.run(['/usr/bin/xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-O2', '-framework', 'DiskArbitration', '-framework', 'CoreFoundation',
                            str(source), '-o', str(temporary)], check=True)
            temporary.replace(binary)
            self.process = subprocess.Popen([str(binary), self.disk], stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE, bufsize=0)
            self.wait_line('READY', 10)
            return self
        except BaseException:
            self.close()
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def check(self):
        require(self.process is not None and self.process.poll() is None,
                'Mount guard exited; refusing to continue card operation')

    def wait_line(self, expected, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.check()
            ready, _, _ = select.select([self.process.stdout], [], [], max(0, deadline - time.monotonic()))
            require(ready, 'Mount guard response timed out')
            line = self.process.stdout.readline(256).decode().strip()
            require(line, 'Mount guard closed its status pipe')
            print('Mount guard: ' + line, flush=True)
            if line == expected:
                return
        raise RuntimeError('Mount guard response timed out')

    def verify_veto(self, partition):
        require(re.fullmatch(re.escape(self.disk) + r's[1-9][0-9]*', partition),
                'Mount check must target a slice of the guarded disk')
        self.check()
        result = subprocess.run(['/usr/sbin/diskutil', 'mount', '/dev/' + partition],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        require(result.returncode != 0, 'Mount suppression failed; no image will be written')
        self.wait_line('BLOCKED ' + partition, 10)
        require(not disk_info(partition).get('MountPoint'), 'Card remounted despite mount guard')
        self.check()

    def close(self):
        if self.process is not None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            self.process.stdout.close()

    def __exit__(self, *_args):
        self.close()


def disk_info(device):
    return plistlib.loads(subprocess.check_output(
        ['/usr/sbin/diskutil', 'info', '-plist', device]))


def inspect_target(device):
    require(re.fullmatch(r'disk[1-9][0-9]*', device), 'Expected a nonzero whole-disk identifier')
    info = disk_info(device)
    listing = plistlib.loads(subprocess.check_output(
        ['/usr/sbin/diskutil', 'list', '-plist', device]))
    volumes = []
    for disk in listing['AllDisksAndPartitions']:
        if disk['DeviceIdentifier'] == device:
            for part in disk.get('Partitions', []):
                details = disk_info(part['DeviceIdentifier'])
                if details.get('VolumeUUID'):
                    volumes.append(details)
    require(volumes, 'A recognizable existing volume UUID is required for target identification')
    volume = volumes[0]
    expected = {key: info[key] for key in ('TotalSize', 'DeviceBlockSize', 'MediaName', 'DeviceTreePath')}
    expected.update(device=device, partition=volume['DeviceIdentifier'],
                    volume_uuid=volume['VolumeUUID'], volume_name=volume.get('VolumeName', ''),
                    mount_details={k: v for k, v in volume.items() if 'mount' in k.lower()})
    if volume.get('MountPoint'):
        mount = Path(volume['MountPoint'])
        expected['macos_metadata'] = {name: (mount / name).exists() for name in
                                     ('.Spotlight-V100', '.fseventsd', '.Trashes')}
    validate_target(expected, info['DeviceBlockSize'])
    return expected


def validate_target(expected, image_bytes):
    disk = expected['device']
    partition = expected['partition']
    require(re.fullmatch(r'disk[1-9][0-9]*', disk), 'Expected a nonzero whole-disk identifier')
    require(re.fullmatch(re.escape(disk) + r's[1-9][0-9]*', partition),
            'Partition does not belong to the recorded disk')
    info = disk_info(disk)
    require(info.get('WholeDisk') is True and info.get('Internal') is False,
            'Refusing anything except an external whole disk')
    require(info.get('VirtualOrPhysical') == 'Physical' and info.get('BusProtocol') == 'USB',
            'Expected the inspected physical USB card reader')
    require(info.get('Writable') is True and info.get('RemovableMediaOrExternalDevice') is True,
            'Card is not writable removable/external media')
    for key in ('TotalSize', 'DeviceBlockSize', 'MediaName', 'DeviceTreePath'):
        require(info.get(key) == expected[key], 'Disk identity changed: ' + key)
    part = disk_info(partition)
    require(part.get('ParentWholeDisk') == disk and
            part.get('VolumeUUID') == expected['volume_uuid'],
            'The inspected volume is no longer on this disk')
    require(info['TotalSize'] >= image_bytes > 0 and image_bytes % info['DeviceBlockSize'] == 0,
            'Image does not fit or is not sector-aligned')
    return '/dev/r' + disk


def digest_stream(stream):
    digest = hashlib.sha256()
    size = 0
    while True:
        data = stream.read(CHUNK)
        if not data:
            break
        digest.update(data)
        size += len(data)
    return digest.hexdigest(), size


def verify_source(image, manifest):
    with image.open('rb') as stream:
        digest, size = digest_stream(stream)
    require((digest, size) == (manifest['compressed_sha256'], manifest['compressed_bytes']),
            'Transferred compressed image checksum/size mismatch')
    with gzip.open(image, 'rb') as stream:
        digest, size = digest_stream(stream)
    require((digest, size) == (manifest['image_sha256'], manifest['image_bytes']),
            'Decompressed image checksum/size mismatch')
    print('Compressed and decompressed image checksums passed.', flush=True)


def progress(phase, size, total, previous):
    now = time.monotonic()
    if now - previous >= 10 or size == total:
        print('{}: {}/{} MiB'.format(phase, size // 1048576, total // 1048576), flush=True)
        return now
    return previous


def compare_streams(source, target, total, sector=512, range_limit=64):
    """Hash the full written region and locate differences without revealing bytes."""
    expected_hash, actual_hash = hashlib.sha256(), hashlib.sha256()
    offset, different_sectors = 0, 0
    ranges = []
    truncated = False
    first_difference = last_difference = None
    last = time.monotonic()
    while offset < total:
        expected = source.read(min(CHUNK, total - offset))
        require(expected, 'Unexpected end of source during comparison')
        actual = bytearray()
        while len(actual) < len(expected):
            block = target.read(len(expected) - len(actual))
            require(block, 'Unexpected end of card during comparison')
            actual.extend(block)
        expected_hash.update(expected)
        actual_hash.update(actual)
        if expected != actual:
            for start in range(0, len(expected), sector):
                end = min(start + sector, len(expected))
                if expected[start:end] == actual[start:end]:
                    continue
                different_sectors += 1
                absolute = offset + start
                if first_difference is None:
                    first_difference = absolute
                last_difference = offset + end - 1
                if ranges and ranges[-1]['offset'] + ranges[-1]['bytes'] == absolute:
                    ranges[-1]['bytes'] += end - start
                elif len(ranges) < range_limit:
                    ranges.append({'offset': absolute, 'bytes': end - start})
                else:
                    truncated = True
        offset += len(expected)
        last = progress('Comparing', offset, total, last)
    require(not source.read(1), 'Source exceeds the recorded image size')
    return {'compared_bytes': offset, 'expected_sha256': expected_hash.hexdigest(),
            'actual_sha256': actual_hash.hexdigest(),
            'different_sectors': different_sectors, 'different_ranges': ranges,
            'first_difference_sector_start': first_difference,
            'last_difference_sector_end': last_difference,
            'ranges_truncated': truncated, 'sector_bytes': sector,
            'matched': different_sectors == 0}


def compare_card(image, expected, manifest):
    raw = validate_target(expected, manifest['image_bytes'])
    before = disk_info(expected['partition'])
    with gzip.open(image, 'rb') as source, open(raw, 'rb', buffering=0) as target:
        require(stat.S_ISCHR(os.fstat(target.fileno()).st_mode), 'Expected a raw disk device')
        result = compare_streams(source, target, manifest['image_bytes'], expected['DeviceBlockSize'])
    require(result['expected_sha256'] == manifest['image_sha256'], 'Source changed during comparison')
    after = disk_info(expected['partition'])
    result.update(device=raw, image=manifest['image'], read_only=True,
                  mount_details_before={k: v for k, v in before.items() if 'mount' in k.lower()},
                  mount_details_after={k: v for k, v in after.items() if 'mount' in k.lower()})
    return result


def flash(image, expected, manifest):
    require(os.geteuid() == 0, '--write requires administrator privileges')
    validate_target(expected, manifest['image_bytes'])
    with MountGuard(expected['device']) as guard:
        return guarded_flash(image, expected, manifest, guard)


def guarded_flash(image, expected, manifest, guard):
    device = '/dev/' + expected['device']
    validate_target(expected, manifest['image_bytes'])
    subprocess.run(['/usr/sbin/diskutil', 'unmountDisk', device], check=True)
    guard.verify_veto(expected['partition'])
    raw = validate_target(expected, manifest['image_bytes'])
    with gzip.open(image, 'rb') as source, open(raw, 'r+b', buffering=0) as target:
        require(stat.S_ISCHR(os.fstat(target.fileno()).st_mode), 'Expected a raw disk device')
        written = 0
        digest = hashlib.sha256()
        last = time.monotonic()
        while True:
            guard.check()
            data = source.read(CHUNK)
            if not data:
                break
            require(written + len(data) <= manifest['image_bytes'], 'Source grew after validation')
            remaining = memoryview(data)
            while remaining:
                count = target.write(remaining)
                require(count is not None and count > 0, 'Short/failed disk write')
                remaining = remaining[count:]
            digest.update(data)
            written += len(data)
            last = progress('Writing', written, manifest['image_bytes'], last)
        require((digest.hexdigest(), written) == (manifest['image_sha256'], manifest['image_bytes']),
                'Source changed while writing')
        os.fsync(target.fileno())
    subprocess.run(['/bin/sync'], check=True)
    digest = hashlib.sha256()
    read = 0
    last = time.monotonic()
    with open(raw, 'rb', buffering=0) as target:
        while read < manifest['image_bytes']:
            guard.check()
            data = target.read(min(CHUNK, manifest['image_bytes'] - read))
            require(data, 'Unexpected end of card during verification')
            digest.update(data)
            read += len(data)
            last = progress('Readback', read, manifest['image_bytes'], last)
    require(digest.hexdigest() == manifest['image_sha256'],
            'Card readback checksum mismatch: actual={} expected={}'.format(
                digest.hexdigest(), manifest['image_sha256']))
    subprocess.run(['/usr/sbin/diskutil', 'eject', device], check=True)
    guard.check()
    return {'device': device, 'card_bytes': expected['TotalSize'], 'image': manifest['image'],
            'written_bytes': written, 'readback_sha256': digest.hexdigest(),
            'readback': 'passed', 'ejected': True, 'hardware_boot_tested': False,
            'mount_guard_verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--inspect', metavar='diskN', help='Record current external-card identity without writing')
    parser.add_argument('--source-only', action='store_true', help='Verify the transfer without accessing a card')
    parser.add_argument('--compare-card', action='store_true',
                        help='Read-only hash/sector comparison against a freshly inspected card')
    args = parser.parse_args()
    require(sys.platform == 'darwin', 'This tool is for macOS')
    os.umask(0o077)
    if args.inspect:
        require(not args.write and not args.source_only and not args.compare_card,
                '--inspect cannot write or verify an image')
        expected = inspect_target(args.inspect)
        args.target.write_text(json.dumps(expected, indent=2) + '\n')
        print(json.dumps(expected, indent=2), flush=True)
        print('Identity recorded only. Confirm the physical spare before a separate write command.')
        return
    require(args.image is not None and args.manifest is not None, 'Image and transfer manifest required')
    require(sum((args.source_only, args.write, args.compare_card)) <= 1,
            'Select only one of --source-only, --write or --compare-card')
    manifest = json.loads(args.manifest.read_text())
    verify_source(args.image, manifest)
    if args.source_only:
        return
    expected = json.loads(args.target.read_text())
    if args.compare_card:
        require(args.report is not None, '--compare-card requires a report destination')
        report = compare_card(args.image, expected, manifest)
        args.report.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)
        require(report['matched'], 'Card differs from image; comparison report retained')
        return
    raw = validate_target(expected, manifest['image_bytes'])
    print('Verified target: {} ({} bytes)'.format(raw, expected['TotalSize']), flush=True)
    if not args.write:
        print('Preflight complete; no disk was written.', flush=True)
        return
    require(args.report is not None, '--write requires a report destination')
    report = flash(args.image, expected, manifest)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
