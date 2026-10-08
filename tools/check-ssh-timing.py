#!/usr/bin/env python3
"""Measure fresh USB and Wi-Fi SSH sessions while awake; no PM or policy writes."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import time

from host_timing import CLOCK_SOURCE, capture_timing, clock_sample, phase, summarize
from private_config import load_env
from remote import LOCAL, device, evidence_directory, python_command, run


PROBE = CLOCK_SOURCE + '''
import json
stats = Path('/sys/power/suspend_stats')
print(json.dumps(dict(clock=clock, pm={name: int((stats/name).read_text())
                                      for name in ('success', 'fail')})))
'''


def probe(config, capture, cycles, burst=False):
    if type(cycles) is not int or not 1 <= cycles <= 10:
        raise ValueError('Use CYCLES=1..10')
    records = []
    transfers = []
    summary = dict(event='started', passed=False, cycles=cycles, samples=records)
    if burst:
        summary['transfers'] = transfers
    try:
        with capture_timing(capture) as timing:
            # Discover the current DHCP address over USB; stale .env Wi-Fi
            # addresses must not quietly probe another host or use USB twice.
            with device(config, 'usb') as client:
                output = run(client, 'sudo -n wpa_cli -i wlan0 status', display=False, timeout=10).decode()
            matches = re.findall(r'^ip_address=(.+)$', output, re.M)
            if len(matches) != 1:
                raise ValueError('A connected Wi-Fi address is required')
            address = str(ipaddress.IPv4Address(matches[0]))
            if address == config.get('GAMESHELL_USB_IP', '192.168.10.1'):
                raise ValueError('Wi-Fi must use a distinct address')
            wifi_config = dict(config, GAMESHELL_IP=address)
            initial = None
            for index in range(cycles):
                for route in ('usb', 'wifi'):
                    with phase('awake.probe'), device(wifi_config, route) as client:
                        with phase('clock.sample'):
                            value = json.loads(run(client, **python_command(PROBE), display=False, timeout=15))
                            clock_sample(value['clock'])
                        current = dict(boot_id=value['clock']['boot_id'], pm=value['pm'])
                        if (set(value['pm']) != {'success', 'fail'} or
                                any(type(n) is not int or n < 0 for n in value['pm'].values())):
                            raise ValueError('Invalid PM counters')
                        if initial is None:
                            initial = current
                        if current != initial:
                            raise ValueError('Boot or PM counters changed during awake probe')
                        records.append(dict(cycle=index+1, route=route, **current))
                        if burst and route == 'usb':
                            # Fixed synthetic bytes; no disk, credentials or payload
                            # artifact. Three 2 MiB replies reproduce collection load.
                            size = 2*1024*1024
                            start = time.monotonic()
                            payload = run(client, **python_command('import sys\nsys.stdout.buffer.write(bytes(2*1024*1024))'),
                                          display=False, timeout=30)
                            elapsed = time.monotonic()-start
                            digest = hashlib.sha256(payload).hexdigest()
                            if len(payload) != size or digest != hashlib.sha256(bytes(size)).hexdigest():
                                raise ValueError('Awake transfer length or digest mismatch')
                            transfers.append(dict(cycle=index+1, bytes=size, sha256=digest, seconds=elapsed))
                            del payload
                if index+1 < cycles:
                    time.sleep(1)
        if timing.failed:
            raise ValueError('Incomplete host timing; probe is not qualified')
        summary.update(event='complete', passed=True)
    except BaseException:
        summary['event'] = 'failed'
        raise
    finally:
        (capture/'awake-ssh.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', action='store_true', help='Summarize an existing capture; no device access')
    args = parser.parse_args()
    os.umask(0o077)
    if args.report:
        capture = Path(os.environ.get('NEO_SSH_CAPTURE', '')).resolve(strict=True)
        if not capture.is_dir() or not capture.is_relative_to((LOCAL/'diagnostics').resolve()):
            raise ValueError('CAPTURE must be an existing private diagnostics directory')
        print(json.dumps(summarize(capture), indent=2))
        return
    capture = evidence_directory()
    print('Private awake SSH timing:', capture, flush=True)
    result = probe(load_env(), capture, int(os.environ.get('NEO_SSH_CYCLES', '3')))
    print('Fresh route samples:', len(result['samples']), '; same boot and unchanged PM counters.')
    (capture/'host-timing-summary.json').write_text(json.dumps(summarize(capture), indent=2)+'\n')


if __name__ == '__main__':
    main()
