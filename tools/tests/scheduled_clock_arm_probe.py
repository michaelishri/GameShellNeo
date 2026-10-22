#!/usr/bin/env python3
"""Offline ARM ABI/workload evidence; deliberately supplies no kernel records."""
import ctypes
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clock_boundary import NativeReader, decoded_ns
from clock_scheduled import NativePause, PLAN, collect, schedule, validate_pause


class OfflineControl:
    def __init__(self): self.events = []
    def start(self): self.events.append('start')
    def stop(self): self.events.append('stop')
    def read(self):
        self.events.append('read')
        return b'Offline ABI/workload only; no kernel recorder or hardware evidence.\n'
    def close(self): self.events.append('close')


def main():
    reader = NativeReader(sys.argv[1]); pause = NativePause(sys.argv[2]); output = Path(sys.argv[3])
    assert sys.byteorder == 'little' and ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_long) == 4
    control, seen = OfflineControl(), []
    public = {1: time.monotonic_ns, 4: lambda: time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW),
              7: lambda: time.clock_gettime_ns(time.CLOCK_BOOTTIME)}

    def native(route, clock, out):
        seen.append((clock, route)); reader(route, clock, out)

    def python(clock):
        seen.append((clock, 'python')); return public[clock]()

    users, raw = collect(control, native, {c: lambda c=c: python(c) for c in public}, pause,
        dict(scope='offline ARM ABI/workload only; no kernel correlation'))
    (output / 'arm-workload-users.json').write_text(json.dumps(users, indent=2) + '\n')
    (output / 'arm-workload-no-kernel.txt').write_bytes(raw)
    assert control.events == ['start', 'stop', 'read', 'close'] and seen == list(PLAN)
    assert users['started'] and users['stopped'] and users['closed'] and not users['errors']
    assert len(users['calls']) == 256 and len(users['pauses']) == 31
    for call, (clock, route) in zip(users['calls'], PLAN):
        assert call['returned'] and call['clock'] == clock and call['route'] == route
        if route == 'syscall64':
            sec, ns, value = decoded_ns(call)
            assert (call['rc'], call['errno'], call['converted']) == (0, 0, 1)
            assert (sec, ns, value) == (call['sec'], call['nsec'], call['native_ns'])
            assert call['python_ns'] == value
        else:
            assert type(call['python_ns']) is int and call['raw'] is None
    assert all(validate_pause(value) for value in users['pauses'])
    summary = dict(schema=1, operation='offline-arm-scheduled-workload', complete=True,
        schedule=schedule(), clocks=256, native_clock_calls=64, python_clock_calls=192,
        relative_pauses=31, control_events=control.events, python_version=sys.version,
        pointer_bytes=ctypes.sizeof(ctypes.c_void_p), long_bytes=ctypes.sizeof(ctypes.c_long),
        byteorder=sys.byteorder, no_kernel_records=True, no_hardware_contact=True,
        pm_admission=False, clock_reliability_qualified=False)
    (output / 'arm-workload-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('Offline ARM exact256/31 workload and original/new native ABI passed; no kernel evidence.')


if __name__ == '__main__':
    main()
