#!/usr/bin/env python3
"""Read-only clock/PM observation check; no battery, driver or sleep operations."""
import json
import os
import sys
import time

from awake_clock import AwakeRun


def main():
    run = AwakeRun()
    for _ in range(19):
        time.sleep(.05)
        run.check()
    proof = run.finish()
    print(json.dumps(dict(passed=True, kernel=os.uname().release,
                          python=sys.version.split()[0], awake_proof=proof)), flush=True)


if __name__ == '__main__':
    main()
