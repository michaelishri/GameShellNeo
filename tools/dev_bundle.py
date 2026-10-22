"""Transfer inactive development roots without requiring on-device loop devices.

Only this module's plain GNU pax archives are supported. Archive metadata is
validated before privileged extraction; root-tree symlinks retain their text,
but no archive member can be extracted through one. Publication never selects
or confirms a system. Failed private snapshots, staging trees and logs remain
beside the destination for diagnosis.
"""
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import tempfile

from dev_images import _directory, _publish, _sync_directory
from dev_systems import BOARD, BOOT_LIMITS, digest, partuuid, slot_id

CONTENTS = {'root', 'boot', 'release.json', 'source-image.json', 'source-fstab'}
TYPES = {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.SYMTYPE,
         tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE}
PAX_KEYS = {'path', 'linkpath', 'size', 'uid', 'gid', 'uname', 'gname',
            'mtime', 'atime', 'ctime', 'hdrcharset',
            'SCHILY.acl.access', 'SCHILY.acl.default'}
METADATA_LIMIT = 16 * 1024 * 1024
PAX_LIMIT = 1024 * 1024


def _open_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOATIME)
    # GNU tar inherits this descriptor, so Python read-ahead must not make the
    # descriptor's real offset differ from stream.seek(0)'s logical offset.
    stream = os.fdopen(fd, 'rb', buffering=0)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        stream.close()
        raise ValueError('Expected a regular bundle file')
    return stream


def _hash(path):
    with _open_regular(path) as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _read(path):
    with _open_regular(path) as stream:
        data = stream.read(METADATA_LIMIT + 1)
    if len(data) > METADATA_LIMIT:
        raise ValueError('Development bundle metadata exceeds its bound')
    return data


def _metadata(directory, name, store=None):
    if {path.name for path in directory.iterdir()} != CONTENTS:
        raise ValueError('Expected one complete imported development version')
    for item in ('root', 'boot'):
        _directory(directory / item)
    raw = _read(directory / 'release.json')
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or manifest.get('schema') != 1 or
            manifest.get('board') != BOARD or manifest.get('slot') != name or
            not isinstance(manifest.get('kernel'), str) or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]{0,127}', manifest['kernel']) or
            not isinstance(manifest.get('boot_files'), dict) or
            not isinstance(manifest.get('immutable_files'), dict)):
        raise ValueError('Invalid imported development manifest')
    if (not {'uImage', 'uInitrd', 'sun8i-r16-clockworkpi-cpi3.dtb'} <= manifest['boot_files'].keys() or
            manifest['boot_files'].keys() - BOOT_LIMITS.keys() or
            not {'etc/gameshellneo/development-slot', 'etc/gameshellneo/image.json'} <= manifest['immutable_files'].keys()):
        raise ValueError('Incomplete development boot/immutable manifest')
    for value in manifest['boot_files'].values():
        digest(value)
    for relative, value in manifest['immutable_files'].items():
        _path(relative)
        digest(value)
    actual_store = partuuid(manifest.get('store_partuuid'), '03')
    if store is not None and actual_store != store:
        raise ValueError('Development bundle belongs to another card store')
    for field in ('source_image_sha256', 'source_manifest_sha256', 'source_fstab_sha256',
                  'deployment_manifest_sha256'):
        digest(manifest.get(field))
    for filename, field in (('source-image.json', 'source_manifest_sha256'),
                            ('source-fstab', 'source_fstab_sha256')):
        if hashlib.sha256(_read(directory / filename)).hexdigest() != manifest[field]:
            raise ValueError('Development source metadata differs from its manifest')
    return manifest, hashlib.sha256(raw).hexdigest()


def _path(name):
    if not isinstance(name, str) or not name or '\0' in name or name.startswith('/'):
        raise ValueError('Unsafe bundle member path')
    parts = tuple(name.rstrip('/').split('/'))
    if any(part in ('', '.', '..') for part in parts):
        raise ValueError('Traversing or noncanonical bundle member path')
    return parts


