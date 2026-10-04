#!/usr/bin/env python3
"""Bind a human cable/display observation to an unchanged saved sleep result."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import sleep_rtc

ROOT = Path(__file__).resolve().parents[1]


def assessment(value, observation, display, lock):
    if observation not in ('during-dark', 'after-return', 'no-action', 'uncertain'):
        raise ValueError('Record during-dark, after-return, no-action or uncertain')
    if display not in ('normal', 'abnormal', 'unknown'):
        raise ValueError('Record normal, abnormal or unknown display return')
    connection = value.get('connection')
    if not sleep_rtc.sleep_connection.transition(connection) or value.get('mode') != 'rtc-wake':
        raise ValueError('Require an original actual cable-transition result')
    sleep_rtc.policy.run_id(value['run_id'])
    accepted = value.get('event') == 'complete' and value.get('passed') is True
    if accepted:
        sleep_rtc.completed_result(sleep_rtc.pm_module(), value, lock, 'rtc-wake')
        final_usb = sleep_rtc.sleep_connection.endpoint(connection, 'rtc-wake', 'after') == 'usb'
        if value.get('usb_ssh_verified') is not final_usb or value.get('wifi_ssh_verified') is not True:
            raise ValueError('Original result lacks the required independent route proofs')
    return dict(run_id=value['run_id'], connection=connection,
        original_event=value.get('event'), original_passed=value.get('passed'),
        original_error=value.get('error'), wake_observation=value.get('wake_observation'),
        cable_irq_observation=value.get('cable_irq_observation'),
        automated_passed=accepted, observer_action=observation, observer_display=display,
        attended_case_passed=accepted and observation == 'during-dark' and display == 'normal',
        electrical_edge_timing_qualified=False, energy_qualified=False,
        limits='Human report of one requested action after ten seconds of darkness; '
               'neither darkness nor IRQ dispatch timestamps the electrical edge inside s2idle.')


def write_report(source, observation, display, lock):
    original = source.read_bytes()
    result = assessment(json.loads(original), observation, display, lock)
    result.update(original_result=str(source.resolve()),
                  original_sha256=hashlib.sha256(original).hexdigest(),
                  assessment_sources=sleep_rtc.sources())
    destination = source.with_name(source.stem+'-cable-observation.json')
    # Never rewrite the device result or an earlier observer statement.
    with destination.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    return destination, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if not os.environ.get('NEO_SLEEP_RESULT'):
        parser.error('Supply RESULT=path/to/original/result.json')
    os.umask(0o077)
    destination, result = write_report(Path(os.environ['NEO_SLEEP_RESULT']),
        os.environ.get('NEO_SLEEP_CABLE_OBSERVATION', ''), os.environ.get('NEO_SLEEP_CABLE_DISPLAY', ''),
        json.loads((ROOT/'build/sources.lock.json').read_text()))
    print('Saved separate observer report:', destination)
    print('Attended case passed:', result['attended_case_passed'])
    print('Electrical edge timing and energy remain unqualified.')


if __name__ == '__main__':
    main()
