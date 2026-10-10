#!/usr/bin/env python3
"""Run one fixed unprivileged awake ARM comparison, preserving the original fault."""
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

import importlib.util

from private_config import load_env
from remote import ROOT, LOCAL, device, evidence_directory, run, upload
from kernel_checks import sha256
from native_clock_report import analyze, validate_inventory

OPERATIONS = {'compare': 'comparison', 'libc-syscall': 'libc-syscall-comparison',
              'inspect-vdso': 'vdso-inventory'}


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_path(value):
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}\.[0-9]{6}Z', value):
        raise ValueError('Use the timestamp BUILD/RUNTIME_CAPTURE printed by the saved tasks')
    return LOCAL / 'diagnostics' / value


def verified_build(value, lock, runtime):
    directory = capture_path(value)
    receipt = json.loads((directory / 'build-receipt.json').read_text())
    files = {'compare-clocks-native.c', 'compare-clocks-native', 'native-readelf.txt',
             'native-disassembly.txt', 'build-output.txt', 'build.sh'}
    if (receipt.get('schema') != 1 or receipt.get('complete') is not True or
            receipt['builder'] != lock['builder'] or receipt['abi']['linux'] != lock['linux'] or
            receipt['source_sha256'] != sha256(ROOT / 'tools/compare-clocks-native.c') or
            receipt['producer_sha256'] != sha256(ROOT / 'tools/build-native-clocks.py') or
            set(receipt['files']) != files or
            receipt['files']['compare-clocks-native.c'] != receipt['source_sha256'] or
            receipt['tests'] != ['host-fixtures', 'arm-qemu-fixtures', 'arm-production-abi-assertions']):
        raise ValueError('Build receipt differs from current sources/locked ABI')
    for name, digest in receipt['files'].items():
        if sha256(directory / name) != digest:
            raise ValueError('Native build artifact differs: ' + name)
    build = load('native_build_validation', 'build-native-clocks.py')
    elf = (directory / 'native-readelf.txt').read_text()
    build.verify_elf(elf)
    # Re-read the hash-verified copied libc, not an editable disassembly receipt.
    exported = subprocess.run(['readelf', '-Ws', str(runtime / 'libc.elf')], check=True,
        capture_output=True, timeout=30).stdout.decode()
    required = build.symbols('\n'.join(line for line in elf.splitlines() if ' UND ' in line))
    if not required or not required <= build.symbols(exported):
        raise ValueError('Target libc does not provide the native binary imports')
    return directory, receipt


def verify_remote_libc(client, inventory):
    record = inventory['files']['libc']
    if not re.fullmatch(r'/(?:usr/)?lib/arm-linux-gnueabihf/libc\.so\.6', record['path']):
        raise ValueError('Unexpected runtime library path')
    result = run(client, shlex.join(['sha256sum', '--', record['path']]), display=False, timeout=20)
    if result.decode().split()[0] != record['sha256']:
        raise ValueError('Installed libc changed since runtime inventory')


def execute(client, build, receipt, capture, inspect_after, mode='compare'):
    """Save raw output and always inspect after the one attempt, even on failure."""
    if mode not in OPERATIONS:
        raise ValueError('Unknown native diagnostic mode')
    directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-native-clock.XXXXXXXX',
                    display=False, timeout=15).decode().strip()
    if not re.fullmatch(r'/tmp/gameshellneo-native-clock\.[A-Za-z0-9]{8}', directory):
        raise ValueError('Unexpected private remote staging path')
    target = directory + '/compare-clocks-native'
    (capture / 'remote-stage.json').write_text(json.dumps(dict(directory=directory)) + '\n')
    try:
        with client.open_sftp() as sftp:
            sftp.get_channel().settimeout(15)
            upload(sftp, build / 'compare-clocks-native', target)
            sftp.chmod(target, 0o700)
        digest = run(client, shlex.join(['sha256sum', '--', target]), display=False, timeout=15)
        if digest.decode().split()[0] != receipt['files']['compare-clocks-native']:
            raise ValueError('Staged native binary differs from verified build')
        with (capture / 'native-output.ndjson').open('wb') as output:
            args = ['timeout', '--signal=TERM', '--kill-after=5', '60', target]
            if mode != 'compare':
                args.append('--' + mode)
            data = run(client, shlex.join(args),
                       output=output, display=False, timeout=90)
    finally:
        after = inspect_after()
    # Only our completed ephemeral binary is removed. Failed staging stays private.
    with client.open_sftp() as sftp:
        sftp.get_channel().settimeout(15)
        sftp.remove(target)
        sftp.rmdir(directory)
    return data, after


