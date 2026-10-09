"""Explicit kernel-clock reads must be ABI-gated and never erase discrepancies."""
from copy import deepcopy
import ctypes
import importlib.util
import itertools
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, MagicMock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, TOOLS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recorder = load('clock_paths_test_recorder', 'compare-clock-paths.py')
host = load('clock_paths_test_host', 'check-clock-paths.py')


def abi():
    return dict(platform='linux', machine='armv7l', byteorder='little', pointer_bytes=4,
                long_bytes=4, int_bytes=4, timespec_bytes=16, timespec_alignment=8,
                timespec_offsets=[0, 8], elf_class=1, elf_data=1, elf_machine=40,
                elf_eabi=5, syscall=403, clocks=dict(monotonic=1, raw=4, boottime=7))


def sample(start=0):
    return {name: dict(cpu_before=0, cpu_after=0, values_ns=list(range(start, start+5)))
            for name in recorder.CLOCKS}


def observation(**kwargs):
    tick = itertools.count()
    return recorder.measure({name: lambda: next(tick) for name in recorder.CLOCKS},
                            lambda _: next(tick), lambda: 0, lambda _: None, **kwargs)


class ABI(unittest.TestCase):
    def test_other_architecture_or_layout_never_resolves_a_syscall(self):
        for change in ({'machine': 'x86_64'}, {'long_bytes': 8}, {'elf_eabi': 0},
                       {'elf_machine': 183}, {'byteorder': 'big'}, {'syscall': 263},
                       {'timespec_offsets': [0, 4]}, {'timespec_bytes': 8}, {'elf_class': True}):
            libc = Mock()
            with self.subTest(change=change), self.assertRaises(ValueError):
                recorder.KernelReader(abi() | change, libc)
            self.assertEqual(libc.mock_calls, [])
            self.assertNotIn('syscall', libc._mock_children)

    def test_time64_structure_and_exact_fixed_call_preserve_large_seconds(self):
        def call(number, clock, pointer):
            self.assertEqual((number, clock), (403, 1))
            value = ctypes.cast(pointer, ctypes.POINTER(recorder.KernelTimespec)).contents
            value.tv_sec, value.tv_nsec = 2**33, 123
            return 0
        libc = SimpleNamespace(syscall=Mock(side_effect=call))
        read = recorder.KernelReader(abi(), libc)
        self.assertEqual(read(1), 2**33 * 1_000_000_000 + 123)
        self.assertEqual(libc.syscall.call_count, 1)
        with self.assertRaises(ValueError):
            read(99)
        self.assertEqual(libc.syscall.call_count, 1)

    def test_kernel_error_and_invalid_timespec_preserve_raw_result_without_retry(self):
        for rc, seconds, nanoseconds in ((-1, -1, -1), (0, 1, 1_000_000_000), (0, -1, 0)):
            def call(number, clock, pointer):
                value = ctypes.cast(pointer, ctypes.POINTER(recorder.KernelTimespec)).contents
                value.tv_sec, value.tv_nsec = seconds, nanoseconds
                ctypes.set_errno(38 if rc else 0)
                return rc
            libc = SimpleNamespace(syscall=Mock(side_effect=call))
            with self.subTest(rc=rc, nanoseconds=nanoseconds):
                with self.assertRaises(recorder.ReadFailure) as error:
                    recorder.KernelReader(abi(), libc)(1)
                self.assertEqual(error.exception.evidence,
                    dict(returncode=rc, errno=38 if rc else 0, tv_sec=seconds, tv_nsec=nanoseconds))
                self.assertEqual(libc.syscall.call_count, 1)

    def test_pinned_definitions_reject_changed_syscall_width_base_and_clock_ids(self):
        files = dict(zip(host.FILES, (
            '403 common clock_gettime64 sys_clock_gettime\n',
            'struct __kernel_timespec { __kernel_time64_t tv_sec; long long tv_nsec; };',
            'typedef long long __kernel_time64_t;',
            '#define CLOCK_MONOTONIC 1\n#define CLOCK_MONOTONIC_RAW 4\n#define CLOCK_BOOTTIME 7\n',
            '#if defined(__thumb__) || defined(__ARM_EABI__)\n#define __NR_SYSCALL_BASE 0\n',
            '#define EF_ARM_EABI_MASK 0xff000000\n#define EF_ARM_EABI_VER5 0x05000000\n',
            '#define ELFCLASS32 1\n#define ELFDATA2LSB 1\n', '#define EM_ARM 40\n')))
        host.verify_headers(files)
        for index, old, new in ((0, '403', '404'), (1, 'long long', 'long'),
                                 (2, 'long long', 'long'), (3, 'RAW 4', 'RAW 5'),
                                 (4, 'BASE 0', 'BASE 0x900000'), (5, '0x05000000', '0x04000000')):
            bad = files | {host.FILES[index]: files[host.FILES[index]].replace(old, new)}
            with self.subTest(index=index), self.assertRaises(ValueError):
                host.verify_headers(bad)


