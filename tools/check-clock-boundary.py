#!/usr/bin/env python3
"""Run one provenance-qualified clock capture; no PM, reboot or clock settings."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid

from clock_boundary import join
from clock_deployment import FILES, SOURCE_ID, configuration, validate_contract
from clock_provenance import loads
from kernel_checks import sha256
from private_config import load_env
from remote import ROOT, LOCAL, device, evidence_directory, run, upload

OUTPUTS = ('before.json', 'kernel.ndjson', 'users.json', 'after.json', 'analysis.json',
           'result.json', 'runner-error.json')
UNIT_FIELDS = ('LoadState', 'ActiveState', 'SubState', 'Result', 'ExecMainStatus', 'ExecMainCode',
               'MainPID', 'ControlPID')


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'tools' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def verified_inputs(build_name, runtime_name):
    """Finish every offline provenance check before connecting to a device."""
    native = module('check-native-clocks')
    directory = native.capture_path(build_name)
    runtime = module('report-clock-runtime').verified_capture(runtime_name)
    receipt = json.loads((directory / 'build-receipt.json').read_text())
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    required_inputs = {'tools/clock-boundary.c', 'tools/clock_boundary.py', 'tools/clock_provenance.py',
        'tools/clock_deployment.py', 'tools/capture-clock-boundary.py', 'tools/build-clock-boundary.py',
        'tools/check-clock-paths.py', 'build/sources.lock.json'}
    required_outputs = {'clock-boundary.so', 'test-host', 'test-arm', 'reader-readelf.txt',
        'reader-disassembly.txt', 'build.sh', 'build-output.txt', 'host-fixtures.txt', 'arm-fixtures.txt'}
    if (receipt.get('schema') != 1 or receipt.get('operation') != 'clock-boundary-build' or
            receipt.get('complete') is not True or receipt['builder'] != lock['builder'] or
            receipt['abi']['linux'] != lock['linux'] or set(receipt['inputs']) != required_inputs or
            set(receipt['outputs']) != required_outputs or receipt['arm_raw_buffer_fixtures'] != 27 or
            receipt['tests'] != ['host-ubsan-fixtures', 'arm-qemu-fixtures', 'arm-production-layout-assertions']):
        raise ValueError('Clock reader build receipt does not match the required sources/tests')
    for name, digest in receipt['inputs'].items():
        if sha256(directory / name) != digest or sha256(ROOT / name) != digest:
            raise ValueError('Clock reader source changed: ' + name)
    for name, digest in receipt['outputs'].items():
        if sha256(directory / name) != digest:
            raise ValueError('Clock reader build output changed: ' + name)
    builder = module('build-clock-boundary')
    elf = (directory / 'reader-readelf.txt').read_text()
    builder.verify_elf(elf)
    builder.verify_arm_fixture((directory / 'arm-fixtures.txt').read_text())
    symbols = module('build-native-clocks').symbols
    exported = subprocess.check_output(['readelf', '-Ws', str(runtime / 'libc.elf')], text=True, timeout=30)
    needed = symbols('\n'.join(line for line in elf.splitlines() if ' UND ' in line))
    if not needed or not needed <= symbols(exported):
        raise ValueError('Captured libc lacks reader imports')
    inventory = json.loads((runtime / 'inventory.json').read_text())
    artifacts = LOCAL / 'artifacts'
    image = json.loads((artifacts / 'image-manifest.json').read_text())
    config = (artifacts / 'kernel.config').read_bytes()
    values = configuration(config)  # Old diagnostic.25 cannot pass this gate.
    if (image['sources'] != lock or image['version'] != lock['image_version'] or
            image['kernel'] != lock['linux']['tag'][1:] + lock['linux']['localversion'] or
            lock.get('experiments', {}).get('clock_provenance') is not True):
        raise ValueError('Expected explicitly instrumented image and matching source lock')
    kernel = module('kernel-artifacts').inventory()
    if (kernel != json.loads((LOCAL / 'build/kernel-completed.json').read_text()) or
            kernel != json.loads((artifacts / 'kernel-completed.json').read_text()) or
            kernel['files']['.local/build/kernel/.config'] != sha256(artifacts / 'kernel.config')):
        raise ValueError('Built kernel artifacts do not match the image')
    notes = subprocess.check_output(['readelf', '-n', str(LOCAL / 'build/kernel/vmlinux')], text=True, timeout=30)
    identities = re.findall(r'Build ID: ([0-9a-f]+)', notes)
    if len(identities) != 1:
        raise ValueError('Missing or ambiguous built-kernel build ID')
    for name, digest in receipt['inputs'].items():
        if image['project_inputs_sha256'].get(name) != digest:
            raise ValueError('Image did not contain matching diagnostic inputs: ' + name)
    verification = json.loads((artifacts / 'verification.json').read_text())
    name = verification['image']
    if (not isinstance(name, str) or Path(name).name != name or not name.endswith('.img') or
            verification['offline_verification'] != 'passed' or
            (artifacts / name).stat().st_size != verification['bytes'] or
            sha256(artifacts / name) != verification['sha256']):
        raise ValueError('Image has not passed matching offline verification')
    if name != f'GameShellNeo-{lock["image_version"]}-cpi31-{verification["sha256"][:12]}.img':
        raise ValueError('Verified image identity differs from the selected manifest')
    contract = dict(schema=1, operation='clock-boundary-contract', boot_id=None,
        kernel=image['kernel'], build_id=identities[0], image_sha256=sha256(artifacts / 'image-manifest.json'),
        config_sha256=sha256(artifacts / 'kernel.config'), source_id=SOURCE_ID,
        time_namespaces=values.get('CONFIG_TIME_NS') == 'y', runtime=inventory['files'],
        files={name: receipt['outputs'][name] if name.endswith('.so') else receipt['inputs']['tools/' + name]
               for name in FILES})
    return directory, contract


def unit_state(client, unit):
    data = run(client, shlex.join(['systemctl', 'show', unit, *['-p' + key for key in UNIT_FIELDS]]),
               timeout=10, display=False).decode()
    result = dict(line.split('=', 1) for line in data.splitlines())
    if set(result) != set(UNIT_FIELDS):
        raise ValueError('Incomplete diagnostic unit state')
    return result


def terminal(state):
    return ((state['ActiveState'] in ('inactive', 'failed') or
             (state['ActiveState'], state['SubState']) == ('active', 'exited')) and state['MainPID'] == '0' and
            state['ControlPID'] == '0')


def contract_bytes(contract):
    # A real development release contains the complete immutable-file map.
    # Compact encoding keeps that evidence within the runner's existing bound;
    # never raise the bound or silently truncate/reduce the manifest.
    raw = (json.dumps(contract, separators=(',', ':')) + '\n').encode()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Clock contract exceeds the existing 2 MiB limit')
    return raw


def supervise(client, unit, target, capture, now=time.monotonic, pause=time.sleep,
              runner='capture-clock-boundary.py'):
    """One launch; host deadline is independent of the GameShell's clocks."""
    states, error, execution_state = [], None, None
    started = now()
    try:
        run(client, shlex.join(['sudo', '-n', 'systemd-run', '--unit=' + unit, '--property=Type=exec',
            '--property=RuntimeMaxSec=45s', '--property=TimeoutStopSec=5s', '--property=Restart=no',
            '--property=KillMode=control-group', '--property=RemainAfterExit=yes', '--property=UMask=0077', '--',
            '/usr/bin/python3.13', '-I', '-S', '-B', target + '/' + runner]),
            display=False, timeout=15)
        while True:
            state = unit_state(client, unit)
            states.append(state)
            if terminal(state):
                execution_state = state
                break
            if now() - started >= 60:
                raise TimeoutError('Host clock-capture deadline expired')
            pause(0.5)
    except BaseException as caught:
        error = dict(type=type(caught).__name__, message=str(caught))
    finally:
        # Also retire the completed RemainAfterExit unit after retaining its
        # exit evidence. A lost start acknowledgement never causes a relaunch.
        try:
            run(client, shlex.join(['sudo', '-n', 'systemctl', 'stop', unit]), display=False, timeout=15)
        except BaseException as caught:
            error = error or dict(type=type(caught).__name__, message=str(caught))
            error['stop_error'] = str(caught)
        try:
            state = unit_state(client, unit)
            states.append(state)
        except BaseException as caught:
            error = error or dict(type=type(caught).__name__, message=str(caught))
            state = None
        succeeded = execution_state is not None and all(execution_state[k] == v for k, v in
            dict(LoadState='loaded', ActiveState='active', SubState='exited', Result='success',
                 ExecMainStatus='0', ExecMainCode='1', MainPID='0', ControlPID='0').items())
        result = dict(unit=unit, states=states, error=error, execution_state=execution_state,
                      execution_succeeded=succeeded, terminal=state is not None and terminal(state) and
                      state['ActiveState'] in ('inactive', 'failed'))
        (capture / 'unit.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def execute(client, directory, contract, capture, *, extra_files=None,
            runner='capture-clock-boundary.py'):
    extra_files = extra_files or {}
    if runner not in ('capture-clock-boundary.py', 'capture-development-clock.py', 'capture-scheduled-clock.py'):
        raise ValueError('Unknown clock capture runner')
    development = runner != 'capture-clock-boundary.py'
    scheduled = runner == 'capture-scheduled-clock.py'
    if bool(extra_files) != development:
        raise ValueError('Development runner requires its explicit adapter inputs')
    if ('development' in contract) != bool(extra_files):
        raise ValueError('Development contracts require the explicit development runner')
    if ('scheduled' in contract) != scheduled:
        raise ValueError('Scheduled contracts require their explicit scheduled runner')
    hashes = dict(contract['files'])
    if extra_files:
        from development_clock import ADAPTERS, validate_development_contract
        validate_development_contract(contract)
        required = set(ADAPTERS)
        if scheduled:
            from clock_scheduled import FILES as SCHEDULED_FILES, validate_contract as validate_scheduled
            validate_scheduled(contract)
            required.update(SCHEDULED_FILES)
            hashes.update(contract['scheduled']['files'])
        if set(extra_files) != required:
            raise ValueError('Incomplete development adapter files')
        hashes.update(contract['development']['adapter_files'])
        for name, path in extra_files.items():
            if Path(path).is_symlink() or sha256(path) != hashes[name]:
                raise ValueError('Development adapter source changed: ' + name)
    payload = contract_bytes(contract)  # Refuse oversized input before any SSH/staging.
    target = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-clock-boundary.XXXXXXXX',
                 display=False, timeout=15).decode().strip()
    if not re.fullmatch(r'/tmp/gameshellneo-clock-boundary\.[A-Za-z0-9]{8}', target):
        raise ValueError('Unexpected diagnostic staging directory')
    unit = 'gameshellneo-clock-boundary-' + uuid.uuid4().hex + '.service'
    (capture / 'remote-stage.json').write_text(json.dumps(dict(directory=target, unit=unit)) + '\n')
    contract_path = capture / 'contract.json'
    contract_path.write_bytes(payload)
    with client.open_sftp() as sftp:
        sftp.get_channel().settimeout(15)
        for name in FILES:
            source = directory / name if name.endswith('.so') else directory / 'tools' / name
            upload(sftp, source, target + '/' + name)
        for name, source in extra_files.items():
            upload(sftp, source, target + '/' + name)
        upload(sftp, contract_path, target + '/contract.json')
        # Independent host download/hash comparison before a privileged launch.
        for name, expected in hashes.items():
            with sftp.open(target + '/' + name, 'rb') as stream:
                if hashlib.sha256(stream.read(32 * 1024 * 1024 + 1)).hexdigest() != expected:
                    raise ValueError('Staged input differs: ' + name)
        with sftp.open(target + '/contract.json', 'rb') as stream:
            if stream.read(2 * 1024 * 1024 + 1) != contract_path.read_bytes():
                raise ValueError('Staged contract differs')
    result = supervise(client, unit, target, capture, runner=runner)
    # Never collect/clean a process still writing or assume a timeout means exit.
    if not result['terminal']:
        raise RuntimeError('Diagnostic termination is unconfirmed; private stage retained')
    with client.open_sftp() as sftp:
        sftp.get_channel().settimeout(15)
        for name in OUTPUTS:
            try:
                size = sftp.stat(target + '/' + name).st_size
            except FileNotFoundError:
                continue
            if not 0 <= size <= 16 * 1024 * 1024 + 1:
                raise ValueError('Oversized diagnostic output: ' + name)
            sftp.get(target + '/' + name, str(capture / name))
    return result  # Keep the stage until host validation and health checks pass.


