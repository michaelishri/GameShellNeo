#!/usr/bin/env python3
"""Plan offline or explicitly run one finite scheduled development capture."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess

from clock_deployment import FILES as ORIGINAL_FILES
from clock_provenance import loads
from clock_scheduled import FILES, OPERATION, join, schedule, validate_contract
from development_clock import ADAPTERS, ROOT, offline_inputs, regular, require, sha
from dev_store_transport import load_hardware
from managed_container import result_for


def module(name, root=ROOT):
    import importlib.util
    spec = importlib.util.spec_from_file_location('scheduled_' + name.replace('-', '_'), root / 'tools' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def pause_inputs(directory, image_checkout, runtime):
    """Qualify the complete new receipt independently of the original reader."""
    directory = Path(directory).resolve(strict=True)
    builder = module('build-scheduled-clock')
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    raw = regular(directory, 'build-receipt.json')
    receipt = loads(raw.decode())
    require(type(receipt.get('schema')) is int and receipt['schema'] == 1 and
            receipt.get('operation') == 'clock-pause-build' and receipt.get('complete') is True and
            receipt.get('no_hardware_contact') is True and receipt['builder'] == lock['builder'] and
            set(receipt['inputs']) == set(builder.INPUTS) and set(receipt['outputs']) == set(builder.OUTPUTS) and
            (receipt['native_fixture_count'], receipt['arm_fixture_count'], receipt['production_calls']) == (4, 4, 2) and
            receipt['tests'] == ['native-ubsan-error-buffers', 'arm-qemu-error-buffers',
                'arm-production-relative-pause', 'arm-production-signal-eintr-no-retry'],
            'Incomplete scheduled pause build')
    for name, expected in receipt['inputs'].items():
        require(sha(directory / name) == sha(ROOT / name) == expected, 'Pause source changed: ' + name)
    for name, expected in receipt['outputs'].items():
        require(sha(directory / name) == expected, 'Pause output changed: ' + name)
    version = lock['linux']['tag'].removeprefix('v')
    archive = Path(image_checkout) / '.local/downloads' / ('linux-' + version + '.tar.xz')
    require(receipt['source_archive_sha256'] == lock['linux']['tarball_sha256'] and
            receipt['abi'] == builder.abi_sources(archive, lock), 'Pause ABI archive/complete source map differs')
    identity, result, _ = result_for(directory / 'managed/managed-run.json')
    state = (result or {}).get('state') or {}
    require(identity['stage'] == 'scheduled-clock-pause' and identity['run'] == receipt['managed_run'] and
            result and result.get('outcome') == 'exited' and result.get('exit_code') == 0 and
            result.get('returncode') == 0 and not result.get('stop_requested') and
            state.get('Running') is False and state.get('Status') == 'exited' and state.get('ExitCode') == 0 and
            not state.get('OOMKilled') and not state.get('Error'), 'Pause managed operation is unresolved/failed')
    for name in ('native-fixtures.txt', 'arm-fixtures.txt'):
        builder.verify_fixtures(regular(directory, name).decode())
    builder.verify_production(regular(directory, 'arm-production.txt').decode())
    symbols = lambda text: set(re.findall(r'\b([A-Za-z_][A-Za-z_0-9]*)@@?(GLIBC_[0-9.]+)\b', text))
    elf = subprocess.check_output(['readelf', '-Ws', str(directory / 'clock-pause.so')], text=True, timeout=30)
    needed = symbols('\n'.join(line for line in elf.splitlines() if ' UND ' in line))
    exports = subprocess.check_output(['readelf', '-Ws', str(Path(runtime) / 'libc.elf')], text=True, timeout=30)
    require(needed and needed <= symbols(exports) and not re.search(r'\b(?:__clock_gettime64|clock_gettime)@', elf),
            'Pause library imports lack runtime support or introduce a clock read')
    return raw, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('image-checkout', 'reader-build', 'runtime-capture', 'release-manifest', 'pause-build'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('boot-id', 'card-cid', 'store-uuid'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--hardware-checkout', type=Path)
    parser.add_argument('--apply', action='store_true', help='One explicit scheduled capture; never repeat')
    args = parser.parse_args()
    os.umask(0o077)
    reader, pause = args.reader_build.resolve(strict=True), args.pause_build.resolve(strict=True)
    contract = offline_inputs(args.image_checkout, reader, args.runtime_capture, args.release_manifest,
                              boot_id=args.boot_id, cid=args.card_cid, store_uuid=args.store_uuid)
    receipt_raw, receipt = pause_inputs(pause, args.image_checkout, args.runtime_capture)
    from clock_deployment import digest
    contract['scheduled'] = dict(schema=1, operation=OPERATION, schedule=schedule(),
        files={name: receipt['outputs'][name] if name.endswith('.so') else sha(ROOT / 'tools' / name) for name in FILES},
        pause_receipt_sha256=digest(receipt_raw), pm_admission=False, clock_reliability_qualified=False)
    validate_contract(contract)
    if not args.apply:
        print(json.dumps(dict(operation='scheduled-clock-plan', apply=False, device_contacted=False, contract=contract), indent=2))
        return
    require(args.hardware_checkout is not None, 'Explicit frozen hardware checkout required for --apply')
    remote, config = load_hardware(args.hardware_checkout)
    capture = ROOT / '.local/diagnostics' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    capture.mkdir(parents=True)
    print('Private finite scheduled capture:', capture, flush=True)
    (capture / 'offline-contract.json').write_text(json.dumps(contract, indent=2) + '\n')
    host = module('check-clock-boundary')
    clock, pm = module('check-clock-paths', remote.ROOT), module('check-pm-stages', remote.ROOT)
    program = clock.inspection_program(pm, '', capture)
    observation = module('check-clock-observation', remote.ROOT)
    extras = {name: ROOT / 'tools' / name for name in (*ADAPTERS, *FILES) if not name.endswith('.so')}
    extras['clock-pause.so'] = pause / 'clock-pause.so'
    with (remote.LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with remote.device(config, 'usb') as client:
            before = clock.inspect(client, program, capture, 'health-before')
            require(before['boot_id'] == contract['boot_id'] and before['kernel'] == contract['kernel'] and
                    before['pm']['pm_test'].split()[0] == '[none]' and not before['failed_units'].strip(),
                    'Current boot/awake health differs; no scheduled recorder launch')
            active = remote.run(client, 'systemctl list-units --all --plain --no-legend '
                '--state=active,activating,deactivating gameshellneo-clock-boundary-*.service '
                'gameshellneo-pm-test.service gameshellneo-sleep-test.service', display=False, timeout=10)
            require(not active.strip(), 'Another diagnostic unit is active')
            try:
                unit = host.execute(client, reader, contract, capture, extra_files=extras, runner='capture-scheduled-clock.py')
            finally:
                after = clock.inspect(client, program, capture, 'health-after')
            observation.validate_state(before, after)
            pm.wifi_proof(config, after)
            raw, users = (capture / 'kernel.ndjson').read_bytes(), loads((capture / 'users.json').read_text())
            analysis = join([loads(line) for line in raw.decode().splitlines()], users)
            original = loads((capture / 'result.json').read_text())
            require(not unit['error'] and unit['terminal'] and unit['execution_succeeded'] and
                    original.get('complete') is True and original.get('state_unchanged') is True and analysis['complete'] and
                    analysis == loads((capture / 'analysis.json').read_text()), 'Scheduled capture incomplete; original stage retained')
            snapshots = [loads((capture / (label + '.json')).read_text()) for label in ('before', 'after')]
            require(snapshots[0] == snapshots[1] and all(s['scheduled'] == contract['scheduled'] and
                    s['development']['source_image_sha256'] == contract['development']['source_image_sha256'] for s in snapshots),
                    'Scheduled source/runtime identity changed')
            stage = loads((capture / 'remote-stage.json').read_text())['directory']
            with client.open_sftp() as sftp:
                for name in (*ORIGINAL_FILES, *extras, 'contract.json', *host.OUTPUTS):
                    try: sftp.remove(stage + '/' + name)
                    except FileNotFoundError: pass
                sftp.rmdir(stage)
            summary = dict(schema=1, operation=OPERATION, complete=True, boot_id=contract['boot_id'],
                slot=contract['development']['slot'], schedule=schedule(), kernel_sha256=sha(capture / 'kernel.ndjson'),
                users_sha256=sha(capture / 'users.json'), contract_sha256=sha(capture / 'contract.json'),
                boundary_findings=analysis['boundary_findings'], kernel_regressions=analysis['kernel']['regressions'],
                userspace_regressions=analysis['userspace_regressions'], device_state_unchanged=True,
                usb_ssh_verified=True, wifi_ssh_verified=True, remote_stage_removed=True,
                pm_admission=False, clock_reliability_qualified=False)
            (capture / 'host-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('One finite scheduled capture replayed; unresolved clock and PM gates remain open.')


if __name__ == '__main__':
    main()
