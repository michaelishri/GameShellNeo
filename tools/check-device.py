#!/usr/bin/env python3
"""On-device integration checks; temporary loopback/BPF probes, no radio changes."""
import argparse
import errno
import json
import os
from pathlib import Path
import pwd
import re
import socket
import struct
import subprocess
import uuid


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=20).strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def journal_acl():
    uid = pwd.getpwnam('cpi').pw_uid
    machine = Path('/etc/machine-id').read_text().strip()
    path = Path('/var/log/journal') / machine / ('user-{}.journal'.format(uid))
    acl = os.getxattr(path, 'system.posix_acl_access')
    require(struct.unpack('<I', acl[:4])[0] == 2, 'Unexpected POSIX ACL format')
    entries = list(struct.iter_unpack('<HHI', acl[4:]))
    user = next((perm for tag, perm, ident in entries if tag == 2 and ident == uid), 0)
    mask = next((perm for tag, perm, _ in entries if tag == 16), 0)
    require(user & mask & 4, 'cpi lacks effective read permission in its journal ACL')
    return {'file': path.name, 'uid': uid, 'user_permissions': user, 'mask': mask,
            'effective_read': True}


def bpf_filter():
    probe = ('import json,socket,sys; s=socket.socket(); s.settimeout(2); '
             'result=s.connect_ex(("127.0.0.1",int(sys.argv[1]))); '
             's.close(); print(json.dumps({"connect_errno":result}))')
    results = {}
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(8)
        port = str(listener.getsockname()[1])
        # The control, deny, and allow-exception probes use the same live listener.
        # Filters affect only the disposable service's cgroup, never SSH or Wi-Fi.
        for name, properties in (('control', []), ('deny', ['IPAddressDeny=any']),
                                 ('allow_exception', ['IPAddressDeny=any', 'IPAddressAllow=localhost'])):
            unit = 'gameshellneo-check-' + uuid.uuid4().hex
            args = ['systemd-run', '--quiet', '--wait', '--pipe', '--collect', '--unit=' + unit,
                    '--property=RuntimeMaxSec=10s']
            args += ['--property=' + item for item in properties]
            args += ['/usr/bin/python3', '-c', probe, port]
            try:
                results[name] = json.loads(command(*args))['connect_errno']
            except Exception:
                subprocess.run(['systemctl', 'stop', unit], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=15, check=False)
                subprocess.run(['systemctl', 'reset-failed', unit], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=15, check=False)
                raise
    require(results['control'] == 0 and results['allow_exception'] == 0,
            'Loopback control or allow-exception probe failed: ' + json.dumps(results))
    require(results['deny'] in (errno.EACCES, errno.EPERM, errno.ETIMEDOUT, errno.EAGAIN),
            'Deny policy did not block the test connection: ' + json.dumps(results))
    return results


def country_state(configured, active):
    text = Path('/etc/wpa_supplicant/wpa_supplicant-wlan0.conf').read_text()
    saved = re.findall(r'^country=([A-Z]{2})$', text, re.M)
    regulatory = command('/usr/sbin/iw', 'reg', 'get')
    global_part = regulatory.split('phy#', 1)[0]
    match = re.search(r'^country (\w{2}):', global_part, re.M)
    observed = match.group(1) if match else None
    result = {'configured_expected': configured, 'configured_observed': saved,
              'global_expected': active, 'global_observed': observed,
              'phy_domains': re.findall(r'phy#(\d+).*?\ncountry (\w{2}):', regulatory),
              'firmware_country_qualified': False}
    require(saved == [configured] and observed == active,
            'Country mismatch: ' + json.dumps(result))
    return result


def service_state():
    units = ['gameshellneo-usb', 'gameshellneo-battery', 'gameshellneo-ready',
             'ssh', 'systemd-networkd', 'wpa_supplicant@wlan0']
    for unit in units:
        require(command('systemctl', 'is-active', unit) == 'active', unit + ' is not active')
        require(command('systemctl', 'show', unit, '-p', 'NRestarts', '--value') == '0',
                unit + ' has restarted')
    require(not command('systemctl', '--failed', '--no-legend', '--plain'), 'Failed systemd units remain')
    for unit in ('wpa_supplicant.service', 'dbus-fi.w1.wpa_supplicant1.service'):
        require(command('systemctl', 'show', unit, '-p', 'LoadState', '--value') == 'masked',
                unit + ' is not masked')
    require(len(command('pgrep', '-x', 'wpa_supplicant').splitlines()) == 1,
            'Expected exactly one Wi-Fi daemon')
    require(command('hostname') == 'gameshellneo', 'Hostname changed')
    require(Path('/proc/sys/kernel/tainted').read_text().strip() == '0', 'Kernel is tainted')
    return {'active_units': units, 'wifi_daemons': 1, 'hostname': 'gameshellneo', 'kernel_taint': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--country', required=True)
    parser.add_argument('--active-country', required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0, 'Run the integration checks with sudo')
    require(all(re.fullmatch('[A-Z]{2}', value) for value in (args.country, args.active_country)),
            'Expected uppercase two-letter country codes')
    results = {}

    def check(name, action):
        try:
            results[name] = {'passed': True, 'details': action()}
        except (OSError, ValueError, subprocess.SubprocessError, KeyError, struct.error) as error:
            results[name] = {'passed': False, 'error': str(error)}

    def identity():
        data = json.loads(Path('/etc/gameshellneo/image.json').read_text())
        require(os.uname().release == args.kernel and data['kernel'] == args.kernel and
                data['version'] == args.version, 'Running image/kernel differs from the source lock')
        return {'kernel': args.kernel, 'version': args.version}

    def database():
        for suffix in ('', '.p7s'):
            path = Path('/usr/lib/firmware/regulatory.db' + suffix)
            require(path.is_file() and path.resolve().name == path.name + '-upstream',
                    'Missing or incorrect regdb alternative')
        require(Path('/sys/module/cfg80211').is_dir(), 'cfg80211 is not loaded')
        require(not Path('/usr/lib/udev/rules.d/90-alsa-restore.rules').exists(), 'Unused ALSA rules remain')
        require(int(Path('/proc/sys/kernel/unprivileged_bpf_disabled').read_text()) >= 1,
                'Unprivileged BPF is enabled')
        return {'upstream_regdb_selected': True, 'cfg80211_loaded': True,
                'alsa_rules_absent': True, 'unprivileged_bpf_disabled': True}

    check('image_identity', identity)
    check('service_state', service_state)
    check('database_and_policy', database)
    check('journal_acl', journal_acl)
    check('bpf_enforcement', bpf_filter)
    check('country', lambda: country_state(args.country, args.active_country))
    print(json.dumps(results, indent=2), flush=True)
    return 0 if all(value['passed'] for value in results.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
