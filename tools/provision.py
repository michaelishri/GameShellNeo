#!/usr/bin/env python3
"""Prepare private, stable per-device identity from owner-supplied inputs."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
from private_config import load_env


def wifi_config(wicd, ssid):
    config = configparser.ConfigParser(interpolation=None)
    config.read(wicd)
    profiles = [p for p in config.values() if p.get('essid') == ssid]
    if not profiles or any(p.get('enctype') != 'wpa-psk' for p in profiles):
        raise ValueError('Expected matching WPA-PSK profiles')
    keys = {p.get('apsk', p.get('key', '')) for p in profiles}
    if len(keys) != 1:
        raise ValueError('Matching profiles disagree on credentials')
    key = keys.pop()
    return wifi_config_from_key(ssid, key)


def wifi_config_from_key(ssid, key):
    encoded_ssid = ssid.encode('utf-8')
    if not 1 <= len(encoded_ssid) <= 32:
        raise ValueError('Invalid SSID length')
    if len(key) == 64 and all(c in '0123456789abcdefABCDEF' for c in key):
        psk = key.lower()
    elif 8 <= len(key.encode('utf-8')) <= 63:
        psk = hashlib.pbkdf2_hmac('sha1', key.encode(), encoded_ssid, 4096, 32).hex()
    else:
        raise ValueError('Invalid WPA-PSK key length')
    return ('ctrl_interface=/run/wpa_supplicant\nupdate_config=0\nnetwork={\n'
            f'    ssid={encoded_ssid.hex()}\n    psk={psk}\n    scan_ssid=1\n    key_mgmt=WPA-PSK\n}}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env', type=Path, help='Read GAMESHELL_WIFI_SSID and GAMESHELL_WIFI_PSK privately')
    parser.add_argument('--wicd', type=Path, help='Legacy Wicd import alternative to --env')
    parser.add_argument('--ssid-file', type=Path)
    parser.add_argument('--authorized-key', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.output.chmod(0o700)
    if args.env:
        if args.wicd or args.ssid_file:
            parser.error('--env and legacy Wicd import are alternatives')
        config = load_env(args.env)
        if not config.get('GAMESHELL_WIFI_SSID') or not config.get('GAMESHELL_WIFI_PSK'):
            parser.error('Set GAMESHELL_WIFI_SSID and GAMESHELL_WIFI_PSK in .env')
        wifi = wifi_config_from_key(config['GAMESHELL_WIFI_SSID'], config['GAMESHELL_WIFI_PSK'])
    else:
        if not args.wicd or not args.ssid_file:
            parser.error('Supply --env, or both --wicd and --ssid-file')
        wifi = wifi_config(args.wicd, args.ssid_file.read_text().rstrip('\n'))
    subprocess.run(['ssh-keygen', '-l', '-f', str(args.authorized_key)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (args.output / 'wpa_supplicant-wlan0.conf').write_text(wifi)
    shutil.copyfile(args.authorized_key, args.output / 'authorized_keys')
    identity = args.output / 'machine-id'
    if not identity.exists():
        identity.write_text(secrets.token_hex(16) + '\n')
    host_key = args.output / 'ssh_host_ed25519_key'
    if not host_key.exists():
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C',
                        'gameshellneo-cpi31', '-f', str(host_key)], check=True)
    fingerprint = subprocess.check_output(['ssh-keygen', '-lf', str(host_key) + '.pub'], text=True)
    (args.output / 'identity.json').write_text(json.dumps({
        'hostname': 'gameshellneo', 'ssh_host_fingerprint': fingerprint.strip(),
        'machine_id': identity.read_text().strip()}, indent=2) + '\n')
    print('Private provisioning prepared. Host fingerprint is in identity.json.')


if __name__ == '__main__':
    main()
