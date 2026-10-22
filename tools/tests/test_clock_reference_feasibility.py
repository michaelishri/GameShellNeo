import copy
from collections import Counter
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clock_reference_feasibility import (FAMILIES, GATES, HALF, MASK, MAX_COUNTER,
                                         RATE, analyze, assess, fixtures, record)


class ReferenceFeasibilityTests(unittest.TestCase):
    def test_fixed_six_family_inventory_and_expected_classifications(self):
        values = fixtures()
        self.assertEqual(len(values), 19)
        self.assertEqual(set(v['family'] for v in values), set(FAMILIES))
        self.assertEqual(Counter(v['family'] for v in values),
            dict(forward=3, **{'architectural-minus18': 1, 'mmio-only-reversal': 1,
                              'wrap': 4, 'brackets': 4, 'premises': 6}))
        self.assertEqual(len({v['name'] for v in values}), 19)
        for case in values:
            with self.subTest(case=case['name']):
                original = copy.deepcopy(case)
                result = analyze(case['first'], case['second'], case['gates'])
                self.assertEqual(result['code'], case['expected_code'])
                self.assertEqual(case, original)
                self.assertFalse(result['hardware_qualified'])
                self.assertFalse(result['parent192_resolved'])
                self.assertFalse(result['pm_admission'])

    def test_minus18_retains_original_values_and_exact_minus750_arithmetic(self):
        case = next(v for v in fixtures() if v['name'] == 'architectural-minus18')
        result = analyze(case['first'], case['second'], case['gates'])
        self.assertEqual((result['first']['counter'], result['second']['counter']), (1000, 982))
        self.assertEqual(result['counter_delta_ticks'], -18)
        self.assertEqual(result['counter_delta_ticks'] * 1_000_000_000, -750 * RATE)
        self.assertEqual(result['interpretation'], 'counter-path-order-disagreement')
        self.assertEqual(result['counter_delta_interval'], [46, 54])
        self.assertEqual(result['uncertainty_ticks'], 8)

    def test_reference_reversal_is_never_rewritten_as_forward_wrap(self):
        case = next(v for v in fixtures() if v['name'] == 'mmio-only-reversal')
        result = analyze(case['first'], case['second'], case['gates'])
        self.assertEqual(result['counter_delta_ticks'], 50)
        self.assertEqual(result['second']['before'], MASK ^ 150)
        self.assertGreaterEqual(result['reference_gap'], HALF)
        self.assertEqual(result['code'], 3)
        self.assertIsNone(result['counter_delta_interval'])

    def test_wrap_has_explicit_assumption_and_preserves_raw_downcounter(self):
        values = {v['name']: analyze(v['first'], v['second'], v['gates']) for v in fixtures()}
        normal = values['wrap-normal']
        self.assertEqual((normal['first']['before'], normal['first']['after']), (3, 1))
        self.assertEqual(normal['reference_spans'], [2, 2])
        self.assertEqual(normal['reference_gap'], 5)
        self.assertEqual(normal['counter_delta_interval'], [3, 11])
        self.assertEqual(values['wrap-unproven-window']['code'], 0)
        for name in ('wrap-half-bracket', 'wrap-half-gap'):
            self.assertEqual(values[name]['code'], 3)

    def test_quantization_and_wide_brackets_do_not_claim_18_tick_resolution(self):
        values = {v['name']: analyze(v['first'], v['second'], v['gates']) for v in fixtures()}
        for name in ('bracket-touch', 'bracket-quantization'):
            self.assertEqual(values[name]['code'], 4)
        wide = values['bracket-wide-minus18']
        self.assertEqual(wide['code'], 2)
        self.assertEqual(wide['uncertainty_ticks'], 64)
        self.assertFalse(wide['historical_18_tick_resolution'])
        self.assertEqual(wide['counter_delta_ticks'], -18)

    def test_full_endpoint_width_at18_ticks_never_claims_resolution(self):
        case = next(v for v in fixtures() if v['name'] == 'bracket-resolution-boundary')
        result = analyze(case['first'], case['second'], case['gates'])
        self.assertEqual(result['counter_delta_interval'], [40, 58])
        self.assertEqual(result['uncertainty_ticks'], 18)
        self.assertFalse(result['historical_18_tick_resolution'])
        self.assertEqual(result['counter_delta_ticks'], -18)

    def test_missing_or_malformed_premises_cannot_assert_ordering(self):
        first, second = record(1000, 100, 102), record(982, 150, 152)
        for gate in GATES:
            context = {key: key != gate for key in GATES}
            self.assertEqual(analyze(first, second, context)['code'], 0)
        for invalid in ({}, dict.fromkeys(GATES, 1), {**dict.fromkeys(GATES, True), 'extra': True}):
            with self.assertRaises(ValueError): analyze(first, second, invalid)

    def test_scalar_abi_bounds_reject_bool_negative_and_overflow(self):
        gates = dict.fromkeys(GATES, True)
        first, second = record(1000, 100, 102), record(1050, 150, 152)
        for key, bad in (('counter', True), ('counter', -1), ('counter', MAX_COUNTER + 1),
                         ('before', -1), ('before', MASK + 1), ('after', 1.0)):
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                analyze({**first, key: bad}, second, gates)
        with self.assertRaises(ValueError): analyze({**first, 'extra': 0}, second, gates)

    def test_completed_feasibility_returns_stop_without_runtime_admission(self):
        result = assess()
        self.assertTrue(result['complete'])
        self.assertEqual(result['decision'], 'STOP')
        self.assertEqual(len(result['reasons']), 4)
        for key in ('kernel_instrumentation', 'image_built', 'device_contacted',
                    'production_or_policy_changed', 'parent192_resolved',
                    'pm_admission', 'clock_reliability_qualified'):
            self.assertIs(result[key], False)


if __name__ == '__main__':
    unittest.main()
