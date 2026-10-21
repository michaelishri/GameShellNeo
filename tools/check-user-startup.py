#!/usr/bin/env python3
"""Inspect user-manager startup and exercise private Unix98 PTYs while awake."""
import argparse
from collections import Counter
import fcntl
import gzip
import json
import os
from pathlib import Path
import re
import select
import shlex
import struct
import subprocess
import termios
import tty

LEGACY = r'tty[p-za-e][0-9a-f]'
TIMESTAMPS = ('UserspaceTimestampMonotonic', 'GeneratorsStartTimestampMonotonic',
              'GeneratorsFinishTimestampMonotonic', 'UnitsLoadStartTimestampMonotonic',
              'UnitsLoadFinishTimestampMonotonic', 'FinishTimestampMonotonic')
CONFIG = ('CONFIG_TTY', 'CONFIG_VT', 'CONFIG_VT_CONSOLE', 'CONFIG_UNIX98_PTYS',
          'CONFIG_LEGACY_PTYS', 'CONFIG_LEGACY_PTY_COUNT', 'CONFIG_SERIAL_8250_CONSOLE')


def command(*arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=30).stdout


def health():
    read = lambda p: Path(p).read_text().strip()
    return dict(boot_id=read('/proc/sys/kernel/random/boot_id'), kernel=os.uname().release,
                pm={p.name: p.read_text().strip() for p in Path('/sys/power/suspend_stats').iterdir()},
                brightness=read('/sys/class/backlight/ocp8178/brightness'),
                bl_power=read('/sys/class/backlight/ocp8178/bl_power'))


def summarize_manager(dump, properties):
    # Parse only unit headings. Environment strings in a full dump stay on the
    # device and are not retained in this report or sent to the host.
    units = re.findall(r'^→ Unit (.+):$', dump, re.M)
    if not units or len(units) != len(set(units)):
        raise ValueError('Missing or duplicate unit headings')
    legacy = [n for n in units if re.fullmatch(r'(?:dev-|sys-devices-virtual-tty-)'+LEGACY+r'\.device', n)]
    values = dict(line.split('=', 1) for line in properties.splitlines() if '=' in line)
    times = {key: int(values[key]) for key in TIMESTAMPS}
    ordered = [times[key] for key in TIMESTAMPS]
    if any(value <= 0 for value in ordered) or ordered != sorted(ordered):
        raise ValueError('Incomplete or inconsistent manager startup clocks')
    return dict(unit_count=len(units), types=dict(Counter(n.rsplit('.', 1)[-1] for n in units)),
                legacy_device_units=len(legacy), timestamps_us=times,
                startup_seconds=(ordered[-1]-ordered[0])/1e6,
                generators_seconds=(ordered[2]-ordered[1])/1e6,
                unit_load_seconds=(ordered[4]-ordered[3])/1e6)


def pty_smoke():
    """Allocate only our own PTY, test both directions and window-size ioctls."""
    master, slave = os.openpty()
    try:
        name = os.ttyname(slave)
        if not re.fullmatch(r'/dev/pts/[0-9]+', name):
            raise ValueError('Expected a Unix98 slave')
        tty.setraw(slave)
        for source, target, payload in ((master, slave, b'neo-to-slave\n'),
                                        (slave, master, b'neo-to-master\n')):
            if os.write(source, payload) != len(payload):
                raise ValueError('Short PTY write')
            received = b''
            # A fixed small payload and bounded read count avoid an interactive
            # terminal protocol or indefinite wait even if a driver misbehaves.
            for _ in range(len(payload)):
                if not select.select([target], [], [], 2)[0]:
                    raise TimeoutError('PTY read did not become ready')
                received += os.read(target, len(payload)-len(received))
                if len(received) == len(payload):
                    break
            if received != payload:
                raise ValueError('PTY data changed')
        size = struct.pack('HHHH', 24, 80, 0, 0)
        fcntl.ioctl(master, termios.TIOCSWINSZ, size)
        if fcntl.ioctl(slave, termios.TIOCGWINSZ, b'\0'*8) != size:
            raise ValueError('PTY resize did not propagate')
        return dict(unix98=True, both_directions=True, resize=True)
    finally:
        os.close(slave)
        os.close(master)


