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
import stat
import subprocess
import sys
import time

CHUNK = 4 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


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
                    volume_uuid=volume['VolumeUUID'], volume_name=volume.get('VolumeName', ''))
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


def flash(image, expected, manifest):
    require(os.geteuid() == 0, '--write requires administrator privileges')
    device = '/dev/' + expected['device']
    validate_target(expected, manifest['image_bytes'])
    subprocess.run(['/usr/sbin/diskutil', 'unmountDisk', device], check=True)
    raw = validate_target(expected, manifest['image_bytes'])
    with gzip.open(image, 'rb') as source, open(raw, 'r+b', buffering=0) as target:
        require(stat.S_ISCHR(os.fstat(target.fileno()).st_mode), 'Expected a raw disk device')
        written = 0
        digest = hashlib.sha256()
        last = time.monotonic()
        while True:
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
            data = target.read(min(CHUNK, manifest['image_bytes'] - read))
            require(data, 'Unexpected end of card during verification')
            digest.update(data)
            read += len(data)
            last = progress('Readback', read, manifest['image_bytes'], last)
    require(digest.hexdigest() == manifest['image_sha256'], 'Card readback checksum mismatch')
    subprocess.run(['/usr/sbin/diskutil', 'eject', device], check=True)
    return {'device': device, 'card_bytes': expected['TotalSize'], 'image': manifest['image'],
            'written_bytes': written, 'readback_sha256': digest.hexdigest(),
            'readback': 'passed', 'ejected': True, 'hardware_boot_tested': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--inspect', metavar='diskN', help='Record current external-card identity without writing')
    parser.add_argument('--source-only', action='store_true', help='Verify the transfer without accessing a card')
    args = parser.parse_args()
    require(sys.platform == 'darwin', 'This tool is for macOS')
    os.umask(0o077)
    if args.inspect:
        require(not args.write and not args.source_only, '--inspect cannot write or verify an image')
        expected = inspect_target(args.inspect)
        args.target.write_text(json.dumps(expected, indent=2) + '\n')
        print(json.dumps(expected, indent=2), flush=True)
        print('Identity recorded only. Confirm the physical spare before a separate write command.')
        return
    require(args.image is not None and args.manifest is not None, 'Image and transfer manifest required')
    require(not (args.source_only and args.write), '--source-only cannot write')
    manifest = json.loads(args.manifest.read_text())
    verify_source(args.image, manifest)
    if args.source_only:
        return
    expected = json.loads(args.target.read_text())
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
