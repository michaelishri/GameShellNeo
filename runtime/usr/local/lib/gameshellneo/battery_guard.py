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

    def update(self, sample, now):
        # A delayed loop or invalid sample breaks the consecutive observation window.
        if self.previous is not None and not INTERVAL * 0.8 <= now - self.previous <= INTERVAL * 1.5:
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
    previous_state = None
    while True:
        now = time.monotonic()
        try:
            sample = read_sample()
            state = {'monitoring': 'valid', **sample}
        except (OSError, ValueError) as error:
            sample = None
            state = {'monitoring': 'degraded', 'reason': str(error)}
        shutdown = guard.update(sample, now)
        log_state = (state['monitoring'], state.get('status'), shutdown)
        if log_state != previous_state:
            logging.info('battery monitoring=%s status=%s critical=%s', *log_state)
            previous_state = log_state
        state.update(monotonic_seconds=now, consecutive_low_samples=guard.count,
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
