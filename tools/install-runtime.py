#!/usr/bin/env python3
"""Install diagnostic files into an offline image root (requires root/QEMU)."""
import argparse
import os
from pathlib import Path
import shutil
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ['systemd-networkd', 'systemd-resolved', 'systemd-timesyncd', 'wpa_supplicant@wlan0',
            'ssh', 'gameshellneo-usb', 'gameshellneo-battery', 'gameshellneo-ready']
MASKED = ['sleep.target', 'suspend.target', 'hibernate.target', 'hybrid-sleep.target',
          'suspend-then-hibernate.target', 'systemd-networkd-wait-online.service',
          'NetworkManager.service', 'NetworkManager-wait-online.service',
          'armbian-resize-filesystem.service', 'armbian-firstlogin.service',
          'armbian-firstrun.service', 'armbian-hardware-optimize.service',
          'armbian-zram-config.service', 'armbian-ramlog.service',
          'armbian-hardware-monitor.service', 'armbian-led-state.service',
          'armbian-disable-autologin.service', 'armbian-disable-autologin.timer',
          'cron.service', 'rsyslog.service', 'apt-daily.timer', 'apt-daily-upgrade.timer',
          'man-db.timer', 'fstrim.timer', 'e2scrub_all.timer',
          'wpa_supplicant.service', 'dbus-fi.w1.wpa_supplicant1.service']


def main():
    os.umask(0o022)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--provision', required=True, type=Path)
    args = parser.parse_args()
    target = args.root.resolve()
    if target == Path('/') or not (target / 'etc/debian_version').is_file():
        raise SystemExit('Expected an offline Debian root directory')
    if os.geteuid() != 0:
        raise SystemExit('Root required for target file ownership')
    for directory in ('etc', 'usr'):
        shutil.copytree(ROOT / 'runtime' / directory, target / directory, dirs_exist_ok=True)
    for script in (target / 'usr/local/sbin').glob('gameshellneo-*'):
        script.chmod(0o755)
    (target / 'etc/sudoers.d/90-gameshellneo').chmod(0o440)
    (target / 'etc/hostname').write_text('gameshellneo\n')
    (target / 'etc/hosts').write_text('127.0.0.1 localhost\n127.0.1.1 gameshellneo\n::1 localhost ip6-localhost ip6-loopback\n')
    chroot = ['chroot', str(target)]
    # Custom upstream kernels trust the upstream regdb key, not Debian's key.
    # This also selects the matching detached signature through its slave link.
    subprocess.run(chroot + ['update-alternatives', '--set', 'regulatory.db',
                            '/lib/firmware/regulatory.db-upstream'], check=True)
    if subprocess.run(chroot + ['id', 'cpi'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        subprocess.run(chroot + ['useradd', '-m', '-s', '/bin/bash', '-G', 'sudo,input,video', 'cpi'], check=True)
    subprocess.run(chroot + ['passwd', '-l', 'root'], check=True, stdout=subprocess.DEVNULL)
    uid = int(subprocess.check_output(chroot + ['id', '-u', 'cpi']))
    gid = int(subprocess.check_output(chroot + ['id', '-g', 'cpi']))
    ssh_dir = target / 'home/cpi/.ssh'
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    os.chown(ssh_dir, uid, gid)
    key = ssh_dir / 'authorized_keys'
    shutil.copyfile(args.provision / 'authorized_keys', key)
    key.chmod(0o600)
    os.chown(key, uid, gid)
    for existing in (target / 'etc/ssh').glob('ssh_host_*'):
        existing.unlink()
    for name, destination in [('ssh_host_ed25519_key', 'etc/ssh/ssh_host_ed25519_key'),
                              ('ssh_host_ed25519_key.pub', 'etc/ssh/ssh_host_ed25519_key.pub'),
                              ('machine-id', 'etc/machine-id'),
                              ('wpa_supplicant-wlan0.conf', 'etc/wpa_supplicant/wpa_supplicant-wlan0.conf')]:
        path = target / destination
        path.parent.mkdir(parents=True, exist_ok=True)
        # Never follow an image symlink to the build host.
        if path.is_symlink():
            path.unlink()
        shutil.copyfile(args.provision / name, path)
        path.chmod(0o644 if name.endswith('.pub') or name == 'machine-id' else 0o600)
    for path, link in [('etc/resolv.conf', '/run/systemd/resolve/stub-resolv.conf'),
                       ('var/lib/dbus/machine-id', '/etc/machine-id')]:
        destination = target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        destination.symlink_to(link)
    (target / 'root/.no_rootfs_resize').touch()
    (target / 'root/.not_logged_in_yet').unlink(missing_ok=True)
    for name in SERVICES:
        subprocess.run(['systemctl', '--root', str(target), 'enable', name], check=True,
                       stdout=subprocess.DEVNULL)
    subprocess.run(['systemctl', '--root', str(target), 'disable', 'wpa_supplicant.service'],
                   check=True, stdout=subprocess.DEVNULL)
    for name in MASKED:
        subprocess.run(['systemctl', '--root', str(target), 'mask', '--force', name], check=True,
                       stdout=subprocess.DEVNULL)
    subprocess.run(chroot + ['visudo', '-c'], check=True)
    ssh_runtime = target / 'run/sshd'
    ssh_runtime.mkdir(mode=0o755, exist_ok=True)
    ssh_runtime.chmod(0o755)
    os.chown(ssh_runtime, 0, 0)
    null = target / 'dev/null'
    created_null = not null.exists()
    if created_null:
        os.mknod(null, stat.S_IFCHR | 0o666, os.makedev(1, 3))
    try:
        subprocess.run(chroot + ['sshd', '-t'], check=True)
        subprocess.run(['systemd-analyze', '--root', str(target), 'verify',
                        'gameshellneo-usb.service', 'gameshellneo-battery.service',
                        'gameshellneo-ready.service'], check=True)
    finally:
        if created_null:
            null.unlink()
    (target / 'var/log/journal').mkdir(parents=True, exist_ok=True)
    print('Runtime and private identity installed; offline SSH/sudo validation passed.')


if __name__ == '__main__':
    main()
