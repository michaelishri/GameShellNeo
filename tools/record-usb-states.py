#!/usr/bin/env python3
"""Temporary on-device USB state recorder; systemd bounds its lifetime."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample-ms', type=int, choices=(20, 250), default=250)
    args = parser.parse_args()
    controllers = list(Path('/sys/class/udc').glob('*/state'))
    if len(controllers) != 1:
        raise RuntimeError('Expected exactly one USB device controller')
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    previous = None
    sequence = 0
    while True:
        state = controllers[0].read_text().strip()
        observed = time.monotonic()
        if state != previous:
            print(json.dumps({'sequence': sequence, 'state': state,
                              'time': datetime.now(timezone.utc).isoformat(),
                              'monotonic': observed, 'sample_interval_ms': args.sample_ms,
                              'boot_id': boot_id}), flush=True)
            sequence += 1
            previous = state
        time.sleep(args.sample_ms / 1000)


if __name__ == '__main__':
    main()
