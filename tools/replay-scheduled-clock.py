#!/usr/bin/env python3
"""Replay saved scheduled-clock originals without device access."""
import argparse
import json
from pathlib import Path

from clock_provenance import loads
from clock_scheduled import join


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', required=True, type=Path)
    parser.add_argument('--users', required=True, type=Path)
    args = parser.parse_args()
    records = [loads(line) for line in args.kernel.read_text().splitlines()]
    print(json.dumps(join(records, loads(args.users.read_text())), indent=2))


if __name__ == '__main__':
    main()
