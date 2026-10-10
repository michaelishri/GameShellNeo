"""Offline replay must retain regressions and reject misleading partial evidence."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import clock_provenance as cp
SPEC = importlib.util.spec_from_file_location('provenance_check', ROOT / 'tools/check-clock-provenance.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def call(ordinal=1, clock=4, cycles=1200, ns=6350):
    base = dict(mask=(1 << 56) - 1, last=1000, xtime=400, max=1 << 40,
                max_raw=1 << 55, base=7_000_000_000, mult=125, shift=2, source_id=3)
    return dict(type='call', ordinal=ordinal, read_order=ordinal*2-1, end_order=ordinal*2,
        clock=clock, abi=64, syscall=403, tid=42, tgid=42, cycles=cycles, ns=ns,
        seq=8, attempts=1, cpu=0, end_cpu=0, accepted=1, valid=1, complete=1, error=0,
        sec=16 if clock == 7 else 7, nsec=ns, namespace_id=99, offset_sec=0, offset_nsec=0,
        tuple=dict(mono=base.copy(), raw=base.copy(), xtime_sec=1007, raw_sec=7,
                   wall_sec=-1000, wall_nsec=0, offs_boot=9_000_000_000,
                   clock_set=0, source_changed=1))


def stream(*calls):
    return [dict(type='header', schema=1, reason=2, calls=len(calls), writers=0,
                 writer_lost=0, limit=len(calls), time_ns=99), *calls]


class ClockReplayTests(unittest.TestCase):
    def test_three_clocks_and_namespace(self):
        values = [call(i + 1, clock) for i, clock in enumerate((1, 4, 7))]
        for c in values:
            c['offset_sec'] = 2
            c['offset_nsec'] = 100
            c['sec'] += 2
            c['nsec'] += 100
        result = cp.replay(stream(*values))
        self.assertTrue(result['complete'])
        self.assertEqual(result['regressions'], [])

    def test_raw_regression_preserved(self):
        result = cp.replay(stream(call(), call(2, cycles=1176, ns=5600)))
        self.assertTrue(result['complete'])
        self.assertEqual(result['regressions'][0]['delta_ns'], -750)
        self.assertEqual(result['regressions'][0]['interpretation'], 'counter-observation-regression')

    def test_tuple_change_is_not_counter_attribution(self):
        second = call(2, cycles=1224, ns=7100)
        second['tuple']['raw_sec'] = second['sec'] = 6
        second['seq'] = 10
        result = cp.replay(stream(call(), second))
        self.assertEqual(result['regressions'][0]['interpretation'], 'regression-needs-tuple-transition-analysis')

    def test_all_upstream_conversion_branches(self):
        base = call()['tuple']['raw']
        self.assertEqual(cp.conversion(base, 999)[:2], (100, 'negative-delta'))
        base['max'] = 100
        self.assertEqual(cp.conversion(base, 2000)[:2], (31350, 'wide'))
        # Wide intermediate cannot be replaced with wrapped 64-bit multiplication.
        base.update(mask=(1 << 64) - 1, last=0, mult=(1 << 32) - 1, shift=32, xtime=0)
        self.assertEqual(cp.conversion(base, 1 << 40)[0], (1 << 40) - 256)

    def test_corruption_or_invalid_acceptance_rejected(self):
        for key, value in [('ns', 6351), ('sec', 8), ('seq', 9), ('attempts', 0),
                           ('end_order', 1), ('ordinal', 2), ('abi', 16), ('syscall', 263),
                           ('accepted', True), ('ordinal', True), ('abi', 64.0), ('syscall', 403.0)]:
            with self.subTest(key=key):
                c = call()
                c[key] = value
                with self.assertRaises(ValueError):
                    cp.replay(stream(c))
        records = stream(call(), call(2))
        records[1].update(read_order=3, end_order=4)
        records[2].update(read_order=1, end_order=2)
        with self.assertRaises(ValueError):
            cp.replay(records)
        c = call()
        c['tuple']['raw']['mask'] = 0xff00
        with self.assertRaises(ValueError):
            cp.replay(stream(c))

    def test_error_and_unfinished_records_never_qualify(self):
        for key, value in [('error', -14), ('valid', 0), ('accepted', 0), ('complete', 0),
                           ('attempts', (1 << 32) - 1)]:
            with self.subTest(key=key):
                c = call()
                c[key] = value
                result = cp.replay(stream(c))
                self.assertFalse(result['complete'])
                self.assertTrue(result['incomplete'])

    def test_counts_duplicates_and_writer_loss(self):
        c = call()
        records = stream(c)
        records[0].update(reason=3, writer_lost=1, writers=2048)
        records += [dict(type='writer', order=i + 3, cpu=0, kind=1,
                         cycles=1200, seq=0, action=0, delta=200, delta_valid=1, old=copy.deepcopy(c['tuple']), new={})
                    for i in range(2048)]
        self.assertFalse(cp.replay(records)['complete'])
        for mutation in ('duplicate', 'missing', 'false_loss'):
            r = copy.deepcopy(records)
            if mutation == 'duplicate':
                r[-1]['order'] = r[-2]['order']
            elif mutation == 'missing':
                r.pop()
            else:
                r[0]['reason'] = 2
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                cp.replay(r)
        with self.assertRaises(ValueError):
            cp.loads('{"type":"call","type":"writer"}')


class KernelResultsTests(unittest.TestCase):
    def test_arm_hooks_resolve_and_disappear_when_disabled(self):
        names = CHECK.REQUIRED_HOOKS
        CHECK.validate_symbols(set(), names, names)
        for off, on, definitions in [({'neo_clock_begin'}, names, names),
                                     (set(), names - {'neo_clock_read'}, names),
                                     (set(), names, names - {'neo_clock_end'})]:
            with self.assertRaises(ValueError):
                CHECK.validate_symbols(off, on, definitions)

    def test_only_complete_clean_kernel_suite_accepted(self):
        n = len(CHECK.CASES)
        counts = dict(tests=n, passed=n, failed=0, crashed=0, skipped=0, errors=0)
        suite = dict(name='neo-clock-provenance', arch='um', misc=counts,
                     test_cases=[dict(name=c, status='PASS') for c in CHECK.CASES], sub_groups=[])
        result = dict(name='KUnit Test Group', arch='um', misc=counts.copy(), test_cases=[], sub_groups=[suite])
        log = '\n'.join(CHECK.CASES)
        self.assertEqual(len(CHECK.results_checked(result, log)), n)
        for mode in ('duplicate', 'missing', 'skip', 'warning', 'panic'):
            r = copy.deepcopy(result)
            text = log
            cases = r['sub_groups'][0]['test_cases']
            if mode == 'duplicate':
                cases[-1] = cases[0].copy()
            elif mode == 'missing':
                cases.pop()
            elif mode == 'skip':
                cases[-1]['status'] = 'SKIP'
            else:
                text += '\n' + ('WARNING:' if mode == 'warning' else 'Kernel panic')
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                CHECK.results_checked(r, text)


if __name__ == '__main__':
    unittest.main()
