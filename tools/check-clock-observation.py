#!/usr/bin/env python3
"""Preserve a bounded awake clock observation without admitting any PM test."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path

from private_config import load_env
from remote import ROOT, LOCAL, device, evidence_directory, run


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_result(result, before, after):
    if (result.get('schema') != 1 or result.get('operation') != 'awake-clock-observation' or
            result.get('complete') is not True or result.get('batches') != 300 or
            result.get('per_batch') != 200 or result.get('pause_seconds') != 0.1 or
            result.get('boot_id') != before['boot_id']):
        raise ValueError('Clock observation identity or bounds failed')
    observation = result['observation']
    count = observation['regression_samples']
    if (observation['samples'] != 60000 or type(count) is not int or not 0 <= count <= 60000 or
            len(observation['anomalies']) != min(count, 32) or
            observation['anomalies_truncated'] is not (count > 32)):
        raise ValueError('Incomplete clock observations or anomaly evidence')
    recorder = load('clock_recorder_validation', 'observe-clocks.py')
    last_index = 0
    observed_counts = {}
    for event in observation['anomalies']:
        if type(event['index']) is not int or not last_index < event['index'] <= 60000:
            raise ValueError('Unordered clock anomaly evidence')
        reasons = recorder.regressions(event['previous'], event['sample'])
        if not reasons or reasons != event['reasons']:
            raise ValueError('Clock anomaly differs from its raw values')
        for reason in reasons:
            observed_counts[reason] = observed_counts.get(reason, 0) + 1
        last_index = event['index']
    counts = observation['regressions']
    allowed = {'monotonic_bracket', 'raw_bracket', 'monotonic_between', 'raw_between', 'boottime_between'}
    if (not set(counts) <= allowed or
            any(type(v) is not int or not 1 <= v <= count for v in counts.values()) or
            not count <= sum(counts.values()) <= 5 * count or
            any(counts.get(k, 0) < v for k, v in observed_counts.items()) or
            (count <= 32 and counts != observed_counts)):
        raise ValueError('Clock anomaly counts disagree with retained evidence')
    for key in ('boot_id', 'image', 'kernel', 'pm', 'stats', 'services', 'backlight',
                'usb', 'charger', 'cpu_policy', 'wifi_config_sha256', 'taint', 'failed_units'):
        if before[key] != after[key]:
            raise ValueError('Awake observation changed ' + key)
    delta = load('clock_kernel_evidence', 'kernel_evidence.py').delta(before, after)
    if any(fault in delta for fault in load('clock_pm_faults', 'test-pm-stages.py').FAULTS):
        raise ValueError('New kernel fault during awake observation')


def main():
    os.umask(0o077)
    capture = evidence_directory()
    print('Private clock evidence:', capture, flush=True)
    pm = load('clock_pm_host', 'check-pm-stages.py')
    source = ROOT / 'tools/observe-clocks.py'
    config = load_env()
    with (LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with device(config, 'usb') as client:
            before = json.loads(pm.inline(client, '--inspect'))
            (capture / 'before.json').write_text(json.dumps(before, indent=2) + '\n')
            if (before['pm']['pm_test'].split()[0] != '[none]' or
                    any(v['ActiveState'] != 'active' for v in before['services'].values())):
                raise ValueError('Observation needs awake, active services')
            active = run(client, 'systemctl list-units --all --plain --no-legend '
                         '--state=active,activating,deactivating gameshellneo-pm-test.service '
                         'gameshellneo-sleep-test.service', display=False).strip()
            if active:
                raise ValueError('A PM diagnostic is active')
            text = source.read_text()
            (capture / 'source.json').write_text(json.dumps(dict(
                source_sha256=hashlib.sha256(text.encode()).hexdigest(),
                host_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))+'\n')
            with (capture / 'observation.json').open('wb') as output:
                data = run(client, 'timeout --signal=TERM --kill-after=5 60 /usr/bin/python3 -B -',
                           input_data=text.encode(), output=output, display=False, timeout=75)
            result = json.loads(data)
            after = json.loads(pm.inline(client, '--inspect'))
            (capture / 'after.json').write_text(json.dumps(after, indent=2) + '\n')
            validate_result(result, before, after)
            pm.wifi_proof(config, after)
    summary = dict(complete=True, observation_validated=True,
                   regressions=result['observation']['regression_samples'],
                   clock_reliability_qualified=False, pm_admission=False,
                   device_state_unchanged=True, usb_ssh_verified=True, wifi_ssh_verified=True)
    (capture / 'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
