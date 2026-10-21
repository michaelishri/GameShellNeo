"""Replay frozen kernel clock tuples. This is not a hardware qualification report."""
import argparse
import hashlib
import json
import os
from pathlib import Path

U64 = (1 << 64) - 1
NS = 1_000_000_000


def integer(value, low=0, high=U64):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid integer in kernel clock record')
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def loads(line):
    return json.loads(line, object_pairs_hook=unique_object)


def conversion(base, cycles):
    mask = integer(base['mask'], 1)
    if mask & (mask + 1):
        raise ValueError('Clock mask is not a low-bit mask')
    last = integer(base['last'])
    mult = integer(base['mult'], 1, (1 << 32) - 1)
    shift = integer(base['shift'], 0, 63)
    xtime = integer(base['xtime'])
    maximum = integer(base['max'])
    delta = (integer(cycles) - last) & mask
    if delta > maximum and delta & ~(mask >> 1):
        return xtime >> shift, 'negative-delta', delta
    if delta > maximum:
        return ((delta * mult + xtime) >> shift) & U64, 'wide', delta
    return ((delta * mult + xtime) & U64) >> shift, 'normal', delta


def signed(value):
    return integer(value, -(1 << 63), (1 << 63) - 1)


def validate_tuple(t):
    for name in ('mono', 'raw'):
        b = t[name]
        conversion(b, b['last'])
        integer(b['max_raw'])
        integer(b['source_id'], 0, (1 << 32) - 1)
        signed(b['base'])
    integer(t['xtime_sec'])
    integer(t['raw_sec'])
    signed(t['wall_sec'])
    integer(t['wall_nsec'], 0, NS - 1)
    signed(t['offs_boot'])
    integer(t['clock_set'], 0, (1 << 32) - 1)
    integer(t['source_changed'], 0, 255)


