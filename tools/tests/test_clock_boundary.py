"""Boundary evidence must distinguish faults from missing or ambiguous calls."""
import copy
import ctypes
import errno
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import clock_boundary as cb
from test_clock_provenance import call as kernel_call


def user_call(k, route):
    u = dict(ordinal=k['ordinal'], clock=k['clock'], route=route, returned=True,
             python_ns=k['sec'] * cb.NS + k['nsec'])
    if route == 'python':
        u['raw'] = None
    else:
        fmt = {'syscall64': '<qq', 'syscall32': '<ii', 'libc64': '<qi'}[route]
        raw = struct.pack(fmt, k['sec'], k['nsec']).ljust(16, b'\xa5')
        u.update(rc=0, errno=0, size=8 if route == 'syscall32' else 16, converted=1,
                 sec=k['sec'], nsec=k['nsec'], native_ns=u['python_ns'], raw=raw.hex())
    return u


def fixture():
    users = dict(schema=1, operation='clock-boundary-capture', started=True, stopped=True, closed=True,
                 errors=[], context=dict(tid=42, tgid=42, namespace_id=99, source_id=3,
                                         affinity=[0, 1, 2, 3], clocksource='arch_sys_counter'), calls=[])
    records = [dict(type='header', schema=1, reason=1, calls=len(cb.PLAN), writers=0,
                    writer_lost=0, limit=1024, time_ns=99)]
    for ordinal, (clock, route) in enumerate(cb.PLAN, 1):
        k = kernel_call(ordinal, clock)
        if route == 'syscall32':
            k.update(abi=32, syscall=263)
        records.append(k)
        users['calls'].append(user_call(k, route))
    return records, users


