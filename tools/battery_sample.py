"""Read the explicit sleep-inclusive battery observation contract; never reinterpret legacy time."""
import math
from pathlib import Path
import time


def sample_age(sample, *, now=None, boot_id=None):
    if (type(sample.get('schema_version')) is not int or sample['schema_version'] != 2 or
            sample.get('sample_clock') != 'CLOCK_BOOTTIME'):
        raise ValueError('Battery sample lacks the BOOTTIME schema; use its matching image tools')
    if boot_id is None:
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if type(boot_id) is not str or not boot_id or sample.get('boot_id') != boot_id:
        raise ValueError('Battery sample is from a different or unknown boot')
    if now is None:
        now = time.clock_gettime(time.CLOCK_BOOTTIME)
    observed = sample.get('boottime_seconds')
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
           for value in (now, observed)) or observed > now:
        raise ValueError('Invalid BOOTTIME battery observation')
    return now - observed
