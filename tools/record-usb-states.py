#!/usr/bin/env python3
"""Temporary on-device USB state recorder; systemd bounds its lifetime."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time


def main():
    controllers = list(Path('/sys/class/udc').glob('*/state'))
    if len(controllers) != 1:
        raise RuntimeError('Expected exactly one USB device controller')
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    previous = None
    sequence = 0
    while True:
        state = controllers[0].read_text().strip()
        if state != previous:
            print(json.dumps({'sequence': sequence, 'state': state,
                              'time': datetime.now(timezone.utc).isoformat(),
                              'boot_id': boot_id}), flush=True)
            sequence += 1
            previous = state
        time.sleep(0.25)


if __name__ == '__main__':
    main()