def main():
    os.umask(0o077)
    directory, contract = verified_inputs(os.environ.get('NEO_BOUNDARY_BUILD', ''),
                                          os.environ.get('NEO_RUNTIME_CAPTURE', ''))
    capture = evidence_directory()
    print('Private kernel/userspace clock capture:', capture, flush=True)
    clock, pm = module('check-clock-paths'), module('check-pm-stages')
    program = clock.inspection_program(pm, '', capture)
    config = load_env()
    with (LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with device(config, 'usb') as client:
            before = clock.inspect(client, program, capture, 'health-before')
            contract['boot_id'] = before['boot_id']
            validate_contract(contract)
            try:
                unit = execute(client, directory, contract, capture)
            finally:
                after = clock.inspect(client, program, capture, 'health-after')
            module('check-clock-observation').validate_state(before, after)
            pm.wifi_proof(config, after)
            raw = (capture / 'kernel.ndjson').read_bytes()
            users = loads((capture / 'users.json').read_text())
            analysis = join([loads(line) for line in raw.decode().splitlines()], users)
            original = loads((capture / 'result.json').read_text())
            if (unit['error'] or not unit['terminal'] or not unit['execution_succeeded'] or
                    original.get('complete') is not True or
                    original.get('state_unchanged') is not True or not analysis['complete'] or
                    analysis != loads((capture / 'analysis.json').read_text())):
                raise ValueError('Clock deployment incomplete; original stage/evidence retained')
            summary = dict(complete=True,
                unit=unit['unit'], kernel_sha256=sha256(capture / 'kernel.ndjson'),
                users_sha256=sha256(capture / 'users.json'), boundary_findings=analysis['boundary_findings'],
                kernel_regressions=analysis['kernel']['regressions'],
                userspace_regressions=analysis['userspace_regressions'],
                pm_admission=False, clock_reliability_qualified=False)
            # Successful original evidence is downloaded before removing our
            # specific private files. Failed/partial stages are left intact.
            stage = json.loads((capture / 'remote-stage.json').read_text())['directory']
            with client.open_sftp() as sftp:
                for name in (*FILES, 'contract.json', *OUTPUTS):
                    try:
                        sftp.remove(stage + '/' + name)
                    except FileNotFoundError:
                        pass
                sftp.rmdir(stage)
            summary['remote_stage_removed'] = True
            (capture / 'host-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('Capture and original-result replay complete; findings retained. PM remains unqualified.')


if __name__ == '__main__':
    main()
