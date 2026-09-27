#!/usr/bin/env python3
"""Bounded CPI v3.1 USB observation; never writes hardware configuration."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import time

PMIC = Path('/sys/kernel/debug/regmap/sunxi-rsb-3a3')
MODE = Path('/sys/devices/platform/soc/1c19000.usb/musb-hdrc.2.auto/mode')
SUPPLIES = ('axp20x-usb', 'axp22x-ac')
INTERVAL = 0.02


def read(path):
    return Path(path).read_text().strip().rstrip('\0')


def irq_counts(text):
    lines = text.splitlines()
    cpus = lines[0].split() if lines else []
    if not cpus or any(not re.fullmatch(r'CPU\d+', cpu) for cpu in cpus):
        raise ValueError('Invalid interrupt CPU columns')
    found = {}
    names = {2: 'ACIN_PLUGIN', 3: 'ACIN_REMOVAL', 5: 'VBUS_PLUGIN', 6: 'VBUS_REMOVAL'}
    for line in lines[1:]:
        fields = line.split()
        offset = 1 + len(cpus)
        if len(fields) <= offset + 2 or fields[offset] != 'axp22x_irq_chip':
            continue
        number = int(fields[offset + 1])
        if number not in names:
            continue
        key = names[number]
        if key in found:
            raise ValueError('Duplicate PMIC interrupt')
        counts = [int(value) for value in fields[1:offset]]
        if any(value < 0 for value in counts):
            raise ValueError('Negative interrupt count')
        found[key] = sum(counts)
    if not {'VBUS_PLUGIN', 'VBUS_REMOVAL'} <= found.keys():
        raise ValueError('AXP223 USB interrupt handlers unavailable')
    return dict(cpus=cpus, counts=found)


def check_counts(before, after):
    if before['cpus'] != after['cpus'] or before['counts'].keys() != after['counts'].keys():
        raise ValueError('Interrupt layout changed')
    if any(after['counts'][key] < value for key, value in before['counts'].items()):
        raise ValueError('Interrupt counter decreased')


def pmic_configuration(directory=PMIC):
    # This exact locked 8-bit regmap has one contiguous printable range and
    # seven-byte rows. pread requests ONLY named, non-destructive registers.
    # Never dump IRQ-status registers, write cache controls, or bypass regcache.
    if read(directory / 'range') != '0-e6':
        raise ValueError('Unsupported PMIC debugfs layout')
    values = {}
    fd = os.open(directory / 'registers', os.O_RDONLY)
    try:
        for register in (0x00, 0x30, 0x40, 0x8f):
            row = os.pread(fd, 7, register * 7).decode('ascii')
            match = re.fullmatch(f'{register:02x}: ([0-9a-f]{{2}})\n', row)
            if not match:
                raise ValueError('Unexpected PMIC row or failed register read')
            values[f'{register:02x}'] = int(match[1], 16)
    finally:
        os.close(fd)
    return dict(registers=values, control_values_may_be_cached=True,
                note='00/40 are volatile; 30/8f use normal regmap cache. Not pin-voltage measurements.')


def parse_uevent(data, sender_pid, flags=0):
    if flags & socket.MSG_TRUNC:
        raise ValueError('Truncated netlink event')
    if sender_pid != 0:
        return None
    fields = dict(part.split('=', 1) for part in data.decode('utf-8', errors='strict').split('\0')
                  if '=' in part)
    if fields.get('SUBSYSTEM') != 'power_supply' or fields.get('POWER_SUPPLY_NAME') not in SUPPLIES:
        return None
    allowed = ('ACTION', 'DEVPATH', 'SUBSYSTEM', 'SEQNUM', 'POWER_SUPPLY_NAME',
               'POWER_SUPPLY_PRESENT', 'POWER_SUPPLY_ONLINE', 'POWER_SUPPLY_HEALTH')
    return {key: fields[key] for key in allowed if key in fields}


def properties():
    started = time.monotonic()
    supplies = {}
    for name in SUPPLIES:
        base = Path('/sys/class/power_supply') / name
        supplies[name] = {key: int(read(base / key)) for key in ('present', 'online')}
    guard = json.loads(read('/run/gameshellneo/battery.json'))
    if (guard.get('monitoring') != 'valid' or guard.get('capacity_percent', 0) <= 20 or
            not 0 <= time.monotonic() - guard['monotonic_seconds'] < 35):
        raise ValueError('Battery monitoring invalid, stale, or charge too low for cable tests')
    if int(read('/proc/sys/kernel/tainted')):
        raise ValueError('Kernel tainted')
    return dict(start=started, end=time.monotonic(), supplies=supplies, guard=guard)


def record(seconds):
    controllers = list(Path('/sys/class/udc').glob('*/state'))
    if len(controllers) != 1:
        raise ValueError('Expected one USB controller')
    compatible = read('/sys/class/power_supply/axp20x-usb/device/of_node/compatible')
    if compatible != 'x-powers,axp223-usb-power-supply':
        raise ValueError('Recorder is specific to AXP223')
    role = read('/sys/firmware/devicetree/base/soc/usb@1c19000/dr_mode')
    if role != 'peripheral':
        raise ValueError('Expected the diagnostic peripheral-only configuration')
    boot = read('/proc/sys/kernel/random/boot_id')
    extcons = [p for p in Path('/sys/class/extcon').glob('*/state')
               if '1c19400.phy' in str(p.resolve())]
    sequence = 0

    def emit(event, **values):
        nonlocal sequence
        print(json.dumps(dict(event=event, sequence=sequence, boot_id=boot,
                              monotonic=time.monotonic(), **values)), flush=True)
        sequence += 1

    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(number, stop)
    # Kernel uevents, independent of the SSH connection and the sysfs sampler.
    with socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, 15) as events:
        events.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
        events.bind((0, 1))
        events.setblocking(False)
        emit('ready', utc=datetime.now(timezone.utc).isoformat(), kernel=os.uname().release,
             compatible=compatible, role=role, pmic=pmic_configuration(),
             regulator_summary=read('/sys/kernel/debug/regulator/regulator_summary'),
             interval_seconds=INTERVAL, properties_interval_seconds=1,
             limits='Userspace observation times, not physical edge times; no power measurement.')
        start = time.monotonic()
        start_cpu = time.process_time()
        next_tick = start
        previous = None
        last_sample = None
        last_emit = start
        max_gap = 0
        samples = 0
        try:
            while not stopped and time.monotonic() - start < seconds:
                readable, _, _ = select.select([events], [], [], max(0, next_tick - time.monotonic()))
                if readable:
                    # Bound a burst so event traffic cannot starve state sampling.
                    for _ in range(64):
                        try:
                            data, _, flags, address = events.recvmsg(65536)
                        except BlockingIOError:
                            break
                        event = parse_uevent(data, address[0], flags)
                        if event is not None:
                            emit('uevent', fields=event)
                now = time.monotonic()
                if now < next_tick:
                    continue
                if last_sample is not None:
                    gap = now - last_sample
                    max_gap = max(max_gap, gap)
                    if gap > 0.1:
                        emit('sampling_gap', seconds=gap)
                sample_start = now
                current = dict(state=read(controllers[0]), irqs=irq_counts(read('/proc/interrupts')),
                               otg_mode=read(MODE), extcon={p.parent.name: read(p) for p in extcons})
                sample_end = time.monotonic()
                if previous is not None:
                    check_counts(previous['irqs'], current['irqs'])
                changed = current != previous
                if changed or now - last_emit >= 1:
                    if read('/proc/sys/kernel/random/boot_id') != boot:
                        raise ValueError('Boot identity changed')
                    power = properties()
                    emit('snapshot', reason='change' if changed else 'heartbeat',
                         start=sample_start, end=sample_end, previous_sample=last_sample,
                         power=power, **current)
                    last_emit = now
                previous = current
                last_sample = now
                samples += 1
                # No catch-up burst after a late observation.
                next_tick = max(next_tick + INTERVAL, time.monotonic())
            emit('complete', samples=samples, max_sample_gap_seconds=max_gap,
                 duration_seconds=time.monotonic() - start, stopped=stopped,
                 observer_cpu_seconds=time.process_time() - start_cpu,
                 process_total_cpu_seconds=time.process_time())
        except (OSError, ValueError, KeyError) as error:
            emit('failed', error=str(error))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=600)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 900:
        parser.error('seconds must be in 5..900')
    record(args.seconds)


if __name__ == '__main__':
    main()