def replay(records):
    if not records or len(records) > 1 + 1024 + 2048:
        raise ValueError('Missing or oversized record stream')
    h = records[0]
    if h.get('type') != 'header' or h.get('schema') != 1:
        raise ValueError('Expected clock provenance schema 1')
    integer(h['schema'], 1, 1)
    integer(h['time_ns'], 0, (1 << 32) - 1)
    limit = integer(h['limit'], 1, 1024)
    calls = records[1:1 + integer(h['calls'], 0, limit)]
    writers = records[1 + len(calls):]
    if len(writers) != integer(h['writers'], 0, 2048):
        raise ValueError('Truncated or extra writer records')
    reason = integer(h['reason'], 1, 4)
    lost = integer(h['writer_lost'], 0, 1)
    if ((reason == 3) != (lost == 1) or (reason == 3 and len(writers) != 2048) or
            (reason == 2 and len(calls) != limit)):
        raise ValueError('Inconsistent stop reason or counts')
    orders = set()
    prior = {}
    comparisons = []
    last_end = 0
    last_writer = 0
    incomplete = []
    if lost:
        incomplete.append('writer-buffer-exhausted')
    for ordinal, c in enumerate(calls, 1):
        if c.get('type') != 'call' or c.get('ordinal') != ordinal:
            raise ValueError('Missing, reordered or duplicate call')
        integer(c['ordinal'], 1, 1024)
        integer(c['abi'], 32, 64)
        integer(c['syscall'], -1, 403)
        clock = integer(c['clock'], 1, 7)
        if clock not in (1, 4, 7) or c['abi'] not in (32, 64):
            raise ValueError('Unsupported clock or ABI')
        if c['syscall'] not in (-1, 403 if c['abi'] == 64 else 263):
            raise ValueError('Syscall does not match ARM ABI')
        for flag in ('accepted', 'valid', 'complete'):
            integer(c[flag], 0, 1)
        if not all(c[k] for k in ('accepted', 'valid', 'complete')):
            incomplete.append(f'call-{ordinal}-incomplete')
            continue
        if integer(c['seq'], 0, (1 << 32) - 1) % 2:
            raise ValueError('Accepted attempt has odd sequence')
        attempts = integer(c['attempts'], 1, (1 << 32) - 1)
        if attempts == (1 << 32) - 1:
            incomplete.append(f'call-{ordinal}-attempt-count-saturated')
        for key in ('read_order', 'end_order'):
            value = integer(c[key], 1)
            if value in orders:
                raise ValueError('Duplicate diagnostic order')
            orders.add(value)
        if c['read_order'] <= last_end:
            raise ValueError('Overlapping or reordered calls in one owning task')
        last_end = c['end_order']
        if c['read_order'] >= c['end_order']:
            raise ValueError('Call completed before its read record')
        for key in ('tid', 'tgid'):
            integer(c[key], 1, (1 << 31) - 1)
        for key in ('cpu', 'end_cpu', 'namespace_id'):
            integer(c[key], 0, (1 << 32) - 1)
        t = c['tuple']
        validate_tuple(t)
        b = t['raw' if clock == 4 else 'mono']
        ns, branch, _ = conversion(b, c['cycles'])
        if integer(c['ns']) != ns:
            raise ValueError('Saved conversion disagrees with tuple replay')
        offset = signed(c['offset_sec']) * NS + signed(c['offset_nsec'])
        if clock == 4:
            value = integer(t['raw_sec']) * NS + ns + offset
        elif clock == 1:
            value = (integer(t['xtime_sec']) + signed(t['wall_sec'])) * NS + ns + signed(t['wall_nsec']) + offset
        else:
            value = signed(b['base']) + signed(t['offs_boot']) + ns + offset
        returned = signed(c['sec']) * NS + integer(c['nsec'], 0, NS - 1)
        if value != returned:
            raise ValueError('Kernel result disagrees with clock/namespace replay')
        error = integer(c['error'], -4095, 0)
        if error:
            incomplete.append(f'call-{ordinal}-syscall-error-{error}')
        else:
            previous = prior.get(clock)
            if previous is not None and returned < previous['returned']:
                unchanged = (t == previous['tuple'] and offset == previous['offset'])
                comparisons.append(dict(ordinal=ordinal, previous=previous['ordinal'],
                    clock=clock, delta_ns=returned - previous['returned'],
                    counter_delta=c['cycles'] - previous['cycles'],
                    unchanged_tuple=unchanged, branch=branch,
                    interpretation='counter-observation-regression' if unchanged and c['cycles'] < previous['cycles']
                    else 'regression-needs-tuple-transition-analysis'))
            prior[clock] = dict(returned=returned, tuple=t, ordinal=ordinal, offset=offset, cycles=c['cycles'])
    for w in writers:
        if w.get('type') != 'writer' or w.get('kind') not in range(5):
            raise ValueError('Invalid writer record')
        integer(w['kind'], 0, 4)
        integer(w['cpu'], 0, (1 << 32) - 1)
        integer(w['action'], 0, (1 << 32) - 1)
        integer(w['seq'], 0, (1 << 32) - 1)
        integer(w['cycles'])
        integer(w['delta'])
        if integer(w['delta_valid'], 0, 1) != int(w['kind'] in (1, 2)):
            raise ValueError('Writer delta validity does not match source site')
        value = integer(w['order'], 1)
        if value in orders or value <= last_writer:
            raise ValueError('Duplicate or reordered writer record')
        orders.add(value)
        last_writer = value
        if w['kind'] == 0 and integer(w['seq'], 0, (1 << 32) - 1) % 2 != 1:
            raise ValueError('Publication sequence must be odd')
        for key in ('old', 'new') if w['kind'] == 0 else ('old',):
            if not isinstance(w[key], dict) or 'raw' not in w[key] or 'mono' not in w[key]:
                raise ValueError('Missing writer tuple')
            validate_tuple(w[key])
    return dict(schema=1, calls=len(calls), writers=len(writers), stop_reason=reason,
                complete=bool(calls) and not incomplete, incomplete=incomplete,
                regressions=comparisons,
                scope='Kernel tuple arithmetic only; user-copy/runtime correlation and hardware qualification are separate.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', default=os.environ.get('NEO_CLOCK_RECORDS'))
    args = parser.parse_args()
    if not args.path:
        parser.error('Supply the saved NDJSON file, or task FILE=<path>')
    path = Path(args.path)
    with path.open('rb') as f:
        raw = f.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError('Oversized capture')
    records = [loads(line) for line in raw.decode().splitlines()]
    result = replay(records)
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
