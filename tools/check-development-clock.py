#!/usr/bin/env python3
"""Plan locally or run one explicit, provenance-qualified development capture."""
import argparse
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sys

from clock_boundary import join
from clock_deployment import FILES
from clock_provenance import loads
from development_clock import ADAPTERS, ROOT, offline_inputs, sha, require
from dev_store_transport import load_hardware


def module(name, root=ROOT):
    spec = importlib.util.spec_from_file_location('development_' + name.replace('-', '_'), root / 'tools' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-checkout', required=True, type=Path)
    parser.add_argument('--reader-build', required=True, type=Path)
    parser.add_argument('--runtime-capture', required=True, type=Path,
                        help='Verified saved ELF evidence; live runtime hashes are checked again')
    parser.add_argument('--release-manifest', required=True, type=Path)
    parser.add_argument('--boot-id', required=True)
    parser.add_argument('--card-cid', required=True)
    parser.add_argument('--store-uuid', required=True)
    parser.add_argument('--hardware-checkout', type=Path)
    parser.add_argument('--apply', action='store_true', help='Explicitly run one bounded awake capture')
    args = parser.parse_args()
    os.umask(0o077)
    reader = args.reader_build.resolve(strict=True)
    contract = offline_inputs(args.image_checkout, reader, args.runtime_capture, args.release_manifest,
                              boot_id=args.boot_id, cid=args.card_cid, store_uuid=args.store_uuid)
    if not args.apply:
        print(json.dumps(dict(operation='development-clock-plan', apply=False, device_contacted=False,
                              contract=contract), indent=2))
        return
    require(args.hardware_checkout is not None, 'Explicit hardware checkout is required for --apply')
    # Complete local checks before importing credentials or SSH. All transport,
    # host-key records and private configuration belong to the frozen checkout.
    remote, config = load_hardware(args.hardware_checkout)
    capture = ROOT / '.local/diagnostics' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    capture.mkdir(parents=True)
    print('Private development clock capture:', capture, flush=True)
    (capture / 'offline-contract.json').write_text(json.dumps(contract, indent=2) + '\n')
    host = module('check-clock-boundary')
    clock, pm = module('check-clock-paths', remote.ROOT), module('check-pm-stages', remote.ROOT)
    program = clock.inspection_program(pm, '', capture)
    observation = module('check-clock-observation', remote.ROOT)
    with (remote.LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with remote.device(config, 'usb') as client:
            before = clock.inspect(client, program, capture, 'health-before')
            require(before['boot_id'] == contract['boot_id'] and before['kernel'] == contract['kernel'] and
                    before['pm']['pm_test'].split()[0] == '[none]' and not before['failed_units'].strip(),
                    'Current boot/awake health differs; no recorder launch')
            active = remote.run(client, 'systemctl list-units --all --plain --no-legend '
                '--state=active,activating,deactivating gameshellneo-clock-boundary-*.service '
                'gameshellneo-pm-test.service gameshellneo-sleep-test.service', display=False, timeout=10)
            require(not active.strip(), 'Another diagnostic unit is active')
            try:
                unit = host.execute(client, reader, contract, capture,
                    extra_files={name: ROOT / 'tools' / name for name in ADAPTERS},
                    runner='capture-development-clock.py')
            finally:
                # A failed postflight never removes the original device stage.
                after = clock.inspect(client, program, capture, 'health-after')
            observation.validate_state(before, after)
            pm.wifi_proof(config, after)
            raw = (capture / 'kernel.ndjson').read_bytes()
            users = loads((capture / 'users.json').read_text())
            analysis = join([loads(line) for line in raw.decode().splitlines()], users)
            original = loads((capture / 'result.json').read_text())
            require(not unit['error'] and unit['terminal'] and unit['execution_succeeded'] and
                    original.get('complete') is True and original.get('state_unchanged') is True and
                    analysis['complete'] and analysis == loads((capture / 'analysis.json').read_text()),
                    'Development clock capture incomplete; original stage retained')
            snapshots = [loads((capture / (label + '.json')).read_text()) for label in ('before', 'after')]
            require(snapshots[0] == snapshots[1] and
                    all(s['development']['source_image_sha256'] == contract['development']['source_image_sha256']
                        for s in snapshots), 'Development identity changed')
            stage = json.loads((capture / 'remote-stage.json').read_text())['directory']
            with client.open_sftp() as sftp:
                for name in (*FILES, *ADAPTERS, 'contract.json', *host.OUTPUTS):
                    try:
                        sftp.remove(stage + '/' + name)
                    except FileNotFoundError:
                        pass
                sftp.rmdir(stage)
            summary = dict(schema=1, operation='development-clock-capture', complete=True,
                boot_id=contract['boot_id'], slot=contract['development']['slot'],
                kernel_sha256=sha(capture / 'kernel.ndjson'), users_sha256=sha(capture / 'users.json'),
                contract_sha256=sha(capture / 'contract.json'), adapter=contract['development']['adapter_files'],
                boundary_findings=analysis['boundary_findings'], kernel_regressions=analysis['kernel']['regressions'],
                userspace_regressions=analysis['userspace_regressions'], device_state_unchanged=True,
                usb_ssh_verified=True, wifi_ssh_verified=True, remote_stage_removed=True,
                pm_admission=False, clock_reliability_qualified=False)
            (capture / 'host-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('Original development capture replayed; prior faults and PM gates remain open.')


if __name__ == '__main__':
    main()
