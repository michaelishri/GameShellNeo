#!/usr/bin/env python3
"""Read documented AXP223 charge/gauge fields; never write controls or enter PM."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

REGMAP = Path('/sys/kernel/debug/regmap/sunxi-rsb-3a3')
PMIC = Path('/sys/bus/sunxi-rsb/devices/sunxi-rsb-3a3')
SUPPLIES = Path('/sys/class/power_supply')
BOOT = Path('/proc/sys/kernel/random/boot_id')
STATS = Path('/sys/power/suspend_stats')
IMAGE = Path('/etc/gameshellneo/image.json')
BOARD = Path('/sys/firmware/devicetree/base/compatible')
# Deliberately exclude IRQ status, undocumented E2/E3 and out-of-range E8/EC.
REGISTERS = (0x00, 0x01, 0x33, 0x34, 0x78, 0x79, 0xb8, 0xb9, 0xe0, 0xe1, 0xe6)
SCHEMA_VERSION = 4
MASKED_ADC_PROFILE = ('0.1.0-diagnostic.22', '6.18.54-gameshellneo21')
NO_LEGACY_PTY_PROFILE = ('0.1.0-diagnostic.23', '6.18.54-gameshellneo22')
PROFILES = {
    ('0.1.0-diagnostic.20', '6.18.54-gameshellneo19'):
        ('axp22x-cached-b8', frozenset((0x00, 0x01, 0x78, 0x79, 0xb9))),
    ('0.1.0-diagnostic.21', '6.18.54-gameshellneo20'):
        ('axp223-volatile-b8', frozenset((0x00, 0x01, 0x78, 0x79, 0xb8, 0xb9))),
    MASKED_ADC_PROFILE:
        ('axp223-volatile-b8', frozenset((0x00, 0x01, 0x78, 0x79, 0xb8, 0xb9))),
    NO_LEGACY_PTY_PROFILE:
        ('axp223-volatile-b8', frozenset((0x00, 0x01, 0x78, 0x79, 0xb8, 0xb9))),
}
LIMITS = [
    'One awake, sequential inventory; not an atomic electrical snapshot.',
    'Nonvolatile register values may come from the kernel cache, including '
    'E0/E1 capacity. B8 provenance follows the admitted image/kernel profile '
    'and observed metadata. No cache bypass is performed.',
    'Current is instantaneous; percentage and configured capacity are not '
    'integrated charge or calibrated battery capacity.',
    'REG34 bit 2 has contradictory polarity descriptions in the AXP223 '
    'manuals; its raw value is not interpreted as an enabled setting.',
    'Voltage bytes are separate volatile reads with no established latch '
    'contract. Formula results are not a coherent or calibrated voltage sample; '
    'the Linux formula follows the admitted image/kernel ADC-width profile.',
    'No accumulated-charge measurement or charging-through-sleep conclusion.',
]


def read(path):
    return Path(path).read_text().strip()


def clock():
    lower = time.monotonic_ns()
    boot = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    upper = time.monotonic_ns()
    return dict(monotonic_before_ns=lower, boottime_ns=boot,
                monotonic_after_ns=upper, offset_low_ns=boot-upper,
                offset_high_ns=boot-lower)


def checkpoint():
    return dict(boot_id=read(BOOT), clock=clock(),
                pm={name: read(STATS/name) for name in ('success', 'fail')})


def validate_continuity(before, after):
    if before['boot_id'] != after['boot_id'] or before['pm'] != after['pm']:
        raise ValueError('Boot or PM counters changed during inventory')
    a, b = before['clock'], after['clock']
    if (b['monotonic_before_ns'] < a['monotonic_after_ns'] or
            b['boottime_ns'] < a['boottime_ns'] or
            b['offset_low_ns'] > a['offset_high_ns']):
        raise ValueError('Clock discontinuity or suspend detected during inventory')


def metadata():
    return {name: read(REGMAP/name)
            for name in ('name', 'range', 'access', 'cache_only', 'cache_bypass')}


def profile_for(kernel, version):
    try:
        return PROFILES[(version, kernel)]
    except KeyError:
        raise ValueError('Re-audit the exact image/kernel register contract') from None


def validate_metadata(meta, volatile):
    # Pinned AXP22x 8-bit regmap, stride 1, no hidden registers. Its debugfs
    # output is exactly seven bytes per register ("00: ff\n"). Reject any
    # changed layout BEFORE opening/reading the register file.
    if (meta['name'] != 'axp20x-rsb' or meta['range'] != '0-e6' or
            meta['cache_only'] != 'N' or meta['cache_bypass'] != 'N'):
        raise ValueError('Unexpected AXP223 regmap layout or cache mode')
    rows = meta['access'].splitlines()
    if len(rows) != 0xe7:
        raise ValueError('Incomplete AXP223 access metadata')
    for address, row in enumerate(rows):
        match = re.fullmatch(r'([0-9a-f]{2}): ([yn]) ([yn]) ([yn]) ([yn])', row)
        if (not match or int(match[1], 16) != address or
                match[2] != 'y' or match[5] != 'n'):
            raise ValueError('Unexpected register visibility or ordering')
        if address in REGISTERS and (match[4] == 'y') != (address in volatile):
            raise ValueError('Changed cache policy for an observed register')


def read_registers(meta, volatile):
    validate_metadata(meta, volatile)
    output = {}
    # os.pread avoids Python buffered read-ahead into other PMIC registers.
    fd = os.open(REGMAP/'registers', os.O_RDONLY | os.O_CLOEXEC)
    try:
        for address in REGISTERS:
            start = clock()
            line = os.pread(fd, 7, address*7)
            end = clock()
            match = re.fullmatch(f'{address:02x}: ([0-9a-f]{{2}})\n'.encode(), line)
            if not match:
                raise ValueError(f'Register {address:02x} read failed or layout changed')
            output[f'{address:02x}'] = dict(value=int(match[1], 16),
                source='volatile-regmap-read' if address in volatile else 'regmap-cache-possible',
                before=start, after=end)
    finally:
        os.close(fd)
    return output


def decode(registers, *, adc_width_masked=False):
    values = {key: entry['value'] for key, entry in registers.items()}
    gauge, high = values['b8'], values['e0']
    capacity_raw = ((high & 0x7f) << 8) | values['e1']
    gauge_percent = values['b9'] & 0x7f
    voltage_high, voltage_low = values['78'], values['79']
    masked_voltage = (voltage_high << 4) | (voltage_low & 0x0f)
    legacy_voltage = (voltage_high << 4) | voltage_low
    linux_voltage = masked_voltage if adc_width_masked else legacy_voltage
    return dict(
        cached_configuration=dict(
            charger_enabled=bool(values['33'] & 0x80),
            capacity_configured=bool(high & 0x80), capacity_raw=capacity_raw,
            configured_capacity_uah=capacity_raw*1456 if high & 0x80 else None,
            warning1_percent=(values['e6'] >> 4)+5, warning2_percent=values['e6'] & 0xf),
        gauge_control=dict(raw=gauge, source=registers['b8']['source'],
            gauge_enabled=bool(gauge & 0x80), coulomb_counter_enabled=bool(gauge & 0x40),
            capacity_calibration_enabled=bool(gauge & 0x20),
            calibration_in_progress_bit=bool(gauge & 0x10)),
        charger_control2=dict(raw=values['34'], bit2=(values['34'] >> 2) & 1,
            source='regmap-cache-possible',
            bit2_interpretation='unresolved: Chinese v1.1 says 1 follows charging '
                'current; English v1.0 says 1 disables this behavior'),
        battery_voltage_bytes=dict(high=voltage_high, low=voltage_low,
            unused_low_bits=voltage_low & 0xf0,
            masked_12bit_formula_uv=masked_voltage*1100,
            unmasked_legacy_formula_uv=legacy_voltage*1100,
            linux_helper_width_masked=adc_width_masked,
            linux_helper_formula_uv=linux_voltage*1100,
            unused_bits_change_formula=masked_voltage != legacy_voltage,
            coherent_sample_established=False, physical_accuracy_qualified=False),
        gauge_result=dict(valid=bool(values['b9'] & 0x80) and gauge_percent <= 100,
                          percent=gauge_percent),
        accumulated_charge_available=False,
        charging_during_sleep='not-measured')


def supply_inventory():
    fields = {
        'axp20x-battery': ('type', 'present', 'status', 'health', 'capacity', 'current_now',
                          'voltage_now', 'voltage_max', 'constant_charge_current',
                          'constant_charge_current_max'),
        'axp20x-usb': ('type', 'present', 'online', 'input_current_limit'),
        'axp22x-ac': ('type', 'present', 'online'),
    }
    return {name: {field: read(SUPPLIES/name/field) for field in names}
            for name, names in fields.items()}


def inspect(kernel, version, result=None):
    if result is None:
        result = {}
    result.update(schema_version=SCHEMA_VERSION, kind='axp223-charge-inventory', completed=False,
                  limits=LIMITS)
    profile, volatile = profile_for(kernel, version)
    adc_width_masked = (version, kernel) in (MASKED_ADC_PROFILE, NO_LEGACY_PTY_PROFILE)
    image = json.loads(read(IMAGE))
    compatibles = BOARD.read_bytes().rstrip(b'\0').split(b'\0')
    if (os.uname().release != kernel or image['version'] != version or image['kernel'] != kernel or
            image['board'] != 'gameshellneo-cpi31' or
            b'clockwork,clockworkpi-cpi3' not in compatibles or
            (PMIC/'of_node/compatible').read_bytes() != b'x-powers,axp223\0'):
        raise ValueError('Expected matching CPI3 image, kernel and AXP223 identity')
    before = checkpoint()
    result.update(kernel=kernel, image=image, before=before, cache_profile=profile,
                  adc_width_masked=adc_width_masked)
    meta = metadata()
    result['metadata'] = meta
    result['registers'] = read_registers(meta, volatile)
    result['supplies'] = supply_inventory()
    if metadata() != meta:
        raise ValueError('Regmap metadata/cache mode changed during inventory')
    after = checkpoint()
    result['after'] = after
    validate_continuity(before, after)
    result.update(completed=True, assessment=decode(result['registers'],
                  adc_width_masked=adc_width_masked))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    result = dict(schema_version=SCHEMA_VERSION, kind='axp223-charge-inventory', completed=False,
                  limits=LIMITS)
    try:
        inspect(args.kernel, args.image, result)
    except (OSError, ValueError, KeyError) as error:
        result.update(completed=False, error=str(error))
        print(json.dumps(result, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
