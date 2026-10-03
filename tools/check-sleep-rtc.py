#!/usr/bin/env python3
"""Prepare attended RTC-wake attempts/batches, or an awake rehearsal."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import time
import uuid

import paramiko
from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run, upload
import sleep_rtc as diagnostic


def pm_host():
    spec = importlib.util.spec_from_file_location('sleep_host_pm', ROOT/'tools/check-pm-stages.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def saved_result(item):
    source = (ROOT/Path(item['capture'])).resolve(strict=True)
    if not source.is_relative_to((LOCAL/'diagnostics').resolve()) or source.name != 'result.json':
        raise ValueError('Qualification must reference saved diagnostic result files')
    value = json.loads(source.read_text())
    if value.get('usb_ssh_verified') is not True or value.get('wifi_ssh_verified') is not True:
        raise ValueError('Missing both-route prerequisite proof')
    return value


def receipt(path, before):
    summary = json.loads(path.read_text())
    records = [saved_result(item) for item in summary['cycles']]
    sleeps = [saved_result(item) for item in summary.get('sleeps', [])]
    if len(sleeps) >= diagnostic.MAX_SLEEP_CHAIN:
        raise ValueError('Sleep history reached its admission limit')
    qualified = diagnostic.history(diagnostic.pm_module(), records, sleeps, before,
                                   json.loads((ROOT/'build/sources.lock.json').read_text()))
    by_id = {r['run_id']: r for r in records+sleeps}
    entries = lambda tokens: [dict(run_id=token, sha256=diagnostic.digest(by_id[token])) for token in tokens]
    return dict(boot_id=before['boot_id'], runs=entries(qualified['runs']),
                sleeps=entries(qualified['sleep_runs']))


def service(directory, token, mode, rehearsal):
    if not re.fullmatch(r'/tmp/gameshellneo-sleep\.[A-Za-z0-9]+', directory):
        raise ValueError('Unexpected sleep helper path')
    diagnostic.policy.run_id(token)
    if mode not in ('rehearse', 'rtc-wake'):
        raise ValueError('Unknown experiment mode')
    script = directory+'/sleep_rtc.py'
    command = ['sudo', '-n', 'systemd-run', '--quiet', '--collect',
        '--unit=gameshellneo-sleep-test', '--property=RuntimeMaxSec=180',
        '--property=TimeoutStopSec=10', '--property=UMask=0077',
        '--property=ExecStopPost=/usr/bin/python3 -B '+script+' --recover --run-id '+token,
        '/usr/bin/systemd-inhibit', '--what=handle-power-key:sleep:idle', '--mode=block',
        '--who=GameShellNeo PM diagnostic', '--why=Guarded RTC sleep qualification',
        '/usr/bin/python3', '-B', script, '--'+mode, '--run-id', token,
        '--lock', directory+'/sources.lock.json', '--receipt', directory+'/qualification.json']
    if mode == 'rtc-wake':
        command += ['--attended', '--rehearsal', diagnostic.policy.run_id(rehearsal)]
    return command


def collect(config, token, route='usb'):
    diagnostic.policy.run_id(token)
    if route not in ('usb', 'wifi'):
        raise ValueError('Collection route must be usb or wifi')
    # Read saved evidence without uploading/replacing the original helper.
    base = '/var/lib/gameshellneo/sleep-tests/'+token
    command = ['sudo', '-n', 'python3', '-c',
        'from pathlib import Path; import sys; p=Path(sys.argv[1]); '
        'f=p/"result.json"; f=f if f.exists() else p/"started.json"; print(f.read_text())', base]
    with device(config, route) as client:
        result = json.loads(run(client, shlex.join(command), display=False))
    if result.get('run_id') != token:
        raise ValueError('Collected another run')
    return result


def validate_result(value, token, before, mode):
    if value.get('run_id') != token or value['before']['boot_id'] != before['boot_id']:
        raise ValueError('Experiment run or boot identity mismatch')
    diagnostic.completed_result(diagnostic.pm_module(), value,
        json.loads((ROOT/'build/sources.lock.json').read_text()), mode)


def inspect_clocks(config, capture):
    with device(config, 'usb') as client:
        directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-sleep.XXXXXXXX', display=False).decode().strip()
        if not re.fullmatch(r'/tmp/gameshellneo-sleep\.[A-Za-z0-9]+', directory):
            raise ValueError('Unexpected clock inspector helper path')
        with client.open_sftp() as sftp:
            for name in diagnostic.SOURCES:
                upload(sftp, ROOT/'tools'/(name+'.py'), directory+'/'+name+'.py')
        # No systemd unit, RTC programming, owner, inhibitor or PM submission.
        value = json.loads(run(client, shlex.join(['python3', '-B', directory+'/sleep_rtc.py', '--clock-inspect']),
                               display=False, timeout=20))
        (capture/'clock-inspection.json').write_text(json.dumps(value, indent=2)+'\n')
        if value['sources'] != diagnostic.sources():
            raise ValueError('Clock inspector sources differ')
        with client.open_sftp() as sftp:
            for name in diagnostic.SOURCES:
                sftp.remove(directory+'/'+name+'.py')
            sftp.rmdir(directory)
    print('Awake clock inspection saved; no alarm, PM or network settings changed.')


def experiment(config, capture, qualification, mode, rehearsal):
    token = uuid.uuid4().hex
    helper = pm_host()
    with device(config, 'usb') as client:
        before = json.loads(helper.inline(client, '--inspect'))
        (capture/'before.json').write_text(json.dumps(before, indent=2)+'\n')
        diagnostic.pm_module().validate(before, json.loads((ROOT/'build/sources.lock.json').read_text()))
        proof = receipt(Path(qualification), before)
        helper.wifi_proof(config, before)
        if run(client, 'systemctl show gameshellneo-sleep-test -p LoadState --value', display=False).decode().strip() != 'not-found':
            raise ValueError('An earlier sleep unit exists; collect it without resubmission')
        directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-sleep.XXXXXXXX', display=False).decode().strip()
        command = service(directory, token, mode, rehearsal)
        (capture/'qualification.json').write_text(json.dumps(proof, indent=2)+'\n')
        (capture/'source.json').write_text(json.dumps(diagnostic.sources(), indent=2)+'\n')
        with client.open_sftp() as sftp:
            for name in diagnostic.SOURCES:
                upload(sftp, ROOT/'tools'/(name+'.py'), directory+'/'+name+'.py')
            upload(sftp, ROOT/'build/sources.lock.json', directory+'/sources.lock.json')
            upload(sftp, capture/'qualification.json', directory+'/qualification.json')
        (capture/'run.json').write_text(json.dumps(dict(run_id=token, mode=mode, helper=directory))+'\n')
        print('RTC sleep run:', token, 'mode:', mode, flush=True)
        try:
            run(client, shlex.join(command), display=False, timeout=20)
        except (OSError, RuntimeError, paramiko.SSHException) as error:
            (capture/'submission-error.txt').write_text(type(error).__name__+': '+str(error)+'\n')
            # Submission can have succeeded before transport loss. Collect this ID only.
    timeout = time.monotonic()+210
    while time.monotonic() < timeout:
        time.sleep(5)
        try:
            value = collect(config, token)
        except (OSError, RuntimeError, paramiko.SSHException) as error:
            with (capture/'collection-errors.txt').open('a') as output:
                output.write(type(error).__name__+': '+str(error)+'\n')
            continue
        (capture/'result.json').write_text(json.dumps(value, indent=2)+'\n')
        if value.get('event') not in ('complete', 'failed'):
            continue
        validate_result(value, token, before, mode)
        helper.wifi_proof(config, value['after'])
        with device(config, 'usb') as client:
            boot = run(client, 'cat /proc/sys/kernel/random/boot_id', display=False).decode().strip()
        if boot != before['boot_id']:
            raise ValueError('Boot changed after collection')
        value.update(usb_ssh_verified=True, wifi_ssh_verified=True)
        (capture/'result.json').write_text(json.dumps(value, indent=2)+'\n')
        print(mode, 'functional/recovery checks passed; original power policy and both SSH routes verified.', flush=True)
        print('CPU retention and energy savings remain unqualified.', flush=True)
        return value
    raise TimeoutError('No complete result. Do not retry sleep; collect original RUN='+token)


def batch(config, capture, qualification, rehearsal, cycles):
    if type(cycles) is not int or not 1 <= cycles <= 4:
        raise ValueError('An attended batch requires one to four cycles')
    original = json.loads(Path(qualification).read_text())
    if len(original.get('sleeps', []))+cycles > diagnostic.MAX_SLEEP_CHAIN:
        raise ValueError('Requested batch exceeds the sleep-chain limit')
    summary = dict(requested=cycles, completed=[], event='started', passed=False)
    save = diagnostic.pm_module().save
    current = Path(qualification)
    save(capture/'batch.json', summary)
    try:
        for index in range(cycles):
            cycle = capture/f'cycle-{index+1}'
            cycle.mkdir(mode=0o700)
            print(f'RTC batch cycle {index+1}/{cycles}: starting one attempt', flush=True)
            value = experiment(config, cycle, current, 'rtc-wake', rehearsal)
            if (value.get('passed') is not True or value.get('event') != 'complete' or
                    value.get('usb_ssh_verified') is not True or value.get('wifi_ssh_verified') is not True):
                raise ValueError('Batch cycle lacks complete recovery and both SSH proofs')
            # A new receipt is published only after the preceding attempt passed.
            continuation = json.loads(current.read_text())
            continuation['sleeps'] = continuation.get('sleeps', []) + [dict(capture=str(cycle/'result.json'))]
            current = cycle/'qualification-next.json'
            save(current, continuation)
            summary['completed'].append(dict(run_id=value['run_id'], capture=str(cycle/'result.json')))
            summary['qualification_next'] = str(current)
            save(capture/'batch.json', summary)
            print(f'RTC batch cycle {index+1}/{cycles}: passed; both SSH routes recovered', flush=True)
            if index+1 < cycles:
                time.sleep(20)  # Awake observation interval, not resume-latency evidence.
        summary.update(event='complete', passed=True)
    except BaseException as error:
        summary.update(event='failed', error=type(error).__name__+': '+str(error))
        raise
    finally:
        save(capture/'batch.json', summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--rehearse', action='store_true')
    modes.add_argument('--rtc-wake', action='store_true')
    modes.add_argument('--rtc-batch', action='store_true')
    modes.add_argument('--collect', action='store_true')
    modes.add_argument('--clock-inspect', action='store_true')
    args = parser.parse_args()
    if (args.rtc_wake or args.rtc_batch) and os.environ.get('NEO_SLEEP_ATTENDED') != '1':
        parser.error('Confirm observer readiness, then supply ATTENDED=1 for this sleep attempt or bounded batch')
    os.umask(0o077)
    config, capture = load_env(), evidence_directory()
    print('Private RTC sleep evidence:', capture, flush=True)
    with (LOCAL/'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.clock_inspect:
            inspect_clocks(config, capture)
            return
        if args.collect:
            token = os.environ.get('NEO_PM_RUN', '')
            route = os.environ.get('NEO_SLEEP_COLLECT_ROUTE', 'usb')
            value = collect(config, token, route)
            (capture/'result.json').write_text(json.dumps(value, indent=2)+'\n')
            # Read-only postmortem, with no upload, policy cleanup or PM submission.
            # Keep the original result even if the separate live snapshot fails.
            with device(config, route) as client:
                command = ['sudo', '-n', 'python3', '-c',
                           (ROOT/'tools/sleep_recovery.py').read_text(), token]
                snapshot = json.loads(run(client, shlex.join(command), display=False))
            (capture/'recovery-snapshot.json').write_text(json.dumps(snapshot, indent=2)+'\n')
            (capture/'collection.json').write_text(json.dumps(dict(route=route,
                run_id=token, original_event=value.get('event'),
                same_boot=snapshot['boot_id'] == value.get('before', {}).get('boot_id')))+'\n')
            print('Original evidence recovered via '+route+'; this does not qualify recovery or retry sleep.')
            return
        qualification = os.environ.get('NEO_SLEEP_QUALIFICATION', '')
        if not qualification:
            raise ValueError('Supply QUALIFICATION=path/to/strict-reference-history.json')
        rehearsal = os.environ.get('NEO_SLEEP_REHEARSAL', '')
        if args.rtc_wake or args.rtc_batch:
            diagnostic.policy.run_id(rehearsal)
        if args.rtc_batch:
            batch(config, capture, Path(qualification), rehearsal,
                  int(os.environ.get('NEO_PM_CYCLES', '4')))
        else:
            value = experiment(config, capture, Path(qualification),
                               'rtc-wake' if args.rtc_wake else 'rehearse', rehearsal)
            if args.rtc_wake:
                continuation = json.loads(Path(qualification).read_text())
                continuation['sleeps'] = continuation.get('sleeps', []) + [dict(capture=str(capture/'result.json'))]
                diagnostic.pm_module().save(capture/'qualification-next.json', continuation)


if __name__ == '__main__':
    main()
