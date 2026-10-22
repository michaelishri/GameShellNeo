"""Conditional synthetic counter intervals; no kernel or device interface."""
from collections import Counter

RATE = 24_000_000
MASK = (1 << 32) - 1
HALF = 1 << 31
MAX_COUNTER = (1 << 63) - 1
GATES = ('ready', 'controls_stable', 'sequence_accepted', 'same_cpu_in_brackets',
         'no_loss', 'ordering_proven', 'wrap_bound_proven')
LABELS = ('premise-unqualified', 'nominal-interval-compatible',
          'counter-path-order-disagreement', 'reference-order-or-wrap-ambiguous',
          'overlap-or-quantization-uncertain', 'nominal-rate-or-offset-disagreement')
FAMILIES = ('forward', 'architectural-minus18', 'mmio-only-reversal',
            'wrap', 'brackets', 'premises')


def integer(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Invalid synthetic unsigned integer')
    return value


def record(counter, before, after):
    """Fixture notation uses increasing counts; preserve exported raw downcounts."""
    return dict(counter=counter, before=MASK ^ before, after=MASK ^ after)


def analyze(first, second, gates):
    """Evaluate declared assumptions, never certify them or a real counter.

    Each reference integer conservatively denotes a closed one-tick interval.
    The nominal rate/offset comparison permits another tick at each counter
    endpoint. These are explicit model assumptions, not measured MMIO bounds.
    """
    for value in (first, second):
        if type(value) is not dict or set(value) != {'counter', 'before', 'after'}:
            raise ValueError('Expected exact synthetic record fields')
        integer(value['counter'], MAX_COUNTER)
        integer(value['before'], MASK); integer(value['after'], MASK)
    if (type(gates) is not dict or set(gates) != set(GATES) or
            any(type(value) is not bool for value in gates.values())):
        raise ValueError('Expected complete strict boolean premise map')
    delta = second['counter'] - first['counter']
    result = dict(schema=1, conditional=True, hardware_qualified=False,
        parent192_resolved=False, pm_admission=False, first=dict(first), second=dict(second),
        gates=dict(gates), rate_hz=RATE, reference_bits=32, counter_delta_ticks=delta,
        code=0, reference_spans=None, reference_gap=None,
        counter_delta_interval=None, uncertainty_ticks=None,
        historical_18_tick_resolution=False)
    if all(gates.values()):
        before1, after1 = MASK ^ first['before'], MASK ^ first['after']
        before2, after2 = MASK ^ second['before'], MASK ^ second['after']
        spans = ((after1 - before1) & MASK, (after2 - before2) & MASK)
        gap = (before2 - after1) & MASK
        result.update(reference_spans=list(spans), reference_gap=gap)
        if max(*spans, gap) >= HALF:
            result['code'] = 3
        else:
            uncertainty = sum(spans) + 4
            interval = [gap - 2, sum(spans) + gap + 2]
            result.update(counter_delta_interval=interval, uncertainty_ticks=uncertainty,
                historical_18_tick_resolution=uncertainty < 18)
            if gap <= 1:
                result['code'] = 4
            elif delta < 0:
                result['code'] = 2
            elif not interval[0] <= delta <= interval[1]:
                result['code'] = 5
            else:
                result['code'] = 1
    result['interpretation'] = LABELS[result['code']]
    return result


def fixtures():
    """Nineteen fixed cases in the six coordinator-approved families."""
    values = []
    def add(name, family, first, second, code, disabled=None):
        gates = {key: key != disabled for key in GATES}
        values.append(dict(name=name, family=family, first=record(*first), second=record(*second),
                           gates=gates, expected_code=code))
    first = (1000, 100, 102)
    add('forward-short', 'forward', first, (1050, 150, 152), 1)
    add('forward-stalled-architectural', 'forward', first, (1000, 150, 152), 5)
    add('forward-rate-offset', 'forward', first, (1100, 150, 152), 5)
    add('architectural-minus18', 'architectural-minus18', first, (982, 150, 152), 2)
    add('mmio-only-reversal', 'mmio-only-reversal', (1000, 200, 202), (1050, 150, 152), 3)
    wrap = (1000, MASK - 3, MASK - 1)
    add('wrap-normal', 'wrap', wrap, (1009, 3, 5), 1)
    add('wrap-half-bracket', 'wrap', (1000, 100, 100 + HALF), (1050, 150, 152), 3)
    add('wrap-half-gap', 'wrap', first, (1050, 102 + HALF, 104 + HALF), 3)
    add('wrap-unproven-window', 'wrap', wrap, (1009, 3, 5), 0, 'wrap_bound_proven')
    add('bracket-touch', 'brackets', first, (982, 102, 104), 4)
    add('bracket-quantization', 'brackets', first, (982, 103, 105), 4)
    add('bracket-wide-minus18', 'brackets', (1000, 100, 130), (982, 150, 180), 2)
    add('bracket-resolution-boundary', 'brackets', (1000, 100, 108), (982, 150, 156), 2)
    for key in GATES[:-1]:
        add('premise-' + key, 'premises', first, (982, 150, 152), 0, key)
    assert len(values) == 19 and set(Counter(v['family'] for v in values)) == set(FAMILIES)
    return values


def assess():
    """The current feasibility outcome cannot authorize an instrumented probe."""
    return dict(schema=1, complete=True, decision='STOP',
        reasons=['Two-sided relaxed-MMIO/CP15 ordering has not been justified by the cited contract.',
                 'Using readl adds DSB before the original ISB/MRRC and changes the observation.',
                 'No actual MMIO bracketing latency or sub-18-tick resolution has been measured.',
                 'No diagnostic provider/lifetime interface has been implemented or qualified.'],
        kernel_instrumentation=False, image_built=False, device_contacted=False,
        production_or_policy_changed=False, parent192_resolved=False, pm_admission=False,
        clock_reliability_qualified=False)
