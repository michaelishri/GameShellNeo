"""Admission, deterministic archives and the loader's actual BusyBox shell code."""
import gzip
import inspect
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import dev_initramfs as loader

BUSYBOX = shutil.which('busybox')
LIBRARY = loader.INIT.read_text().split('\n# The namespace qualification harness', 1)[0]


def elf(architecture='armhf', extra=None):
    bits, machine = (1, 40) if architecture == 'armhf' else (2, 62)
    header_format = '<HHIIIIIHHHHHH' if bits == 1 else '<HHIQQQIHHHHHH'
    program_format = '<IIIIIIII' if bits == 1 else '<IIQQQQQQ'
    offset = 16 + struct.calcsize(header_format)
    program_size = struct.calcsize(program_format)
    data = bytearray(256)
    data[:16] = b'\x7fELF' + bytes((bits, 1, 1)) + b'\0' * 9
    struct.pack_into(header_format, data, 16, 2, machine, 1, 0, offset, 0,
                     0x5000400 if bits == 1 else 0, offset, program_size,
                     2 if extra else 1, 0, 0, 0)
    program = (1, 0, 0, 0, 256, 256, 5, 4096) if bits == 1 else (1, 5, 0, 0, 0, 256, 256, 4096)
    struct.pack_into(program_format, data, offset, *program)
    if extra:
        struct.pack_into(program_format, data, offset + program_size,
                         extra, 200, 0, 0, 16, 16, 4, 4)
        if extra == 2:
            struct.pack_into('<IIII', data, 200, 1, 7, 0, 0)
    return bytes(data)


class ElfAdmission(unittest.TestCase):
    def test_arm_requires_little_endian_32_bit_eabi_five(self):
        self.assertTrue(loader.inspect_elf(elf(), 'armhf')['static'])
        for position, replacement in ((4, 2), (5, 2), (6, 2), (18, 62), (39, 4)):
            changed = bytearray(elf())
            changed[position] = replacement
            with self.subTest(position=position), self.assertRaises(ValueError):
                loader.inspect_elf(changed, 'armhf')
        with self.assertRaises(ValueError):
            loader.inspect_elf(elf('x86_64-test'), 'armhf')
        self.assertEqual(loader.inspect_elf(elf('x86_64-test'), 'x86_64-test')['machine'], 62)

    def test_dynamic_and_truncated_program_headers_reject(self):
        for data in (b'not ELF', elf()[:80], elf(extra=3), elf(extra=2)):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                loader.inspect_elf(data, 'armhf')
        with self.assertRaises(ValueError):
            loader.inspect_elf(elf(), 'automatic')

    def test_hash_and_applet_admission_precede_archive_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'busybox'
            path.write_bytes(elf())
            with self.assertRaisesRegex(ValueError, 'hash differs'):
                loader.inspect_busybox(path, 'armhf', expected_sha256='0' * 64)
            with patch.object(loader.platform, 'machine', return_value='x86_64'), self.assertRaisesRegex(ValueError, 'emulator'):
                loader.inspect_busybox(path, 'armhf')
            with patch.object(loader.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'sh\n', '')), \
                    self.assertRaisesRegex(ValueError, 'required applets'):
                loader.inspect_busybox(path, 'armhf', emulator=path)


