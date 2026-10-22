"""Development-card catalog and explicit, non-rebooting system selection."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
import zlib

from dev_boot_scripts import dispatcher, release_script, script_image
from usb_poll_boot import script_source

BOARD = 'gameshellneo-cpi31'
CARD_FILE = 'DEVBOOT.JSON'
RELEASES_FILE = 'RELEASES.JSON'
SLOT_PATTERN = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z')
BOOT_LIMITS = {'uImage': 0x1000000,
               'sun8i-r16-clockworkpi-cpi3.dtb': 0x100000,
               'uInitrd': 0x1000000,
               'sun8i-r16-clockworkpi-cpi3-power-off.dtb': 0x100000}
BOOT_FILES = ('uImage', 'sun8i-r16-clockworkpi-cpi3.dtb', 'uInitrd')
OPTIONAL_DTB = 'sun8i-r16-clockworkpi-cpi3-power-off.dtb'


def slot_id(value):
    if not isinstance(value, str) or len(value) > 48 or not SLOT_PATTERN.fullmatch(value):
        raise ValueError('Invalid development system identifier')
    return value


def partuuid(value, partition):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{8}-' + partition, value):
        raise ValueError('Unexpected development-card partition identity')
    return value


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Expected a SHA-256 digest')
    return value


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular file: ' + str(path))
    return path


def child(root, relative):
    """Manifest paths cannot escape the store or traverse host-side symlinks."""
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(p in ('.', '..') for p in path.parts):
        raise ValueError('Unsafe development manifest path')
    target = root
    for component in path.parts:
        target /= component
        if target.is_symlink():
            raise ValueError('Manifest path traverses a symlink: ' + str(path))
    return target


def atomic_write(path, data):
    """Durable file replacement; this makes no FAT power-loss atomicity claim."""
    if path.is_symlink():
        raise ValueError('Refusing to replace a symlink')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.devboot-', dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        if regular(path).read_bytes() != data:
            raise ValueError('Development boot-state readback differs')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def boot_bundle(directory, include_initrd):
    names = list(BOOT_FILES) if include_initrd else list(BOOT_FILES)[:2]
    if (directory / OPTIONAL_DTB).exists() or (directory / OPTIONAL_DTB).is_symlink():
        names.append(OPTIONAL_DTB)
    hashes = {}
    for name in names:
        path = regular(directory / name)
        data = path.read_bytes()
        if not 0 < len(data) < BOOT_LIMITS[name]:
            raise ValueError('Boot asset exceeds its reserved RAM window: ' + name)
        if name.endswith('.dtb'):
            if len(data) < 40 or struct.unpack('>I', data[:4])[0] != 0xd00dfeed:
                raise ValueError('Invalid device tree header')
            if struct.unpack('>I', data[4:8])[0] != len(data):
                raise ValueError('Device tree length differs from its header')
        else:
            if len(data) < 64:
                raise ValueError('Truncated U-Boot image')
            fields = struct.unpack('>7I4B32s', data[:64])
            header = bytearray(data[:64])
            header[4:8] = b'\0' * 4
            kind = 2 if name == 'uImage' else 3
            if (fields[0] != 0x27051956 or zlib.crc32(header) != fields[1] or
                    fields[3] != len(data) - 64 or zlib.crc32(data[64:]) != fields[6] or
                    fields[7:10] != (5, 2, kind)):
                raise ValueError('Invalid ARM Linux boot image: ' + name)
        hashes[name] = sha(path)
    return hashes


class Card:
    """Both paths must refer to the prepared development card, never an image OS."""

    def __init__(self, boot, store, *, _initializing=False):
        self.boot, self.store = Path(boot), Path(store)
        if self.boot.is_symlink() or self.store.is_symlink():
            raise ValueError('Development mount paths must not be symlinks')
        self.record = json.loads(regular(self.boot / CARD_FILE).read_text())
        if (self.record.get('schema') != 1 or self.record.get('board') != BOARD or
                self.record.get('development_only') is not True):
            raise ValueError('This is not a prepared development card')
        disk = partuuid(self.record['store_partuuid'], '03')[:8]
        if partuuid(self.record['recovery_partuuid'], '02')[:8] != disk:
            raise ValueError('Recovery and system store belong to different cards')
        if json.loads(regular(self.store / CARD_FILE).read_text()) != self.record:
            raise ValueError('Boot partition and system store identities differ')
        self.releases = json.loads(regular(self.store / RELEASES_FILE).read_text())
        if not isinstance(self.releases, dict):
            raise ValueError('Invalid development release catalog')
        expected_recovery = script_image(release_script('recovery',
            self.record['recovery_partuuid'], directory=False,
            suspend_diagnostics=self.record['recovery_suspend_diagnostics']))
        if ((not _initializing and
             regular(self.boot / 'boot.scr').read_bytes() != script_image(dispatcher())) or
                regular(self.boot / 'RECOVER.SCR').read_bytes() != expected_recovery or
                boot_bundle(child(self.boot, 'systems/recovery'), False) != self.record['recovery_boot_files']):
            raise ValueError('Fixed development/recovery boot files changed')

    def lock(self):
        path = self.store / '.selection.lock'
        if path.is_symlink():
            raise ValueError('Invalid selection lock')
        stream = path.open('a')
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Another selector may have published a version after this object
            # was constructed. Read the catalog while owning the writer lock.
            self.releases = json.loads(regular(self.store / RELEASES_FILE).read_text())
            if not isinstance(self.releases, dict):
                raise ValueError('Invalid development release catalog')
        except BaseException:
            stream.close()
            raise
        return stream

    def verify(self, name):
        slot_id(name)
        expected = digest(self.releases[name]['manifest_sha256'])
        directory = child(self.store, 'systems/' + name)
        path = regular(directory / 'release.json')
        if sha(path) != expected:
            raise ValueError('Development release manifest changed')
        release = json.loads(path.read_text())
        if (release.get('schema') != 1 or release.get('board') != BOARD or
                release.get('slot') != name or release.get('store_partuuid') != self.record['store_partuuid']):
            raise ValueError('Release belongs to another development slot/card')
        files = boot_bundle(child(self.boot, 'systems/' + name), True)
        if files != release['boot_files']:
            raise ValueError('Release kernel/DTB/initramfs changed')
        root = child(directory, 'root')
        if not root.is_dir():
            raise ValueError('Development root is absent')
        for relative, expected in release['immutable_files'].items():
            if sha(regular(child(root, relative))) != digest(expected):
                raise ValueError('Development system input changed: ' + relative)
        marker = f'schema=1\nid={name}\nkernel={release["kernel"]}\n'.encode()
        if regular(root / 'etc/gameshellneo/development-slot').read_bytes() != marker:
            raise ValueError('Development root marker differs from its catalog')
        return release

    def descriptor(self, name):
        release = self.verify(name)
        return script_image(release_script(name, self.record['store_partuuid'],
            directory=True, suspend_diagnostics=release.get('suspend_diagnostics', False)))

    def register(self, name):
        """Publish an imported, inactive release without changing any boot selection."""
        slot_id(name)
        if name == 'recovery':
            raise ValueError('The fixed recovery identifier is reserved')
        with self.lock():
            if name in self.releases:
                raise ValueError('System identifiers are immutable; import a new version')
            directory = child(self.store, 'systems/' + name)
            manifest = regular(directory / 'release.json')
            release = json.loads(manifest.read_text())
            if (release.get('slot') != name or release.get('store_partuuid') != self.record['store_partuuid']):
                raise ValueError('Imported release belongs to another system/card')
            source = child(directory, 'boot')
            files = boot_bundle(source, True)
            if files != release['boot_files']:
                raise ValueError('Imported boot bundle differs from its manifest')
            target = child(self.boot, 'systems/' + name)
            if target.exists():
                if boot_bundle(target, True) != files:
                    raise ValueError('A different orphaned boot bundle already uses this name')
            else:
                temporary = Path(tempfile.mkdtemp(prefix='.dev-system-', dir=self.boot / 'systems'))
                try:
                    for filename in files:
                        atomic_write(temporary / filename, regular(source / filename).read_bytes())
                    temporary.rename(target)
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
            updated = dict(self.releases)
            updated[name] = {'manifest_sha256': sha(manifest)}
            self.releases = updated
            self.verify(name)
            atomic_write(self.store / RELEASES_FILE, json_bytes(updated))
        return {'registered': name, 'boot_selection_changed': False, 'reboot_performed': False}

    def select(self, name):
        with self.lock():
            data = self.descriptor(name)
            atomic_write(self.boot / 'NEXT.SCR', data)
        return {'next': name, 'trial': True, 'reboot_performed': False,
                'fallback': 'last confirmed descriptor, then fixed recovery'}

    def select_recovery(self):
        with self.lock():
            data = regular(self.boot / 'RECOVER.SCR').read_bytes()
            script_source(data)
            atomic_write(self.boot / 'NEXT.SCR', data)
        return {'next': 'recovery', 'reboot_performed': False}

    def confirm(self, name, *, running_root=Path('/'), runtime_record=Path('/run/gameshellneo-development-slot')):
        """Only the running release can become the default; selection alone is no health proof."""
        with self.lock():
            release = self.verify(name)
            expected = f'schema=1\nid={name}\nkernel={release["kernel"]}\n'.encode()
            if regular(runtime_record).read_bytes() != expected or os.uname().release != release['kernel']:
                raise ValueError('Running kernel/early-userspace identity differs')
            actual = running_root.stat()
            wanted = child(self.store, 'systems/' + name + '/root').stat()
            if (actual.st_dev, actual.st_ino) != (wanted.st_dev, wanted.st_ino):
                raise ValueError('The requested system is not the running root')
            data = self.descriptor(name)
            # A failed second write still leaves two valid complete descriptors.
            atomic_write(self.boot / 'GOOD.SCR', data)
            atomic_write(self.boot / 'NEXT.SCR', data)
        return {'confirmed': name, 'reboot_performed': False,
                'health_qualification': 'explicit operator confirmation; no PM/energy claim'}

    def status(self):
        result = {'development_only': True, 'recovery_partuuid': self.record['recovery_partuuid'],
                  'store_partuuid': self.record['store_partuuid'], 'systems': {},
                  'reboot_performed': False}
        for name in sorted(self.releases):
            release = self.verify(name)
            result['systems'][name] = {'kernel': release['kernel'],
                'source_image_sha256': release['source_image_sha256']}
        next_boot = regular(self.boot / 'NEXT.SCR').read_bytes()
        good = regular(self.boot / 'GOOD.SCR').read_bytes()
        script_source(next_boot)
        script_source(good)
        result['trial_pending'] = next_boot != good
        descriptors = {'recovery': regular(self.boot / 'RECOVER.SCR').read_bytes()}
        descriptors.update({name: self.descriptor(name) for name in self.releases})
        result['next_system'] = next((name for name, data in descriptors.items() if data == next_boot), None)
        result['confirmed_system'] = next((name for name, data in descriptors.items() if data == good), None)
        if result['next_system'] is None or result['confirmed_system'] is None:
            raise ValueError('Boot state refers to no verified complete system')
        return result


def initialize(boot, store, *, recovery_partuuid, recovery_boot, releases,
               recovery_suspend_diagnostics=False):
    """Prepare mounted OFFLINE image filesystems; this function never finds a disk or reboots."""
    boot, store, recovery_boot = Path(boot), Path(store), Path(recovery_boot)
    disk = partuuid(recovery_partuuid, '02')[:8]
    releases = list(releases)
    if type(recovery_suspend_diagnostics) is not bool:
        raise ValueError('Recovery policy must be explicit')
    if (boot / CARD_FILE).exists() or (store / CARD_FILE).exists():
        raise ValueError('Development catalog already exists')
    recovery_hashes = boot_bundle(recovery_boot, False)
    destination = boot / 'systems/recovery'
    destination.mkdir(parents=True, exist_ok=False)
    for name in recovery_hashes:
        shutil.copyfile(regular(recovery_boot / name), destination / name)
    record = {'schema': 1, 'board': BOARD, 'development_only': True,
              'recovery_partuuid': recovery_partuuid, 'store_partuuid': disk + '-03',
              'recovery_boot_files': recovery_hashes,
              'recovery_suspend_diagnostics': recovery_suspend_diagnostics}
    catalog = {}
    for name in releases:
        slot_id(name)
        if name == 'recovery':
            raise ValueError('The fixed recovery identifier is reserved')
        directory = child(store, 'systems/' + name)
        manifest = regular(directory / 'release.json')
        source = directory / 'boot'
        target = boot / 'systems' / name
        target.mkdir(parents=True, exist_ok=False)
        for filename in boot_bundle(source, True):
            shutil.copyfile(regular(source / filename), target / filename)
        catalog[name] = {'manifest_sha256': sha(manifest)}
    data = json_bytes(record)
    atomic_write(store / CARD_FILE, data)
    atomic_write(boot / CARD_FILE, data)
    atomic_write(store / RELEASES_FILE, json_bytes(catalog))
    recovery = script_image(release_script('recovery', recovery_partuuid, directory=False,
        suspend_diagnostics=recovery_suspend_diagnostics))
    for name in ('RECOVER.SCR', 'GOOD.SCR', 'NEXT.SCR'):
        atomic_write(boot / name, recovery)
    card = Card(boot, store, _initializing=True)
    for name in releases:
        card.verify(name)
    # The existing executable remains selected until all referenced files verify.
    atomic_write(boot / 'boot.cmd', dispatcher())
    atomic_write(boot / 'boot.scr', script_image(dispatcher()))
    return record
