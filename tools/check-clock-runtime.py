#!/usr/bin/env python3
"""Save the installed clock runtime and inspect copied ELF metadata offline."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

from private_config import load_env
from remote import ROOT, LOCAL, device, evidence_directory, run


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_inventory(value, before, after):
    if (value.get('schema') != 1 or value.get('operation') != 'clock-runtime-inventory' or
            value.get('complete') is not True or value.get('binaries_unchanged') is not True or
            value['boot_id'] != value['after_boot_id'] or value['boot_id'] != before['boot_id'] or
            value['kernel'] != before['kernel'] or value['machine'] != 'armv7l' or
            value['time_module'] != 'built-in' or type(value['vdso_mapped']) is not bool or
            set(value['files']) != {'python', 'libc'}):
        raise ValueError('Incomplete or unexpected runtime identity')
    flags = value['loader_environment_present']
    if set(flags) != {'LD_PRELOAD', 'LD_AUDIT', 'LD_LIBRARY_PATH'} or any(v is not False for v in flags.values()):
        raise ValueError('Loader environment needs separate source attribution')
    expected = {'python': r'/usr/bin/python3\.13', 'libc': r'/(?:usr/)?lib/arm-linux-gnueabihf/libc\.so\.6'}
    for role, record in value['files'].items():
        if (not re.fullmatch(expected[role], record['path']) or type(record['size']) is not int or
                not 0 < record['size'] <= 32 * 1024 * 1024 or
                not re.fullmatch('[0-9a-f]{64}', record['sha256'])):
            raise ValueError('Unexpected binary path/size/hash')
    load('runtime_clock_state', 'check-clock-observation.py').validate_state(before, after)


def save_binary(sftp, record, destination):
    # Bound the transfer independently of the remote metadata. A partial file
    # remains private on failure, and is never passed to readelf as qualified.
    with sftp.open(record['path'], 'rb') as source, destination.open('wb') as output:
        remaining = record['size'] + 1
        while remaining:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            output.write(chunk)
            remaining -= len(chunk)
    data = destination.read_bytes()
    if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError('Copied runtime binary differs from its device receipt')


def main():
    os.umask(0o077)
    capture = evidence_directory()
    print('Private clock-runtime evidence:', capture, flush=True)
    clock = load('runtime_clock_host', 'check-clock-paths.py')
    pm = load('runtime_clock_pm', 'check-pm-stages.py')
    program = clock.inspection_program(pm, os.environ.get('NEO_CLOCK_INSPECTION_REVISION', ''), capture)
    config = load_env()
    source = (ROOT / 'tools/inspect-clock-runtime.py').read_bytes()
    (capture / 'source.json').write_text(json.dumps(dict(device_sha256=hashlib.sha256(source).hexdigest(),
        host_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())) + '\n')
    with (LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with device(config, 'usb') as client:
            before = clock.inspect(client, program, capture, 'before')
            if before['pm']['pm_test'].split()[0] != '[none]':
                raise ValueError('Runtime inventory requires awake diagnostic state')
            active = run(client, 'systemctl list-units --all --plain --no-legend '
                         '--state=active,activating,deactivating gameshellneo-pm-test.service '
                         'gameshellneo-sleep-test.service', display=False).strip()
            if active:
                raise ValueError('A PM diagnostic is active')
            try:
                with (capture / 'inventory-output.txt').open('wb') as output:
                    data = run(client, 'timeout --signal=TERM --kill-after=5 30 /usr/bin/python3 -B -',
                               input_data=source, output=output, display=False, timeout=45)
                value = json.loads(data)
                (capture / 'inventory.json').write_text(json.dumps(value, indent=2) + '\n')
            finally:
                after = clock.inspect(client, program, capture, 'after')
            validate_inventory(value, before, after)
            with client.open_sftp() as sftp:
                sftp.get_channel().settimeout(15)
                for role, record in value['files'].items():
                    save_binary(sftp, record, capture / (role + '.elf'))
            pm.wifi_proof(config, after)
    for role in ('python', 'libc'):
        with (capture / (role + '-readelf.txt')).open('wb') as output:
            subprocess.run(['readelf', '-h', '-n', '-d', '-Ws', '-Wr', str(capture / (role + '.elf'))],
                           stdout=output, stderr=subprocess.STDOUT, check=True, timeout=30)
    summary = dict(complete=True, binaries_verified=True, device_state_unchanged=True,
                   usb_ssh_verified=True, wifi_ssh_verified=True, pm_admission=False,
                   clock_reliability_qualified=False, per_call_dispatch_proven=False)
    (capture / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
