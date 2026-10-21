#!/usr/bin/python3
"""Awake-only diagnostic battery guard. No charger or gauge programming."""
import json
import logging
import os
from pathlib import Path
import subprocess
import time

INTERVAL = 10
THRESHOLD = 10
REQUIRED = 3
MAX_SAMPLE_SECONDS = 2


class ClockFault(ValueError):
    """An unusable observation, with original integers (or partial reads)."""

    def __init__(self, reason, observations):
        super().__init__(reason)
        self.observations = observations


def clocks():
    # Bracket BOOTTIME with MONOTONIC to bound syscall/preemption uncertainty.
    raw = {}
    try:
        raw['monotonic_ns'] = left = time.monotonic_ns()
        raw['boottime_ns'] = boot = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        raw['monotonic_right_ns'] = right = time.monotonic_ns()
    except (OSError, ValueError) as error:
        raise ClockFault('clock read failed: ' + str(error), [raw]) from error
    if any(type(value) is not int or value < 0 for value in raw.values()):
        raise ClockFault('invalid clock integer', [raw])
    if right < left:
        raise ClockFault('decreasing MONOTONIC bracket', [raw])
    return dict(raw, gap_low=boot-right, gap_high=boot-left)


def ordered(before, after):
    if (after['monotonic_ns'] < before['monotonic_right_ns'] or
            after['boottime_ns'] < before['boottime_ns']):
        raise ClockFault('decreasing consecutive clock observations', [before, after])


def saved_clock_fault(path, boot_id):
    # battery.json is both the atomic published state and the boot-local latch.
    # RuntimeDirectoryPreserve=yes keeps it through a service restart. Never
    # overwrite unreadable/malformed evidence with a clean state on startup.
    try:
        state = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    if (type(state) is not dict or state.get('boot_id') != boot_id or
            type(state.get('schema_version')) is not int or state['schema_version'] not in (2, 3)):
        raise ValueError('Existing battery state has an unknown schema or boot identity')
    if 'clock_fault' not in state:
        return None
    fault = state['clock_fault']
    if (type(fault) is not dict or type(fault.get('schema_version')) is not int or
            fault['schema_version'] != 1 or
            fault.get('boot_id') != boot_id or type(fault.get('count')) is not int or
            fault['count'] < 1 or any(type(fault.get(key)) is not dict or
                not isinstance(fault[key].get('reason'), str) or
                type(fault[key].get('observations')) is not list
                for key in ('first', 'last'))):
        raise ValueError('Existing battery clock-fault evidence is malformed')
    return fault


def crossed_suspend(before, after):
    # Non-overlapping offset bounds establish elapsed time excluded by MONOTONIC.
    return after['gap_low'] > before['gap_high']


def read_sample(root=Path('/sys/class/power_supply')):
    batteries = [p for p in root.iterdir() if (p / 'type').read_text().strip() == 'Battery']
    if len(batteries) != 1:
        raise ValueError('expected one battery')
    battery = batteries[0]
    if (battery / 'present').read_text().strip() != '1':
        raise ValueError('battery absent')
    capacity = int((battery / 'capacity').read_text())
    status = (battery / 'status').read_text().strip()
    voltage = int((battery / 'voltage_now').read_text())
    if not 0 <= capacity <= 100 or voltage <= 0:
        raise ValueError('invalid capacity or voltage')
    if status not in ('Charging', 'Discharging', 'Full', 'Not charging'):
        raise ValueError('unknown battery status')
    return {'capacity_percent': capacity, 'status': status, 'voltage_uv': voltage}


class Guard:
    def __init__(self):
        self.reset()

    def reset(self):
        self.count = 0
        self.previous = None

    def update(self, sample, now, resumed=False):
        # A delayed loop or invalid sample breaks the consecutive observation window.
        if resumed or (self.previous is not None and
                       not INTERVAL * 0.8 <= now - self.previous <= INTERVAL * 1.5):
            self.count = 0
        self.previous = now
        if sample is None or sample['status'] != 'Discharging' or sample['capacity_percent'] > THRESHOLD:
            self.count = 0
        else:
            self.count += 1
        return self.count >= REQUIRED


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    guard = Guard()
    state_dir = Path('/run/gameshellneo')
    state_dir.mkdir(exist_ok=True)
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    clock_fault = saved_clock_fault(state_dir / 'battery.json', boot_id)
    previous_state = None
    previous_clock = None
    while True:
        phase = 'start'
        now = monotonic = elapsed = None
        try:
            started = clocks()
            phase = 'between-samples'
            if previous_clock is not None:
                ordered(previous_clock, started)
            try:
                sample = read_sample()
                state = {'monitoring': 'valid', **sample}
            except (OSError, ValueError) as error:
                sample = None
                state = {'monitoring': 'degraded', 'reason': str(error)}
            phase = 'finish'
            finished = clocks()
            phase = 'sample-window'
            ordered(started, finished)
            elapsed = (finished['boottime_ns'] - started['boottime_ns']) / 1e9
            if elapsed > MAX_SAMPLE_SECONDS or crossed_suspend(started, finished):
                sample = None
                state = {'monitoring': 'degraded', 'reason': 'battery read delayed or crossed suspend'}
            resumed = previous_clock is not None and crossed_suspend(previous_clock, started)
            previous_clock = finished
            now = started['boottime_ns'] / 1e9
            monotonic = started['monotonic_ns'] / 1e9
            shutdown = guard.update(sample, now, resumed=resumed)
        except ClockFault as error:
            event = dict(phase=phase, reason=str(error), observations=error.observations)
            clock_fault = dict(schema_version=1, boot_id=boot_id,
                count=clock_fault['count'] + 1 if clock_fault else 1,
                first=clock_fault['first'] if clock_fault else event, last=event)
            logging.error('battery clock fault: %s', json.dumps(event))
            guard.reset()
            previous_clock = None
            shutdown = False
            state = {'monitoring': 'degraded', 'reason': 'unusable clock observation'}
        log_state = (state['monitoring'], state.get('status'), shutdown)
        if log_state != previous_state:
            logging.info('battery monitoring=%s status=%s critical=%s', *log_state)
            previous_state = log_state
        # Schema 3 forces older strict age consumers to reject this producer
        # instead of overlooking a latched fault after current readings recover.
        state.update(schema_version=3, sample_clock='CLOCK_BOOTTIME', boot_id=boot_id,
                     boottime_seconds=now, sample_monotonic_seconds=monotonic,
                     sample_duration_seconds=elapsed, consecutive_low_samples=guard.count,
                     provisional_threshold_percent=THRESHOLD)
        if clock_fault is not None:
            state['clock_fault'] = clock_fault
        temporary = state_dir / 'battery.json.tmp'
        temporary.write_text(json.dumps(state) + '\n')
        os.replace(temporary, state_dir / 'battery.json')
        if shutdown:
            logging.warning('Three valid low discharging samples; requesting orderly poweroff')
            # Retry on later samples if systemd rejects the request. Never fake success.
            result = subprocess.run(['systemctl', '--no-block', 'poweroff'], check=False)
            if result.returncode == 0:
                return
            logging.error('Poweroff request failed: %d', result.returncode)
        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
