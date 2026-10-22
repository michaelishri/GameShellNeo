"""Import supplied offline image trees as an explicitly different development deployment.

The caller supplies already mounted, read-only root/boot trees and verifies the
raw image digest. This module never mounts, finds devices, or changes its inputs.
Import requires real root privileges. Files retain uid/gid, modes, timestamps,
xattrs/ACLs, symlink text and hardlinks within the root tree; links are never
followed while copying. Device nodes/FIFOs are copied as metadata, never opened.
Sockets and nested filesystems reject. Only the copied fstab/image identity change;
their original bytes are retained alongside release.json. Strict clock/PM image
admission remains separate and must reject this new deployment until qualified.
"""
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import stat
import struct
import tempfile
import zlib


MARKER = Path('etc/gameshellneo/development-slot')
IMAGE = Path('etc/gameshellneo/image.json')
DTB = 'sun8i-r16-clockworkpi-cpi3.dtb'
BASE_DTB = 'sun8i-r16-clockworkpi-cpi3-power-off.dtb'
MAX_KERNEL_EXPANSION = 64 * 1024 * 1024
MAX_INITRAMFS_EXPANSION = 32 * 1024 * 1024


def _sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _directory(value):
    path = Path(value)
    if '..' in path.parts:
        raise ValueError('Directory path contains a parent traversal')
    path = path.absolute()
    for component in (path, *path.parents):
        if component.is_symlink() or not component.is_dir():
            raise ValueError('Expected a real directory: ' + str(component))
    return path


def _regular(root, relative):
    path = root / relative
    _directory(path.parent)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Expected a regular input file: ' + str(path))
    return path


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _metadata(source, target, before):
    os.chown(target, before.st_uid, before.st_gid, follow_symlinks=False)
    if not stat.S_ISLNK(before.st_mode):
        os.chmod(target, stat.S_IMODE(before.st_mode), follow_symlinks=False)
    attrs = {name: os.getxattr(source, name, follow_symlinks=False)
             for name in os.listxattr(source, follow_symlinks=False)}
    for name in os.listxattr(target, follow_symlinks=False):
        if name not in attrs:
            os.removexattr(target, name, follow_symlinks=False)
    for name, value in attrs.items():
        os.setxattr(target, name, value, follow_symlinks=False)
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns), follow_symlinks=False)
    actual = target.lstat()
    fields = ('st_uid', 'st_gid', 'st_mode', 'st_rdev', 'st_mtime_ns')
    if any(getattr(actual, key) != getattr(before, key) for key in fields):
        raise ValueError('Unable to preserve imported metadata: ' + str(source))
    if {name: os.getxattr(target, name, follow_symlinks=False)
            for name in os.listxattr(target, follow_symlinks=False)} != attrs:
        raise ValueError('Unable to preserve imported extended attributes')


def _copy_tree(source, target, device, links):
    before = source.lstat()
    if before.st_dev != device:
        raise ValueError('Nested filesystem in supplied image tree: ' + str(source))
    mode = before.st_mode
    if stat.S_ISDIR(mode):
        target.mkdir(mode=0o700)
        for child in sorted(source.iterdir()):
            _copy_tree(child, target / child.name, device, links)
    elif stat.S_ISLNK(mode):
        target.symlink_to(os.readlink(source))
    elif stat.S_ISREG(mode):
        identity = (before.st_dev, before.st_ino)
        if identity in links:
            os.link(links[identity], target, follow_symlinks=False)
        else:
            fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream, target.open('xb') as out:
                if os.fstat(stream.fileno()) != before:
                    raise ValueError('Source file changed before copying')
                shutil.copyfileobj(stream, out)
            if _sha(source) != _sha(target):
                raise ValueError('Imported file content differs: ' + str(source))
            links[identity] = target
    elif stat.S_ISFIFO(mode):
        os.mkfifo(target, stat.S_IMODE(mode))
    elif stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
        os.mknod(target, mode, before.st_rdev)
    else:
        raise ValueError('Unsupported image file type: ' + str(source))
    after = source.lstat()
    fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if any(getattr(after, key) != getattr(before, key) for key in fields):
        raise ValueError('Source image changed while copying: ' + str(source))
    _metadata(source, target, before)
    if stat.S_ISDIR(mode):
        _sync_directory(target)
    elif stat.S_ISREG(mode):
        with target.open('rb') as stream:
            os.fsync(stream.fileno())


