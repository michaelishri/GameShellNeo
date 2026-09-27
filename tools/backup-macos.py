#!/usr/bin/env python3
"""Read a complete external USB card into a verified, private recovery archive."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time

CHUNK = 4 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(disk):
    require(re.fullmatch(r'disk[1-9][0-9]*', disk), 'Expected a nonzero whole-disk identifier')
    info = plistlib.loads(subprocess.check_output(
        ['/usr/sbin/diskutil', 'info', '-plist', disk]))
    require(info.get('WholeDisk') is True and info.get('Internal') is False and
            info.get('VirtualOrPhysical') == 'Physical' and info.get('BusProtocol') == 'USB' and
            info.get('RemovableMediaOrExternalDevice') is True,
            'Backup requires an external physical USB whole disk')
    result = {key: info[key] for key in ('TotalSize', 'DeviceBlockSize', 'MediaName', 'DeviceTreePath')}
    require(result['TotalSize'] > 0 and result['DeviceBlockSize'] > 0 and
            result['TotalSize'] % result['DeviceBlockSize'] == 0, 'Invalid card size')
    listing = plistlib.loads(subprocess.check_output(
        ['/usr/sbin/diskutil', 'list', '-plist', disk]))
    entry = next(item for item in listing['AllDisksAndPartitions'] if item['DeviceIdentifier'] == disk)
    # macOS cannot supply filesystem UUIDs for the original Linux filesystems.
    # Record partition geometry/types; this record cannot authorize a flash.
    result.update(device=disk, content=entry.get('Content', ''), partitions=[
        {key: part[key] for key in ('DeviceIdentifier', 'Content', 'Size', 'PartitionMapPartitionOffset',
                                   'DiskUUID', 'VolumeUUID') if key in part}
        for part in entry.get('Partitions', [])])
    return result


def read_card(raw, size, output):
    digest = hashlib.sha256()
    count = 0
    last = time.monotonic()
    # This helper never opens a device for writing.
    with open(raw, 'rb', buffering=0) as source:
        require(stat.S_ISCHR(os.fstat(source.fileno()).st_mode), 'Expected a raw disk device')
        while count < size:
            data = source.read(min(CHUNK, size - count))
            require(data, 'Unexpected end of card during backup')
            output.write(data)
            digest.update(data)
            count += len(data)
            now = time.monotonic()
            if now - last >= 10 or count == size:
                print('Backing up: {}/{} MiB'.format(count // 1048576, size // 1048576), flush=True)
                last = now
    return digest.hexdigest()


def digest_file(path, compressed=False):
    digest = hashlib.sha256()
    count = 0
    with (gzip.open(path, 'rb') if compressed else path.open('rb')) as stream:
        while True:
            data = stream.read(CHUNK)
            if not data:
                break
            digest.update(data)
            count += len(data)
    return digest.hexdigest(), count


def backup(disk, destination):
    require(os.geteuid() == 0, 'Raw-card backup requires administrator privileges')
    expected = identity(disk)
    require(destination.name.endswith('.img.gz'), 'Backup destination must end in .img.gz')
    require(not destination.exists() and not destination.is_symlink(), 'Backup destination already exists')
    require(shutil.disk_usage(destination.parent).free > expected['TotalSize'] + 1024**3,
            'Not enough free space for a worst-case whole-card archive plus 1 GiB')
    print(json.dumps(expected, indent=2), flush=True)
    device = '/dev/' + disk
    subprocess.run(['/usr/sbin/diskutil', 'unmountDisk', device], check=True)
    require(identity(disk) == expected, 'Card identity changed before backup')
    partial = destination.with_name(destination.name + '.part')
    # Exclusive creation protects earlier backups and rejects symlinks.
    with partial.open('xb') as archive:
        with gzip.GzipFile(filename='', fileobj=archive, mode='wb', compresslevel=1, mtime=0) as output:
            raw_digest = read_card('/dev/r' + disk, expected['TotalSize'], output)
        archive.flush()
        os.fsync(archive.fileno())
    print('Verifying the complete decompressed archive...', flush=True)
    require(digest_file(partial, compressed=True) == (raw_digest, expected['TotalSize']),
            'Backup archive does not match the bytes read from the card')
    require(identity(disk) == expected, 'Card identity changed during backup')
    compressed_digest, compressed_size = digest_file(partial)
    # A hard link publishes without replacing a file created since the initial check.
    os.link(partial, destination)
    partial.unlink()
    # Let the originating account download its own private archive over SFTP.
    if 'SUDO_UID' in os.environ and 'SUDO_GID' in os.environ:
        os.chown(destination, int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID']))
    subprocess.run(['/usr/sbin/diskutil', 'eject', device], check=True)
    return {'card': expected, 'archive': str(destination), 'image_bytes': expected['TotalSize'],
            'image_sha256': raw_digest, 'compressed_bytes': compressed_size,
            'compressed_sha256': compressed_digest, 'archive_verification': 'passed',
            'card_written': False, 'ejected': True, 'restore_boot_tested': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disk', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    require(sys.platform == 'darwin', 'This tool is for macOS')
    os.umask(0o077)
    require(not args.report.exists() and not args.report.is_symlink(), 'Report already exists')
    report = backup(args.disk, args.output)
    with args.report.open('x') as output:
        output.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
