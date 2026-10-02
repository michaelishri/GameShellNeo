#!/usr/bin/env python3
"""Compare saved PM reference snapshots; never submit a device test."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys

LINK = 'consumer:platform:1c10000.mmc'


def summarize(captures):
    rows, identities, runs = [], set(), set()
    for path, result in captures:
        before, after = result['before'], result['after']
        run = result['run_id']
        if (result.get('passed') is not True or result.get('stage') not in ('freezer', 'devices', 'platform') or
                not re.fullmatch(r'[a-f0-9]{32}', run) or run in runs):
            raise ValueError('Unaccepted, duplicate or invalid PM run')
        runs.add(run)
        values, policies = [], []
        for snapshot in (before, after):
            identities.add((snapshot['boot_id'], snapshot['kernel']))
            power = snapshot['rsb_links'][LINK]['consumer']['power']
            value = power['runtime_usage']
            if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value):
                raise ValueError('Missing or invalid runtime-usage counter')
            values.append(int(value))
            policy = {name: power[name] for name in ('control', 'runtime_enabled', 'runtime_status')}
            if any(not isinstance(v, str) or not v for v in policy.values()):
                raise ValueError('Missing runtime policy')
            policies.append(policy)
        if policies[0] != policies[1]:
            raise ValueError('Runtime policy changed across a PM cycle')
        start, end = before['monotonic_seconds'], after['monotonic_seconds']
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end)) or not 0 <= start < end:
            raise ValueError('Invalid snapshot time ordering')
        rows.append(dict(capture=str(path), run_id=run, stage=result['stage'], before=values[0],
                         after=values[1], delta=values[1]-values[0], policy=policies[0], start=start, end=end))
    if not rows or len(identities) != 1:
        raise ValueError('Supply accepted captures from exactly one boot and kernel')
    rows.sort(key=lambda row: row['start'])
    for previous, following in zip(rows, rows[1:]):
        if previous['end'] >= following['start'] or previous['policy'] != following['policy']:
            raise ValueError('Overlapping captures or runtime policy changed between cycles')
    boot, kernel = identities.pop()
    return dict(boot_id=boot, kernel=kernel, device='1c10000.mmc', cycles=rows,
                stable=len({row[key] for row in rows for key in ('before', 'after')}) == 1,
                limits='Sequential snapshots, not isolated reference attribution or an energy measurement. '
                       'Investigate changes, including possible transient host claims; do not reset counters or auto-repeat PM.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-stable', action='store_true')
    parser.add_argument('captures', nargs='+', type=Path, help='Saved cycle result.json files from one boot')
    args = parser.parse_args(sys.argv[1:] or shlex.split(os.environ.get('NEO_COMMAND', '')))
    result = summarize([(path, json.loads(path.read_text())) for path in args.captures])
    print(json.dumps(result, indent=2))
    if args.require_stable and not result['stable']:
        raise SystemExit('SDIO reference snapshots changed; inspect the original captures before another PM test.')


if __name__ == '__main__':
    main()