@unittest.skipUnless(BUSYBOX, 'supplied host BusyBox required')
class LoaderShell(unittest.TestCase):
    def run_shell(self, invocation, *arguments):
        return subprocess.run([BUSYBOX, 'sh', '-c', LIBRARY + '\n' + invocation,
                               'loader-test', *arguments], capture_output=True, text=True, timeout=3)

    def test_exact_development_cmdline_and_normal_kernel_arguments(self):
        line = 'console=ttyS0,115200 neo.dev=1 neo.slot=diagnostic-27 neo.store=PARTUUID=0a1b2c3d-03 rootwait'
        result = self.run_shell('parse_cmdline "$1"; printf "%s %s\\n" "$slot" "$store"', line)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'diagnostic-27 PARTUUID=0a1b2c3d-03\n')

    def test_missing_duplicate_unsafe_or_unknown_arguments_stop(self):
        valid = 'neo.dev=1 neo.slot=a neo.store=PARTUUID=1234abcd-03'
        bad = [valid.replace('neo.dev=1', ''), valid.replace('neo.slot=a', ''),
               valid.replace('neo.store=PARTUUID=1234abcd-03', ''),
               valid + ' neo.dev=1', valid + ' neo.slot=b', valid + ' neo.store=PARTUUID=1234abcd-03',
               valid + ' neo.extra=1', valid.replace('neo.dev=1', 'neo.dev=0'),
               valid.replace('neo.slot=a', 'neo.slot=../a'), valid.replace('neo.slot=a', 'neo.slot=A'),
               valid.replace('neo.slot=a', 'neo.slot=' + 'a' * 49),
               valid.replace('neo.slot=a', 'neo.slot=a;echo'), valid.replace('neo.slot=a', 'neo.slot=$(id)'),
               valid.replace('neo.slot=a', 'neo.slot=*'), valid.replace('neo.slot=a', 'neo.slot="a"'),
               valid.replace('-03', '-02'), valid.replace('1234abcd', '1234ABCD'),
               valid.replace('PARTUUID=', 'UUID='), 'x' * 4097]
        for line in bad:
            with self.subTest(line=line[:100]):
                result = self.run_shell('parse_cmdline "$1"; echo SHOULD_NOT_CONTINUE', line)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('GameShellNeo development initramfs:', result.stderr)
                self.assertNotIn('SHOULD_NOT_CONTINUE', result.stdout)

    def test_plain_marker_is_exact_bounded_and_kernel_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / 'etc/gameshellneo/development-slot'
            marker.parent.mkdir(parents=True)
            good = b'schema=1\nid=release-1\nkernel=6.18.54-test\n'
            marker.write_bytes(good)
            self.assertEqual(self.run_shell('validate_marker "$1" release-1 6.18.54-test', str(root)).returncode, 0)
            for data in (good[:-1], good + b'\n', good + b'extra=1\n', good.replace(b'release-1', b'release-2'),
                         good.replace(b'test', b'other'), good.replace(b'schema=1', b'schema=2'),
                         good.replace(b'id=', b'id=\0'), b'x' * 1024 * 1024):
                marker.write_bytes(data)
                with self.subTest(size=len(data)):
                    self.assertNotEqual(self.run_shell('validate_marker "$1" release-1 6.18.54-test', str(root)).returncode, 0)
            marker.unlink()
            target = root / 'actual-marker'
            target.write_bytes(good)
            marker.symlink_to(target)
            self.assertNotEqual(self.run_shell('validate_marker "$1" release-1 6.18.54-test', str(root)).returncode, 0)

    def test_absolute_usrmerge_init_links_resolve_inside_selected_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'usr/sbin').mkdir(parents=True)
            (root / 'usr/lib/systemd').mkdir(parents=True)
            (root / 'sbin').symlink_to('usr/sbin')
            (root / 'lib').symlink_to('usr/lib')
            (root / 'usr/sbin/init').symlink_to('/lib/systemd/systemd')
            executable = root / 'usr/lib/systemd/systemd'
            executable.write_text('#!/bin/sh\nexit 0\n')
            executable.chmod(0o755)
            result = self.run_shell('resolve_root_path "$1" /sbin/init', str(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(executable))
            (root / 'usr/sbin/init').unlink()
            (root / 'usr/sbin/init').symlink_to('/lib/systemd/systemd\n')
            self.assertNotEqual(self.run_shell('resolve_root_path "$1" /sbin/init', str(root)).returncode, 0)
            (root / 'usr/sbin/init').unlink()
            (root / 'usr/sbin/init').symlink_to('../../../../../../outside')
            result = self.run_shell('resolve_root_path "$1" /sbin/init', str(root))
            self.assertEqual(result.stdout.strip(), str(root / 'outside'))
            (root / 'usr/sbin/init').unlink()
            (root / 'usr/sbin/init').symlink_to('init')
            self.assertNotEqual(self.run_shell('resolve_root_path "$1" /sbin/init', str(root)).returncode, 0)


class ArchiveAdmission(unittest.TestCase):
    def test_newc_roundtrip_has_root_owners_modes_devices_and_symlinks(self):
        entries = [('bin', stat.S_IFDIR | 0o755, b'', 0, 0),
                   ('bin/busybox', stat.S_IFREG | 0o755, b'provided executable', 0, 0),
                   ('bin/sh', stat.S_IFLNK | 0o777, b'busybox', 0, 0),
                   ('dev/console', stat.S_IFCHR | 0o600, b'', 5, 1)]
        archive = loader.newc(entries)
        # Decode headers independently of the builder's admission reader.
        position = 0
        observed = {}
        while True:
            header = archive[position:position + 110]
            self.assertEqual(header[:6], b'070701')
            fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
            self.assertEqual((fields[2], fields[3], fields[5]), (0, 0, 0))
            start = position + 110
            name = archive[start:start + fields[11] - 1].decode()
            start = (start + fields[11] + 3) & ~3
            payload = archive[start:start + fields[6]]
            position = (start + fields[6] + 3) & ~3
            if name == 'TRAILER!!!':
                break
            observed[name] = (fields[1], payload, fields[9], fields[10])
        self.assertEqual(observed, {name: (mode, data, major, minor) for name, mode, data, major, minor in entries})
        self.assertEqual(set(loader.unpack_newc(archive)), set(observed))

    def test_archive_reader_rejects_duplicates_traversal_and_truncation(self):
        for entries in ([('../init', 0, b'', 0, 0)], [('init', 0, b'', 0, 0)] * 2,
                        [('/init', 0, b'', 0, 0)]):
            with self.assertRaises(ValueError):
                loader.unpack_newc(loader.newc(entries))
        with self.assertRaises(ValueError):
            loader.unpack_newc(loader.newc([('init', 0, b'data', 0, 0)])[:-100])

    def test_legacy_header_checksums_are_independently_readable(self):
        payload = gzip.compress(b'cpio payload', mtime=0)
        image = loader.legacy_u_initrd(payload)
        fields = list(struct.unpack('>7I4B32s', image[:64]))
        self.assertEqual(fields[0], 0x27051956)
        self.assertEqual(fields[7:11], [5, 2, 3, 1])
        self.assertEqual(fields[3], len(payload))
        self.assertEqual(fields[6], zlib.crc32(payload))
        crc, fields[1] = fields[1], 0
        self.assertEqual(crc, zlib.crc32(struct.pack('>7I4B32s', *fields)))

    def test_board_artifact_admission_requires_source_receipt_and_exact_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in loader.INPUTS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / name).read_bytes())
            binary = elf()
            dependency = root / 'development/multiboot/dependencies.lock.json'
            value = json.loads(dependency.read_text())
            value['busybox']['binary_sha256'] = loader.sha256(binary)
            dependency.write_text(json.dumps(value))
            image = root / 'uInitrd'
            payload = gzip.compress(loader.newc(loader.loader_entries(loader.INIT.read_bytes(), binary)), mtime=0)
            data = loader.legacy_u_initrd(payload)
            image.write_bytes(data)
            record = dict(schema_version=1, development_only=True, architecture='armhf',
                          inputs={name: loader.sha256((root / name).read_bytes()) for name in loader.INPUTS},
                          u_initrd_sha256=loader.sha256(data), u_initrd_bytes=len(data),
                          initramfs_sha256=loader.sha256(payload), initramfs_bytes=len(payload),
                          init_sha256=loader.sha256(loader.INIT.read_bytes()),
                          busybox=dict(**loader.inspect_elf(binary, 'armhf'), sha256=loader.sha256(binary),
                                       required_applets=list(loader.APPLETS)))
            receipt = Path(str(image) + '.json')
            receipt.write_text(json.dumps(record))
            with patch.object(loader, 'ROOT', root):
                self.assertEqual(loader.verify_u_initrd(image)['architecture'], 'armhf')
                for field, changed in (('architecture', 'x86_64-test'), ('development_only', False),
                                       ('u_initrd_sha256', '0' * 64), ('init_sha256', '0' * 64)):
                    receipt.write_text(json.dumps(dict(record, **{field: changed})))
                    with self.subTest(field=field), self.assertRaises(ValueError):
                        loader.verify_u_initrd(image)
                receipt.write_text(json.dumps(record))
                for offset in (4, 30, 70):
                    changed = bytearray(data)
                    changed[offset] ^= 1
                    image.write_bytes(changed)
                    with self.subTest(offset=offset), self.assertRaises(ValueError):
                        loader.verify_u_initrd(image)
                bad = loader.loader_entries(loader.INIT.read_bytes(), binary)
                bad = [(name, mode, b'evil' if name == 'bin/mount' else body, major, minor)
                       for name, mode, body, major, minor in bad]
                changed_payload = gzip.compress(loader.newc(bad), mtime=0)
                changed_data = loader.legacy_u_initrd(changed_payload)
                image.write_bytes(changed_data)
                receipt.write_text(json.dumps(dict(record, u_initrd_sha256=loader.sha256(changed_data),
                    u_initrd_bytes=len(changed_data), initramfs_sha256=loader.sha256(changed_payload),
                    initramfs_bytes=len(changed_payload))))
                with self.assertRaisesRegex(ValueError, 'applet links differ'):
                    loader.verify_u_initrd(image)

    @unittest.skipUnless(BUSYBOX and os.uname().machine == 'x86_64', 'native x86 BusyBox required')
    def test_supplied_native_busybox_archive_is_reproducible_and_never_arm(self):
        try:
            loader.inspect_elf(Path(BUSYBOX).read_bytes(), 'x86_64-test')
        except ValueError:
            self.skipTest('host BusyBox is not static x86-64')
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'loader.cpio.gz'
            first = loader.build_initramfs(BUSYBOX, output, architecture='x86_64-test')
            archive = output.read_bytes()
            self.assertEqual(loader.build_initramfs(BUSYBOX, output, architecture='x86_64-test'), first)
            self.assertEqual(output.read_bytes(), archive)
            entries = loader.unpack_newc(gzip.decompress(archive))
            self.assertEqual(entries['init'][1], loader.INIT.read_bytes())
            self.assertEqual(entries['bin/busybox'][1], Path(BUSYBOX).read_bytes())
            self.assertEqual(json.loads(Path(str(output) + '.json').read_text()), first)
            with self.assertRaises(ValueError):
                loader.build_initramfs(BUSYBOX, output)
            with self.assertRaises(ValueError):
                loader.build_initramfs(BUSYBOX, output, architecture='x86_64-test', u_initrd=output.parent / 'uInitrd')