class Capture(unittest.TestCase):
    def test_fixed_work_with_equal_ticks_and_cpu_counts(self):
        api, kernel, cpu, pause = Mock(return_value=10), Mock(return_value=10), Mock(return_value=2), Mock()
        result = recorder.measure(dict.fromkeys(recorder.CLOCKS, api), kernel, cpu, pause, 2, 3)
        self.assertTrue(result['complete'])
        self.assertEqual((result['samples'], result['discrepancy_samples']), (6, 0))
        self.assertEqual((api.call_count, kernel.call_count, cpu.call_count, pause.call_count), (54, 36, 36, 2))
        self.assertEqual(result['cpu_before_counts'], dict.fromkeys(recorder.CLOCKS, {'2': 6}))

    def test_individual_path_cross_path_and_between_sequence_ordering(self):
        for values, expected in (([10, 9, 12, 13, 14], {'monotonic.interleaved'}),
                                 ([10, 11, 9, 13, 14], {'monotonic.python', 'monotonic.interleaved'}),
                                 ([10, 13, 14, 12, 16], {'monotonic.syscall', 'monotonic.interleaved'})):
            current = sample(); current['monotonic']['values_ns'] = values
            with self.subTest(values=values):
                self.assertEqual(set(recorder.discrepancies(None, current)), expected)
        reasons = recorder.discrepancies(sample(10), sample())
        self.assertEqual(set(reasons), {name+'.'+path+'_between' for name in recorder.CLOCKS
                                       for path in ('python', 'syscall', 'interleaved')})

    def test_event_cap_keeps_original_values_and_total_counts(self):
        tick = itertools.cycle([10, 9, 12, 13, 14])
        result = recorder.measure({name: lambda: next(tick) for name in recorder.CLOCKS},
                                  lambda _: next(tick), lambda: 0, lambda _: None, 1, 40)
        self.assertEqual((result['samples'], result['discrepancy_samples']), (40, 40))
        self.assertEqual(len(result['events']), 32)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['events'][0]['sample']['monotonic']['values_ns'], [10, 9, 12, 13, 14])

    def test_partial_read_failure_stops_without_claiming_complete_or_retry(self):
        failure = recorder.ReadFailure({'errno': 38})
        kernel = Mock(side_effect=failure)
        result = recorder.measure(dict.fromkeys(recorder.CLOCKS, lambda: 10), kernel,
                                  lambda: 0, lambda _: None, 2, 3)
        self.assertFalse(result['complete'])
        self.assertEqual(result['samples'], 0)
        self.assertEqual(result['error']['stage'], 'monotonic.syscall')
        self.assertEqual(result['error']['partial']['monotonic']['values_ns'], [10])
        self.assertEqual(result['error']['detail'], {'errno': 38})
        self.assertEqual(kernel.call_count, 1)


