#!/usr/bin/env python3
"""Offline wake/clock assessment; never rewrites or requalifies the original result."""
import hashlib
import json
import os
from pathlib import Path

from remote import LOCAL, ROOT, evidence_directory
import sleep_rtc


def assess(path):
    raw = path.read_bytes()
    record = json.loads(raw)
    if record.get('event') not in ('failed', 'complete') or type(record.get('passed')) is not bool:
        raise ValueError('Require the original final result, not an in-progress snapshot')
    result = dict(original_run=record['run_id'], original_passed=record['passed'],
                  original_error=record.get('error'), input_sha256=hashlib.sha256(raw).hexdigest(),
                  overall_requalified=False, criteria_sources=sleep_rtc.sources(),
                  limits='Offline RTC/trace/clock assessment only; original recovery result is unchanged.')
    try:
        result['measurement'] = sleep_rtc.validate_delivery(record)
        if sleep_rtc.sleep_window.recorded(record) != sleep_rtc.SECONDS:
            result['battery_observation'] = sleep_rtc.sleep_window.assess(record)
        lock = record.get('before', {}).get('image', {}).get('sources', {})
        if sleep_rtc.cpi_idle.enabled(lock):
            result['cpi_wfi'] = sleep_rtc.cpi_idle.assess(record.get('cpu_idle_before'),
                record.get('cpu_idle_after'), record['mode'], result['measurement'])
        result['measurement_checks_passed'] = True
    except (ValueError, KeyError, TypeError) as error:
        result.update(measurement_checks_passed=False, measurement_error=type(error).__name__+': '+str(error))
    if path.read_bytes() != raw:
        raise ValueError('Original result changed during offline analysis')
    return result


def main():
    value = os.environ.get('NEO_SLEEP_RESULT', '')
    if not value:
        raise ValueError('Supply RESULT=path/to/saved/final-result.json')
    path = (ROOT/Path(value)).resolve(strict=True)
    if not path.is_relative_to((LOCAL/'diagnostics').resolve()) or not path.is_file():
        raise ValueError('Use a saved private diagnostic result')
    result = assess(path)
    capture = evidence_directory()
    (capture/'sleep-evidence.json').write_text(json.dumps(result, indent=2)+'\n')
    print('Private offline sleep assessment:', capture)
    print('Original overall pass:', result['original_passed'], '; overall requalified: False')
    print('RTC/trace/clock checks:', 'passed' if result['measurement_checks_passed'] else 'failed')
    if not result['measurement_checks_passed']:
        raise ValueError('Measurement checks failed; see the separate assessment')


if __name__ == '__main__':
    main()