def main():
    os.umask(0o077)
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    mode = os.environ.get('NEO_NATIVE_MODE', 'compare')
    if mode not in OPERATIONS:
        raise ValueError('Unknown native diagnostic mode')
    operation = OPERATIONS[mode]
    runtime = load('native_runtime_inputs', 'report-clock-runtime.py').verified_capture(
        os.environ.get('NEO_RUNTIME_CAPTURE', ''))
    inventory = json.loads((runtime / 'inventory.json').read_text())
    build, receipt = verified_build(os.environ.get('NEO_NATIVE_BUILD', ''), lock, runtime)
    capture = evidence_directory()
    print('Private native clock comparison:', capture, flush=True)
    (capture / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    (capture / 'inputs.json').write_text(json.dumps(dict(build=build.name, runtime=runtime.name,
        host_sha256=sha256(Path(__file__)), analyzer_sha256=sha256(ROOT / 'tools/native_clock_report.py'),
        libc=inventory['files']['libc'], operation=operation), indent=2) + '\n')
    pm = load('native_clock_pm', 'check-pm-stages.py')
    clock = load('native_clock_host', 'check-clock-paths.py')
    program = clock.inspection_program(pm, os.environ.get('NEO_CLOCK_INSPECTION_REVISION', ''), capture)
    config = load_env()
    with (LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with device(config, 'usb') as client:
            before = clock.inspect(client, program, capture, 'before')
            if (before['kernel'] != lock['linux']['tag'][1:] + lock['linux']['localversion'] or
                    before['image']['version'] != lock['image_version'] or
                    before['pm']['pm_test'].split()[0] != '[none]' or before['usb'] != ['configured'] or
                    before['external_power']['axp20x-usb'] != {'type': 'USB', 'present': '1', 'online': '1'} or
                    any(v['ActiveState'] != 'active' for v in before['services'].values())):
                raise ValueError('Comparison needs matching awake image, active services and USB power')
            active = run(client, 'systemctl list-units --all --plain --no-legend '
                '--state=active,activating,deactivating gameshellneo-pm-test.service '
                'gameshellneo-sleep-test.service', display=False).strip()
            if active:
                raise ValueError('A PM diagnostic is active')
            verify_remote_libc(client, inventory)
            data, after = execute(client, build, receipt, capture,
                lambda: clock.inspect(client, program, capture, 'after'), mode)
            verify_remote_libc(client, inventory)
            version = inventory['libc'].removeprefix('glibc ')
            result = (validate_inventory(data, before['boot_id'], version) if mode == 'inspect-vdso' else
                      analyze(data, before['boot_id'], version, two_path=mode == 'libc-syscall'))
            (capture / 'analysis.json').write_text(json.dumps(result, indent=2) + '\n')
            load('native_clock_state', 'check-clock-observation.py').validate_state(before, after)
            pm.wifi_proof(config, after)
    summary = dict(complete=True, observation_validated=True, device_state_unchanged=True,
        operation=operation,
        usb_ssh_verified=True, wifi_ssh_verified=True, pm_admission=False, clock_reliability_qualified=False,
        discrepancy_sequences=result.get('discrepancy_sequences'), samples=result.get('samples', 0),
        raw_sha256=sha256(capture / 'native-output.ndjson'))
    (capture / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
