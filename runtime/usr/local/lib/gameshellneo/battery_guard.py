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


def clocks():
    # Bracket BOOTTIME with MONOTONIC to bound syscall/preemption uncertainty.
    left = time.monotonic_ns()
    boot = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    right = time.monotonic_ns()
    if right < left:
        raise ValueError('non-increasing clock observation')
    return dict(boottime_ns=boot, monotonic_ns=left,
                gap_low=boot-right, gap_high=boot-left)


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
    previous_state = None
    previous_clock = None
    while True:
        started = clocks()
        try:
            sample = read_sample()
            state = {'monitoring': 'valid', **sample}
        except (OSError, ValueError) as error:
            sample = None
            state = {'monitoring': 'degraded', 'reason': str(error)}
        finished = clocks()
        elapsed = (finished['boottime_ns'] - started['boottime_ns']) / 1e9
        if not 0 <= elapsed <= MAX_SAMPLE_SECONDS or crossed_suspend(started, finished):
            sample = None
            state = {'monitoring': 'degraded', 'reason': 'battery read delayed or crossed suspend'}
        resumed = previous_clock is not None and crossed_suspend(previous_clock, started)
        previous_clock = finished
        now = started['boottime_ns'] / 1e9
        shutdown = guard.update(sample, now, resumed=resumed)
        log_state = (state['monitoring'], state.get('status'), shutdown)
        if log_state != previous_state:
            logging.info('battery monitoring=%s status=%s critical=%s', *log_state)
            previous_state = log_state
        state.update(schema_version=2, sample_clock='CLOCK_BOOTTIME', boot_id=boot_id,
                     boottime_seconds=now, sample_monotonic_seconds=started['monotonic_ns'] / 1e9,
                     sample_duration_seconds=elapsed, consecutive_low_samples=guard.count,
                     provisional_threshold_percent=THRESHOLD)
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
