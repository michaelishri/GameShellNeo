#!/usr/bin/env python3
"""Private image finalization and byte-level layout verification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
from usb_poll_boot import boot_script, verify_scripts
import keypad_supply

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / 'build/sources.lock.json').read_text())
LOCAL = ROOT / '.local'


def sha(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(*command, **kwargs):
    return subprocess.run([str(p) for p in command], check=True, **kwargs)


def apt_sources(root):
    destination = root / 'etc/apt/sources.list.d'
    destination.mkdir(parents=True, exist_ok=True)
    (root / 'etc/apt/sources.list').unlink(missing_ok=True)
    for path in destination.iterdir():
        if path.suffix in ('.list', '.sources'):
            path.unlink()
    blocks = []
    for archive, snapshot, suite in [('debian', LOCK['debian']['snapshot'], 'trixie'),
                                     ('debian-security', LOCK['debian']['security_snapshot'], 'trixie-security')]:
        blocks.append(f'Types: deb\nURIs: https://snapshot.debian.org/archive/{archive}/{snapshot}/\n'
                      f'Suites: {suite}\nComponents: main\n'
                      'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\nCheck-Valid-Until: no\n')
    (destination / 'debian.sources').write_text('\n'.join(blocks))


def input_manifest():
    names = ['build', 'kernel', 'runtime', 'tools']
    paths = [p for name in names for p in sorted((ROOT / name).rglob('*'))
             if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    paths.append(ROOT / 'Taskfile.yml')
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def finalize(root, loop):
    if not root.is_dir() or root.resolve() == Path('/') or not loop.startswith('/dev/loop'):
        raise SystemExit('Expected mounted offline root and image loop device')
    kernel = LOCAL / 'build/kernel'
    release = (kernel / 'include/config/kernel.release').read_text().strip()
    run('python3', ROOT / 'tools/check-kernel-config.py', kernel / '.config')
    run('python3', ROOT / 'tools/kernel-artifacts.py', 'check')
    run('python3', ROOT / 'tools/install-runtime.py', root,
        '--provision', LOCAL / 'provisioning/device')
    apt_sources(root)
    modules = LOCAL / 'kernel-install/lib/modules' / release
    shutil.copytree(modules, root / 'usr/lib/modules' / release, dirs_exist_ok=True, symlinks=True)
    for link in ('build', 'source'):
        (root / 'usr/lib/modules' / release / link).unlink(missing_ok=True)
    run('depmod', '-b', root, release)
    firmware = root / 'usr/lib/firmware/brcm'
    firmware.mkdir(parents=True, exist_ok=True)
    for kind, asset in LOCK['radio'].items():
        if not isinstance(asset, dict):
            continue
        path = LOCAL / 'inputs' / asset['filename']
        if sha(path) != asset['sha256']:
            raise SystemExit(f'Incorrect private radio input: {kind}')
        name = asset['filename']
        if kind == 'nvram':
            name = 'brcmfmac43430a0-sdio.clockwork,clockworkpi-cpi3.txt'
        shutil.copyfile(path, firmware / name)
    boot = root / 'boot'
    for pattern in ('initrd*', 'uInitrd*', 'armbianEnv.txt', 'boot.bmp'):
        for path in boot.glob(pattern):
            path.unlink()
    run('mkimage', '-A', 'arm', '-O', 'linux', '-T', 'kernel', '-C', 'none',
        '-a', '0x40008000', '-e', '0x40008000', '-n', 'GameShellNeo diagnostic',
        '-d', kernel / 'arch/arm/boot/zImage', boot / 'uImage')
    if (boot / 'uImage').stat().st_size >= 0x1000000:
        raise SystemExit('uImage overlaps DTB load address')
    dtb = 'sun8i-r16-clockworkpi-cpi3.dtb'
    shutil.copyfile(kernel / 'arch/arm/boot/dts/allwinner' / dtb, boot / dtb)
    keypad = None
    if keypad_supply.enabled(LOCK):
        shutil.copyfile(boot / dtb, boot / keypad_supply.BASE_DTB)
        keypad = keypad_supply.prepare(boot / keypad_supply.BASE_DTB, boot / dtb)
    if (boot / dtb).stat().st_size >= 0x100000:
        raise SystemExit('Unexpectedly large DTB')
    partuuid = subprocess.check_output(['blkid', '-s', 'PARTUUID', '-o', 'value', loop + 'p2'], text=True).strip()
    if not partuuid:
        raise SystemExit('Missing root PARTUUID')
    experiment = LOCK.get('experiments', {}).get('usb_absent_poll')
    if experiment is not None and type(experiment) is not bool:
        raise ValueError('USB polling selection must be an explicit boolean')
    selected = None if experiment is None else 'experimental' if experiment else 'stock'
    diagnostics = LOCK.get('experiments', {}).get('usb_diagnostics', False)
    suspend_tests = LOCK.get('experiments', {}).get('suspend_diagnostics', False)
    (boot / 'boot.cmd').write_bytes(boot_script(partuuid, selected, diagnostics, suspend_tests))
    run('mkimage', '-A', 'arm', '-T', 'script', '-C', 'none', '-n', 'GameShellNeo',
        '-d', boot / 'boot.cmd', boot / 'boot.scr')
    (root / 'etc/fstab').write_text(f'PARTUUID={partuuid} / ext4 defaults,noatime,data=ordered,commit=5 0 1\n'
                                   f'{loop_uuid(loop + "p1")} /boot vfat defaults,noatime 0 2\n'
                                   'tmpfs /tmp tmpfs defaults,nosuid,size=64M 0 0\n')
    run('tune2fs', '-o', '^journal_data_writeback', loop + 'p2')
    destination = root / 'etc/gameshellneo'
    destination.mkdir(exist_ok=True)
    identity = {'version': LOCK['image_version'], 'board': LOCK['board'], 'kernel': release,
                'hardware_qualified': False, 'root_partuuid': partuuid,
                'sources': LOCK, 'project_inputs_sha256': input_manifest()}
    if keypad is not None:
        identity['keypad_supply'] = keypad
    if selected is not None:
        files = {}
        for mode in ('stock', 'experimental'):
            source = boot / f'boot-usb-{mode}.cmd'
            compiled = boot / f'boot-usb-{mode}.scr'
            source.write_bytes(boot_script(partuuid, mode, diagnostics))
            run('mkimage', '-A', 'arm', '-T', 'script', '-C', 'none', '-n', 'GameShellNeo',
                '-d', source, compiled)
            files.update({source.name: sha(source), compiled.name: sha(compiled)})
        for suffix in ('cmd', 'scr'):
            shutil.copyfile(boot / f'boot-usb-{selected}.{suffix}', boot / f'boot.{suffix}')
        identity['usb_poll_boot'] = {'initial_mode': selected, 'files': files}
        verify_scripts(boot, identity)
    (destination / 'image.json').write_text(json.dumps(identity, indent=2) + '\n')
    output = LOCAL / 'artifacts'
    output.mkdir(exist_ok=True, mode=0o700)
    shutil.copyfile(destination / 'image.json', output / 'image-manifest.json')
    shutil.copyfile(kernel / '.config', output / 'kernel.config')
    for name in ('kernel-completed.json', 'compiler.txt', 'builder-packages.txt'):
        shutil.copyfile(LOCAL / 'build' / name, output / name)
    with (output / 'image-builder-packages.txt').open('w') as stream:
        run('dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\n', stdout=stream)
    run('python3', ROOT / 'tools/kernel-inputs.py', '--export', output / 'kernel-patches')
    with (output / 'packages.txt').open('w') as stream:
        run('chroot', root, 'dpkg-query', '-W', '-f=${Package}\t${Version}\t${Architecture}\n', stdout=stream)


def loop_uuid(device):
    return 'UUID=' + subprocess.check_output(['blkid', '-s', 'UUID', '-o', 'value', device], text=True).strip()


def verify_layout(image):
    if not image.is_file() or image.stat().st_size != LOCK['layout']['image_bytes']:
        raise SystemExit('Expected a regular, fixed 4 GiB image')
    with image.open('rb') as stream:
        mbr = stream.read(512)
        if mbr[510:] != b'\x55\xaa':
            raise SystemExit('Missing MBR signature')
        for i, name in enumerate(('boot', 'root')):
            flag, _, kind, _, start, sectors = struct.unpack('<B3sB3sII', mbr[446 + 16*i:462 + 16*i])
            spec = LOCK['layout'][name]
            if (flag, kind, start, sectors) != (0x80 if i == 0 else 0, int(spec['type'], 16), spec['start_sector'], spec['sectors']):
                raise SystemExit(f'Incorrect {name} partition')
        if any(mbr[478:510]):
            raise SystemExit('Unexpected extra partitions')
        stream.seek(LOCK['bootloader']['offset_bytes'])
        data = stream.read(LOCK['bootloader']['size_bytes'])
        if hashlib.sha256(data).hexdigest() != LOCK['bootloader']['sha256']:
            raise SystemExit('Bootloader readback differs from locked binary')
        stream.seek(LOCK['layout']['boot']['start_sector'] * 512)
        if stream.read(64)[54:62] != b'FAT16   ':
            raise SystemExit('Expected FAT16 boot filesystem')
    return {'layout': 'passed', 'bootloader_readback': 'passed', 'fat16': 'passed'}


def inject(image):
    if not image.is_file() or image.stat().st_size != LOCK['layout']['image_bytes']:
        raise SystemExit('Refusing to write anything except the fixed-size image file')
    binary = LOCAL / 'inputs' / LOCK['bootloader']['filename']
    if sha(binary) != LOCK['bootloader']['sha256'] or binary.stat().st_size != LOCK['bootloader']['size_bytes']:
        raise SystemExit('Incorrect bootloader input')
    if LOCK['bootloader']['offset_bytes'] + binary.stat().st_size >= LOCK['layout']['boot']['start_sector'] * 512:
        raise SystemExit('Bootloader would overlap filesystem')
    with image.open('r+b') as stream:
        stream.seek(LOCK['bootloader']['offset_bytes'])
        stream.write(binary.read_bytes())
        stream.flush()
        os.fsync(stream.fileno())
    image.chmod(0o600)
    if os.geteuid() == 0:
        owner = ROOT.stat()
        os.chown(image, owner.st_uid, owner.st_gid)
    print(json.dumps(verify_layout(image)))


def main():
    os.umask(0o022)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apt-sources', 'finalize', 'inject', 'verify'])
    parser.add_argument('path', type=Path)
    parser.add_argument('--loop')
    args = parser.parse_args()
    if args.action == 'apt-sources':
        apt_sources(args.path)
    elif args.action == 'finalize':
        finalize(args.path, args.loop or '')
    elif args.action == 'inject':
        inject(args.path)
    else:
        print(json.dumps(verify_layout(args.path), indent=2))


if __name__ == '__main__':
    main()
