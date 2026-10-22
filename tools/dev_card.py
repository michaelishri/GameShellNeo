"""Development layout derived from a verified two-partition recovery image."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile

from dev_systems import initialize, Card, sha, slot_id

SECTOR = 512
MIB = 1024 * 1024
SOURCE_BYTES = 4 * 1024 ** 3
ROOT = Path(__file__).resolve().parents[1]


def source_layout(path, expected_hash):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != SOURCE_BYTES:
        raise ValueError('Expected a regular fixed-size source image')
    if not re.fullmatch('[0-9a-f]{64}', expected_hash) or sha(path) != expected_hash:
        raise ValueError('Source image hash differs')
    with path.open('rb') as stream:
        mbr = stream.read(SECTOR)
    if mbr[510:] != b'\x55\xaa' or any(mbr[478:510]):
        raise ValueError('Expected the established two-partition MBR image')
    first = struct.unpack('<B3sB3sII', mbr[446:462])
    second = struct.unpack('<B3sB3sII', mbr[462:478])
    if ((first[0], first[2], first[4], first[5]) != (0x80, 0x0e, 32768, 262144) or
            (second[0], second[2], second[4], second[5]) != (0, 0x83, 294912, 8093696)):
        raise ValueError('Unexpected recovery-image geometry')
    disk_id = f'{struct.unpack("<I", mbr[440:444])[0]:08x}'
    if disk_id == '00000000':
        raise ValueError('Recovery image has no stable disk identifier')
    loader = json.loads((ROOT / 'build/sources.lock.json').read_text())['bootloader']
    if range_sha(path, loader['offset_bytes'], loader['size_bytes']) != loader['sha256']:
        raise ValueError('Source image differs from the qualified development bootloader')
    return {'bytes': SOURCE_BYTES, 'sha256': expected_hash, 'disk_id': disk_id,
            'recovery_start_sector': second[4], 'recovery_sectors': second[5]}


def layout(source, output_bytes):
    if (type(output_bytes) is not int or output_bytes < SOURCE_BYTES + 2 * 1024 ** 3 or
            output_bytes % MIB or output_bytes // SECTOR > 0xffffffff):
        raise ValueError('Development image needs at least 6 GiB, MiB alignment and MBR addressing')
    return dict(source, development_only=True, output_bytes=output_bytes,
                store_start_sector=SOURCE_BYTES // SECTOR,
                store_sectors=(output_bytes - SOURCE_BYTES) // SECTOR,
                store_partuuid=source['disk_id'] + '-03',
                recovery_partuuid=source['disk_id'] + '-02')


def append_partition(mbr, plan):
    if len(mbr) != SECTOR or any(mbr[478:510]) or mbr[510:] != b'\x55\xaa':
        raise ValueError('Refusing to overwrite an existing partition entry')
    result = bytearray(mbr)
    result[478:494] = struct.pack('<B3sB3sII', 0, b'\xfe\xff\xff', 0x83,
                                b'\xfe\xff\xff', plan['store_start_sector'], plan['store_sectors'])
    return bytes(result)


def run(*args):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}):\n' + result.stdout + result.stderr)
    return result.stdout


@contextlib.contextmanager
def attached(path, readonly):
    # GET_FREE can create a loop kernel object after Docker populated /dev.
    # Materialize its verified node before attaching, including for the second
    # simultaneous image. An allocation race fails rather than taking ownership
    # of another caller's already attached loop.
    device = run('losetup', '--find').strip()
    if not re.fullmatch('/dev/loop[0-9]+', device):
        raise ValueError('Unexpected loop-device allocation')
    node = Path(device)
    major, minor = map(int, (Path('/sys/class/block') / node.name / 'dev').read_text().strip().split(':'))
    if not node.exists() and not node.is_symlink():
        os.mknod(node, stat.S_IFBLK | 0o600, os.makedev(major, minor))
    if node.is_symlink() or not stat.S_ISBLK(node.stat().st_mode) or node.stat().st_rdev != os.makedev(major, minor):
        raise ValueError('Loop node has another identity')
    args = ['losetup', '--partscan']
    if readonly:
        args.append('--read-only')
    run(*args, device, path)
    try:
        for number in (1, 2, 3):
            name = device.rsplit('/', 1)[1] + 'p' + str(number)
            info = Path('/sys/class/block') / name / 'dev'
            if not info.exists():
                continue
            node = Path('/dev') / name
            major, minor = map(int, info.read_text().strip().split(':'))
            if not node.exists():
                os.mknod(node, stat.S_IFBLK | 0o600, os.makedev(major, minor))
            elif not stat.S_ISBLK(node.stat().st_mode) or node.stat().st_rdev != os.makedev(major, minor):
                raise ValueError('Loop partition node has another identity')
        yield device
    finally:
        run('losetup', '--detach', device)


@contextlib.contextmanager
def mounted(device, directory, *, readonly=False, filesystem=None):
    directory.mkdir()
    options = 'ro,noload' if readonly and filesystem == 'ext4' else 'ro' if readonly else 'rw,noatime'
    run('mount', '-o', options, device, directory)
    try:
        yield directory
    finally:
        run('umount', directory)


def range_sha(path, offset, length):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        stream.seek(offset)
        while length:
            data = stream.read(min(length, 8 * MIB))
            if not data:
                raise ValueError('Unexpected image truncation')
            digest.update(data)
            length -= len(data)
    return digest.hexdigest()


def fresh_output(output):
    output = Path(output)
    if output.suffix != '.img':
        raise ValueError('Output must be a new regular .img path')
    for path in (output, output.with_suffix('.json')):
        if path.exists() or path.is_symlink():
            raise FileExistsError('Refusing existing artifact or receipt: ' + str(path))
    for path in output.absolute().parents:
        if path.is_symlink():
            raise ValueError('Output parents must not be symlinks')


def admit_recovery(root, boot, expected_partuuid):
    from dev_images import inspect_source
    identity = inspect_source(root, boot)
    entries = [line.split() for line in (root / 'etc/fstab').read_bytes().splitlines()
               if line.strip() and not line.lstrip().startswith(b'#')]
    roots = [fields for fields in entries if len(fields) >= 2 and fields[1] == b'/']
    if (identity.get('root_partuuid') != expected_partuuid or len(roots) != 1 or
            len(roots[0]) < 3 or roots[0][:3] != [b'PARTUUID=' + expected_partuuid.encode(), b'/', b'ext4']):
        raise ValueError('Recovery manifest/fstab differs from its actual MBR root identity')
    return identity


def assemble(recovery, release, output, *, recovery_hash, release_hash, system, initramfs, output_bytes):
    """Root-only offline regular-file assembly; callers provide managed container ownership."""
    from dev_images import import_release
    from dev_initramfs import verify_u_initrd
    recovery, release, output, initramfs = map(Path, (recovery, release, output, initramfs))
    fresh_output(output)
    loader = verify_u_initrd(initramfs)
    source = source_layout(recovery, recovery_hash)
    source_layout(release, release_hash)
    plan = layout(source, output_bytes)
    slot_id(system)
    if system == 'recovery' or os.geteuid() != 0:
        raise ValueError('Expected root in the isolated offline builder and a non-recovery slot')
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Sparse/reflink copying never changes the source recovery artifact.
    run('cp', '--reflink=auto', '--sparse=always', '--', recovery, output)
    output.chmod(0o600)
    with output.open('r+b') as stream:
        stream.truncate(output_bytes)
        mbr = stream.read(SECTOR)
        stream.seek(0)
        stream.write(append_partition(mbr, plan))
        stream.flush()
        os.fsync(stream.fileno())
    with tempfile.TemporaryDirectory(prefix='gameshellneo-devcard-') as work:
        work = Path(work)
        with attached(output, False) as target, attached(release, True) as source_device:
            run('mkfs.ext4', '-F', '-L', 'NEO-DEVSTORE', target + 'p3')
            with mounted(target + 'p1', work / 'boot') as boot, \
                    mounted(target + 'p3', work / 'store', filesystem='ext4') as store, \
                    mounted(source_device + 'p1', work / 'source-boot', readonly=True) as source_boot, \
                    mounted(source_device + 'p2', work / 'source-root', readonly=True, filesystem='ext4') as source_root:
                systems = store / 'systems'
                systems.mkdir(mode=0o700)
                imported = import_release(source_root, source_boot, systems / system,
                    slot=system, source_image_sha256=release_hash,
                    store_partuuid=plan['store_partuuid'], initramfs=initramfs)
                recovery_boot = work / 'recovery-boot'
                recovery_boot.mkdir()
                # Output p1 is still the original recovery image's boot filesystem.
                for name in ('uImage', 'sun8i-r16-clockworkpi-cpi3.dtb',
                             'sun8i-r16-clockworkpi-cpi3-power-off.dtb'):
                    if (boot / name).is_file():
                        shutil.copyfile(boot / name, recovery_boot / name)
                with mounted(target + 'p2', work / 'recovery-root', readonly=True, filesystem='ext4') as recovery_root:
                    recovery_identity = admit_recovery(recovery_root, recovery_boot, plan['recovery_partuuid'])
                record = initialize(boot, store, recovery_partuuid=plan['recovery_partuuid'],
                    recovery_boot=recovery_boot, releases=[system],
                    recovery_suspend_diagnostics=recovery_identity['suspend_diagnostics'])
                admin = store / 'admin'
                admin.mkdir(mode=0o700)
                for name in ('dev-systems.py', 'dev_systems.py', 'dev_boot_scripts.py', 'usb_poll_boot.py',
                             'dev_card.py', 'dev_images.py', 'dev_bundle.py', 'dev_initramfs.py', 'build-dev-initramfs.py'):
                    destination = admin / 'tools' / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(Path(__file__).parent / name, destination)
                for name in ('development/initramfs/init', 'development/multiboot/dependencies.lock.json',
                             'build/sources.lock.json'):
                    destination = admin / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / name, destination)
                (admin / 'loader').mkdir()
                shutil.copyfile(initramfs, admin / 'loader/uInitrd')
                shutil.copyfile(Path(str(initramfs) + '.json'), admin / 'loader/uInitrd.json')
                selected = Card(boot, store).select(system)
                state = Card(boot, store).status()
                (store / 'assembly.json').write_text(json.dumps(dict(plan=plan,
                    source_release_sha256=release_hash, imported=imported,
                    recovery_identity=recovery_identity,
                    initial_selection=selected, status=state), indent=2) + '\n')
                os.sync()
            checks = {'boot': run('fsck.fat', '-n', target + 'p1'),
                      'recovery': run('e2fsck', '-fn', target + 'p2'),
                      'store': run('e2fsck', '-fn', target + 'p3')}
    offset, length = source['recovery_start_sector'] * SECTOR, source['recovery_sectors'] * SECTOR
    if range_sha(output, offset, length) != range_sha(recovery, offset, length):
        raise ValueError('Recovery root partition changed during assembly')
    if range_sha(output, SECTOR, 16 * MIB - SECTOR) != range_sha(recovery, SECTOR, 16 * MIB - SECTOR):
        raise ValueError('Reserved SPL/U-Boot image prefix changed')
    result = dict(schema=1, operation='development-card-assembly', development_only=True,
                  plan=plan, source_release_sha256=release_hash, initial_system=system, loader=loader,
                  image=str(output), bytes=output.stat().st_size, sha256=sha(output),
                  recovery_root_byte_identical=True, recovery_kernel=recovery_identity['kernel'],
                  reserved_bootloader_prefix_byte_identical=True,
                  offline_filesystem_checks='passed', filesystem_reports=checks,
                  hardware_qualified=False, clock_pm_admission=False)
    with output.with_suffix('.json').open('x') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    return result