def _pax(data):
    """Reject ambiguous/unsupported extended records before either TAR parser runs."""
    values = {}
    position = 0
    while position < len(data):
        space = data.find(b' ', position)
        number = data[position:space] if space >= 0 else b''
        if not re.fullmatch(rb'[1-9][0-9]*', number):
            raise ValueError('Malformed pax record length')
        end = position + int(number)
        if end > len(data) or end <= space + 1 or data[end - 1:end] != b'\n':
            raise ValueError('Truncated pax record')
        key, separator, value = data[space + 1:end - 1].partition(b'=')
        key = key.decode('ascii')
        if (not separator or key in values or
                (key not in PAX_KEYS and not key.startswith('SCHILY.xattr.'))):
            raise ValueError('Duplicate or unsupported pax keyword')
        if key in ('size', 'uid', 'gid') and not re.fullmatch(rb'0|[1-9][0-9]*', value):
            raise ValueError('Noncanonical pax numeric value')
        if key == 'hdrcharset' and value != b'BINARY':
            raise ValueError('Unsupported pax character encoding')
        values[key] = value
        position = end
    return values


def _raw_headers(stream):
    """Require ordinary headers, one local pax record, and a clean TAR ending.

    GNU sparse/global/long-name extensions could make GNU and Python interpret
    names or sizes differently. GNU --format=pax does not need those extensions.
    """
    pending = None
    while True:
        block = stream.read(512)
        if len(block) != 512:
            raise ValueError('Truncated bundle TAR header')
        if block == bytes(512):
            if pending is not None or stream.read(512) != bytes(512):
                raise ValueError('Incomplete bundle TAR ending')
            while chunk := stream.read(1024 * 1024):
                if chunk.strip(b'\0'):
                    raise ValueError('Data follows the bundle TAR ending')
            return
        header = tarfile.TarInfo.frombuf(block, 'utf-8', 'surrogateescape')
        if header.type == tarfile.XHDTYPE:
            if pending is not None or not 0 < header.size <= PAX_LIMIT:
                raise ValueError('Unsupported stacked or oversized pax header')
            data = stream.read((header.size + 511) // 512 * 512)
            if len(data) < header.size:
                raise ValueError('Truncated pax header')
            pending = _pax(data[:header.size])
            continue
        if header.type not in TYPES:
            raise ValueError('Unsupported bundle TAR member type')
        size = int(pending.get('size', header.size)) if pending else header.size
        if size < 0 or (not header.isreg() and size):
            raise ValueError('Invalid bundle TAR member size')
        stream.seek((size + 511) // 512 * 512, os.SEEK_CUR)
        pending = None


def _members(stream, name):
    stream.seek(0)
    _raw_headers(stream)
    stream.seek(0)
    with tarfile.open(fileobj=stream, mode='r:') as archive:
        members = {}
        for member in archive:
            path = _path(member.name)
            if path[0] != name or path in members or member.type not in TYPES:
                raise ValueError('Wrong version, duplicate or unsupported bundle member')
            if len(path) == 1:
                if not member.isdir():
                    raise ValueError('Bundle prefix must be a directory')
            elif path[1] not in CONTENTS or (len(path) > 2 and path[1] not in ('root', 'boot')):
                raise ValueError('Unexpected version bundle content')
            if len(path) == 2:
                if (path[1] in ('root', 'boot') and not member.isdir() or
                        path[1] not in ('root', 'boot') and not member.isreg()):
                    raise ValueError('Invalid version bundle structure')
            if len(path) > 2 and path[1] == 'boot':
                if len(path) != 3 or path[2] not in BOOT_LIMITS or not member.isreg():
                    raise ValueError('Unexpected development boot asset')
            if member.issym() and (not member.linkname or '\0' in member.linkname or path[1] != 'root'):
                raise ValueError('Invalid root symlink target')
            if member.islnk():
                target = _path(member.linkname)
                if target[0] != name:
                    raise ValueError('Bundle hardlink escapes its version')
            if not 0 <= member.uid < 0xffffffff or not 0 <= member.gid < 0xffffffff:
                raise ValueError('Unsupported bundle ownership')
            members[path] = member
    for path, member in members.items():
        for length in range(1, len(path)):
            ancestor = members.get(path[:length])
            if ancestor is None or not ancestor.isdir():
                raise ValueError('Bundle member traverses a missing/non-directory ancestor')
        if member.islnk():
            target = members.get(_path(member.linkname))
            if target is None or not target.isreg():
                raise ValueError('Bundle hardlink must target a regular version member')
    if any((name, item) not in members for item in CONTENTS):
        raise ValueError('Incomplete development version bundle')
    return members


def _execute(arguments, log, *, stdin=None, stdout=None):
    environment = dict(os.environ, LC_ALL='C')
    environment.pop('TAR_OPTIONS', None)
    log.write((json.dumps(arguments) + '\n').encode())
    log.flush()
    subprocess.run(arguments, stdin=stdin, stdout=stdout or log, stderr=log,
                   env=environment, check=True)


def _probe_capabilities(operation, members):
    """Check the destination kernel/filesystem before extracting capability xattrs."""
    key = 'SCHILY.xattr.security.capability'
    required = {member.pax_headers[key].encode('utf-8', 'surrogateescape')
                for member in members.values() if key in member.pax_headers}
    if not required:
        return
    guidance = ('boot a capable maintenance system or prepare the development card offline')
    probe = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.capability-probe-', dir=operation,
                                         delete=False) as stream:
            probe = Path(stream.name)
            for value in sorted(required):
                try:
                    os.setxattr(stream.fileno(), 'security.capability', value)
                    actual = os.getxattr(stream.fileno(), 'security.capability')
                except OSError as error:
                    raise ValueError('Destination cannot preserve required security.capability '
                                     'attributes; ' + guidance + ': ' + str(error)) from error
                if actual != value:
                    raise ValueError('Destination security.capability roundtrip differs; ' + guidance)
    finally:
        if probe is not None:
            probe.unlink()


def _verify_tree(stage, members):
    """Fail closed if extraction lost ownership, modes, timestamps, links or xattrs."""
    for parts, member in reversed(list(members.items())):
        path = stage.joinpath(*parts)
        observed = path.lstat()
        kind = (stat.S_ISREG if member.isreg() or member.islnk() else
                stat.S_ISDIR if member.isdir() else stat.S_ISLNK if member.issym() else
                stat.S_ISFIFO if member.isfifo() else stat.S_ISCHR if member.ischr() else stat.S_ISBLK)
        if (not kind(observed.st_mode) or stat.S_IMODE(observed.st_mode) != member.mode or
                (observed.st_uid, observed.st_gid) != (member.uid, member.gid)):
            raise ValueError('Extracted ownership/mode/type differs: ' + member.name)
        if member.isreg() and observed.st_size != member.size:
            raise ValueError('Extracted file size differs: ' + member.name)
        if member.issym() and os.readlink(path) != member.linkname:
            raise ValueError('Extracted symlink text differs')
        if member.islnk():
            target = stage.joinpath(*_path(member.linkname)).lstat()
            if (observed.st_dev, observed.st_ino) != (target.st_dev, target.st_ino):
                raise ValueError('Extracted hardlink identity differs')
        if (member.ischr() or member.isblk()) and observed.st_rdev != os.makedev(member.devmajor, member.devminor):
            raise ValueError('Extracted device identity differs')
        # GNU records inode xattrs once, on the regular payload member. Every
        # hardlink must expose that same inode metadata after extraction.
        attributes = members[_path(member.linkname)] if member.islnk() else member
        expected = {key.removeprefix('SCHILY.xattr.'): value.encode('utf-8', 'surrogateescape')
                    for key, value in attributes.pax_headers.items() if key.startswith('SCHILY.xattr.')}
        actual = {key: os.getxattr(path, key, follow_symlinks=False)
                  for key in os.listxattr(path, follow_symlinks=False)}
        if actual != expected:
            raise ValueError('Extracted extended attributes/ACLs differ: ' + member.name)
        mtime = int(Decimal(member.pax_headers.get('mtime', str(member.mtime))) * 1000000000)
        atime = int(Decimal(member.pax_headers.get('atime', str(member.mtime))) * 1000000000)
        os.utime(path, ns=(atime, mtime), follow_symlinks=False)
        if path.lstat().st_mtime_ns != mtime or path.lstat().st_atime_ns != atime:
            raise ValueError('Extracted timestamps differ')
        if member.isreg() or member.islnk():
            with _open_regular(path) as stream:
                os.fsync(stream.fileno())
        elif member.isdir():
            _sync_directory(path)


def pack_release(directory, output) -> dict:
    """Write only a new uncompressed TAR; the caller owns its separate receipt."""
    directory = _directory(directory)
    name = slot_id(directory.name)
    if name == 'recovery':
        raise ValueError('The fixed recovery identifier is reserved')
    output = Path(output)
    output = _directory(output.parent) / output.name
    if output.suffix != '.tar' or output.is_relative_to(directory):
        raise ValueError('Bundle must be a new .tar outside its source version')
    manifest, manifest_hash = _metadata(directory, name)
    operation = Path(tempfile.mkdtemp(prefix='.dev-bundle-pack-', dir=output.parent))
    with (operation / 'operation.log').open('xb') as log:
        try:
            with output.open('xb') as archive:
                _execute(['tar', '--format=pax', '--numeric-owner', '--xattrs', '--xattrs-include=*',
                          '--acls', '--atime-preserve=system', '--sort=name', '--create', '--file=-',
                          '--directory=' + str(directory.parent), '--', name], log, stdout=archive)
                archive.flush()
                os.fsync(archive.fileno())
            with _open_regular(output) as archive:
                _members(archive, name)
            if _metadata(directory, name)[1] != manifest_hash:
                raise ValueError('Version manifest changed while packing')
            _sync_directory(output.parent)
            return dict(slot=name, sha256=_hash(output), bytes=output.stat().st_size,
                        source_image_sha256=manifest['source_image_sha256'],
                        manifest_sha256=manifest_hash,
                        source_manifest_sha256=manifest['source_manifest_sha256'])
        except BaseException as error:
            log.write((type(error).__name__ + ': ' + str(error) + '\n').encode())
            raise


def unpack_release(archive, destination, *, expected_hash, store_partuuid) -> dict:
    """Validate and publish one inactive version; caller holds the card writer lock."""
    if os.geteuid() != 0:
        raise PermissionError('Bundle import requires root to preserve image ownership')
    digest(expected_hash)
    partuuid(store_partuuid, '03')
    destination = Path(destination)
    name = slot_id(destination.name)
    if name == 'recovery':
        raise ValueError('The fixed recovery identifier is reserved')
    destination = _directory(destination.parent) / name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    archive = Path(archive)
    _directory(archive.parent)
    operation = Path(tempfile.mkdtemp(prefix='.' + name + '-bundle-', dir=destination.parent))
    snapshot = operation / 'archive.tar'
    with (operation / 'operation.log').open('xb') as log:
        try:
            calculated = hashlib.sha256()
            with _open_regular(archive) as source, snapshot.open('xb') as target:
                while data := source.read(1024 * 1024):
                    calculated.update(data)
                    target.write(data)
                target.flush()
                os.fsync(target.fileno())
            if calculated.hexdigest() != expected_hash:
                raise ValueError('Development bundle SHA-256 differs')
            with _open_regular(snapshot) as source:
                members = _members(source, name)
                _probe_capabilities(operation, members)
                stage = operation / 'extracted'
                stage.mkdir(mode=0o700)
                source.seek(0)
                _execute(['tar', '--extract', '--file=-', '--directory=' + str(stage),
                          '--numeric-owner', '--same-owner', '--same-permissions', '--xattrs',
                          '--xattrs-include=*', '--acls', '--delay-directory-restore', '--keep-old-files'],
                         log, stdin=source)
            manifest, _ = _metadata(stage / name, name, store_partuuid)
            _verify_tree(stage, members)
            _publish(stage / name, destination)
            snapshot.unlink()
            stage.rmdir()
            _sync_directory(operation)
            return manifest
        except BaseException as error:
            log.write((type(error).__name__ + ': ' + str(error) + '\n').encode())
            raise
