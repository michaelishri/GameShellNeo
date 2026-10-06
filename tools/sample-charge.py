#!/usr/bin/env python3
"""Bounded USB-connected awake battery telemetry; no power or display writes."""
import argparse
import json
import signal
import sys
import time

import charge_inventory as inventory

INTERVAL_NS = 10_000_000_000
READ_BUDGET_NS = 2_000_000_000
LIMITS = [
    'Awake instantaneous samples; current and gauge are uncalibrated.',
    'Trapezoidal current integration is a sampled estimate, not a hardware '
    'charge integral. Between-sample variation is unmeasured.',
    'No charging-through-sleep, battery-capacity or standby-energy conclusion.',
    'Clock/PM checks reject detected sleep; sub-bracket transitions with a '
    'pending PM counter update cannot be excluded absolutely.',
]


def emit(event, **fields):
    print(json.dumps(dict(event=event, **fields)), flush=True)


def capture(index):
    before = inventory.checkpoint()
    supplies = inventory.supply_inventory()
    state = {name: inventory.read(path) for name, path in {
        'brightness': '/sys/class/backlight/ocp8178/brightness',
        'bl_power': '/sys/class/backlight/ocp8178/bl_power',
        'temperature_millic': '/sys/class/thermal/thermal_zone0/temp',
        'taint': '/proc/sys/kernel/tainted',
    }.items()}
    return dict(index=index, before=before, after=inventory.checkpoint(),
                supplies=supplies, state=state)


def integer(value):
    if not isinstance(value, str) or not value.lstrip('-').isdigit():
        raise ValueError('Expected an integer sysfs reading')
    return int(value)


def validate(sample, previous=None):
    before, after = sample['before'], sample['after']
    inventory.validate_continuity(before, after)
    if after['clock']['boottime_ns']-before['clock']['boottime_ns'] > READ_BUDGET_NS:
        raise ValueError('Battery sample exceeded read budget')
    supplies, state = sample['supplies'], sample['state']
    for name, kind in (('axp20x-usb', 'USB'), ('axp22x-ac', 'Mains')):
        supply = supplies[name]
        if supply['type'] != kind or supply['present'] != '1' or supply['online'] != '1':
            raise ValueError('Connected external power changed or is unavailable')
    battery = supplies['axp20x-battery']
    if (battery['type'] != 'Battery' or battery['present'] != '1' or battery['health'] != 'Good' or
            battery['status'] not in ('Charging', 'Full', 'Not charging') or
            not 20 < integer(battery['capacity']) <= 100 or
            not 0 <= integer(battery['current_now']) <= 4095000 or
            not 0 < integer(battery['voltage_now']) < 6000000 or
            integer(state['taint']) != 0 or not 0 <= integer(state['temperature_millic']) < 80000):
        raise ValueError('Awake charging telemetry conditions failed')
    if previous is None:
        if sample['index'] != 0:
            raise ValueError('Expected first sample index zero')
        return
    inventory.validate_continuity(previous['after'], before)
    separation = before['clock']['boottime_ns']-previous['before']['clock']['boottime_ns']
    if (sample['index'] != previous['index']+1 or
            not INTERVAL_NS-READ_BUDGET_NS <= separation <= INTERVAL_NS+READ_BUDGET_NS):
        raise ValueError('Missed, extra or delayed battery sample')
    for key in ('brightness', 'bl_power'):
        if state[key] != previous['state'][key]:
            raise ValueError('Display changed during awake charging baseline')
    previous_battery = previous['supplies']['axp20x-battery']
    for key in ('constant_charge_current', 'constant_charge_current_max', 'voltage_max'):
        if battery[key] != previous_battery[key]:
            raise ValueError('Charging configuration changed during baseline')
    if supplies['axp20x-usb']['input_current_limit'] != previous['supplies']['axp20x-usb']['input_current_limit']:
        raise ValueError('USB input limit changed during baseline')


def summary(samples, seconds):
    if len(samples) != seconds//10+1:
        raise ValueError('Incomplete charging sample sequence')
    previous = None
    for sample in samples:
        validate(sample, previous)
        previous = sample
    def midpoint(sample):
        return (sample['before']['clock']['boottime_ns']+sample['after']['clock']['boottime_ns'])/2
    currents = [integer(s['supplies']['axp20x-battery']['current_now']) for s in samples]
    capacities = [integer(s['supplies']['axp20x-battery']['capacity']) for s in samples]
    duration = (midpoint(samples[-1])-midpoint(samples[0]))/1e9
    if abs(duration-seconds) > 2:
        raise ValueError('Charging trace duration differs from requested bound')
    estimate = sum((currents[i-1]+currents[i])/2 *
                   (midpoint(samples[i])-midpoint(samples[i-1]))/1e9/3600
                   for i in range(1, len(samples)))
    return dict(samples=len(samples), elapsed_seconds=duration,
                current_ua_min=min(currents), current_ua_max=max(currents),
                capacity_percent_first=capacities[0], capacity_percent_last=capacities[-1],
                sampled_net_charge_estimate_uah=estimate,
                sleep_charge_measured=False, limits=LIMITS)


def collect(seconds):
    samples = []
    anchor = time.monotonic_ns()
    for index in range(seconds//10+1):
        delay = (anchor+index*INTERVAL_NS-time.monotonic_ns())/1e9
        if delay > 0:
            time.sleep(delay)
        sample = capture(index)
        # Preserve a rejected observation before evaluating its eligibility.
        emit('sample', sample=sample)
        validate(sample, samples[-1] if samples else None)
        samples.append(sample)
    return summary(samples, seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args()
    if not 60 <= args.seconds <= 600 or args.seconds % 10:
        parser.error('Use a multiple of ten seconds in 60..600')
    def interrupted(_signum, _frame):
        raise InterruptedError('Charging baseline interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    initial = {}
    try:
        inventory.inspect(args.kernel, args.image, initial)
        emit('started', schema_version=1, seconds=args.seconds, interval_seconds=10,
             inventory=initial, limits=LIMITS)
        result = collect(args.seconds)
        emit('completed', passed=True, summary=result)
        return 0
    except (OSError, ValueError, KeyError) as error:
        emit('failed', passed=False, error=str(error), initial_inventory=initial, limits=LIMITS)
        return 1


if __name__ == '__main__':
    sys.exit(main())
