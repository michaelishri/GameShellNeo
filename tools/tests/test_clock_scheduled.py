"""Scheduled clock evidence is finite, separate and incomplete on any lost boundary."""
import copy
import ctypes
import errno
import importlib.util
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import clock_boundary as cb
import clock_scheduled as cs
from test_clock_boundary import FakeControl, fixture as original_fixture, user_call
from test_clock_provenance import call as kernel_call

SPEC = importlib.util.spec_from_file_location('scheduled_pause_builder', ROOT / 'tools/build-scheduled-clock.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def pause_value(ordinal=1):
    return dict(ordinal=ordinal, after_clock_ordinal=ordinal * 8, returned=True,
        rc=0, errno=0, clock=1, syscall=407, flags=0, calls=1,
        request_before=cs.REQUEST, request_after=cs.REQUEST, remaining='a5' * 16)


def fixture():
    users = dict(schema=1, operation=cs.OPERATION, schedule=cs.schedule(), started=True,
        stopped=True, closed=True, errors=[], context=original_fixture()[1]['context'], calls=[],
        pauses=[pause_value(i) for i in range(1, 32)])
    records = [dict(type='header', schema=1, reason=1, calls=256, writers=0,
                    writer_lost=0, limit=1024, time_ns=99)]
    for ordinal, (clock, route) in enumerate(cs.PLAN, 1):
        call = kernel_call(ordinal, clock)
        records.append(call)
        users['calls'].append(user_call(call, route))
    return records, users


class ReplayTests(unittest.TestCase):
    def test_exact_guard_raw_rounds_and_relative_pause_schedule(self):
        records, users = fixture()
        result = cs.join(records, users)
        self.assertTrue(result['complete'])
        self.assertEqual((result['calls'], result['pauses']), (256, 31))
        self.assertEqual(result['boundary_findings'], [])
        self.assertEqual(result['userspace_regressions'], [])
        self.assertEqual(cs.ROUND[:3], ((1, 'python'), (7, 'python'), (1, 'python')))
        self.assertEqual(cs.ROUND[3:], ((4, 'python'), (4, 'syscall64'), (4, 'python'),
                                      (4, 'syscall64'), (4, 'python')))
        self.assertEqual(cs.PLAN, cs.ROUND * 32)
        self.assertEqual(cs.schedule()['relative_pause_ns'] * 31, 3_100_000_000)
        self.assertEqual(len(cb.PLAN), 384)

    def test_both_monotonic_and_raw_regressions_after_pause_remain_evidence(self):
        for ordinal in (9, 12):
            records, users = fixture()
            call = records[ordinal]
            call.update(cycles=1176, ns=5600, nsec=5600)
            users['calls'][ordinal - 1] = user_call(call, cs.PLAN[ordinal - 1][1])
            result = cs.join(records, users)
            with self.subTest(clock=call['clock']):
                self.assertTrue(result['complete'])
                self.assertEqual(result['kernel']['regressions'][0]['delta_ns'], -750)
                self.assertEqual(result['userspace_regressions'][0]['delta_ns'], -750)
                self.assertEqual(result['boundary_findings'], [])

    def test_copy_integer_and_python_boundary_failures_remain_separate(self):
        for index, field, boundary in ((0, 'python_ns', 'kernel-to-python'),
                (4, 'sec', 'raw-to-native-fields'), (4, 'native_ns', 'native-integer-conversion'),
                (4, 'python_ns', 'python-integer-conversion')):
            records, users = fixture()
            users['calls'][index][field] += 1
            with self.subTest(field=field):
                self.assertEqual([f['boundary'] for f in cs.join(records, users)['boundary_findings']], [boundary])
        records, users = fixture()
        altered = copy.deepcopy(records[5]); altered['nsec'] -= 750
        users['calls'][4] = user_call(altered, 'syscall64')
        self.assertEqual([f['boundary'] for f in cs.join(records, users)['boundary_findings']], ['kernel-to-raw'])

    def test_truncated_extra_and_wrong_capacity_evidence_cannot_align(self):
        for mode in ('missing-kernel', 'extra-kernel', 'partial-user', 'pause-missing', 'capacity', 'reason'):
            records, users = fixture()
            if mode == 'missing-kernel': records.pop(); records[0]['calls'] -= 1
            elif mode == 'extra-kernel': records.append(kernel_call(257)); records[0]['calls'] += 1
            elif mode == 'partial-user': users['calls'].pop()
            elif mode == 'pause-missing': users['pauses'].pop()
            elif mode == 'capacity': records[0]['limit'] = 256
            else: records[0]['reason'] = 4
            with self.subTest(mode=mode):
                result = cs.join(records, users)
                self.assertFalse(result['complete'])
                self.assertFalse(result['aligned'])
                self.assertEqual(result['boundary_findings'], [])

    def test_pause_error_or_unreturned_signal_is_incomplete_and_never_a_success(self):
        for interrupted in (True, False):
            records, users = fixture()
            value = users['pauses'][0]
            value.update(rc=-1, errno=errno.EINTR, remaining=struct.pack('<qq', 0, 30_000_000).hex())
            if interrupted: value['returned'] = False
            self.assertFalse(cs.join(records, users)['complete'])

    def test_changed_pause_type_order_flags_request_or_extra_is_rejected(self):
        for key, value in (('ordinal', 2), ('ordinal', True), ('after_clock_ordinal', 8.0),
                ('returned', 1), ('clock', 4), ('syscall', 263), ('flags', 1), ('calls', 2),
                ('request_before', '0' * 32), ('request_after', '0' * 32), ('remaining', '00'), ('errno', 4)):
            records, users = fixture()
            users['pauses'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                cs.join(records, users)
        records, users = fixture(); users['pauses'].append(pause_value(32))
        with self.assertRaises(ValueError): cs.join(records, users)

    def test_schema_schedule_and_wrong_operation_are_strict(self):
        for key, value in (('schema', True), ('rounds', 32.0), ('pause_count', 32), ('relative_pause_ns', 1)):
            records, users = fixture(); users['schedule'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): cs.join(records, users)
        records, users = original_fixture()
        with self.assertRaises(ValueError): cs.join(records, users)
        records, users = fixture()
        with self.assertRaises(ValueError): cb.join(records, users)

    def test_kernel_tuple_owner_abi_and_actual_cpu_cannot_be_forged(self):
        for key, value in (('tid', 1), ('tgid', 1), ('namespace_id', 1), ('abi', 32),
                ('syscall', -1), ('cpu', 4), ('ns', 1)):
            records, users = fixture(); records[1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): cs.join(records, users)
        records, users = fixture(); users['calls'][0]['clock'] = 1.0
        with self.assertRaises(ValueError): cs.join(records, users)


class CollectionTests(unittest.TestCase):
    def workload(self, *, failed_control=None, failed_clock=None, failed_pause=None, pending_signal=False):
        control, seen, pauses = FakeControl(failed_control), [], []

        def clock(clock, route):
            seen.append((clock, route))
            if len(seen) == failed_clock: raise OSError(errno.EFAULT, 'injected read')
            return kernel_call(len(seen), clock)

        def native(route, clock_id, out):
            value = user_call(clock(clock_id, route), route)
            for name in ('rc', 'size', 'converted', 'sec', 'nsec', 'native_ns'):
                setattr(out, name, value[name])
            out.error = value['errno']; out.bytes[:] = bytes.fromhex(value['raw'])

        def public(clock_id):
            value = clock(clock_id, 'python')
            return value['sec'] * cb.NS + value['nsec']

        def pause(out):
            pauses.append(len(seen))
            out.clock, out.syscall, out.flags, out.calls = 1, 407, 0, 1
            out.request_before[:] = bytes.fromhex(cs.REQUEST)
            out.request_after[:] = bytes.fromhex(cs.REQUEST)
            out.remaining[:] = b'\xa5' * 16
            if len(pauses) == failed_pause:
                out.rc, out.error = -1, errno.EINTR
                out.remaining[:] = struct.pack('<qq', 0, 30_000_000)
                if pending_signal: raise KeyboardInterrupt('pending Python signal after C filled slot')

        users, raw = cs.collect(control, native, {c: lambda c=c: public(c) for c in (1, 4, 7)},
                                pause, fixture()[1]['context'])
        return control, seen, pauses, users, raw

    def test_single_exact_workload_has_no_extra_clock_reads_or_pause_retries(self):
        control, seen, pauses, users, raw = self.workload()
        self.assertEqual(seen, list(cs.PLAN))
        self.assertEqual(pauses, list(range(8, 256, 8)))
        self.assertEqual(control.events, ['start', 'stop', 'read', 'close'])
        self.assertEqual(users, fixture()[1])
        self.assertEqual(raw, b'original kernel bytes\n')

    def test_pause_errno_and_pending_python_signal_preserve_preallocated_originals(self):
        for failed_pause in (1, 17, 31):
            for pending in (False, True):
                control, seen, pauses, users, raw = self.workload(failed_pause=failed_pause, pending_signal=pending)
                with self.subTest(pause=failed_pause, signal=pending):
                    self.assertEqual(len(seen), failed_pause * 8)
                    self.assertEqual(len(pauses), failed_pause)
                    self.assertEqual(len(users['pauses']), failed_pause)
                    value = users['pauses'][-1]
                    self.assertEqual((value['rc'], value['errno'], value['calls']), (-1, errno.EINTR, 1))
                    self.assertEqual(value['returned'], not pending)
                    self.assertEqual(value['remaining'], struct.pack('<qq', 0, 30_000_000).hex())
                    self.assertEqual(control.events, ['start', 'stop', 'read', 'close'])
                    self.assertEqual(users['errors'][0]['stage'], 'pause')
                    self.assertEqual(raw, b'original kernel bytes\n')

    def test_partial_clock_and_every_control_failure_still_export_and_close(self):
        for ordinal in (1, 8, 9, 256):
            control, seen, _, users, _ = self.workload(failed_clock=ordinal)
            self.assertEqual(len(seen), ordinal)
            self.assertFalse(users['calls'][-1]['returned'])
            self.assertEqual(control.events, ['start', 'stop', 'read', 'close'])
        for stage in ('start', 'stop', 'read', 'close'):
            control, seen, _, users, _ = self.workload(failed_control=stage)
            self.assertEqual(len(seen), 0 if stage == 'start' else 256)
            self.assertEqual(control.events, ['start', 'stop', 'read', 'close'])
            self.assertEqual(users['errors'][0]['stage'], 'export' if stage == 'read' else stage)


class PauseLayoutTests(unittest.TestCase):
    def library(self, word_bytes=4, rejected=False):
        class Function:
            def __init__(self, function): self.function = function
            def __call__(self, *args): return self.function(*args)

        class Library:
            calls = 0
            def __init__(self):
                self.neo_clock_pause_layout = Function(self.layout)
                self.neo_clock_pause = Function(self.pause)
            def layout(self, out, count):
                if count != 12: raise AssertionError('Wrong layout count')
                out[:] = [1, 72, 24, 40, 56, 16, 407, 1, 0, 100_000_000, word_bytes, word_bytes]
                return 0
            def pause(self, out):
                self.calls += 1
                out._obj.rc = -1
                out._obj.error = errno.EINTR
                return errno.EINVAL if rejected else 0

        return Library()

    def test_wrong_arm_word_layout_is_rejected_before_pause(self):
        library = self.library(8)
        with patch.object(cs.ctypes, 'PyDLL', return_value=library), self.assertRaises(ValueError):
            cs.NativePause('/fixture-only.so')
        self.assertEqual(library.calls, 0)
        self.assertEqual(ctypes.sizeof(cs.PauseObservation), 72)

    def test_pydll_keeps_one_native_return_without_retrying_syscall_error(self):
        library = self.library()
        with patch.object(cs.ctypes, 'PyDLL', return_value=library), patch.object(cs.ctypes, 'CDLL') as cdll:
            pause = cs.NativePause('/fixture-only.so')
            slot = cs.PauseObservation(); pause(slot)
            cdll.assert_not_called()
        self.assertEqual(library.calls, 1)
        self.assertEqual((slot.rc, slot.error), (-1, errno.EINTR))
        with patch.object(cs.ctypes, 'PyDLL', return_value=self.library(rejected=True)):
            pause = cs.NativePause('/fixture-only.so')
            with self.assertRaises(ValueError): pause(cs.PauseObservation())


class PauseBuilderTests(unittest.TestCase):
    def test_pinned_abi_ignores_comments_but_requires_all_five_sources_and_exact_constants(self):
        files = dict(zip(BUILDER.ABI_FILES, (
            '407 common clock_nanosleep_time64 sys_clock_nanosleep\n',
            'struct __kernel_timespec { __kernel_time64_t tv_sec; /* seconds */ long long tv_nsec; };',
            'typedef long long __kernel_time64_t;', '#define CLOCK_MONOTONIC 1\n',
            'SYSCALL_DEFINE4(clock_nanosleep, const clockid_t, which_clock, int, flags,')))
        BUILDER.verify_abi(files)
        for name in files:
            altered = dict(files); del altered[name]
            with self.subTest(missing=name), self.assertRaises(ValueError): BUILDER.verify_abi(altered)
        for name, old, new in ((BUILDER.ABI_FILES[0], '407', '403'),
                (BUILDER.ABI_FILES[1], 'long long', 'long'), (BUILDER.ABI_FILES[3], '1', '4')):
            altered = dict(files); altered[name] = altered[name].replace(old, new)
            with self.subTest(changed=name), self.assertRaises(ValueError): BUILDER.verify_abi(altered)

    def test_all_original_fake_buffers_and_production_signal_evidence_are_required(self):
        records = []
        for scenario, status in enumerate(((0, 0), (-1, 4), (-1, 14), (0, 0))):
            value = pause_value(); value.update(scenario=scenario, rc=status[0], errno=status[1])
            if scenario == 1: value['remaining'] = struct.pack('<qq', 0, 30_000_000).hex()
            if scenario == 3: value['request_after'] = struct.pack('<qq', 0, 1).hex()
            records.append(value)

        def text(values):
            return '\n'.join('NEO_PAUSE_FIXTURE ' + json.dumps(v) for v in values) + '\npause fixtures passed:'

        self.assertEqual(BUILDER.verify_fixtures(text(records)), 4)
        for altered in (records[:-1], records + [records[-1]], records[::-1]):
            with self.assertRaises(ValueError): BUILDER.verify_fixtures(text(altered))
        wrong = copy.deepcopy(records); wrong[0]['calls'] = True
        with self.assertRaises(ValueError): BUILDER.verify_fixtures(text(wrong))
        success, interrupted = pause_value(), pause_value()
        success['mode'] = 'success'
        interrupted.update(mode='interrupted', rc=-1, errno=4, remaining=struct.pack('<qq', 0, 30_000_000).hex())
        original = 'NEO_PAUSE_REAL ' + json.dumps(success) + '\nNEO_PAUSE_REAL ' + json.dumps(interrupted)
        original += '\nARM production pause library passed:'
        self.assertEqual(BUILDER.verify_production(original), 2)
        with self.assertRaises(ValueError): BUILDER.verify_production(original.replace('"calls": 1', '"calls": 2'))


if __name__ == '__main__':
    unittest.main()
