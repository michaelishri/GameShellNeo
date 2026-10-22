"""Recompute charging results on the host without executing collector I/O."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re

from awake_clock import checked_proof, validate as validate_awake
import charge_inventory as inventory

_spec = importlib.util.spec_from_file_location('_charge_result_sampler', Path(__file__).with_name('sample-charge.py'))
sampler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sampler)


def require(condition, message):
    if not condition:
        raise ValueError('Charging result: ' + message)


def checkpoint(value):
    """Derive bounds from raw integers in a private copy; ignore stored offsets."""
    require(type(value) is dict and type(value.get('boot_id')) is str and bool(value['boot_id']),
            'missing checkpoint boot identity')
    clock, pm = value.get('clock'), value.get('pm')
    require(type(clock) is dict and type(pm) is dict and set(pm) == {'success', 'fail'} and
            all(type(number) is str and re.fullmatch(r'0|[1-9][0-9]*', number) for number in pm.values()),
            'invalid raw PM counters or clock')
    keys = ('monotonic_before_ns', 'boottime_ns', 'monotonic_after_ns')
    require(all(type(clock.get(key)) is int and clock[key] >= 0 for key in keys),
            'invalid raw clock integer')
    before, boot, after = (clock[key] for key in keys)
    observation = dict(schema_version=1, boot_id=value['boot_id'], monotonic_before_ns=before,
        boottime_ns=boot, monotonic_after_ns=after, pm_counts={key:int(number) for key, number in pm.items()})
    normalized = copy.deepcopy(value)
    normalized['clock']['offset_low_ns'] = boot - after
    normalized['clock']['offset_high_ns'] = boot - before
    return normalized, observation


def admit(rows, *, seconds, kernel, image):
    """Check one result stream, not current device/image admission or calibration."""
    require(type(seconds) is int and 60 <= seconds <= 600 and seconds % 10 == 0 and
            all(type(value) is str and bool(value) for value in (kernel, image)),
            'invalid expected operation')
    require(type(rows) is list and all(type(row) is dict for row in rows), 'invalid result stream')
    events = [row.get('event') for row in rows]
    require(events == ['started'] + ['sample'] * (seconds // 10 + 1) + ['completed'],
            'missing, repeated, failed or incomplete result events')
    started, completed = rows[0], rows[-1]
    require(type(started.get('schema_version')) is int and started['schema_version'] == 1 and
            type(started.get('seconds')) is int and started['seconds'] == seconds and
            type(started.get('interval_seconds')) is int and started['interval_seconds'] == 10 and
            started.get('limits') == sampler.LIMITS and completed.get('passed') is True,
            'started/completed operation identity differs')
    initial = started.get('inventory')
    require(type(initial) is dict and type(initial.get('schema_version')) is int and
            initial['schema_version'] == inventory.SCHEMA_VERSION and
            initial.get('kind') == 'axp223-charge-inventory' and initial.get('completed') is True and
            initial.get('kernel') == kernel and type(initial.get('image')) is dict and
            initial['image'].get('kernel') == kernel and initial['image'].get('version') == image and
            initial['image'].get('board') == 'gameshellneo-cpi31', 'inventory result identity differs')
    try:
        first, first_observation = checkpoint(initial['before'])
        last, last_observation = checkpoint(initial['after'])
        inventory.validate_continuity(first, last)
        observations = [first_observation, last_observation]
        samples, measured = [], []
        for index, row in enumerate(rows[1:-1]):
            value = row['sample']
            require(type(value) is dict and type(value.get('index')) is int and value['index'] == index,
                    'sample identity differs')
            value = copy.deepcopy(value)
            for point in ('before', 'after'):
                value[point], observation = checkpoint(value[point])
                measured.append(observation)
                observations.append(observation)
            samples.append(value)
        # This existing validator checks integer order, bounded brackets, one common
        # raw offset and stable boot/PM counts. Its original limits remain explicit.
        validate_awake(observations)
        validation = checked_proof(dict(schema_version=1, observations=measured),
                                   seconds=seconds, boot_id=first['boot_id'])
        summary = sampler.summary(samples, seconds)
        stored = completed.get('summary')
        require(type(stored) is dict and json.dumps(stored, sort_keys=True, allow_nan=False) ==
                json.dumps(summary, sort_keys=True, allow_nan=False), 'stored summary differs from raw samples')
    except (KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError('Charging result: incomplete or malformed raw evidence') from error
    return dict(schema=1, operation='host-charge-result-admission', requested_seconds=seconds,
        expected_kernel=kernel, expected_image=image, boot_id=first['boot_id'],
        sample_count=len(samples), awake_validation=validation, summary=summary,
        calibrated=False, charging_safety_qualified=False, sleep_charge_measured=False,
        current_device_or_image_admitted=False, clock_reliability_qualified=False)


def admit_capture(path, *, seconds, kernel, image):
    """Preserve raw bytes on refusal and save a separate successful replay receipt."""
    path = Path(path)
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.decode().splitlines()]
    result = admit(rows, seconds=seconds, kernel=kernel, image=image)
    receipt = dict(result, raw_sha256=hashlib.sha256(raw).hexdigest())
    with path.with_suffix('.admission.json').open('x') as output:
        json.dump(receipt, output, indent=2); output.write('\n')
    return result
