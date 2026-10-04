"""Explicit connection profiles and passive cable evidence for RTC diagnostics."""
from pathlib import Path
import math
import re
import time


def profile(value):
    if value not in ('usb', 'battery', 'usb-remove', 'usb-attach'):
        raise ValueError('Unknown sleep connection profile')
    return value


def transition(value):
    return profile(value) in ('usb-remove', 'usb-attach')


def endpoint(value, mode='rtc-wake', side='before'):
    """Ordinary health gates for the scenario's explicit starting/ending state."""
    profile(value)
    if mode not in ('rehearse', 'rtc-wake') or side not in ('before', 'after'):
        raise ValueError('Unknown cable phase')
    initial = {'usb-remove': 'usb', 'usb-attach': 'battery'}.get(value, value)
    if transition(value) and mode == 'rtc-wake' and side == 'after':
        return 'battery' if initial == 'usb' else 'usb'
    return initial


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
    evidence(value)


def evidence(value):
    t = value['monotonic_seconds']
    irq = value['irqs']
    if (type(t) not in (int, float) or not math.isfinite(t) or t < 0 or
            not irq['cpus'] or len(set(irq['cpus'])) != len(irq['cpus']) or
            any(not re.fullmatch(r'CPU\d+', c) for c in irq['cpus']) or
            set(irq['counts']) != {'ACIN_PLUGIN', 'ACIN_REMOVAL', 'VBUS_PLUGIN', 'VBUS_REMOVAL'} or
            any(type(n) is not int or n < 0 for n in irq['counts'].values())):
        raise ValueError('Invalid battery cable observation time or interrupt evidence')


def present(value):
    expected = {'axp20x-usb': dict(type='USB', present='1', online='1'),
                'axp22x-ac': dict(type='Mains', present='1', online='1')}
    if (value['udc'] != 'configured' or value['carrier'] != '1' or
            value['extcon'].splitlines() != ['USB=1', 'USB-HOST=0'] or
            value['supplies'] != expected):
        raise ValueError('Cable test requires configured USB, carrier and both external inputs')
    evidence(value)


def state(value, connection):
    if connection == 'battery':
        absent(value)
    elif connection == 'usb':
        present(value)
    else:
        raise ValueError('Expected an endpoint connection state')


def unchanged(before, after, connection='battery'):
    for value in (before, after):
        state(value, connection)
    if (before['boot_id'] != after['boot_id'] or before['irqs'] != after['irqs'] or
            before['monotonic_seconds'] >= after['monotonic_seconds']):
        raise ValueError('Cable interrupt, boot or observation order changed')


def validate(record):
    connection = profile(record.get('connection', 'usb'))
    if connection == 'usb':
        return
    if transition(connection):
        return validate_transition(record)
    if record.get('cable_absent_confirmed') is not True:
        raise ValueError('Missing physical cable-absence confirmation')
    cable = record['cable']
    unchanged(cable['before'], cable['entry'])
    unchanged(cable['entry'], cable['after'])
    if any(cable[side]['boot_id'] != record['before']['boot_id'] for side in ('before', 'entry', 'after')):
        raise ValueError('Cable observations belong to another boot')
    # Three state samples and IRQ counts are not electrical edge instrumentation.
    # Physical absence still requires the observer to leave the cable untouched.


def validate_transition(record):
    connection, mode = record['connection'], record['mode']
    if record.get('cable_action_confirmed') is not True:
        raise ValueError('Missing physical cable-action readiness')
    if endpoint(connection) == 'battery' and record.get('cable_absent_confirmed') is not True:
        raise ValueError('Missing initial physical cable-absence confirmation')
    cable = record['cable']
    sources = record['before']['image'].get('sources', {})
    irq_policy = sources.get('features', {}).get('sleep_cable_irq_policy', 'exact-v1')
    if irq_policy not in ('exact-v1', 'masked-removal-v1'):
        raise ValueError('Unknown sleep cable IRQ policy')
    if irq_policy == 'masked-removal-v1' and (
            sources.get('board') != 'gameshellneo-cpi31' or
            sources.get('features', {}).get('usb_system_wakeup') is not False or
            record['before']['image'] != record['after']['image']):
        raise ValueError('Masked removal policy requires the matching CPI v3.1 image')
    initial = endpoint(connection, mode)
    assessment = None
    unchanged(cable['before'], cable['entry'], initial)
    if mode == 'rehearse':
        unchanged(cable['entry'], cable['after'], initial)
    else:
        a, b = cable['entry'], cable['after']
        state(b, endpoint(connection, mode, 'after'))
        if (a['boot_id'] != b['boot_id'] or a['irqs']['cpus'] != b['irqs']['cpus'] or
                a['monotonic_seconds'] >= b['monotonic_seconds']):
            raise ValueError('Cable-transition boot, CPU inventory or time order changed')
        direction = 'PLUGIN' if connection == 'usb-attach' else 'REMOVAL'
        delta = {k: b['irqs']['counts'][k] - v for k, v in a['irqs']['counts'].items()}
        masked = irq_policy == 'masked-removal-v1' and connection == 'usb-remove'
        for name, count in delta.items():
            allowed = (0, 1) if masked and name.endswith(direction) else (int(name.endswith(direction)),)
            if count not in allowed:
                raise ValueError('Cable IRQ delta violates the recorded image policy')
        assessment = dict(policy=irq_policy, deltas=delta,
            removal_dispatch_may_be_masked=masked,
            requested_handlers_observed=all(v == 1 for k, v in delta.items() if k.endswith(direction)),
            electrical_edge_timing_qualified=False,
            limits='Handler counts are dispatch evidence, not electrical edge timestamps. '
                   'Masked removal may be acknowledged by regmap before its handler runs.')
    if any(cable[side]['boot_id'] != record['before']['boot_id'] for side in ('before', 'entry', 'after')):
        raise ValueError('Cable observations belong to another boot')
    # IRQ dispatch can be deferred until resume. These counts do not timestamp
    # the electrical edge or prove it occurred inside machine_suspend.
    return assessment
