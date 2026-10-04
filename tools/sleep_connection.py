"""Explicit connection profiles and passive cable evidence for RTC diagnostics."""
from pathlib import Path
import math
import re
import time


def profile(value):
    if value not in ('usb', 'battery'):
        raise ValueError('Sleep connection must be usb or battery')
    return value


def cable_irqs(text):
    rows = text.splitlines()
    cpus = rows[0].split() if rows else []
    if not cpus or any(not re.fullmatch(r'CPU\d+', c) for c in cpus):
        raise ValueError('Invalid cable interrupt CPU columns')
    found = {}
    names = {2: 'ACIN_PLUGIN', 3: 'ACIN_REMOVAL', 5: 'VBUS_PLUGIN', 6: 'VBUS_REMOVAL'}
    for row in rows[1:]:
        fields = row.split()
        offset = 1 + len(cpus)
        if len(fields) <= offset + 2 or fields[offset] != 'axp22x_irq_chip':
            continue
        number = int(fields[offset + 1])
        if number not in names:
            continue
        name = names[number]
        counts = [int(v) for v in fields[1:offset]]
        if name in found or any(v < 0 for v in counts):
            raise ValueError('Invalid cable interrupt count')
        found[name] = sum(counts)
    if set(found) != set(names.values()):
        raise ValueError('Missing AXP223 cable interrupt handlers')
    return dict(cpus=cpus, counts=found)


def observe():
    """Read only; no polling worker, IRQ clearing or register access."""
    read = lambda p: Path(p).read_text().strip()
    extcons = [p for p in Path('/sys/class/extcon').glob('*/state')
               if '1c19400.phy' in str(p.resolve())]
    udcs = list(Path('/sys/class/udc').glob('*/state'))
    if len(extcons) != 1 or len(udcs) != 1:
        raise ValueError('Require the single qualified Allwinner PHY and UDC')
    return dict(boot_id=read('/proc/sys/kernel/random/boot_id'),
        monotonic_seconds=time.monotonic(), udc=read(udcs[0]),
        carrier=read('/sys/class/net/usb0/carrier'),
        extcon=read(extcons[0]),
        supplies={name: {field: read('/sys/class/power_supply/'+name+'/'+field)
                        for field in ('type', 'present', 'online')}
                  for name in ('axp20x-usb', 'axp22x-ac')},
        irqs=cable_irqs(read('/proc/interrupts')))


def absent(value):
    expected = {'axp20x-usb': dict(type='USB', present='0', online='0'),
                'axp22x-ac': dict(type='Mains', present='0', online='0')}
    if (value['udc'] != 'not attached' or value['carrier'] != '0' or
            value['extcon'].splitlines() != ['USB=0', 'USB-HOST=0'] or
            value['supplies'] != expected):
        raise ValueError('Battery sleep requires absent USB/AC, PHY cable and USB carrier')
    t = value['monotonic_seconds']
    irq = value['irqs']
    if (type(t) not in (int, float) or not math.isfinite(t) or t < 0 or
            not irq['cpus'] or len(set(irq['cpus'])) != len(irq['cpus']) or
            any(not re.fullmatch(r'CPU\d+', c) for c in irq['cpus']) or
            set(irq['counts']) != {'ACIN_PLUGIN', 'ACIN_REMOVAL', 'VBUS_PLUGIN', 'VBUS_REMOVAL'} or
            any(type(n) is not int or n < 0 for n in irq['counts'].values())):
        raise ValueError('Invalid battery cable observation time or interrupt evidence')


def unchanged(before, after):
    for value in (before, after):
        absent(value)
    if (before['boot_id'] != after['boot_id'] or before['irqs'] != after['irqs'] or
            before['monotonic_seconds'] >= after['monotonic_seconds']):
        raise ValueError('Cable interrupt, boot or observation order changed')


def validate(record):
    if profile(record.get('connection', 'usb')) == 'usb':
        return
    if record.get('cable_absent_confirmed') is not True:
        raise ValueError('Missing physical cable-absence confirmation')
    cable = record['cable']
    unchanged(cable['before'], cable['entry'])
    unchanged(cable['entry'], cable['after'])
    if any(cable[side]['boot_id'] != record['before']['boot_id'] for side in ('before', 'entry', 'after')):
        raise ValueError('Cable observations belong to another boot')
    # Three state samples and IRQ counts are not electrical edge instrumentation.
    # Physical absence still requires the observer to leave the cable untouched.