def namespace_fixture():
    """Run inside a dedicated managed container; all block writes are a new file."""
    import fcntl
    import time
    work = Path('/fixture')
    disk = work / 'store.img'
    oldroot = Path('/oldroot')
    temporary_mount = Path('/fixture-mount')
    run = lambda *args, **kwargs: subprocess.run(args, check=True, text=True,
        capture_output=True, timeout=30, **kwargs)
    oldroot.mkdir()
    temporary_mount.mkdir()
    with disk.open('wb') as stream:
        stream.truncate(64 * 1024 * 1024)
    signature = uuid.uuid4().hex[:8]
    run('sfdisk', str(disk), input='label: dos\nlabel-id: 0x' + signature + '\nunit: sectors\n\n'
        'start=2048,size=2048,type=c\nstart=4096,size=2048,type=83\nstart=6144,type=83\n')
    os.mknod('/dev/loop-control', stat.S_IFCHR | 0o600, os.makedev(10, 237))
    with open('/dev/loop-control', 'rb') as control:
        number = fcntl.ioctl(control.fileno(), 0x4C82)
    if number > 4096:
        raise ValueError('Unexpected test loop index')
    loop = '/dev/loop' + str(number)
    os.mknod(loop, stat.S_IFBLK | 0o600, os.makedev(7, number))
    attached = False
    mounted = False
    results = []
    try:
        run('losetup', '--partscan', loop, str(disk))
        attached = True
        partition = loop + 'p3'
        major, minor = (Path('/sys/class/block') / Path(partition).name / 'dev').read_text().strip().split(':')
        os.mknod(partition, stat.S_IFBLK | 0o600, os.makedev(int(major), int(minor)))
        run('mkfs.ext4', '-q', '-F', partition)
        run('mount', '-t', 'ext4', '-o', 'rw,data=ordered', partition, str(temporary_mount))
        mounted = True
        kernel = os.uname().release
        for slot in ('valid', 'bad-marker', 'bad-init'):
            root = temporary_mount / 'systems' / slot / 'root'
            for directory in ('bin', 'etc/gameshellneo', 'usr/sbin', 'usr/lib/systemd',
                              'usr/lib/modules/' + kernel, 'var', 'dev', 'sys', 'proc', 'run'):
                (root / directory).mkdir(parents=True, exist_ok=True)
            shutil.copyfile('/busybox', root / 'bin/busybox')
            (root / 'bin/busybox').chmod(0o755)
            for name in ('sh', 'cat', 'grep', 'readlink', 'printf'):
                (root / 'bin' / name).symlink_to('busybox')
            (root / 'sbin').symlink_to('usr/sbin')
            (root / 'lib').symlink_to('usr/lib')
            (root / 'usr/sbin/init').symlink_to('init' if slot == 'bad-init' else '/lib/systemd/systemd')
            marker_id = 'wrong' if slot == 'bad-marker' else slot
            marker = f'schema=1\nid={marker_id}\nkernel={kernel}\n'
            (root / 'etc/gameshellneo/development-slot').write_text(marker)
            (root / 'var/slot-private').write_text(slot)
            (root / 'usr/lib/modules' / kernel / 'slot-private').write_text(slot)
            target = root / 'usr/lib/systemd/systemd'
            target.write_text('''#!/bin/sh
set -eu
export PATH=/bin
[ "$$" = 1 ]
[ "$(cat /etc/gameshellneo/development-slot)" = "$(cat /run/gameshellneo-development-slot)" ]
[ "$(cat /var/slot-private)" = valid ]
[ "$(cat /lib/modules/''' + kernel + '''/slot-private)" = valid ]
[ "$(cat /run/gameshellneo-store/systems/valid/root/var/slot-private)" = valid ]
[ -d /proc/1 ] && [ -d /sys/class/block ]
grep -q ' /run/gameshellneo-store ext4 ' /proc/mounts
[ ! -e /init ]
printf 'INITRAMFS_HANDOFF_OK pid=%s\\n' "$$"
''')
            target.chmod(0o755)
        (temporary_mount / 'systems/bad-root').mkdir()
        (temporary_mount / 'systems/bad-root/root').symlink_to('../valid/root')
        run('umount', str(temporary_mount))
        mounted = False
        for slot in ('valid', 'bad-marker', 'bad-root', 'bad-init', 'missing-store'):
            console = work / (slot + '.console.log')
            console.touch()
            run('mount', '-t', 'tmpfs', 'tmpfs', str(oldroot))
            try:
                extracted = subprocess.run(['/busybox', 'cpio', '-id'],
                    input=gzip.decompress((work / 'native.cpio.gz').read_bytes()),
                    cwd=oldroot, capture_output=True, timeout=10)
                if extracted.returncode:
                    raise ValueError(extracted.stderr.decode())
                # Keep the real /init unchanged. The test-only mount shim calls
                # BusyBox mount unchanged, then supplies a namespace-local kernel
                # command line and console file after their virtual mounts exist.
                (oldroot / '.console-source').touch()
                run('mount', '-o', 'bind', str(console), str(oldroot / '.console-source'))
                store = signature if slot != 'missing-store' else ('00000000' if signature != '00000000' else 'ffffffff')
                (oldroot / '.cmdline-source').write_text(f'neo.dev=1 neo.slot={slot} neo.store=PARTUUID={store}-03\n')
                (oldroot / 'bin/mount').unlink()
                shim = oldroot / 'bin/mount'
                shim.write_text('''#!/bin/sh
/bin/busybox mount "$@" || exit
case "$*" in
  "-t devtmpfs -o nosuid devtmpfs /dev") /bin/busybox mount -o bind /.console-source /dev/console ;;
  "-t proc -o nosuid,nodev,noexec proc /proc") /bin/busybox mount -o bind /.cmdline-source /proc/cmdline ;;
esac
''')
                shim.chmod(0o755)
                started = time.monotonic()
                result = subprocess.run(['unshare', '--mount', '--pid', '--fork', '--kill-child',
                    'chroot', str(oldroot), '/init'], capture_output=True, text=True, timeout=25)
                elapsed = time.monotonic() - started
                output = console.read_text() + result.stdout + result.stderr
                successful = result.returncode == 0 and 'INITRAMFS_HANDOFF_OK pid=1' in output
                if slot == 'valid':
                    if not successful:
                        raise ValueError('Real handoff failed: ' + output)
                elif successful or result.returncode == 0 or 'GameShellNeo development initramfs:' not in output:
                    raise ValueError('Negative boot was not rejected: ' + slot + ': ' + output)
                if slot == 'missing-store' and elapsed > 12:
                    raise ValueError('Store wait exceeded its bound')
                results.append(dict(slot=slot, returncode=result.returncode, seconds=elapsed,
                                    handed_off=successful, console_sha256=hashlib.sha256(console.read_bytes()).hexdigest()))
                print(slot + ': ' + output, flush=True)
            finally:
                # Child mounts are private; only these two outer test mounts
                # remain. The source file bind must go before the tmpfs.
                subprocess.run(['umount', str(oldroot / '.console-source')], check=False, capture_output=True)
                run('umount', str(oldroot))
        (work / 'result.json').write_text(json.dumps(dict(passed=True, cases=results,
            scope='Actual native /init, ext4 loop store, sysfs PARTUUID, mount moves, '
                  'PID-1 switch_root and absolute usrmerge init. Test-only mount shim supplies '
                  'console/cmdline; no board kernel, bootloader, physical media or ARM handoff.'), indent=2) + '\n')
    finally:
        if mounted:
            subprocess.run(['umount', str(temporary_mount)], check=False)
        if attached:
            run('losetup', '-d', loop)


