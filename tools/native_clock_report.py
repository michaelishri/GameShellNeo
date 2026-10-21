"""Independently classify all retained integer readings; never repair their order."""
import json
import hashlib
import os
import re

ROUTES = (0, 1, 2, 0, 2, 1, 2, 1, 0)
PAIR_ROUTES = (0, 1, 0, 1, 0, 1)
NAMES = ('libc', 'kernel', 'vdso')
CLOCKS = (1, 4, 7)
SAMPLES = 15000
MAX_BYTES = 16 * 1024 * 1024


def validate_inventory(data, boot_id, libc_version):
    value = json.loads(data)
    meta = value['before']
    if (value.get('type') != 'vdso-inventory' or value.get('schema') != 1 or
            value.get('complete') is not True or value.get('mapping_found') is not True or
            value.get('handle_base_verified') is not True or value.get('version') != 'LINUX_2.6' or
            value.get('libc') != libc_version or meta != value['after'] or
            meta['boot_id'] != boot_id or meta['clocksource'] != 'arch_sys_counter' or
            type(meta['affinity']) is not int or not 0 < meta['affinity'] < 16 or
            set(value['symbols']) != {'__vdso_clock_gettime64', '__vdso_clock_gettime',
                                     '__vdso_gettimeofday', '__vdso_clock_getres'}):
        raise ValueError('Unqualified vDSO inventory identity')
    for record in value['symbols'].values():
        if (set(record) != {'versioned', 'unversioned', 'base_verified'} or
                any(type(v) is not bool for v in record.values()) or
                record['versioned'] is not record['base_verified']):
            raise ValueError('Incomplete vDSO symbol attribution')
    return value


