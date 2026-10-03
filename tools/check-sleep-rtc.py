#!/usr/bin/env python3
"""Prepare/run one explicitly attended RTC-wake experiment, or an awake rehearsal."""
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


def receipt(path, before):
    summary = json.loads(path.read_text())
    records = []
    for item in summary['cycles']:
        source = (ROOT/Path(item['capture'])).resolve(strict=True)
        if not source.is_relative_to((LOCAL/'diagnostics').resolve()) or source.name != 'result.json':
            raise ValueError('Qualification must reference saved diagnostic result files')
        value = json.loads(source.read_text())
        if value.get('usb_ssh_verified') is not True or value.get('wifi_ssh_verified') is not True:
            raise ValueError('Missing both-route prerequisite proof')
        records.append(value)
    ids = diagnostic.prerequisite(records, before)
    by_id = {r['run_id']: r for r in records}
    return dict(boot_id=before['boot_id'], runs=[dict(run_id=token,
                sha256=diagnostic.digest(by_id[token])) for token in ids])


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


def collect(config, token):
    diagnostic.policy.run_id(token)
    # Read saved evidence without uploading/replacing the original helper.
    base = '/var/lib/gameshellneo/sleep-tests/'+token
    command = ['sudo', '-n', 'python3', '-c',
        'from pathlib import Path; import sys; p=Path(sys.argv[1]); '
        'f=p/"result.json"; f=f if f.exists() else p/"started.json"; print(f.read_text())', base]
    with device(config, 'usb') as client:
        result = json.loads(run(client, shlex.join(command), display=False))
    if result.get('run_id') != token:
        raise ValueError('Collected another run')
    return result


def validate_result(value, token, before, mode):
    if (value.get('run_id') != token or value.get('mode') != mode or value.get('event') != 'complete' or
            value.get('passed') is not True or value.get('policy_restored') is not True or
            any(value.get(key) is not False for key in
                ('policy_owner_retained', 'dropin_retained', 'controls_retained', 'rtc_owner_retained'))):
        raise ValueError('Experiment failed/incomplete; preserve evidence and retained policy, never resubmit')
    if value['before']['boot_id'] != before['boot_id'] or value['sources'] != diagnostic.sources():
        raise ValueError('Experiment boot or helper source mismatch')
    if value['policy_before'] != value['policy_after']:
        raise ValueError('Policy changed')
    if value['power_key'].get('events') or not all(value['power_key'].get(k) is True
            for k in ('handed_back', 'logical_release_verified', 'descriptor_closed')):
        raise ValueError('Untouched power-key handoff not established')
    diagnostic.health(diagnostic.pm_module(), value, json.loads((ROOT/'build/sources.lock.json').read_text()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--rehearse', action='store_true')
    modes.add_argument('--rtc-wake', action='store_true')
    modes.add_argument('--collect', action='store_true')
    args = parser.parse_args()
    if args.rtc_wake and os.environ.get('NEO_SLEEP_ATTENDED') != '1':
        parser.error('Confirm observer readiness, then supply ATTENDED=1 for this one sleep attempt')
    os.umask(0o077)
    config, capture = load_env(), evidence_directory()
    print('Private RTC sleep evidence:', capture, flush=True)
    with (LOCAL/'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.collect:
            value = collect(config, os.environ.get('NEO_PM_RUN', ''))
            (capture/'result.json').write_text(json.dumps(value, indent=2)+'\n')
            print('Original evidence recovered; inspect status/ownership before further action.')
            return
        qualification = os.environ.get('NEO_SLEEP_QUALIFICATION', '')
        if not qualification:
            raise ValueError('Supply QUALIFICATION=path/to/strict-reference-history.json')
        mode = 'rtc-wake' if args.rtc_wake else 'rehearse'
        rehearsal = os.environ.get('NEO_SLEEP_REHEARSAL', '')
        if args.rtc_wake:
            diagnostic.policy.run_id(rehearsal)
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
            print(mode, 'passed; original power policy and both SSH routes verified.', flush=True)
            return
        raise TimeoutError('No complete result. Do not retry sleep; collect original RUN='+token)


if __name__ == '__main__':
    main()
