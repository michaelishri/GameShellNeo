#!/usr/bin/env python3
"""Four alternating cable sleeps, one explicitly attended step per invocation."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import uuid

from private_config import load_env
from remote import LOCAL, ROOT, evidence_directory
import sleep_rtc as diagnostic


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


host = module('cable_batch_sleep_host', 'check-sleep-rtc.py')
report = module('cable_batch_observer', 'report-sleep-cable.py')
save = diagnostic.pm_module().save


def sources():
    files = ('check-sleep-cable-batch.py', 'check-sleep-rtc.py', 'report-sleep-cable.py')
    return dict(device=diagnostic.sources(), host={name: hashlib.sha256(
        (ROOT/'tools'/name).read_bytes()).hexdigest() for name in files})


def checked_root(value):
    path = (ROOT/Path(value)).resolve(strict=True)
    if not path.is_relative_to((LOCAL/'diagnostics').resolve()) or not path.is_dir():
        raise ValueError('BATCH must be the saved private diagnostic directory')
    return path


def read(root, check_sources=True):
    state = json.loads((root/'batch.json').read_text())
    if check_sources and state.get('sources') != sources():
        raise ValueError('Batch sources changed; preserve this session and prepare a fresh baseline')
    diagnostic.policy.run_id(state['id'])
    if state.get('sequence') != list(diagnostic.sleep_cable_batch.SEQUENCE):
        raise ValueError('Batch sequence changed')
    return state


def local_file(root, relative):
    path = (root/relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Batch evidence must remain inside its original capture')
    return path


def original(root, entry, field='result'):
    path = local_file(root, entry[field])
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry[field+'_sha256']:
        raise ValueError('Previously accepted batch evidence changed')
    return path


def record_file(root, path, field):
    return {field: str(path.relative_to(root)), field+'_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def qualification(root, state):
    base = local_file(root, 'baseline.json')
    if hashlib.sha256(base.read_bytes()).hexdigest() != state['baseline_sha256']:
        raise ValueError('Batch baseline changed')
    value = json.loads(base.read_text())
    if value.get('sleeps') or 'cable_batch' in value:
        raise ValueError('Start a cable batch from an unused debug baseline')
    value['cable_batch'] = dict(id=state['id'], sequence=state['sequence'])
    value['sleeps'] = []
    for entry in state['completed']:
        result = original(root, entry)
        awake = original(root, entry, 'rehearsal')
        original(root, entry, 'observation')
        original(root, entry, 'endpoint')
        value['sleeps'].append(dict(capture=str(result), rehearsal=str(awake)))
    return value


def step(config, root, state):
    if state['event'] != 'ready' or len(state['completed']) >= 4 or state.get('pending'):
        raise ValueError('Batch is not ready; inspect/observe the original attempt, never replay it')
    index = len(state['completed'])
    q = qualification(root, state)
    profile = state['sequence'][index]
    diagnostic.sleep_cable_batch.definition(q['cable_batch'], index, profile)
    cycle = root/f'cycle-{index+1}'
    cycle.mkdir(mode=0o700)
    # Persist before contacting the device. A killed/uncertain step cannot be
    # resumed by calling next; its original run must be collected separately.
    state.update(event='running', current_cycle=index+1)
    save(root/'batch.json', state)
    try:
        source = cycle/'qualification.json'
        save(source, q)
        awake_dir, sleep_dir = cycle/'awake', cycle/'sleep'
        awake_dir.mkdir(mode=0o700)
        print(f'Cycle {index+1}/4: awake alarm rehearsal; keep USB unchanged.', flush=True)
        awake = host.experiment(config, awake_dir, source, 'rehearse', '', profile)
        check_result(awake, profile, 'rehearse')
        if state['sources'] != sources():
            raise ValueError('Sources changed during the awake rehearsal')
        sleep_dir.mkdir(mode=0o700)
        print(f'Cycle {index+1}/4: one {profile} sleep; follow the GameShell screen.', flush=True)
        result = host.experiment(config, sleep_dir, source, 'rtc-wake', awake['run_id'], profile)
        check_result(result, profile, 'rtc-wake')
        # Keep the original physical endpoint untouched until its observation.
        # This separate inspection must also pass before any next cycle.
        endpoint = cycle/'endpoint'
        endpoint.mkdir(mode=0o700)
        host.inspect_live(config, endpoint, 'connection', 'wifi')
        path = endpoint/'connection-inspection.json'
        inspection = json.loads(path.read_text())
        if inspection['sources'] != diagnostic.sources():
            raise ValueError('Endpoint inspector sources changed')
        diagnostic.sleep_connection.unchanged(result['cable']['after'], inspection['connection'],
            diagnostic.sleep_connection.endpoint(profile, 'rtc-wake', 'after'))
        state['pending'] = (dict(run_id=result['run_id'], connection=profile) |
            record_file(root, sleep_dir/'result.json', 'result') |
            record_file(root, awake_dir/'result.json', 'rehearsal') |
            record_file(root, path, 'endpoint'))
        state['event'] = 'awaiting-observation'
        print('Stopped for owner observation. Keep the cable in its ending state.', flush=True)
    except BaseException as error:
        state.update(event='failed', error=type(error).__name__+': '+str(error))
        raise
    finally:
        save(root/'batch.json', state)


def check_result(value, profile, mode):
    diagnostic.completed_result(diagnostic.pm_module(), value,
        json.loads((ROOT/'build/sources.lock.json').read_text()), mode)
    expected_usb = diagnostic.sleep_connection.endpoint(profile, mode, 'after') == 'usb'
    if (value.get('connection') != profile or value.get('wifi_ssh_verified') is not True or
            value.get('usb_ssh_verified') is not expected_usb):
        raise ValueError('Cable batch is missing its endpoint-specific route proofs')


def start(config, root, baseline):
    value = json.loads(Path(baseline).read_text())
    if value.get('sleeps') or 'cable_batch' in value:
        raise ValueError('Cable batch requires a fresh seven-debug baseline')
    save(root/'baseline.json', value)
    state = dict(id=uuid.uuid4().hex, sequence=list(diagnostic.sleep_cable_batch.SEQUENCE),
                 sources=sources(), event='ready', passed=False, completed=[],
                 baseline_sha256=hashlib.sha256((root/'baseline.json').read_bytes()).hexdigest())
    save(root/'batch.json', state)
    step(config, root, state)


def observe(root, state, observation, display):
    if state['event'] != 'awaiting-observation':
        raise ValueError('No completed attempt awaiting its first observer report')
    entry = state['pending']
    result = original(root, entry)
    original(root, entry, 'rehearsal')
    original(root, entry, 'endpoint')
    destination, value = report.write_report(result, observation, display,
        json.loads((ROOT/'build/sources.lock.json').read_text()))
    entry.update(record_file(root, destination, 'observation'))
    if value['attended_case_passed'] is not True:
        state.update(event='failed', error='Owner observation did not qualify this cable action/display')
    else:
        state['completed'].append(entry)
        state.pop('pending')
        done = len(state['completed']) == 4
        state.update(event='complete' if done else 'ready', passed=done)
    save(root/'batch.json', state)
    print('Batch:', state['event'], '; accepted cycles:', len(state['completed']))
    print('No device action performed. A next step needs fresh ATTENDED=1 and CABLE_ACTION=1.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for name in ('start', 'next', 'observe', 'status'):
        modes.add_argument('--'+name, action='store_true')
    args = parser.parse_args()
    if args.start or args.next:
        if (os.environ.get('NEO_SLEEP_ATTENDED') != '1' or
                os.environ.get('NEO_SLEEP_CABLE_ACTION') != '1'):
            parser.error('Describe this next cable step, confirm readiness, then set ATTENDED=1 CABLE_ACTION=1')
    os.umask(0o077)
    with (LOCAL/'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.start:
            baseline = os.environ.get('NEO_SLEEP_QUALIFICATION', '')
            if not baseline:
                parser.error('Supply QUALIFICATION=the fresh seven-debug history')
            root = evidence_directory()
            print('Private cable batch:', root, flush=True)
            start(load_env(), root, Path(baseline))
        else:
            name = os.environ.get('NEO_SLEEP_BATCH', '')
            if not name:
                parser.error('Supply BATCH=the original private batch directory')
            root = checked_root(name)
            state = read(root, check_sources=not args.status)
            if args.observe:
                observe(root, state, os.environ.get('NEO_SLEEP_CABLE_OBSERVATION', ''),
                        os.environ.get('NEO_SLEEP_CABLE_DISPLAY', ''))
            elif args.next:
                step(load_env(), root, state)
            else:
                print(json.dumps(state, indent=2))


if __name__ == '__main__':
    main()