def _write(path, data, template=None):
    """Replace only a private staging file, breaking any imported hardlink."""
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            if template is not None:
                _metadata(template, temporary, template.lstat())
            os.fsync(stream.fileno())
            os.replace(temporary, path)
            _sync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)


def _gzip(data, limit, *, trailing=False):
    try:
        inflater = zlib.decompressobj(31)
        result = inflater.decompress(data, limit + 1)
    except zlib.error as error:
        raise ValueError('Invalid gzip boot payload') from error
    if len(result) > limit or not inflater.eof or (inflater.unused_data and not trailing):
        raise ValueError('Incomplete or oversized gzip boot payload')
    return result


def _kernel_release(payload):
    if len(payload) < 48 or struct.unpack_from('<I', payload, 36)[0] != 0x016f2818:
        raise ValueError('Expected an ARM zImage kernel')
    position = 0
    for _ in range(32):
        position = payload.find(b'\x1f\x8b\x08', position)
        if position < 0:
            break
        try:
            raw = _gzip(payload[position:], MAX_KERNEL_EXPANSION, trailing=True)
        except ValueError:
            position += 1
            continue
        versions = set(re.findall(rb'Linux version ([^\s\0]+) ', raw))
        if len(versions) == 1:
            return versions.pop().decode('ascii')
        position += 1
    raise ValueError('Cannot verify the gzip zImage kernel release')


def _module_release(root, kernel):
    modules = _directory(root / 'usr/lib/modules')
    if {path.name for path in modules.iterdir()} != {kernel}:
        raise ValueError('Installed module release differs from the image kernel')
    directory = _directory(modules / kernel)
    found = 0
    for path in directory.rglob('*'):
        if path.is_symlink():
            raise ValueError('Module paths must not be symlinks')
        if '.ko.' in path.name:
            raise ValueError('Compressed modules are not supported by this importer')
        if path.suffix != '.ko':
            continue
        data = _regular(root, path.relative_to(root)).read_bytes()
        if (len(data) < 20 or data[:6] != b'\x7fELF\x01\x01' or
                struct.unpack_from('<H', data, 18)[0] != 40):
            raise ValueError('Expected an ARM module')
        versions = re.findall(rb'(?:^|\0)vermagic=([^\0]+)\0', data)
        if len(versions) != 1 or versions[0].split()[0] != kernel.encode():
            raise ValueError('Module vermagic differs from the image kernel')
        found += 1
    if not found:
        raise ValueError('Image has no verifiable installed kernel modules')


def _fstab(data):
    result = []
    for line in data.splitlines(keepends=True):
        fields = line.split()
        if fields and not fields[0].startswith(b'#') and len(fields) >= 2:
            point = re.sub(rb'\\([0-7]{3})', lambda match: bytes([int(match[1], 8)]), fields[1])
            point = posixpath.normpath(point).lstrip(b'/')
            if point in (b'', b'boot'):
                continue
        result.append(line)
    return b''.join(result)


