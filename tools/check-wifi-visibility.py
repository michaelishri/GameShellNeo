#!/usr/bin/env python3
"""Compare cached radio scan results with the private .env SSID over USB."""
import json
import os
import re
import sys

import paramiko
from private_config import load_env
from remote import device, evidence_directory, run


def ssid_bytes(value):
    """Decode wpa_supplicant's printf_encode representation, not Python escapes."""
    result = bytearray()
    escapes = {'n': b'\n', 'r': b'\r', 't': b'\t', 'e': b'\x1b', '\\': b'\\', '"': b'"'}
    while value:
        if value.startswith('\\x') and re.match(r'^[0-9a-fA-F]{2}', value[2:4]):
            result.extend(bytes.fromhex(value[2:4]))
            value = value[4:]
        elif len(value) >= 2 and value[0] == '\\' and value[1] in escapes:
            result.extend(escapes[value[1]])
            value = value[2:]
        else:
            result.extend(value[0].encode('utf-8'))
            value = value[1:]
    return bytes(result)


def summarize(text, ssid):
    lines = text.splitlines()
    if not lines or not lines[0].startswith('bssid / frequency / signal level / flags / ssid'):
        raise ValueError('Radio scan cache is unavailable')
    entries, matches = 0, []
    for line in lines[1:]:
        row = line.split('\t', 4)
        if (len(row) != 5 or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', row[0]) or
                not re.fullmatch(r'\d+', row[1]) or not re.fullmatch(r'-?\d+', row[2]) or
                not re.fullmatch(r'[\[\]A-Za-z0-9+_.-]*', row[3])):
            raise ValueError('Unexpected radio scan-cache row; raw data withheld')
        entries += 1
        if ssid_bytes(row[4]) == ssid.encode('utf-8'):
            matches.append(dict(frequency_mhz=int(row[1]), signal_dbm=int(row[2]), security=row[3]))
    return dict(visible_entries=entries, target_matches=matches,
                limits='Cached results only; an absent match does not prove the AP is off or out of range.')


def main():
    os.umask(0o077)
    config = load_env()
    capture = evidence_directory()
    with device(config, 'usb') as client:
        data = run(client, 'sudo -n /usr/sbin/wpa_cli -i wlan0 scan_results', display=False).decode()
    result = summarize(data, config['GAMESHELL_WIFI_SSID'])
    (capture / 'wifi-visibility.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    print('Private evidence:', capture)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, paramiko.SSHException) as error:
        print('Wi-Fi visibility check failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
