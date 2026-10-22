"""Recompute standalone measurement proof before host success or stage removal."""
import hashlib
import json
import math
from pathlib import Path
import re

from awake_clock import checked_proof

PREFIXES = {'idle': 'idle', 'power-profile': 'power-profile', 'governor-compare': 'governor',
            'governor-profile': 'sugov', 'rsb-compare': 'rsb'}
UNITS = {'idle': 'idle-sample', 'power-profile': 'power-profile',
         'governor-compare': 'governor-comparison', 'governor-profile': 'governor-profile',
         'rsb-compare': 'rsb-comparison'}


def require(condition, message):
    if not condition:
        raise ValueError('Awake result: ' + message)


def duration(value, minimum):
    require(type(value) in (int, float) and math.isfinite(value) and value >= minimum - 1,
            'invalid or short measurement duration')
    return value


def save_context(capture, operation, seconds, stage):
    """Retain the owned stage identity before any possibly interrupted command."""
    require(operation in PREFIXES and re.fullmatch(
        r'/tmp/gameshellneo-' + re.escape(PREFIXES[operation]) + r'\.[A-Za-z0-9]+', stage),
        'unexpected owned helper directory')
    record = dict(schema=1, operation=operation, requested_seconds=seconds,
                  remote_stage=stage, unit='gameshellneo-' + UNITS[operation],
                  scope='Owned measurement context; no clock-health or PM admission.')
    with (Path(capture) / 'awake-result-context.json').open('x') as output:
        json.dump(record, output, indent=2); output.write('\n')


def admit(records, *, operation, seconds, setting=None):
    """Check raw proof against this operation's ready identity and duration.

    The ready boot is a result-stream identity, not an independently measured
    current device boot. No source/image admission or clock-cause claim follows.
    """
    require(operation in PREFIXES and type(seconds) is int and seconds > 0,
            'unknown operation or invalid requested duration')
    require(type(records) is list and bool(records) and
            all(type(row) is dict and type(row.get('event')) is str for row in records),
            'missing or malformed result stream')
    ready = [row for row in records if row['event'] == 'ready']
    complete = [row for row in records if row['event'] == 'complete']
    require(len(ready) == len(complete) == 1 and records[-1] is complete[0] and
            complete[0].get('passed') is True and
            not any(row['event'] == 'failed' for row in records),
            'missing, repeated or failed completion')
    ready, complete = ready[0], complete[0]
    phase_operation = operation in ('governor-compare', 'rsb-compare')
    require(ready.get('seconds_per_phase' if phase_operation else 'seconds') == seconds and
            type(ready.get('seconds_per_phase' if phase_operation else 'seconds')) is int,
            'ready operation duration differs from the request')
    try:
        boot = ready['boot_id'] if operation == 'rsb-compare' else ready['initial']['boot_id']
        require(type(boot) is str and bool(boot), 'missing ready boot identity')
        if operation == 'idle':
            require(setting in ('keep', 'off') and ready.get('backlight_mode') == setting and
                    complete.get('backlight_mode') == setting and
                    ready.get('settle_seconds') == 60 and ready.get('interval_seconds') == 10,
                    'idle operation identity differs')
            minimum = duration(complete['duration_seconds'], seconds) + 60
        elif operation == 'power-profile':
            require(ready.get('settle_seconds') == 30 and type(ready.get('capabilities')) is dict,
                    'power-profile operation identity differs')
            minimum = duration(complete['duration_seconds'], seconds) + 30
        elif operation == 'governor-profile':
            require(ready.get('event_name') == 'cpu-clock:k' and
                    ready.get('sample_frequency_hz') == 99 and ready.get('callchains') is False,
                    'governor-profile operation identity differs')
            for key in ('pid', 'start_ticks'):
                require(type(ready['worker'][key]) is int and ready['worker'][key] > 0 and
                        complete['worker_after'][key] == ready['worker'][key],
                        'governor worker identity changed')
            require(complete['final']['boot_id'] == boot, 'governor profile boot changed')
            minimum = seconds
        else:
            governor = operation == 'governor-compare'
            unit = 'us' if governor else 'ms'
            candidate, original = ready['candidate_' + unit], ready['original_' + unit]
            require(type(setting) is int and type(candidate) is int and type(original) is int and
                    candidate == setting and 0 <= original and
                    complete['restored_' + unit] == original,
                    'requested or restored comparison setting differs')
            phases = complete['phases']
            labels = ['original_before', 'slower' if governor else 'shorter', 'original_after']
            require(type(phases) is list and len(phases) == 3 and
                    [phase['phase'] for phase in phases] == labels,
                    'comparison phases are missing or changed')
            setting_key = 'rate_limit_us' if governor else 'delay_ms'
            require([phase[setting_key] for phase in phases] == [original, candidate, original],
                    'comparison setting sequence differs')
            if governor:
                require(ready.get('settle_seconds') == 30 and ready.get('sample_interval_seconds') == 10,
                        'governor comparison operation identity differs')
                minimum = sum(duration(phase['counters']['duration_seconds'], seconds) for phase in phases) + 90
                for phase in phases:
                    duration(phase['battery']['duration_seconds'], seconds)
            else:
                require(ready['initial']['health']['boot_id'] == boot and
                        complete['final']['health']['boot_id'] == boot,
                        'RSB comparison boot identity changed')
                minimum = sum(duration(phase['residency']['seconds'], seconds) for phase in phases) + 45
        validation = checked_proof(complete.get('awake_proof'), seconds=minimum, boot_id=boot)
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('Awake result: incomplete operation identity or raw proof') from error
    return dict(schema=1, measurement_operation=operation, boot_id=boot,
                requested_seconds=seconds, required_coverage_seconds=minimum,
                awake_validation=validation, pm_admission=False, clock_reliability_qualified=False)


def admit_capture(path, *, operation, seconds, setting=None):
    """Preserve raw bytes on rejection; write a separate successful proof receipt."""
    path = Path(path)
    raw = path.read_bytes()
    records = [json.loads(line) for line in raw.decode().splitlines()]
    validation = admit(records, operation=operation, seconds=seconds, setting=setting)
    record = dict(validation, operation='standalone-awake-result-admission',
                  raw_sha256=hashlib.sha256(raw).hexdigest())
    with path.with_suffix('.admission.json').open('x') as output:
        json.dump(record, output, indent=2); output.write('\n')
    return records
