"""Build the development-only external loader from a supplied static BusyBox."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import struct
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / 'development/initramfs/init'
APPLETS = ('cat', 'grep', 'head', 'mkdir', 'mount', 'printf', 'readlink', 'sh', 'sleep',
           'switch_root', 'test', 'timeout', 'uname', 'wc')
INPUTS = ('development/initramfs/init', 'development/multiboot/dependencies.lock.json',
          'tools/dev_initramfs.py', 'tools/build-dev-initramfs.py')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def inspect_elf(data, architecture):
    """Check class, byte order, EABI and absence of a loader/shared libraries."""
    shapes = {'armhf': (1, 40, '<HHIIIIIHHHHHH', '<IIIIIIII'),
              'x86_64-test': (2, 62, '<HHIQQQIHHHHHH', '<IIQQQQQQ')}
    if architecture not in shapes:
        raise ValueError('Expected armhf or explicit x86_64-test architecture')
    bits, machine, header_format, program_format = shapes[architecture]
    if len(data) < 64 or data[:7] != b'\x7fELF' + bytes((bits, 1, 1)):
        raise ValueError('BusyBox ELF class, byte order or version differs')
    header = struct.unpack_from(header_format, data, 16)
    kind, observed_machine, version, _, offset, _, flags, header_size, program_size, count, *_ = header
    if (kind not in (2, 3) or observed_machine != machine or version != 1 or
            header_size != 16 + struct.calcsize(header_format) or
            program_size != struct.calcsize(program_format) or not 0 < count <= 1024 or
            offset < header_size or offset + count * program_size > len(data)):
        raise ValueError('Malformed or wrong-architecture BusyBox ELF')
    if architecture == 'armhf' and flags >> 24 != 5:
        raise ValueError('Expected ARM EABI version 5')
    executable = False
    for index in range(count):
        program = struct.unpack_from(program_format, data, offset + index * program_size)
        if bits == 1:
            tag, start, _, _, size, memory_size, mode, _ = program
        else:
            tag, mode, start, _, _, size, memory_size, _ = program
        if start + size > len(data) or size > memory_size:
            raise ValueError('Malformed BusyBox program segment')
        if tag == 3:
            raise ValueError('BusyBox requires a dynamic interpreter')
        if tag == 1 and mode & 1:
            executable = True
        if tag == 2:
            dynamic_format = '<II' if bits == 1 else '<QQ'
            entry_size = struct.calcsize(dynamic_format)
            if size % entry_size:
                raise ValueError('Malformed BusyBox dynamic segment')
            terminated = False
            for position in range(start, start + size, entry_size):
                entry, _ = struct.unpack_from(dynamic_format, data, position)
                if entry == 1:
                    raise ValueError('BusyBox requires shared libraries')
                if entry == 0:
                    terminated = True
                    break
            if not terminated:
                raise ValueError('Unterminated BusyBox dynamic segment')
    if not executable:
        raise ValueError('BusyBox has no executable load segment')
    return dict(architecture=architecture, elf_class=bits, machine=machine,
                little_endian=True, eabi=5 if bits == 1 else None, static=True)


def inspect_busybox(path, architecture, *, emulator=None, expected_sha256=None):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Expected a supplied BusyBox regular file under 16 MiB')
    data = path.read_bytes()
    digest = sha256(data)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('Supplied BusyBox hash differs')
    information = inspect_elf(data, architecture)
    command = [str(path), '--list']
    if emulator is not None:
        command.insert(0, str(Path(emulator).resolve(strict=True)))
    elif architecture == 'armhf' and platform.machine() not in ('armv7l', 'armv6l', 'arm'):
        raise ValueError('ARM applet validation on this host requires an explicit emulator')
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('Cannot execute supplied BusyBox applet check') from error
    applets = result.stdout.splitlines()
    missing = set(APPLETS) - set(applets)
    if missing:
        raise ValueError('BusyBox lacks required applets: ' + ', '.join(sorted(missing)))
    if path.read_bytes() != data:
        raise ValueError('Supplied BusyBox changed during validation')
    return data, dict(**information, sha256=digest, required_applets=list(APPLETS),
                      applet_list_sha256=sha256(result.stdout.encode()))


def newc(entries):
    """Encode deterministic newc without host cpio, root or device creation."""
    result = bytearray()
    for inode, (name, mode, data, major, minor) in enumerate(
            [*entries, ('TRAILER!!!', 0, b'', 0, 0)], 1):
        encoded = name.encode() + b'\0'
        fields = (inode, mode, 0, 0, 2 if stat.S_ISDIR(mode) else 1, 0, len(data),
                  0, 0, major, minor, len(encoded), 0)
        result += b'070701' + ''.join(f'{value:08x}' for value in fields).encode() + encoded
        result += b'\0' * (-len(result) % 4)
        result += data
        result += b'\0' * (-len(result) % 4)
    return bytes(result)


def legacy_u_initrd(payload):
    """ARM/Linux ramdisk/gzip legacy header, with reproducible time and CRCs."""
    values = (0x27051956, 0, 0, len(payload), 0, 0, zlib.crc32(payload), 5, 2, 3, 1,
              b'GameShellNeo development loader')
    header = struct.pack('>7I4B32s', *values)
    values = (values[0], zlib.crc32(header), *values[2:])
    return struct.pack('>7I4B32s', *values) + payload


def loader_entries(init, binary):
    entries = [(name, stat.S_IFDIR | 0o755, b'', 0, 0)
               for name in ('bin', 'dev', 'newroot', 'proc', 'run', 'sbin', 'store', 'sys')]
    entries += [('init', stat.S_IFREG | 0o755, init, 0, 0),
                ('bin/busybox', stat.S_IFREG | 0o755, binary, 0, 0),
                ('dev/console', stat.S_IFCHR | 0o600, b'', 5, 1),
                ('dev/null', stat.S_IFCHR | 0o666, b'', 1, 3)]
    entries += [('bin/' + name, stat.S_IFLNK | 0o777, b'busybox', 0, 0) for name in APPLETS]
    return sorted(entries)


def unpack_newc(data):
    """Read only a small, bounded loader archive; never extract untrusted paths."""
    entries, position = {}, 0
    while position + 110 <= len(data) and len(entries) <= 128:
        header = data[position:position + 110]
        if header[:6] != b'070701':
            raise ValueError('Expected newc initramfs')
        try:
            fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        except ValueError as error:
            raise ValueError('Malformed newc header') from error
        mode, size, name_size = fields[1], fields[6], fields[11]
        start = position + 110
        if not 1 < name_size <= 512 or start + name_size > len(data):
            raise ValueError('Malformed newc name')
        encoded = data[start:start + name_size]
        if encoded[-1:] != b'\0' or b'\0' in encoded[:-1]:
            raise ValueError('Malformed newc name terminator')
        name = encoded[:-1].decode('ascii')
        start = (start + name_size + 3) & ~3
        if start + size > len(data):
            raise ValueError('Truncated newc file')
        payload = data[start:start + size]
        position = (start + size + 3) & ~3
        if name == 'TRAILER!!!':
            if size or any(data[position:]):
                raise ValueError('Trailing initramfs data')
            return entries
        if (name in entries or name.startswith('/') or
                any(part in ('', '.', '..') for part in name.split('/'))):
            raise ValueError('Unsafe or duplicate newc path')
        entries[name] = (mode, payload)
    raise ValueError('Missing initramfs trailer or excessive entries')


def verify_u_initrd(path, receipt_path=None):
    path = Path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Development uInitrd is too large')
    data = path.read_bytes()
    if len(data) < 64:
        raise ValueError('Truncated development uInitrd')
    header = list(struct.unpack('>7I4B32s', data[:64]))
    if header[0] != 0x27051956 or tuple(header[7:11]) != (5, 2, 3, 1):
        raise ValueError('Expected ARM Linux gzip ramdisk header')
    expected_crc, header[1] = header[1], 0
    if zlib.crc32(struct.pack('>7I4B32s', *header)) != expected_crc:
        raise ValueError('uInitrd header CRC differs')
    payload = data[64:]
    if len(payload) != header[3] or zlib.crc32(payload) != header[6]:
        raise ValueError('uInitrd payload size or CRC differs')
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        raw = inflater.decompress(payload, 32 * 1024 * 1024 + 1)
    except zlib.error as error:
        raise ValueError('Malformed initramfs gzip') from error
    if len(raw) > 32 * 1024 * 1024 or not inflater.eof or inflater.unused_data:
        raise ValueError('Oversized or concatenated initramfs gzip')
    entries = unpack_newc(raw)
    try:
        init_mode, init = entries['init']
        busybox_mode, busybox = entries['bin/busybox']
    except KeyError as error:
        raise ValueError('Loader executable is missing') from error
    if any(not stat.S_ISREG(mode) or not mode & 0o111 for mode in (init_mode, busybox_mode)):
        raise ValueError('Loader executable modes differ')
    if raw != newc(loader_entries(INIT.read_bytes(), busybox)):
        raise ValueError('Loader archive entries, modes or applet links differ')
    information = inspect_elf(busybox, 'armhf')
    record = json.loads(Path(receipt_path or (str(path) + '.json')).read_text())
    dependency = json.loads((ROOT / 'development/multiboot/dependencies.lock.json').read_text())
    expected_inputs = {name: sha256((ROOT / name).read_bytes()) for name in INPUTS}
    if (record.get('schema_version') != 1 or record.get('development_only') is not True or
            record.get('architecture') != 'armhf' or record.get('inputs') != expected_inputs or
            record.get('u_initrd_sha256') != sha256(data) or
            record.get('u_initrd_bytes') != len(data) or
            record.get('initramfs_sha256') != sha256(payload) or
            record.get('initramfs_bytes') != len(payload) or
            record.get('init_sha256') != sha256(init) or sha256(init) != expected_inputs['development/initramfs/init'] or
            record.get('busybox', {}).get('sha256') != sha256(busybox) or
            any(record.get('busybox', {}).get(key) != value for key, value in information.items()) or
            sha256(busybox) != dependency['busybox']['binary_sha256'] or
            record.get('busybox', {}).get('required_applets') != list(APPLETS)):
        raise ValueError('Development uInitrd receipt/source/dependency pins differ')
    return dict(development_only=True, architecture='armhf', u_initrd_sha256=sha256(data),
                initramfs_sha256=sha256(payload), init_sha256=sha256(init),
                busybox_sha256=sha256(busybox), elf=information,
                receipt_sha256=sha256(Path(receipt_path or (str(path) + '.json')).read_bytes()))


def write_artifact(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('Refusing symlink artifact destination')
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.chmod(0o644)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def build_initramfs(busybox, output, *, architecture='armhf', emulator=None,
                    expected_sha256=None, u_initrd=None):
    binary, information = inspect_busybox(busybox, architecture, emulator=emulator,
                                         expected_sha256=expected_sha256)
    if u_initrd is not None and architecture != 'armhf':
        raise ValueError('Only ARM development initramfs can become uInitrd')
    init = INIT.read_bytes()
    archive = gzip.compress(newc(loader_entries(init, binary)), compresslevel=9, mtime=0)
    write_artifact(output, archive)
    record = dict(schema_version=1, development_only=True, architecture=architecture,
                  inputs={name: sha256((ROOT / name).read_bytes()) for name in INPUTS},
                  init_sha256=sha256(init), busybox=information,
                  initramfs_sha256=sha256(archive), initramfs_bytes=len(archive))
    if u_initrd is not None:
        wrapped = legacy_u_initrd(archive)
        write_artifact(u_initrd, wrapped)
        record['u_initrd_sha256'] = sha256(wrapped)
        record['u_initrd_bytes'] = len(wrapped)
    metadata = (json.dumps(record, sort_keys=True, indent=2) + '\n').encode()
    write_artifact(Path(str(output) + '.json'), metadata)
    if u_initrd is not None:
        write_artifact(Path(str(u_initrd) + '.json'), metadata)
    return record
