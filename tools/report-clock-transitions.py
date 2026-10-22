#!/usr/bin/env python3
"""Reconcile one saved kernel clock stream offline; never connect to a device."""
import argparse
import json
import os

from clock_transitions import report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', default=os.environ.get('NEO_CLOCK_RECORDS'))
    args = parser.parse_args()
    if not args.path:
        parser.error('Supply a saved NDJSON path, or task FILE=<path>')
    print(json.dumps(report(args.path), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