class BoundaryReplayTests(unittest.TestCase):
    def test_all_routes_three_clocks_and_raw_padding(self):
        records, users = fixture()
        result = cb.join(records, users)
        self.assertTrue(result['complete'])
        self.assertTrue(result['aligned'])
        self.assertEqual(result['calls'], 384)
        self.assertEqual(result['boundary_findings'], [])
        self.assertEqual(result['userspace_regressions'], [])
        # libc padding and bytes beyond a time32 buffer must remain raw evidence,
        # not become part of the decoded nanoseconds.
        for u in users['calls']:
            if u['route'] == 'syscall32':
                u['raw'] = u['raw'][:16] + 'ff' * 8
            elif u['route'] == 'libc64':
                u['raw'] = u['raw'][:24] + 'ff' * 4
        self.assertEqual(cb.join(records, users)['boundary_findings'], [])

    def test_actual_kernel_and_user_regression_survives(self):
        records, users = fixture()
        k = records[2]
        k.update(cycles=1176, ns=5600, nsec=5600)
        users['calls'][1] = user_call(k, 'syscall32')
        result = cb.join(records, users)
        self.assertTrue(result['complete'])  # Complete evidence != healthy clock.
        self.assertEqual(result['kernel']['regressions'][0]['delta_ns'], -750)
        self.assertEqual(result['userspace_regressions'][0]['delta_ns'], -750)
        self.assertEqual(result['boundary_findings'], [])

    def test_user_copy_disagreement_is_saved_not_clamped(self):
        records, users = fixture()
        changed = copy.deepcopy(records[1])
        changed['nsec'] -= 750
        users['calls'][0] = user_call(changed, 'syscall64')
        result = cb.join(records, users)
        self.assertTrue(result['complete'])
        self.assertEqual([x['boundary'] for x in result['boundary_findings']], ['kernel-to-raw'])
        self.assertEqual(result['boundary_findings'][0]['observed_ns'], 7_000_005_600)

    def test_field_integer_and_public_api_disagreements_separate(self):
        for index, key, boundary in [(0, 'sec', 'raw-to-native-fields'),
                (0, 'native_ns', 'native-integer-conversion'),
                (0, 'python_ns', 'python-integer-conversion'),
                (3, 'python_ns', 'kernel-to-python')]:
            records, users = fixture()
            users['calls'][index][key] += 1
            with self.subTest(key=key, index=index):
                result = cb.join(records, users)
                self.assertEqual([x['boundary'] for x in result['boundary_findings']], [boundary])

    def test_missing_extra_early_stop_no_speculative_join(self):
        for mode in ('missing-kernel', 'extra-kernel', 'partial-user', 'limit', 'reason', 'namespace'):
            records, users = fixture()
            if mode == 'missing-kernel':
                records.pop(); records[0]['calls'] -= 1
            elif mode == 'extra-kernel':
                records.append(kernel_call(385)); records[0]['calls'] += 1
            elif mode == 'partial-user':
                users['calls'].pop()
            elif mode == 'reason':
                records[0].update(reason=2, limit=384)
            elif mode == 'namespace':
                records[0]['time_ns'] += 1
            else:
                records[0]['limit'] = 1000
            with self.subTest(mode=mode):
                result = cb.join(records, users)
                self.assertFalse(result['aligned'])
                self.assertFalse(result['complete'])
                self.assertEqual(result['boundary_findings'], [])

    def test_wrong_task_namespace_clock_abi_or_order_rejected(self):
        for key, value in [('tid', 41), ('tgid', 41), ('namespace_id', 98),
                           ('clock', 4), ('abi', 32), ('syscall', -1), ('cpu', 4)]:
            records, users = fixture()
            records[1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                cb.join(records, users)
        for key, value in [('ordinal', 2), ('ordinal', True), ('clock', True),
                           ('route', 'python'), ('returned', 1), ('raw', 'aa'),
                           ('size', 8), ('converted', True)]:
            records, users = fixture()
            users['calls'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                cb.join(records, users)

    def test_faults_and_source_change_are_incomplete(self):
        records, users = fixture()
        records[1]['error'] = -errno.EFAULT
        u = users['calls'][0]
        u.update(rc=-1, errno=errno.EFAULT, raw='a5' * 16, converted=0, native_ns=-1, python_ns=None)
        u['sec'], u['nsec'], _ = cb.decoded_ns(u)
        result = cb.join(records, users)
        self.assertFalse(result['complete'])
        self.assertEqual(result['boundary_findings'], [])
        records, users = fixture()
        records[4]['tuple']['source_changed'] += 1
        self.assertIn('call-4-clocksource-context-changed', cb.join(records, users)['incomplete'])
        for key in ('started', 'stopped', 'closed'):
            records, users = fixture()
            users[key] = False
            self.assertFalse(cb.join(records, users)['complete'])
        records, users = fixture()
        users['errors'] = [dict(stage='close', message='failure')]
        self.assertFalse(cb.join(records, users)['complete'])


class FakeControl:
    def __init__(self, failure=None):
        self.events = []
        self.failure = failure

    def event(self, name):
        self.events.append(name)
        if name == self.failure:
            raise OSError('injected ' + name)

    def start(self): self.event('start')
    def stop(self): self.event('stop')
    def close(self): self.event('close')
    def read(self):
        self.event('read')
        return b'original kernel bytes\n'


class WorkloadTests(unittest.TestCase):
    def workload(self, failed=None, failed_call=None):
        control = FakeControl(failed)
        seen = []

        def observe(clock, route):
            seen.append((clock, route))
            if len(seen) == failed_call:
                raise OSError(errno.EFAULT, 'injected read')

        def native(route, clock, out):
            observe(clock, route)
            k = kernel_call(len(seen), clock)
            u = user_call(k, route)
            for key in ('rc', 'size', 'converted', 'sec', 'nsec', 'native_ns'):
                setattr(out, key, u[key])
            out.error = u['errno']
            out.bytes[:] = bytes.fromhex(u['raw'])

        def public(clock):
            observe(clock, 'python')
            return (16 if clock == 7 else 7) * cb.NS + 6350

        context = fixture()[1]['context']
        users, raw = cb.collect(control, native, {c: lambda c=c: public(c) for c in (1, 4, 7)}, context)
        return control, seen, users, raw

    def test_fixed_workload_and_no_extra_reads(self):
        control, seen, users, raw = self.workload()
        self.assertEqual(seen, list(cb.PLAN))
        self.assertEqual(control.events, ['start', 'stop', 'read', 'close'])
        self.assertEqual(users, fixture()[1])
        self.assertEqual(raw, b'original kernel bytes\n')

    def test_partial_failure_saved_and_never_retried(self):
        for failed_call in (1, 4, 201, 384):
            control, seen, users, raw = self.workload(failed_call=failed_call)
            self.assertEqual(len(seen), failed_call)
            self.assertEqual(len(users['calls']), failed_call)
            self.assertFalse(users['calls'][-1]['returned'])
            self.assertEqual(users['errors'][0]['stage'], 'workload')
            self.assertEqual(control.events, ['start', 'stop', 'read', 'close'])
            self.assertEqual(raw, b'original kernel bytes\n')

    def test_every_control_failure_still_attempts_cleanup(self):
        for stage in ('start', 'stop', 'read', 'close'):
            control, seen, users, raw = self.workload(failed=stage)
            self.assertEqual(control.events, ['start', 'stop', 'read', 'close'])
            self.assertEqual(len(seen), 0 if stage == 'start' else 384)
            self.assertEqual(users['errors'][0]['stage'], 'export' if stage == 'read' else stage)
            self.assertEqual(raw, b'' if stage == 'read' else b'original kernel bytes\n')

    def test_raw_partial_export_and_short_command_are_preserved(self):
        control = cb.KernelControl(42)
        with patch.object(cb.os, 'read', side_effect=[b'partial raw', OSError('broken')]):
            with self.assertRaises(cb.ExportError) as raised:
                control.read()
        self.assertEqual(raised.exception.partial, b'partial raw')
        with patch.object(cb.os, 'write', return_value=1) as write:
            with self.assertRaises(OSError):
                control.start()
        write.assert_called_once_with(42, b'start 1024\n')
        fake = FakeControl()
        fake.read = lambda: (_ for _ in ()).throw(cb.ExportError('broken', b'partial'))
        fake.start = lambda: (_ for _ in ()).throw(OSError('start ambiguous'))
        users, raw = cb.collect(fake, None, {}, fixture()[1]['context'])
        self.assertEqual(raw, b'partial')
        self.assertTrue(users['closed'])

    def test_interrupt_stops_exports_and_returns_original_partial_evidence(self):
        control = FakeControl()
        def interrupted(*args):
            raise KeyboardInterrupt('injected interrupt')
        users, raw = cb.collect(control, interrupted, {}, fixture()[1]['context'])
        self.assertEqual(control.events, ['start', 'stop', 'read', 'close'])
        self.assertEqual(users['errors'][0]['type'], 'KeyboardInterrupt')
        self.assertEqual(len(users['calls']), 1)
        self.assertFalse(users['calls'][0]['returned'])
        self.assertEqual(raw, b'original kernel bytes\n')

    def test_native_layout_mismatch_rejected_before_read(self):
        class Function:
            def __init__(self, function): self.function = function
            def __call__(self, *args): return self.function(*args)

        class Library:
            def __init__(self, long_size):
                self.neo_clock_layout = Function(lambda out, count: self.layout(out, count, long_size))
                self.neo_clock_read = Function(lambda *args: self.fail())
            def layout(self, out, count, long_size):
                out[:] = [1, 56, 16, 40, 16, 8, long_size, 4, 4]
                return 0
            def fail(self): raise AssertionError('Must not read during construction')

        with patch.object(cb.ctypes, 'PyDLL', return_value=Library(8)), self.assertRaises(ValueError):
            cb.NativeReader('/fixture-only.so')
        with patch.object(cb.ctypes, 'PyDLL', return_value=Library(4)):
            cb.NativeReader('/fixture-only.so')
        self.assertEqual(ctypes.sizeof(cb.NativeObservation), 56)


if __name__ == '__main__':
    unittest.main()
