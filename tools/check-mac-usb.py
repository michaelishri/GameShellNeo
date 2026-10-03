#!/usr/bin/env python3
"""Save read-only Mac USB/network state without renewing leases or changing routes."""
import ipaddress
import json
import os
import shlex

import paramiko

from private_config import load_env
from remote import connect_mac, evidence_directory, run

POWER_HISTORY = '''
from collections import deque
import re, subprocess
p = subprocess.Popen(['/usr/bin/pmset', '-g', 'log'], stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, text=True)
rows = deque(maxlen=100)
for line in p.stdout:
    if re.match(r'^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2} [+-]\\d{4}\\s+(?:Sleep|Wake|DarkWake)\\s{2,}', line):
        rows.append(line.rstrip())
code = p.wait()
print('\\n'.join(rows))
raise SystemExit(code)
'''


def main():
    os.umask(0o077)
    config = load_env()
    address = str(ipaddress.IPv4Address(config.get('GAMESHELL_USB_IP', '192.168.10.1')))
    capture = evidence_directory()
    print('Private Mac USB/network evidence:', capture, flush=True)
    commands = {
        'interfaces': ['/sbin/ifconfig', '-a'],
        'route': ['/sbin/route', '-n', 'get', address],
        'hardware-ports': ['/usr/sbin/networksetup', '-listallhardwareports'],
        'service-order': ['/usr/sbin/networksetup', '-listnetworkserviceorder'],
        'usb-tree': ['/usr/sbin/ioreg', '-p', 'IOUSB', '-l', '-w', '0'],
        'sleep-wake': ['/usr/bin/python3', '-c', POWER_HISTORY],
    }
    results = {}
    with connect_mac(config) as client:
        for name, command in commands.items():
            with (capture/(name+'.txt')).open('wb') as output:
                try:
                    run(client, shlex.join(command), output=output, display=False, timeout=30)
                    results[name] = {'collected': True}
                except (OSError, RuntimeError, paramiko.SSHException) as error:
                    results[name] = {'collected': False, 'error': type(error).__name__+': '+str(error)}
            (capture/'summary.json').write_text(json.dumps(results, indent=2)+'\n')
    print('Read-only capture finished; no DHCP, interface or route settings changed.')
    if not all(value['collected'] for value in results.values()):
        raise RuntimeError('Some reads failed; inspect the saved partial capture')


if __name__ == '__main__':
    main()
