#!/usr/bin/env python3
"""Bounded awake clock observations; no clock, affinity or PM writes."""
import ctypes
import json
import platform
import sys
import time
from pathlib import Path

BATCHES = 300
PER_BATCH = 200
PAUSE = 0.1
MAX_ANOMALIES = 32


def regressions(previous, sample):
    bad = []
    for name in ('monotonic', 'raw'):
        if sample[name + '_right'] < sample[name + '_left']:
            bad.append(name + '_bracket')
        if previous is not None and sample[name + '_left'] < previous[name + '_right']:
            bad.append(name + '_between')
    if previous is not None and sample['boottime'] < previous['boottime']:
        bad.append('boottime_between')
    return bad


def observe(reader, pause, batches=BATCHES, per_batch=PER_BATCH):
    previous = None
    result = dict(samples=0, regression_samples=0, regressions={}, anomalies=[],
                  anomalies_truncated=False, cpu_brackets_differ=0,
                  min_monotonic_bracket_ns=None, min_raw_bracket_ns=None)
    for _ in range(batches):
        for _ in range(per_batch):
            sample = reader()
            bad = regressions(previous, sample)
            result['samples'] += 1
            if sample['cpu_before'] != sample['cpu_after']:
                result['cpu_brackets_differ'] += 1
            for name in ('monotonic', 'raw'):
                key = 'min_' + name + '_bracket_ns'
                span = sample[name + '_right'] - sample[name + '_left']
                result[key] = span if result[key] is None else min(result[key], span)
            if bad:
                result['regression_samples'] += 1
                for name in bad:
                    result['regressions'][name] = result['regressions'].get(name, 0) + 1
                if len(result['anomalies']) < MAX_ANOMALIES:
                    result['anomalies'].append(dict(index=result['samples'], reasons=bad,
                                                    previous=previous, sample=sample))
                else:
                    result['anomalies_truncated'] = True
            if previous is None:
                result['first'] = sample
            previous = sample
        pause(PAUSE)
    result['last'] = previous
    return result


def main():
    libc = ctypes.CDLL(None, use_errno=True)
    getcpu = libc.sched_getcpu
    getcpu.argtypes = []
    getcpu.restype = ctypes.c_int

    def cpu():
        value = getcpu()
        if value < 0:
            raise OSError(ctypes.get_errno(), 'sched_getcpu failed')
        return value

    def reader():
        before = cpu()
        raw_left = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
        left = time.monotonic_ns()
        boot = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        right = time.monotonic_ns()
        raw_right = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
        after = cpu()
        return dict(cpu_before=before, cpu_after=after, raw_left=raw_left,
                    monotonic_left=left, boottime=boot, monotonic_right=right,
                    raw_right=raw_right)

    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    source_path = Path('/sys/devices/system/clocksource/clocksource0/current_clocksource')
    source = source_path.read_text().strip()
    info = time.get_clock_info('monotonic')
    consumed = time.process_time_ns()
    observation = observe(reader, time.sleep)
    result = dict(schema=1, operation='awake-clock-observation', complete=True,
                  boot_id=boot_id, clocksource=source, machine=platform.machine(),
                  python=sys.version, batches=BATCHES, per_batch=PER_BATCH,
                  pause_seconds=PAUSE, process_cpu_ns=time.process_time_ns()-consumed,
                  monotonic_info=vars(info), observation=observation)
    if (boot_id != Path('/proc/sys/kernel/random/boot_id').read_text().strip() or
            source != source_path.read_text().strip()):
        raise ValueError('Boot or clocksource changed during observation')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