def analyze(data, boot_id, libc_version, *, two_path=False, cpu_coverage=False):
    if (type(two_path) is not bool or type(cpu_coverage) is not bool or
            (cpu_coverage and not two_path)):
        raise ValueError('Select an explicit clock-comparison plan')
    routes = PAIR_ROUTES if two_path else ROUTES
    names = NAMES[:2] if two_path else NAMES
    if len(data) > MAX_BYTES:
        raise ValueError('Native capture exceeds its fixed bound')
    lines = data.splitlines()
    if len(lines) != SAMPLES + 2:
        raise ValueError('Incomplete native capture')
    header, footer = json.loads(lines[0]), json.loads(lines[-1])
    expected = dict(type='header', schema=1,
        operation='native-clock-libc-syscall' if two_path else 'native-clock-comparison', batches=300,
        per_batch=50, pause_ns=100000000, routes=list(routes), clocks=list(CLOCKS), libc=libc_version)
    if two_path:
        expected.update(direct_vdso_called=False, vdso_time64_exported=False,
                        vdso_time32_exported=False, vdso_handle_verified=True)
    else:
        expected.update(vdso_symbol='__vdso_clock_gettime64', vdso_version='LINUX_2.6', vdso_base_verified=True)
    if cpu_coverage:
        expected.update(operation='native-clock-libc-syscall-cpus', cpu_schedule=[0, 1, 2, 3],
            cpu_batches=[dict(cpu=i % 4, before=1 << (i % 4), after=1 << (i % 4),
                              begin_rc=0, end_rc=0) for i in range(300)])
    elif ('cpu_schedule' in header or 'cpu_batches' in header or 'affinity_restore_rc' in footer):
        raise ValueError('CPU coverage requires its explicit comparison plan')
    # Equality alone accepts booleans as integers; require matching JSON types too.
    if any(json.dumps(header.get(k), sort_keys=True) != json.dumps(v, sort_keys=True)
           for k, v in expected.items()):
        raise ValueError('Unexpected native capture identity or bounds')
    meta = header['before']
    mask = meta['affinity']
    if (meta['boot_id'] != boot_id or meta['clocksource'] != 'arch_sys_counter' or
            type(mask) is not int or not 0 < mask < 16 or meta != footer.get('after') or
            footer.get('type') != 'footer' or footer.get('complete') is not True or
            type(footer.get('completed')) is not int or footer['completed'] != SAMPLES or
            json.dumps(footer.get('failure'), sort_keys=True) != json.dumps(dict(present=False,
                sequence=0, clock=0, position=0, stage=0, rc=0, errno=0, sec=0, nsec=0), sort_keys=True)):
        raise ValueError('Native capture incomplete or metadata changed')
    if cpu_coverage and (mask != 15 or type(footer.get('affinity_restore_rc')) is not int or
                         footer['affinity_restore_rc'] != 0):
        raise ValueError('Four-core capture did not restore its original affinity')
    result = {str(c): dict(adjacent={}, within={}, between={}, interleaved_between={}, cpu_before_counts={},
        cpu_brackets_differ=0) for c in CLOCKS}
    previous = {}
    previous_cpu = {}
    if cpu_coverage:
        for stats in result.values():
            stats['cpu_transitions'] = {}
    events = []
    bad_sequences = 0

    def observe(stats, key, delta):
        entry = stats.setdefault(key, dict(count=0, negative=0, min_ns=delta, max_ns=delta))
        entry['count'] += 1
        entry['negative'] += int(delta < 0)
        entry['min_ns'] = min(entry['min_ns'], delta)
        entry['max_ns'] = max(entry['max_ns'], delta)
        return delta < 0

    for index, line in enumerate(lines[1:-1], 1):
        row = json.loads(line)
        if (row.get('type') != 'sample' or type(row.get('index')) is not int or row['index'] != index or
                type(row.get('clocks')) is not list or len(row['clocks']) != 3):
            raise ValueError('Unordered or incomplete native samples')
        target = ((index - 1) // 50) % 4
        if cpu_coverage:
            if type(row.get('requested_cpu')) is not int or row['requested_cpu'] != target:
                raise ValueError('Sample does not follow the fixed CPU schedule')
        elif 'requested_cpu' in row:
            raise ValueError('CPU coverage requires its explicit comparison plan')
        reasons = []
        for clock, family in zip(CLOCKS, row['clocks']):
            stats = result[str(clock)]
            cpus = [family['cpu_before'], family['cpu_after']]
            if any(type(c) is not int or c not in range(4) or not mask & (1 << c) for c in cpus):
                raise ValueError('CPU context outside process affinity')
            if cpu_coverage and cpus != [target, target]:
                raise ValueError('CPU observation differs from the requested core')
            counts = stats['cpu_before_counts']
            counts[str(cpus[0])] = counts.get(str(cpus[0]), 0) + 1
            stats['cpu_brackets_differ'] += int(cpus[0] != cpus[1])
            readings = family['ns']
            if (type(readings) is not list or len(readings) != len(routes) or
                    any(type(n) is not int or not 0 <= n <= 2**63-1 for n in readings)):
                raise ValueError('Invalid integer nanosecond evidence')
            for p in range(1, len(routes)):
                pair = names[routes[p-1]] + '->' + names[routes[p]]
                if observe(stats['adjacent'], pair, readings[p] - readings[p-1]):
                    reasons.append(dict(clock=clock, kind='adjacent', position=p, pair=pair,
                                        delta_ns=readings[p] - readings[p-1]))
            last_key = (clock, routes[-1])
            if last_key in previous:
                pair = names[routes[-1]] + '->' + names[routes[0]]
                delta = readings[0] - previous[last_key]
                if observe(stats['interleaved_between'], pair, delta):
                    reasons.append(dict(clock=clock, kind='interleaved_between', pair=pair,
                                        previous_ns=previous[last_key], delta_ns=delta))
                if cpu_coverage:
                    transition = str(previous_cpu[clock]) + '->' + str(target)
                    observe(stats['cpu_transitions'], transition, delta)
                    if delta < 0:
                        reasons[-1].update(previous_cpu=previous_cpu[clock], requested_cpu=target)
            for route, name in enumerate(names):
                ns = [n for r, n in zip(routes, readings) if r == route]
                for p in range(1, len(ns)):
                    if observe(stats['within'], name, ns[p] - ns[p-1]):
                        reasons.append(dict(clock=clock, kind='within', route=name,
                                            position=p, delta_ns=ns[p] - ns[p-1]))
                key = (clock, route)
                if key in previous and observe(stats['between'], name, ns[0] - previous[key]):
                    reasons.append(dict(clock=clock, kind='between', route=name,
                                        previous_ns=previous[key], delta_ns=ns[0] - previous[key]))
                previous[key] = ns[-1]
            previous_cpu[clock] = cpus[-1]
        if reasons:
            bad_sequences += 1
            if len(events) < 32:
                events.append(dict(index=index, reasons=reasons, sample=row))
    return dict(complete=True, operation=expected['operation'], routes=list(routes),
        samples=SAMPLES, reads=SAMPLES*len(CLOCKS)*len(routes), discrepancy_sequences=bad_sequences,
        statistics=result, first_events=events, events_truncated=bad_sequences > len(events),
        all_readings_retained=True, metadata=meta, clock_reliability_qualified=False, pm_admission=False,
        cpu_coverage_verified=cpu_coverage, diagnostic_affinity_restored=cpu_coverage,
        per_read_cpu_proven=False, vdso_internal_fallback_excluded=False)


def main():
    """Replay a completed capture offline, leaving the original report intact."""
    from remote import LOCAL, evidence_directory
    name = os.environ.get('NEO_CAPTURE', '')
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}\.[0-9]{6}Z', name):
        raise ValueError('Use the timestamp CAPTURE printed by device:clock-native')
    capture = LOCAL / 'diagnostics' / name
    summary = json.loads((capture / 'summary.json').read_text())
    raw = capture / 'native-output.ndjson'
    if raw.stat().st_size > MAX_BYTES:
        raise ValueError('Native capture exceeds its fixed bound')
    data = raw.read_bytes()
    if (summary.get('complete') is not True or summary.get('observation_validated') is not True or
            summary.get('operation') not in ('comparison', 'libc-syscall-comparison', 'libc-syscall-cpu-comparison') or
            hashlib.sha256(data).hexdigest() != summary.get('raw_sha256')):
        raise ValueError('Original completed capture or raw hash is missing/changed')
    before = json.loads((capture / 'before.json').read_text())
    # The original host validation checked this header version against the
    # hash-verified installed runtime. Replay never re-executes a device helper.
    version = json.loads(data.splitlines()[0])['libc']
    result = analyze(data, before['boot_id'], version,
                     two_path=summary['operation'] != 'comparison',
                     cpu_coverage=summary['operation'] == 'libc-syscall-cpu-comparison')
    os.umask(0o077)
    destination = evidence_directory()
    result['original_capture'] = name
    result['raw_sha256'] = summary['raw_sha256']
    (destination / 'analysis.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Offline native analysis:', destination)
    print('Discrepancy sequences:', result['discrepancy_sequences'])


if __name__ == '__main__':
    main()
