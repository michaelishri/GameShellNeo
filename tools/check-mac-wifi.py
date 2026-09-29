#!/usr/bin/env python3
"""Inspect the Mac's Wi-Fi band and cached visibility without publishing SSIDs."""
import json
import os
import sys

import paramiko
from private_config import load_env
from remote import connect_mac, evidence_directory, run


def summarize(data, ssid):
    results = []
    for section in data.get('SPAirPortDataType', []):
        for interface in section.get('spairport_airport_interfaces', []):
            current = interface.get('spairport_current_network_information', {})
            fields = ('spairport_network_channel', 'spairport_security_mode',
                      'spairport_signal_noise', 'spairport_network_phymode')
            current_name = current.get('_name', '')
            known = bool(current_name) and current_name.lower() not in ('<redacted>', 'redacted')
            matches = []
            for network in interface.get('spairport_airport_other_local_wireless_networks', []):
                if network.get('_name') == ssid:
                    matches.append({key: network[key] for key in fields if key in network})
            results.append(dict(current={key: current[key] for key in fields if key in current},
                                current_ssid_matches= current_name == ssid if known else None,
                                target_cached_matches=matches))
    if not results:
        raise ValueError('No Wi-Fi interface found in the Mac system profile')
    return dict(interfaces=results,
                limits='Read-only cached profile. Redacted names cannot be matched; current band does not prove an AP lacks other bands.')


def main():
    os.umask(0o077)
    config = load_env()
    capture = evidence_directory()
    with connect_mac(config) as client:
        data = run(client, '/usr/sbin/system_profiler SPAirPortDataType -json', display=False, timeout=45)
    (capture / 'mac-wifi-private.json').write_bytes(data)
    result = summarize(json.loads(data), config['GAMESHELL_WIFI_SSID'])
    (capture / 'mac-wifi-summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    print('Private evidence:', capture)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, paramiko.SSHException) as error:
        print('Mac Wi-Fi check failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