def inspect(expected):
    if expected not in ('either', 'enabled', 'disabled'):
        raise ValueError('Unknown legacy PTY expectation')
    before = health()
    text = gzip.decompress(Path('/proc/config.gz').read_bytes()).decode()
    config = dict(re.findall(r'^(CONFIG_\w+)=(.*)$', text, re.M))
    selected = {key: config.get(key, 'n') for key in CONFIG}
    for key in CONFIG:
        if key not in ('CONFIG_LEGACY_PTYS', 'CONFIG_LEGACY_PTY_COUNT') and selected[key] != 'y':
            raise ValueError('Required terminal support is absent: '+key)
    if expected != 'either' and selected['CONFIG_LEGACY_PTYS'] != ('y' if expected == 'enabled' else 'n'):
        raise ValueError('Unexpected legacy PTY configuration')
    sysfs = sorted(p.name for p in Path('/sys/class/tty').iterdir() if re.fullmatch(LEGACY, p.name))
    manager = summarize_manager(command('systemd-analyze', '--user', 'dump'),
                                command('systemctl', '--user', 'show',
                                        *['--property='+key for key in TIMESTAMPS]))
    if selected['CONFIG_LEGACY_PTYS'] == 'n' and (sysfs or manager['legacy_device_units']):
        raise ValueError('Legacy PTYs remain despite disabled configuration')
    result = dict(schema=1, before=before, config=selected, legacy_sysfs_count=len(sysfs),
                  manager=manager, pty=pty_smoke())
    after = health()
    result['after'] = after
    if before != after:
        raise ValueError('Boot, PM or display state changed during awake inspection')
    result['passed'] = True
    return result


def ssh_pty(client):
    channel = client.get_transport().open_session(timeout=10)
    try:
        channel.settimeout(15)
        channel.get_pty(term='vt100', width=80, height=24)
        channel.exec_command('tty')
        data = bytearray()
        while len(data) <= 128:
            chunk = channel.recv(129-len(data))
            if not chunk:
                break
            data.extend(chunk)
        if (len(data) > 128 or not re.fullmatch(rb'/dev/pts/[0-9]+\r?\n', data) or
                channel.recv_exit_status() != 0):
            raise ValueError('SSH terminal allocation failed')
        return True
    finally:
        channel.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--on-device', action='store_true')
    parser.add_argument('--legacy', choices=('either', 'enabled', 'disabled'),
                        default=os.environ.get('NEO_LEGACY_PTYS', 'either'))
    args = parser.parse_args()
    if args.on_device:
        print(json.dumps(inspect(args.legacy), indent=2))
        return
    from host_timing import capture_timing
    from private_config import load_env
    from remote import device, evidence_directory, run
    os.umask(0o077)
    capture = evidence_directory()
    print('Private user-manager/PTY evidence:', capture, flush=True)
    with capture_timing(capture), device(load_env(), os.environ.get('NEO_ROUTE', 'usb')) as client:
        # Deliberately use the ordinary SSH user, not sudo/root: its own user
        # manager and PTY permissions are what this check must exercise.
        value = json.loads(run(client, shlex.join(['python3', '-B', '-', '--on-device', '--legacy', args.legacy]),
                               input_data=Path(__file__).read_bytes(), display=False, timeout=60))
        (capture/'user-startup.json').write_text(json.dumps(value, indent=2)+'\n')
        value['ssh_pty_verified'] = ssh_pty(client)
        (capture/'user-startup.json').write_text(json.dumps(value, indent=2)+'\n')
    print(json.dumps(dict(manager=value['manager'], legacy_sysfs_count=value['legacy_sysfs_count'],
                          pty=value['pty'], ssh_pty_verified=value['ssh_pty_verified']), indent=2))


if __name__ == '__main__':
    main()
