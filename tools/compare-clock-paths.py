#!/usr/bin/env python3
"""Bounded ARM EABI clock reads; no clock, affinity, service or PM writes."""
import ctypes
import json
import os
from pathlib import Path
import platform
import struct
import sys
import time

CLOCKS = {'monotonic': 1, 'raw': 4, 'boottime': 7}
BATCHES, PER_BATCH, PAUSE, MAX_EVENTS = 300, 50, 0.1, 32
SYSCALL = 403  # ARM EABI clock_gettime64; host checks the pinned Linux UAPI.


class KernelTimespec(ctypes.Structure):
    _fields_ = [('tv_sec', ctypes.c_int64), ('tv_nsec', ctypes.c_int64)]


def check_abi(identity):
    expected = dict(platform='linux', machine='armv7l', byteorder='little',
                    pointer_bytes=4, long_bytes=4, int_bytes=4, timespec_bytes=16,
                    timespec_alignment=8, timespec_offsets=[0, 8], elf_class=1,
                    elf_data=1, elf_machine=40, elf_eabi=5, syscall=403, clocks=CLOCKS)
    if json.dumps(identity, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError('Clock comparison requires the verified ARM EABI/time64 layout')


def identity():
    with Path('/proc/self/exe').open('rb') as stream:
        elf = stream.read(52)
    if len(elf) != 52 or elf[:4] != b'\x7fELF':
        raise ValueError('Clock comparison needs a verified ELF process')
    result = dict(platform=sys.platform, machine=platform.machine(), byteorder=sys.byteorder,
                  pointer_bytes=ctypes.sizeof(ctypes.c_void_p), long_bytes=ctypes.sizeof(ctypes.c_long),
                  int_bytes=ctypes.sizeof(ctypes.c_int), timespec_bytes=ctypes.sizeof(KernelTimespec),
                  timespec_alignment=ctypes.alignment(KernelTimespec),
                  timespec_offsets=[KernelTimespec.tv_sec.offset, KernelTimespec.tv_nsec.offset],
                  elf_class=elf[4], elf_data=elf[5], elf_machine=struct.unpack_from('<H', elf, 18)[0],
                  elf_eabi=struct.unpack_from('<I', elf, 36)[0] >> 24, syscall=SYSCALL,
                  clocks=dict(monotonic=time.CLOCK_MONOTONIC, raw=time.CLOCK_MONOTONIC_RAW,
                              boottime=time.CLOCK_BOOTTIME))
    check_abi(result)
    return result


class ReadFailure(ValueError):
    def __init__(self, evidence):
        super().__init__('clock_gettime64 failed or returned an invalid timespec')
        self.evidence = evidence


class KernelReader:
    def __init__(self, abi, libc):
        check_abi(abi)  # Reject before resolving or invoking the syscall symbol.
        self.call = libc.syscall
        self.call.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.POINTER(KernelTimespec)]
        self.call.restype = ctypes.c_long

    def __call__(self, clock):
        if clock not in CLOCKS.values():
            raise ValueError('Clock ID is outside the fixed comparison')
        value = KernelTimespec(-1, -1)
        ctypes.set_errno(0)
        rc = self.call(SYSCALL, clock, ctypes.byref(value))
        if rc != 0 or value.tv_sec < 0 or not 0 <= value.tv_nsec < 1_000_000_000:
            raise ReadFailure(dict(returncode=rc, errno=ctypes.get_errno(),
                                   tv_sec=value.tv_sec, tv_nsec=value.tv_nsec))
        return value.tv_sec * 1_000_000_000 + value.tv_nsec


def discrepancies(previous, sample):
    reasons = []
    for name in CLOCKS:
        v = sample[name]['values_ns']
        if len(v) != 5 or any(type(x) is not int or x < 0 for x in v):
            raise ValueError('Incomplete or invalid clock sequence')
        for label, indices in (('python', (0, 2, 4)), ('syscall', (1, 3)),
                               ('interleaved', (0, 1, 2, 3, 4))):
            if any(v[b] < v[a] for a, b in zip(indices, indices[1:])):
                reasons.append(name + '.' + label)
            if previous is not None and v[indices[0]] < previous[name]['values_ns'][indices[-1]]:
                reasons.append(name + '.' + label + '_between')
    return reasons


