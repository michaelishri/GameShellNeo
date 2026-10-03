"""Reject observed sleep/PM activity in awake-only measurements; no clock substitution."""
from pathlib import Path
import math
import time

BOOT = Path('/proc/sys/kernel/random/boot_id')
STATS = Path('/sys/power/suspend_stats')
MAX_BRACKET_NS = 1_000_000


def pm_counts():
    values = {key: int((STATS / key).read_text().strip()) for key in ('success', 'fail')}
    if any(value < 0 for value in values.values()):
        raise ValueError('Invalid suspend counters')
    return values


def observe():
    boot = BOOT.read_text().strip()
    before = pm_counts()
    lower = time.monotonic_ns()
    boottime = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    upper = time.monotonic_ns()
    after = pm_counts()
    if before != after:
        raise ValueError('System PM changed during clock observation')
    value = dict(schema_version=1, boot_id=boot, monotonic_before_ns=lower,
                 boottime_ns=boottime, monotonic_after_ns=upper, pm_counts=after)
    validate([value])
    return value


def validate(observations):
    """All samples must admit one common BOOTTIME-MONOTONIC offset and PM count."""
    if type(observations) is not list or not observations:
        raise ValueError('Missing awake clock observations; use matching measurement tools')
    lower_bound = upper_bound = previous = baseline = None
    for value in observations:
        if (type(value) is not dict or type(value.get('schema_version')) is not int or
                value['schema_version'] != 1 or type(value.get('boot_id')) is not str or
                not value['boot_id']):
            raise ValueError('Invalid awake clock schema or boot identity')
        names = ('monotonic_before_ns', 'boottime_ns', 'monotonic_after_ns')
        if any(type(value.get(key)) is not int or value[key] < 0 for key in names):
            raise ValueError('Invalid awake clock timestamp')
        start, boot, end = (value[key] for key in names)
        if not 0 <= end - start <= MAX_BRACKET_NS or boot < start:
            raise ValueError('Awake clock observation is inconsistent or too uncertain')
        counts = value.get('pm_counts')
        if (type(counts) is not dict or set(counts) != {'success', 'fail'} or
                any(type(x) is not int or x < 0 for x in counts.values())):
            raise ValueError('Missing or invalid suspend counters')
        if baseline is None:
            baseline = value
            lower_bound, upper_bound = boot - end, boot - start
        else:
            if value['boot_id'] != baseline['boot_id'] or counts != baseline['pm_counts']:
                raise ValueError('Boot or system PM counters changed during awake measurement')
            if start < previous:
                raise ValueError('Awake clock observations are out of order')
            lower_bound = max(lower_bound, boot - end)
            upper_bound = min(upper_bound, boot - start)
            if lower_bound > upper_bound:
                raise ValueError('Sleep or clock discontinuity observed during awake measurement')
        previous = end
    return dict(schema_version=1, boot_id=baseline['boot_id'],
                observation_count=len(observations), pm_counts=dict(baseline['pm_counts']),
                offset_lower_ns=lower_bound, offset_upper_ns=upper_bound,
                max_bracket_ns=max(x['monotonic_after_ns'] - x['monotonic_before_ns'] for x in observations),
                limits='Stable PM counters and intersecting clock bounds; not exclusive sleep ownership. '
                       'Sub-bracket sleep and a final pending PM-counter update can escape detection.')


def windows(records):
    observations = []
    for record in records:
        window = record.get('awake_window')
        if type(window) is not list or len(window) != 2:
            raise ValueError('Missing awake measurement window; historical results remain unqualified')
        validate(window)
        boot = record.get('boot_id', record.get('health', {}).get('boot_id'))
        if boot is not None and boot != window[0]['boot_id']:
            raise ValueError('Awake window does not match its measurement boot')
        times = [record[key] for key in ('started_ns', 'finished_ns') if key in record]
        if 'monotonic_seconds' in record:
            value = record['monotonic_seconds']
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('Invalid measurement timestamp')
            times.append(round(value * 1e9))
        if any(type(value) is not int or not window[0]['monotonic_before_ns'] - 1 <= value <=
               window[-1]['monotonic_after_ns'] + 1 for value in times):
            raise ValueError('Awake window does not enclose its measurement timestamp')
        observations.extend(window)
    return validate(observations)


def checked_proof(proof, *, seconds=0, boot_id=None):
    if type(proof) is not dict or type(proof.get('schema_version')) is not int or proof['schema_version'] != 1:
        raise ValueError('Missing awake measurement proof; use matching measurement tools')
    observations = proof.get('observations')
    if type(observations) is not list or len(observations) < 2:
        raise ValueError('Awake measurement proof needs start and end observations')
    result = validate(observations)
    elapsed = (observations[-1]['monotonic_after_ns'] - observations[0]['monotonic_before_ns']) / 1e9
    if elapsed < seconds or (boot_id is not None and result['boot_id'] != boot_id):
        raise ValueError('Awake proof does not cover the measurement duration or boot')
    return result


class AwakeRun:
    def __init__(self):
        self.observations = []
        self.check()

    def check(self):
        self.observations.append(observe())
        validate(self.observations)

    def finish(self):
        self.check()
        return dict(schema_version=1, observations=list(self.observations),
                    validation=validate(self.observations))