@unittest.skipUnless(os.environ.get('NEO_DEV_INITRAMFS_NAMESPACE') == '1',
                     'opt-in managed native mount/PID namespace qualification')
class NativeNamespaceHandoff(unittest.TestCase):
    def test_actual_ext4_root_handoff_and_failures(self):
        import hashlib
        from managed_container import execute
        self.assertIsNotNone(BUSYBOX)
        attempt = ROOT / '.local/build/dev-initramfs-handoff' / uuid.uuid4().hex
        fixture = attempt / 'fixture'
        fixture.mkdir(parents=True)
        record = loader.build_initramfs(BUSYBOX, fixture / 'native.cpio.gz', architecture='x86_64-test')
        script = ('from pathlib import Path\nimport os,stat,subprocess,shutil,gzip,json,uuid,hashlib\n' +
                  inspect.getsource(namespace_fixture) + '\nnamespace_fixture()\n')
        (fixture / 'run.py').write_text(script)
        (fixture / 'inputs.json').write_text(json.dumps(dict(init=record['init_sha256'],
            busybox=record['busybox']['sha256'], fixture=hashlib.sha256(script.encode()).hexdigest()), indent=2) + '\n')
        image = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']['image']
        execute('dev-initramfs-handoff', ['--pull=never', '--network=none', '--user=0:0',
            '--memory=512m', '--cpus=1', '--pids-limit=128', '--cap-add=SYS_ADMIN',
            '--device-cgroup-rule=c 10:237 rwm', '--device-cgroup-rule=b 7:* rwm',
            '--device-cgroup-rule=b 259:* rwm',
            '--security-opt=seccomp=unconfined', '--security-opt=apparmor=unconfined',
            '--entrypoint=python3', '-v', f'{fixture}:/fixture', '-v', f'{BUSYBOX}:/busybox:ro',
            image, '/fixture/run.py'], attempt / 'managed', timeout=100)
        result = json.loads((fixture / 'result.json').read_text())
        self.assertTrue(result['passed'])
        self.assertEqual(len(result['cases']), 5)
        self.assertEqual(sum(case['handed_off'] for case in result['cases']), 1)
        print('Native handoff evidence:', attempt.relative_to(ROOT))


if __name__ == '__main__':
    unittest.main()