class Validation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        metadata = dict(boot_id='boot', clocksource='arch_sys_counter', affinity=[0, 1, 2, 3])
        cls.result = dict(schema=1, operation='awake-clock-path-comparison', complete=True,
            abi=abi(), metadata=metadata, after_metadata=metadata.copy(), batches=300,
            per_batch=50, pause_seconds=0.1, observation=observation())

    def test_missing_work_context_metadata_and_unexplained_counts_reject(self):
        state = Mock()
        def module(name, file):
            return recorder if file == 'compare-clock-paths.py' else SimpleNamespace(validate_state=state)
        with patch.object(host, 'load', side_effect=module):
            host.validate_result(self.result, {'boot_id': 'boot'}, {'boot_id': 'boot'})
            state.assert_called_once()
            for change in ('bounds', 'work', 'cpu', 'metadata', 'failure', 'counts', 'abi'):
                bad = deepcopy(self.result)
                if change == 'bounds': bad['per_batch'] = 51
                if change == 'work': bad['observation']['samples'] -= 1
                if change == 'cpu': bad['observation']['cpu_before_counts']['raw'] = {'3': 1}
                if change == 'metadata': bad['after_metadata']['clocksource'] = 'timer'
                if change == 'failure': bad['observation']['error'] = {'reason': 'read failed'}
                if change == 'counts': bad['observation']['counts'] = {'raw.python': 1}
                if change == 'abi': bad['abi']['elf_machine'] = 183
                with self.subTest(change=change), self.assertRaises(ValueError):
                    host.validate_result(bad, {'boot_id': 'boot'}, {'boot_id': 'boot'})

    def test_raw_events_are_reclassified_not_trusted(self):
        result = deepcopy(self.result)
        first = result['observation']['first']
        first['monotonic']['values_ns'] = [10, 9, 12, 13, 14]
        event = dict(index=1, previous=None, sample=first, reasons=['monotonic.interleaved'])
        result['observation'].update(discrepancy_samples=1, events=[event], counts={'monotonic.interleaved': 1})
        def module(name, file):
            return recorder if file == 'compare-clock-paths.py' else SimpleNamespace(validate_state=Mock())
        with patch.object(host, 'load', side_effect=module):
            host.validate_result(result, {'boot_id': 'boot'}, {'boot_id': 'boot'})
            event['sample']['monotonic']['values_ns'] = [10, 11, 12, 13, 14]
            with self.assertRaisesRegex(ValueError, 'classification'):
                host.validate_result(result, {'boot_id': 'boot'}, {'boot_id': 'boot'})

    def test_remote_failure_still_collects_postflight_without_resubmission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'build').mkdir(); (root/'tools').mkdir()
            lock = dict(image_version='test', linux=dict(tag='v6.18.54', localversion='-test'))
            (root/'build/sources.lock.json').write_text(json.dumps(lock))
            (root/'tools/compare-clock-paths.py').write_text('test source')
            before = dict(kernel='6.18.54-test', image={'version': 'test'},
                pm={'pm_test': '[none]'}, usb=['configured'],
                external_power={'axp20x-usb': {'type': 'USB', 'present': '1', 'online': '1'}},
                services={'battery': {'ActiveState': 'active', 'NRestarts': '1'}})
            pm = SimpleNamespace(wifi_proof=Mock())
            inspect = Mock(return_value=before)
            remote = Mock(side_effect=[b'', RuntimeError('transport ended')])
            with patch.object(sys, 'argv', ['clock-paths']), patch.object(host, 'ROOT', root), \
                    patch.object(host, 'LOCAL', root), patch.object(host, 'evidence_directory', return_value=root), \
                    patch.object(host, 'source_receipt', return_value={}), patch.object(host, 'load_env'), \
                    patch.object(host, 'device', return_value=MagicMock()), patch.object(host, 'load', return_value=pm), \
                    patch.object(host, 'inspection_program', return_value='inspection source'), \
                    patch.object(host, 'inspect', inspect), \
                    patch.object(host, 'run', remote), self.assertRaisesRegex(RuntimeError, 'transport ended'):
                host.main()
            self.assertEqual(remote.call_count, 2)  # Active-unit check and one submission.
            self.assertEqual(inspect.call_count, 2)
            self.assertEqual([call.args[-1] for call in inspect.call_args_list], ['before', 'after'])
            self.assertFalse((root/'summary.json').exists())
            pm.wifi_proof.assert_not_called()


if __name__ == '__main__':
    unittest.main()