def _publish(stage, destination):
    """Linux no-replace rename also rejects a destination created during import."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise OSError(errno.ENOSYS, 'Atomic no-replace publication requires renameat2')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(destination), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))
    _sync_directory(destination.parent)


def inspect_source(source_root, source_boot) -> dict:
    """Read-only admission of an original image's root and boot trees.

    No initramfs or root privileges are required. The returned original identity
    also carries the verified source hashes, boot hashes and diagnostic policy.
    The caller must keep both supplied trees read-only throughout inspection.
    """
    from dev_systems import BOARD, boot_bundle

    source_root, source_boot = _directory(source_root), _directory(source_boot)
    original_image = _regular(source_root, IMAGE).read_bytes()
    original_fstab = _regular(source_root, 'etc/fstab').read_bytes()
    identity = json.loads(original_image)
    if not isinstance(identity, dict):
        raise ValueError('Expected an image identity object')
    kernel = identity.get('kernel')
    if (identity.get('board') != BOARD or identity.get('hardware_qualified') is not False or
            not isinstance(kernel, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}', kernel) or
            'deployment' in identity or (source_root / MARKER).exists() or
            (source_root / MARKER).is_symlink()):
        raise ValueError('Expected an original unqualified CPI image identity')
    sources = identity.get('sources')
    linux = sources.get('linux') if isinstance(sources, dict) else None
    if (not isinstance(linux, dict) or not isinstance(linux.get('tag'), str) or
            not isinstance(linux.get('localversion'), str) or
            linux['tag'].removeprefix('v') + linux['localversion'] != kernel):
        raise ValueError('Image source lock differs from its kernel release')
    experiments = sources.get('experiments', {})
    if not isinstance(experiments, dict) or type(experiments.get('suspend_diagnostics', False)) is not bool:
        raise ValueError('Expected a boolean source suspend diagnostics policy')
    if ('usb_poll_boot' in identity or
            any(name in experiments for name in ('usb_absent_poll', 'usb_diagnostics'))):
        raise ValueError('Legacy USB boot experiments are not supported by development descriptors')
    _module_release(source_root, kernel)
    for name in ('uImage', DTB, BASE_DTB):
        if name == BASE_DTB and not ((source_boot / name).exists() or (source_boot / name).is_symlink()):
            if 'keypad_supply' in identity:
                raise ValueError('Image is missing its original keypad baseline DTB')
            continue
        _regular(source_boot, name)
    boot_files = boot_bundle(source_boot, False)
    kernel_data = (source_boot / 'uImage').read_bytes()
    fields = struct.unpack('>7I4B32s', kernel_data[:64])
    if fields[4:6] != (0x40008000, 0x40008000) or fields[10] != 0:
        raise ValueError('Unexpected kernel load/entry/compression')
    if _kernel_release(kernel_data[64:]) != kernel:
        raise ValueError('Boot kernel differs from the root/modules release')
    if 'keypad_supply' in identity:
        keypad = identity['keypad_supply']
        if (not isinstance(keypad, dict) or boot_files.get(BASE_DTB) != keypad.get('baseline_sha256') or
                boot_files[DTB] != keypad.get('installed_sha256')):
            raise ValueError('Keypad DTBs differ from the source image identity')
    return dict(identity, suspend_diagnostics=experiments.get('suspend_diagnostics', False),
                source_manifest_sha256=hashlib.sha256(original_image).hexdigest(),
                source_fstab_sha256=hashlib.sha256(original_fstab).hexdigest(), boot_files=boot_files)


def import_release(source_root, source_boot, destination, *, slot, source_image_sha256,
                   store_partuuid, initramfs: Path) -> dict:
    """Publish destination/{root,boot,release.json}; the destination must be absent.

    Ownership preservation is mandatory, never a best-effort copy. Caller-held
    read-only image mounts and its catalog lock must remain valid until return.
    """
    # Lazy import lets the catalog call this helper without an import cycle.
    from dev_systems import BOARD, boot_bundle, digest, partuuid, slot_id

    slot_id(slot)
    if slot == 'recovery':
        raise ValueError('The fixed recovery identifier is reserved')
    digest(source_image_sha256)
    partuuid(store_partuuid, '03')
    if os.geteuid() != 0:
        raise PermissionError('Import requires root to preserve all image ownership')
    source_root, source_boot = _directory(source_root), _directory(source_boot)
    destination = Path(destination)
    if '..' in destination.parts or not destination.name:
        raise ValueError('Unsafe import destination')
    destination = _directory(destination.parent) / destination.name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    if any(destination.is_relative_to(path) for path in (source_root, source_boot)):
        raise ValueError('Import destination overlaps its read-only source')
    initramfs = Path(initramfs).absolute()
    _regular(initramfs.parent, initramfs.name)
    inspection = inspect_source(source_root, source_boot)
    original_image = _regular(source_root, IMAGE).read_bytes()
    original_fstab = _regular(source_root, 'etc/fstab').read_bytes()
    if (hashlib.sha256(original_image).hexdigest() != inspection['source_manifest_sha256'] or
            hashlib.sha256(original_fstab).hexdigest() != inspection['source_fstab_sha256']):
        raise ValueError('Source image metadata changed after inspection')
    identity = json.loads(original_image)
    kernel = inspection['kernel']
    stage = Path(tempfile.mkdtemp(prefix='.' + destination.name + '-import-', dir=destination.parent))
    try:
        root, boot = stage / 'root', stage / 'boot'
        _copy_tree(source_root, root, source_root.stat().st_dev, {})
        boot.mkdir()
        for name in ('uImage', DTB, BASE_DTB):
            if name == BASE_DTB and not ((source_boot / name).exists() or (source_boot / name).is_symlink()):
                if 'keypad_supply' in identity:
                    raise ValueError('Image is missing its original keypad baseline DTB')
                continue
            source = _regular(source_boot, name)
            _copy_tree(source, boot / name, source.stat().st_dev, {})
        _copy_tree(initramfs, boot / 'uInitrd', initramfs.stat().st_dev, {})
        boot_files = boot_bundle(boot, True)
        if any(boot_files[name] != value for name, value in inspection['boot_files'].items()):
            raise ValueError('Source boot assets changed after inspection')
        ramdisk = (boot / 'uInitrd').read_bytes()
        if ramdisk[31] not in (0, 1):
            raise ValueError('Unsupported initramfs compression header')
        if not _gzip(ramdisk[64:], MAX_INITRAMFS_EXPANSION).startswith((b'070701', b'070702')):
            raise ValueError('Expected a gzip newc initramfs')
        source_manifest_sha256 = inspection['source_manifest_sha256']
        source_fstab_sha256 = inspection['source_fstab_sha256']
        identity.update(deployment='development-directory', slot=slot,
                        source_image_sha256=source_image_sha256,
                        source_manifest_sha256=source_manifest_sha256,
                        source_fstab_sha256=source_fstab_sha256, root_partuuid=store_partuuid)
        _write(stage / 'source-image.json', original_image)
        _write(stage / 'source-fstab', original_fstab)
        _write(root / 'etc/fstab', _fstab(original_fstab), root / 'etc/fstab')
        _write(root / IMAGE, (json.dumps(identity, indent=2, sort_keys=True) + '\n').encode(), root / IMAGE)
        _write(root / MARKER, f'schema=1\nid={slot}\nkernel={kernel}\n'.encode(), root / IMAGE)
        immutable = {str(path.relative_to(root)): _sha(path) for path in (root / 'usr').rglob('*')
                     if stat.S_ISREG(path.lstat().st_mode)}
        immutable.update({str(path): _sha(root / path) for path in (MARKER, IMAGE)})
        result = dict(schema=1, board=BOARD, slot=slot, kernel=kernel, store_partuuid=store_partuuid,
                      suspend_diagnostics=inspection['suspend_diagnostics'],
                      source_image_sha256=source_image_sha256,
                      source_manifest_sha256=source_manifest_sha256,
                      source_fstab_sha256=source_fstab_sha256,
                      deployment_manifest_sha256=_sha(root / IMAGE),
                      boot_files=boot_files, immutable_files=immutable)
        _write(stage / 'release.json', (json.dumps(result, indent=2, sort_keys=True) + '\n').encode())
        _sync_directory(boot)
        _sync_directory(stage)
        _publish(stage, destination)
        return result
    finally:
        if stage.exists():
            shutil.rmtree(stage)
