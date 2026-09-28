#!/usr/bin/env python3
"""Inspect a read-only mounted diagnostic image without executing its services."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import ssl
import struct
import subprocess
import tempfile
import zlib
from usb_poll_boot import verify_scripts


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def uboot_payload(path, image_type):
    data = path.read_bytes()
    header = bytearray(data[:64])
    fields = struct.unpack('>7I4B32s', header)
    magic, hcrc, _, size, _, _, dcrc, _, arch, kind, compression, _ = fields
    header[4:8] = b'\0' * 4
    require(magic == 0x27051956 and zlib.crc32(header) == hcrc, 'Invalid U-Boot header')
    require((arch, kind, compression) == (2, image_type, 0), 'Unexpected U-Boot image format')
    payload = data[64:]
    require(size == len(payload) and zlib.crc32(payload) == dcrc, 'Invalid U-Boot payload checksum')
    return payload, fields


def verify_regulatory(root, project, sources):
    firmware = root / 'usr/lib/firmware'
    for suffix in ('', '.p7s'):
        name = 'regulatory.db' + suffix
        require((firmware / name).readlink() == Path('/etc/alternatives') / name,
                'Regulatory database must use the package alternatives')
        require((root / 'etc/alternatives' / name).readlink() == Path('/lib/firmware') / (name + '-upstream'),
                'Regulatory database/signature must use the upstream signing key')
        require((firmware / (name + '-upstream')).is_file(), 'Missing signed upstream regulatory database')
    certs = project / '.local/sources' / ('linux-' + sources['linux']['tag'][1:]) / 'net/wireless/certs'
    with tempfile.TemporaryDirectory() as directory:
        trusted = Path(directory) / 'regdb-keys.pem'
        trusted.write_text(''.join(ssl.DER_cert_to_PEM_cert(bytes(int(value, 16) for value in
                            re.findall(r'0x([0-9a-fA-F]{2})', path.read_text())))
                            for path in sorted(certs.glob('*.hex'))))
        # Use only keys shipped in the locked kernel, never a signer supplied
        # by the signature itself. No external CA chain is involved.
        subprocess.run(['openssl', 'cms', '-verify', '-binary', '-inform', 'DER',
                        '-in', str(firmware / 'regulatory.db.p7s-upstream'),
                        '-content', str(firmware / 'regulatory.db-upstream'),
                        '-certfile', str(trusted), '-nointern', '-noverify', '-out', '/dev/null'], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('boot', type=Path)
    args = parser.parse_args()
    root, boot = args.root, args.boot
    identity = json.loads((root / 'etc/gameshellneo/image.json').read_text())
    project = Path(__file__).resolve().parents[1]
    built = json.loads((project / '.local/build/kernel-completed.json').read_text())
    require(identity['kernel'] == identity['sources']['linux']['tag'][1:] + identity['sources']['linux']['localversion'],
            'Kernel release differs from the image source lock')
    require(identity['hardware_qualified'] is False, 'Image must be marked unqualified')
    payload, fields = uboot_payload(boot / 'uImage', 2)
    require(fields[4:6] == (0x40008000, 0x40008000), 'Unexpected kernel load/entry')
    require(hashlib.sha256(payload).hexdigest() == built['files']['.local/build/kernel/arch/arm/boot/zImage'],
            'Installed kernel differs from completed stage')
    script, _ = uboot_payload(boot / 'boot.scr', 6)
    require(script[8:] == (boot / 'boot.cmd').read_bytes(), 'Boot script differs from source')
    require(f'root=PARTUUID={identity["root_partuuid"]}'.encode() in script, 'Root PARTUUID mismatch')
    require(b'bootm 0x48000000 - 0x49000000' in script, 'Unexpected boot handoff')
    require(not list(boot.glob('*Initrd*')) and not list(boot.glob('initrd*')), 'Unexpected initramfs')
    experiment = identity['sources'].get('experiments', {}).get('usb_absent_poll')
    if experiment is not None:
        require(type(experiment) is bool, 'Invalid USB policy selection')
        _, mode = verify_scripts(boot, identity)
        expected = 'experimental' if experiment else 'stock'
        require(mode == expected and identity['usb_poll_boot']['initial_mode'] == expected,
                'Image USB policy differs from source lock')
    for key, expected in built['files'].items():
        if '/lib/modules/' in key:
            relative = key.split('/lib/modules/', 1)[1]
            require(hashlib.sha256((root / 'usr/lib/modules' / relative).read_bytes()).hexdigest() == expected,
                    f'Installed module differs: {relative}')
    dtb = boot / 'sun8i-r16-clockworkpi-cpi3.dtb'
    require(hashlib.sha256(dtb.read_bytes()).hexdigest() == built['files']['.local/build/kernel/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dtb'],
            'Installed DTB differs from completed stage')
    for kind in ('firmware', 'nvram'):
        asset = identity['sources']['radio'][kind]
        name = asset['filename'] if kind == 'firmware' else 'brcmfmac43430a0-sdio.clockwork,clockworkpi-cpi3.txt'
        require(hashlib.sha256((root / 'usr/lib/firmware/brcm' / name).read_bytes()).hexdigest() == asset['sha256'],
                f'Installed radio {kind} differs from locked input')
    for name, relative in [('machine-id', 'etc/machine-id'),
                           ('authorized_keys', 'home/cpi/.ssh/authorized_keys'),
                           ('ssh_host_ed25519_key.pub', 'etc/ssh/ssh_host_ed25519_key.pub')]:
        require((root / relative).read_bytes() == (project / '.local/provisioning/device' / name).read_bytes(),
                f'Installed device identity differs: {name}')
    require((root / 'etc/wpa_supplicant/wpa_supplicant-wlan0.conf').stat().st_mode & 0o777 == 0o600,
            'Wi-Fi configuration permissions are too broad')
    wifi = root / 'etc/wpa_supplicant/wpa_supplicant-wlan0.conf'
    require(wifi.read_bytes() == (project / '.local/provisioning/device/wpa_supplicant-wlan0.conf').read_bytes(),
            'Wi-Fi settings differ from private provisioning')
    require(re.search(r'^country=[A-Z]{2}$', wifi.read_text(), re.M), 'Explicit Wi-Fi country is missing')
    verify_regulatory(root, project, identity['sources'])
    require((root / 'etc/ssh/ssh_host_ed25519_key').stat().st_mode & 0o777 == 0o600,
            'Host private key permissions are too broad')
    require('data=ordered,commit=5' in (root / 'etc/fstab').read_text(), 'Incorrect root mount policy')
    for name in ('gameshellneo-usb', 'gameshellneo-battery', 'gameshellneo-ready'):
        require((root / 'etc/systemd/system/multi-user.target.wants' / (name + '.service')).is_symlink(),
                f'Service not enabled: {name}')
    for name in ('sleep.target', 'suspend.target', 'hibernate.target',
                 'wpa_supplicant.service', 'dbus-fi.w1.wpa_supplicant1.service'):
        require((root / 'etc/systemd/system' / name).readlink() == Path('/dev/null'), f'Unit is not masked: {name}')
    require((root / 'etc/systemd/system/multi-user.target.wants/wpa_supplicant@wlan0.service').is_symlink(),
            'Interface-specific Wi-Fi service must remain enabled')
    require(not (root / 'usr/lib/udev/rules.d/90-alsa-restore.rules').exists(), 'Unused ALSA restore rules remain')
    require(not (root / '.env').exists() and not (root / 'home/cpi/.env').exists(), 'Unexpected credential source')
    require(not list((root / 'usr/bin').glob('qemu-arm*')), 'Builder QEMU binaries remain in the image')
    print('Offline contents: kernel/DTB/modules/boot CRCs, identity permissions and service policies passed')


if __name__ == '__main__':
    main()
