"""Strict, stdlib-only admission for an inactive development ext4 store package.

This module never mounts, selects, writes a device or reads security xattrs.
The installer owns device identity/exclusion and complete raw readback. Content
checks work from the older recovery kernel; raw pins preserve all filesystem
metadata until the capable kernel can qualify its attributes.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

BOARD = 'gameshellneo-cpi31'
FLAGS = ('next.scr', 'good.scr', 'recover.scr')
DTB = 'sun8i-r16-clockworkpi-cpi3.dtb'
BASE_DTB = 'sun8i-r16-clockworkpi-cpi3-power-off.dtb'
BOOT_ASSETS = {'uImage', DTB, BASE_DTB, 'uInitrd'}
ADMIN_FILES = {'admin/tools/' + name for name in (
    'dev-systems.py', 'dev_systems.py', 'dev_boot_scripts.py', 'usb_poll_boot.py',
    'dev_card.py', 'dev_images.py', 'dev_bundle.py', 'dev_initramfs.py', 'build-dev-initramfs.py')}
ADMIN_FILES |= {'admin/development/initramfs/init',
                'admin/development/multiboot/dependencies.lock.json',
                'admin/build/sources.lock.json', 'admin/loader/uInitrd', 'admin/loader/uInitrd.json'}
JSON_LIMIT = 16 * 1024 * 1024


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('Unexpected development-store schema fields')


def _integer(value, *, minimum=1):
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise ValueError('Invalid bounded development-store integer')
    return value


def _pattern(value, expression, description):
    if not isinstance(value, str) or not re.fullmatch(expression, value):
        raise ValueError('Invalid ' + description)
    return value


def _digest(value):
    return _pattern(value, '[0-9a-f]{64}', 'SHA-256 digest')


def _uuid(value):
    return _pattern(value, '[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', 'filesystem/boot UUID')


def _slot(value):
    _pattern(value, '[a-z][a-z0-9]*(?:-[a-z0-9]+)*', 'development slot')
    if len(value) > 48 or value == 'recovery':
        raise ValueError('Invalid inactive development slot')
    return value


def _relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or
            any(ord(character) < 32 for character in value) or
            value.startswith('/') or any(part in ('', '.', '..') for part in value.split('/')) or
            PurePosixPath(value).as_posix() != value):
        raise ValueError('Unsafe development-store relative path')
    return value


def _basename(value):
    _relative(value)
    if '/' in value:
        raise ValueError('Expected plain development-store artifact filename')
    return value


def _filemap(value):
    if not isinstance(value, dict) or not value or len(value) > 100000:
        raise ValueError('Invalid development-store file hash map')
    for name, digest in value.items():
        _relative(name)
        _digest(digest)
    return value


def _catalog(value, *, empty=False):
    if not isinstance(value, dict) or (empty and value) or (not empty and not value):
        raise ValueError('Invalid registered development catalog')
    for name, entry in value.items():
        _slot(name)
        _keys(entry, ('manifest_sha256',))
        _digest(entry['manifest_sha256'])


def _card(value):
    _keys(value, ('schema', 'board', 'development_only', 'recovery_partuuid',
                  'store_partuuid', 'recovery_boot_files', 'recovery_suspend_diagnostics'))
    if (type(value['schema']) is not int or value['schema'] != 1 or value['board'] != BOARD or
            value['development_only'] is not True or type(value['recovery_suspend_diagnostics']) is not bool):
        raise ValueError('Invalid development-card identity')
    disk = _pattern(value['store_partuuid'], '[0-9a-f]{8}-03', 'store PARTUUID')[:8]
    if value['recovery_partuuid'] != disk + '-02' or disk == '00000000':
        raise ValueError('Development recovery/store identities differ')
    files = _filemap(value['recovery_boot_files'])
    if not {'uImage', DTB} <= files.keys() or files.keys() - {'uImage', DTB, BASE_DTB}:
        raise ValueError('Invalid fixed recovery boot bundle')
    return disk


def _partitions(value, disk, *, filesystems=False):
    _keys(value, ('boot', 'recovery', 'store'))
    previous_end = 0
    for name, suffix in (('boot', '01'), ('recovery', '02'), ('store', '03')):
        part = value[name]
        fields = {'start_sector', 'bytes', 'partuuid'} | ({'filesystem_uuid'} if filesystems else set())
        _keys(part, fields)
        start, size = _integer(part['start_sector']), _integer(part['bytes'])
        if part['partuuid'] != disk + '-' + suffix or size % 512 or start < previous_end:
            raise ValueError('Invalid or overlapping development partition geometry')
        previous_end = start + size // 512
        if filesystems:
            if name == 'boot':
                _pattern(part['filesystem_uuid'], '[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}', 'FAT UUID')
            else:
                _uuid(part['filesystem_uuid'])
    return previous_end * 512


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def validate_manifest(data):
    _keys(data, ('schema', 'operation', 'development_only', 'archive', 'raw', 'source_card',
                 'target', 'card', 'slot', 'original_catalog', 'catalog', 'boot_files', 'store_files'))
    if (type(data['schema']) is not int or data['schema'] != 1 or
            data['operation'] != 'development-store-package' or data['development_only'] is not True):
        raise ValueError('Not a development-store package')
    for name in ('archive', 'raw'):
        value = data[name]
        _keys(value, {'file', 'bytes', 'sha256'} | ({'filesystem_uuid'} if name == 'raw' else set()))
        _basename(value['file'])
        _integer(value['bytes'])
        _digest(value['sha256'])
    if (not data['archive']['file'].endswith('.ext4.gz') or
            data['archive']['file'] != data['raw']['file'] + '.gz' or
            data['raw']['bytes'] % 512):
        raise ValueError('Store package must contain one bounded gzip ext4 image')
    _uuid(data['raw']['filesystem_uuid'])
    source, target = data['source_card'], data['target']
    _keys(source, ('image', 'bytes', 'sha256', 'receipt_sha256'))
    _basename(source['image'])
    _integer(source['bytes'])
    _digest(source['sha256']); _digest(source['receipt_sha256'])
    _keys(target, ('parent_minimum_bytes', 'sector_bytes', 'parent_partuuid_prefix', 'partitions'))
    if target['sector_bytes'] != 512 or type(target['sector_bytes']) is not int:
        raise ValueError('Development store requires 512-byte sectors')
    disk = _card(data['card'])
    if target['parent_partuuid_prefix'] != disk:
        raise ValueError('Package belongs to another card')
    end = _partitions(target['partitions'], disk)
    if (end != _integer(target['parent_minimum_bytes']) or end != source['bytes'] or
            target['partitions']['store']['bytes'] != data['raw']['bytes']):
        raise ValueError('Package raw/card geometry differs')
    slot = data['slot']
    _keys(slot, ('id', 'kernel', 'manifest_sha256', 'source_image_sha256',
                 'source_manifest_sha256', 'source_fstab_sha256', 'deployment_manifest_sha256'))
    name = _slot(slot['id'])
    _pattern(slot['kernel'], '[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}', 'kernel release')
    for key in slot.keys() - {'id', 'kernel'}:
        _digest(slot[key])
    _catalog(data['original_catalog'])
    _catalog(data['catalog'], empty=True)
    if data['original_catalog'] != {name: {'manifest_sha256': slot['manifest_sha256']}}:
        raise ValueError('Expected exactly one complete source-card release')
    boot, store = _filemap(data['boot_files']), _filemap(data['store_files'])
    required_boot = {'DEVBOOT.JSON', 'boot.cmd', 'boot.scr', *FLAGS}
    required_boot |= {'systems/recovery/' + asset for asset in data['card']['recovery_boot_files']}
    if set(boot) != required_boot or any(boot[flag] != boot['recover.scr'] for flag in FLAGS):
        raise ValueError('Expected fixed boot assets and all flags at recovery')
    for asset, digest in data['card']['recovery_boot_files'].items():
        if boot['systems/recovery/' + asset] != digest:
            raise ValueError('Fixed recovery asset pin differs')
    prefix = 'systems/' + name + '/'
    required_store = ADMIN_FILES | {'DEVBOOT.JSON', 'RELEASES.JSON', 'assembly.json'}
    required_store |= {prefix + entry for entry in ('release.json', 'source-image.json', 'source-fstab')}
    required_store |= {prefix + 'boot/' + entry for entry in ('uImage', DTB, 'uInitrd')}
    if not required_store <= store.keys() or any(
            path not in {'DEVBOOT.JSON', 'RELEASES.JSON', 'assembly.json'} and
            not path.startswith(('admin/', prefix)) for path in store):
        raise ValueError('Incomplete or unexpected inactive store input pins')
    if (store['DEVBOOT.JSON'] != boot['DEVBOOT.JSON'] or
            store['DEVBOOT.JSON'] != hashlib.sha256(json_bytes(data['card'])).hexdigest() or
            store['RELEASES.JSON'] != hashlib.sha256(json_bytes({})).hexdigest() or
            store[prefix + 'release.json'] != slot['manifest_sha256']):
        raise ValueError('Inactive store/card/catalog hash differs')
    return data


def validate_backup(data, manifest):
    validate_manifest(manifest)
    _keys(data, ('schema', 'operation', 'development_only', 'verified', 'root', 'parent',
                 'partitions', 'regions', 'card', 'catalog', 'flags', 'store_files', 'evidence'))
    if (type(data['schema']) is not int or data['schema'] != 1 or
            data['operation'] != 'development-store-backup' or
            data['development_only'] is not True or data['verified'] is not True):
        raise ValueError('Expected a fully verified development-store backup')
    disk = _card(data['card'])
    if data['card'] != manifest['card']:
        raise ValueError('Backup and package belong to different cards')
    _keys(data['root'], ('boot_id', 'root_partuuid', 'directory_deployment', 'image_sha256', 'kernel'))
    _uuid(data['root']['boot_id'])
    _digest(data['root']['image_sha256'])
    _pattern(data['root']['kernel'], '[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}', 'recovery kernel release')
    if (data['root']['root_partuuid'] != disk + '-02' or
            data['root']['directory_deployment'] is not False):
        raise ValueError('Backup must originate from fixed recovery')
    parent = data['parent']
    _keys(parent, ('cid', 'bytes', 'sector_bytes', 'partuuid_prefix'))
    _pattern(parent['cid'], '[0-9a-f]{32}', 'SD-card CID')
    if (parent['sector_bytes'] != 512 or type(parent['sector_bytes']) is not int or
            parent['partuuid_prefix'] != disk or
            _integer(parent['bytes']) < manifest['target']['parent_minimum_bytes']):
        raise ValueError('Backup physical parent identity/size differs')
    _partitions(data['partitions'], disk, filesystems=True)
    for name, expected in manifest['target']['partitions'].items():
        if {key: data['partitions'][name][key] for key in expected} != expected:
            raise ValueError('Backup partition geometry differs')
    _keys(data['regions'], ('boot', 'store'))
    for name, region in data['regions'].items():
        _keys(region, ('file', 'partuuid', 'raw_bytes', 'raw_sha256', 'gzip_bytes',
                       'gzip_sha256', 'source_unmounted', 'verified_full_decompressed'))
        _basename(region['file'])
        _digest(region['raw_sha256']); _digest(region['gzip_sha256'])
        _integer(region['gzip_bytes'])
        if (region['raw_bytes'] != data['partitions'][name]['bytes'] or
                type(region['raw_bytes']) is not int or
                region['partuuid'] != data['partitions'][name]['partuuid'] or
                region['source_unmounted'] is not True or region['verified_full_decompressed'] is not True):
            raise ValueError('Backup region was not fully verified while unmounted')
    _catalog(data['catalog'])
    if data['flags'] != {name: manifest['boot_files'][name] for name in FLAGS}:
        raise ValueError('Backup flags are not the fixed recovery descriptors')
    pins = _filemap(data['store_files'])
    required = ADMIN_FILES | {'DEVBOOT.JSON', 'RELEASES.JSON'}
    required |= {'systems/' + name + '/' + item for name in data['catalog']
                 for item in ('release.json', 'source-image.json', 'source-fstab')}
    if not required <= pins.keys():
        raise ValueError('Backup lacks original admin/release/source pins')
    if (pins['DEVBOOT.JSON'] != manifest['boot_files']['DEVBOOT.JSON'] or
            pins['RELEASES.JSON'] != hashlib.sha256(json_bytes(data['catalog'])).hexdigest() or
            any(pins['systems/' + name + '/release.json'] != value['manifest_sha256']
                for name, value in data['catalog'].items())):
        raise ValueError('Backup original catalog pins differ')
    _keys(data['evidence'], ('admission_sha256', 'checkpoint_result_sha256', 'failed_import_sha256'))
    for value in data['evidence'].values():
        _digest(value)
    return data


def child(root, relative):
    path = Path(root)
    if path.is_symlink() or not path.is_dir():
        raise ValueError('Expected an existing real development-store directory')
    for part in _relative(relative).split('/'):
        path /= part
        if path.is_symlink():
            raise ValueError('Development-store path traverses a symlink')
    return path


def read_file(path, limit=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('Expected a regular development-store file')
        data = stream.read() if limit is None else stream.read(limit + 1)
    if limit is not None and len(data) > limit:
        raise ValueError('Development-store metadata exceeds its bound')
    return data


def sha(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('Expected a regular development-store file')
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('Duplicate development-store JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Nonfinite development-store JSON value: ' + value)
    return json.loads(read_file(path, JSON_LIMIT), object_pairs_hook=pairs, parse_constant=constant)


def _verify_files(root, files):
    for relative, expected in files.items():
        if sha(child(root, relative)) != expected:
            raise ValueError('Development-store file content differs: ' + relative)


def verify_boot(boot_path, manifest):
    validate_manifest(manifest)
    boot = Path(boot_path)
    names = [path.name for path in boot.iterdir()]
    for flag in FLAGS:
        if [name for name in names if name.casefold() == flag] != [flag]:
            raise ValueError('Boot flags require unique lowercase entries with mixed FAT presentation')
    _verify_files(boot, manifest['boot_files'])
    if load_json(child(boot, 'DEVBOOT.JSON')) != manifest['card']:
        raise ValueError('Current boot card identity differs')
    return manifest


def verify_store(store_path, manifest):
    validate_manifest(manifest)
    store, slot = Path(store_path), manifest['slot']
    _verify_files(store, manifest['store_files'])
    if (load_json(child(store, 'DEVBOOT.JSON')) != manifest['card'] or
            load_json(child(store, 'RELEASES.JSON')) != {}):
        raise ValueError('Expected the new complete but unregistered store')
    prefix = 'systems/' + slot['id'] + '/'
    release = load_json(child(store, prefix + 'release.json'))
    if (not isinstance(release, dict) or type(release.get('schema')) is not int or release['schema'] != 1 or
            release.get('board') != BOARD or release.get('slot') != slot['id'] or
            release.get('kernel') != slot['kernel'] or
            release.get('store_partuuid') != manifest['card']['store_partuuid']):
        raise ValueError('Inactive release belongs to another slot/card/kernel')
    for key in ('source_image_sha256', 'source_manifest_sha256', 'source_fstab_sha256',
                'deployment_manifest_sha256'):
        if release.get(key) != slot[key]:
            raise ValueError('Inactive release source provenance differs')
    immutable = _filemap(release.get('immutable_files'))
    if not {'etc/gameshellneo/image.json', 'etc/gameshellneo/development-slot'} <= immutable.keys():
        raise ValueError('Inactive release lacks deployment identity pins')
    _verify_files(child(store, prefix + 'root'), immutable)
    assets = _filemap(release.get('boot_files'))
    if not {'uImage', DTB, 'uInitrd'} <= assets.keys() or assets.keys() - BOOT_ASSETS:
        raise ValueError('Inactive release boot assets differ')
    _verify_files(child(store, prefix + 'boot'), assets)
    for filename, key in (('source-image.json', 'source_manifest_sha256'),
                          ('source-fstab', 'source_fstab_sha256'),
                          ('root/etc/gameshellneo/image.json', 'deployment_manifest_sha256')):
        if sha(child(store, prefix + filename)) != slot[key]:
            raise ValueError('Inactive source/deployment metadata hash differs')
    marker = f'schema=1\nid={slot["id"]}\nkernel={slot["kernel"]}\n'.encode()
    if read_file(child(store, prefix + 'root/etc/gameshellneo/development-slot'), 256) != marker:
        raise ValueError('Inactive root marker differs')
    return manifest