def measure(api, kernel, cpu, pause, batches=BATCHES, per_batch=PER_BATCH):
    result = dict(samples=0, discrepancy_samples=0, counts={}, events=[], truncated=False,
                  cpu_before_counts={name: {} for name in CLOCKS},
                  cpu_brackets_differ={name: 0 for name in CLOCKS})
    previous = None
    sample, stage = {}, 'start'
    try:
        for _ in range(batches):
            for _ in range(per_batch):
                sample = {}
                for name, clock in CLOCKS.items():
                    stage = name + '.cpu_before'
                    current = sample[name] = dict(cpu_before=cpu(), values_ns=[])
                    for i in range(5):
                        stage = name + ('.python' if i % 2 == 0 else '.syscall')
                        value = api[name]() if i % 2 == 0 else kernel(clock)
                        current['values_ns'].append(value)
                        if type(value) is not int or value < 0:
                            raise ValueError('Invalid clock integer')
                    stage = name + '.cpu_after'
                    current['cpu_after'] = cpu()
                bad = discrepancies(previous, sample)
                result['samples'] += 1
                for name, current in sample.items():
                    counts = result['cpu_before_counts'][name]
                    key = str(current['cpu_before'])
                    counts[key] = counts.get(key, 0) + 1
                    result['cpu_brackets_differ'][name] += current['cpu_before'] != current['cpu_after']
                if bad:
                    result['discrepancy_samples'] += 1
                    for reason in bad:
                        result['counts'][reason] = result['counts'].get(reason, 0) + 1
                    if len(result['events']) < MAX_EVENTS:
                        result['events'].append(dict(index=result['samples'], reasons=bad,
                                                     previous=previous, sample=sample))
                    else:
                        result['truncated'] = True
                if previous is None:
                    result['first'] = sample
                previous = sample
            stage = 'batch-pause'
            pause(PAUSE)
    except (OSError, ValueError) as error:
        result['error'] = dict(stage=stage, reason=str(error), partial=sample,
                               detail=getattr(error, 'evidence', None))
    result['last'] = previous
    result['complete'] = 'error' not in result
    return result


def main():
    abi = identity()
    libc = ctypes.CDLL(None, use_errno=True)
    kernel = KernelReader(abi, libc)
    getcpu = libc.sched_getcpu
    getcpu.argtypes, getcpu.restype = [], ctypes.c_int

    def cpu():
        value = getcpu()
        if value < 0:
            raise OSError(ctypes.get_errno(), 'sched_getcpu failed')
        return value

    api = dict(monotonic=time.monotonic_ns,
               raw=lambda: time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW),
               boottime=lambda: time.clock_gettime_ns(time.CLOCK_BOOTTIME))
    boot = Path('/proc/sys/kernel/random/boot_id')
    source = Path('/sys/devices/system/clocksource/clocksource0/current_clocksource')
    metadata = dict(boot_id=boot.read_text().strip(), clocksource=source.read_text().strip(),
                    affinity=sorted(os.sched_getaffinity(0)))
    consumed = time.process_time_ns()
    observation = measure(api, kernel, cpu, time.sleep)
    after = dict(boot_id=boot.read_text().strip(), clocksource=source.read_text().strip(),
                 affinity=sorted(os.sched_getaffinity(0)))
    result = dict(schema=1, operation='awake-clock-path-comparison', abi=abi, metadata=metadata,
                  after_metadata=after, batches=BATCHES, per_batch=PER_BATCH, pause_seconds=PAUSE,
                  process_cpu_ns=time.process_time_ns()-consumed, python=sys.version,
                  observation=observation, complete=observation['complete'] and metadata == after)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
