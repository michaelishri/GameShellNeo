#!/usr/bin/env python3
"""Bounded two-ended TCP metadata around saved awake probes or one attended sleep."""
import argparse
import fcntl
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time
import uuid

from private_config import load_env
from remote import ROOT, LOCAL, connect_mac, device, evidence_directory, run, sudo, upload
import tcp_metadata
import tcp_report
import tcp_supervisor


def module(filename):
    spec = importlib.util.spec_from_file_location(filename.replace('-', '_'), ROOT/'tools'/filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def save(path, value):
    temporary = path.with_suffix(path.suffix+'.part')
    temporary.write_text(json.dumps(value, indent=2)+'\n')
    temporary.replace(path)


def command(config, side, arguments):
    return sudo(config, arguments) if side == 'mac' else (shlex.join(['sudo', '-n']+arguments), None)


def helper(config, client, manifest, side, mode, *arguments):
    remote = manifest[side]['directory']
    if not re.fullmatch(r'/tmp/gameshellneo-tcp\.[A-Za-z0-9]+', remote):
        raise ValueError('Unexpected remote capture path')
    cmd, password = command(config, side, ['/usr/bin/python3', '-B', remote+'/tcp_metadata.py', mode,
        '--directory', remote, '--run-id', tcp_metadata.token(manifest['run_id']), *arguments])
    return run(client, cmd, password=password, display=False, timeout=20)


def ready(config, client, manifest, side):
    # The same already-open setup connection is used; no extra SSH connections
    # are injected into the diagnostic's timed connection path.
    for _ in range(20):
        remote = manifest[side]['directory']
        cmd, password = command(config, side, ['/bin/test', '-f', remote+'/ready.json'])
        try:
            run(client, cmd, password=password, display=False, timeout=5)
        except RuntimeError:
            time.sleep(0.25)
            continue
        value = json.loads(helper(config, client, manifest, side, 'export', '--file', 'ready.json'))
        if (value.get('ready') is not True or value['run_id'] != manifest['run_id'] or
                value['source_sha256'] != manifest['source_sha256']):
            raise ValueError('Recorder readiness/source mismatch')
        return value
    raise TimeoutError('Recorder did not become ready; preserve its bounded original run')


def mac_clock(config, client, manifest):
    start = time.monotonic_ns()
    value = json.loads(helper(config, client, manifest, 'mac', 'clock'))
    return dict(host_before_ns=start, host_after_ns=time.monotonic_ns(), clock=value)


def prepare(config, client, manifest, side, interface):
    directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-tcp.XXXXXXXX', display=False).decode().strip()
    if not re.fullmatch(r'/tmp/gameshellneo-tcp\.[A-Za-z0-9]+', directory):
        raise ValueError('Unexpected capture directory')
    manifest[side] = dict(directory=directory, interface=interface, ready=False)
    with client.open_sftp() as sftp:
        upload(sftp, ROOT/'tools/tcp_metadata.py', directory+'/tcp_metadata.py')
        if side == 'device':
            upload(sftp, ROOT/'tools/tcp_supervisor.py', directory+'/tcp_supervisor.py')


def observer(manifest):
    return dict(directory=manifest['device']['directory'], run_id=manifest['run_id'],
                source_sha256=manifest['source_sha256'],
                supervisor_sha256=manifest['supervisor_sha256'], address=manifest['address'])


def start_smoke(config, client, manifest):
    if run(client, 'systemctl show gameshellneo-sleep-test -p LoadState --value', display=False).decode().strip() != 'not-found':
        raise ValueError('An earlier sleep unit exists; collect it without resubmission')
    directory = manifest['device']['directory']
    command = ['sudo', '-n', 'systemd-run', '--quiet', '--collect', '--unit=gameshellneo-sleep-test',
               '--property=RuntimeMaxSec=180', '--property=TimeoutStopSec=10', '--property=UMask=0077']
    command += tcp_supervisor.prefix(observer(manifest))
    command += ['/usr/bin/systemd-inhibit', '--what=handle-power-key:sleep:idle', '--mode=block',
                '--who=GameShellNeo observer smoke', '--why=Read-only unit ownership validation',
                '/usr/bin/python3', '-B', directory+'/tcp_supervisor.py', '--directory', directory,
                '--run-id', manifest['run_id'], '--smoke']
    run(client, shlex.join(command), display=False, timeout=15)
    manifest['device']['ready_record'] = ready(config, client, manifest, 'device')
    manifest['device']['ready'] = True


def start(config, client, manifest, side):
    info = manifest[side]
    arguments = ['--interface', info['interface'], '--address', manifest['address'], '--seconds', '300']
    if side == 'mac':
        helper(config, client, manifest, side, 'launch', *arguments)
    else:
        script = info['directory']+'/tcp_metadata.py'
        cmd = ['sudo', '-n', 'systemd-run', '--quiet', '--collect', '--unit=gameshellneo-tcp-metadata',
               '--property=RuntimeMaxSec=315', '--property=TimeoutStopSec=5', '--property=UMask=0077',
               '/usr/bin/python3', '-B', script, 'capture', '--directory', info['directory'],
               '--run-id', manifest['run_id'], *arguments]
        run(client, shlex.join(cmd), display=False, timeout=15)
    info['launched'] = True
    info['ready_record'] = ready(config, client, manifest, side)
    info['ready'] = True


def finish_side(config, client, manifest, side, path):
    try:
        helper(config, client, manifest, side, 'stop')
    except RuntimeError:
        # A worker that failed before readiness can still have a final result.
        # Collection, not a second launch, determines what actually happened.
        pass
    info = manifest[side]
    for _ in range(30):
        cmd, password = command(config, side, ['/bin/test', '-f', info['directory']+'/result.json'])
        try:
            run(client, cmd, password=password, display=False, timeout=5)
        except RuntimeError:
            time.sleep(0.2)
            continue
        destination = path/('tcp-'+side)
        destination.mkdir(mode=0o700, exist_ok=True)
        for name in ('result.json', 'packets.jsonl'):
            data = helper(config, client, manifest, side, 'export', '--file', name)
            file = destination/name
            # Recollection must not overwrite a different original artifact.
            if file.exists():
                if file.read_bytes() != data:
                    raise ValueError('Original capture changed during recollection')
            else:
                with tcp_metadata.exclusive(file) as output:
                    output.write(data)
        info['collected'] = True
        if side == 'device' and info.get('sleep_unit'):
            # The recorder closes before the supervisor publishes its outcome.
            for _ in range(30):
                try:
                    run(client, shlex.join(['sudo', '-n', '/bin/test', '-f', info['directory']+'/supervisor.json']),
                        display=False, timeout=5)
                    break
                except RuntimeError:
                    time.sleep(0.2)
            else:
                raise TimeoutError('Observer supervisor has not completed')
            names = ['supervisor.json']+(['smoke.json'] if manifest['mode'] == 'smoke' else [])
            for name in names:
                data = helper(config, client, manifest, side, 'export', '--file', name)
                file = destination/name
                if file.exists():
                    if file.read_bytes() != data:
                        raise ValueError('Original observer artifact changed')
                else:
                    with tcp_metadata.exclusive(file) as output:
                        output.write(data)
            info['supervisor_collected'] = True
        return
    raise TimeoutError('Recorder result is not available; original run remains bounded')


def collect(config, path, manifest):
    errors = []
    # Independent attempts ensure a missing device route cannot prevent Mac
    # cleanup. Never issue a second diagnostic/sleep on uncertain submission.
    for side in ('mac', 'device'):
        if not manifest.get(side, {}).get('launch_requested'):
            continue
        try:
            connection = connect_mac(config) if side == 'mac' else device(config, os.environ.get('NEO_ROUTE', 'usb'))
            with connection as client:
                if side == 'mac' and len(manifest['mac_clocks']) < 2:
                    manifest['mac_clocks'].append(mac_clock(config, client, manifest))
                finish_side(config, client, manifest, side, path)
                if side == 'mac':
                    route = run(client, shlex.join(['/sbin/route', '-n', 'get', manifest['address']]), display=False).decode()
                    current = re.findall(r'^\s*interface: (en[0-9]+)\s*$', route, re.M)
                    if current != [manifest['mac']['interface']]:
                        raise ValueError('Mac USB route changed during capture')
        except Exception as error:
            errors.append(dict(side=side, error_type=type(error).__name__))
        save(path/'tcp-run.json', manifest)
    save(path/'tcp-collection.json', dict(passed=not errors, errors=errors))
    if errors:
        raise RuntimeError('Capture collection incomplete; use device:ssh-trace-collect with this CAPTURE')


def inspect_boot(client):
    value = run(client, "cat /proc/sys/kernel/random/boot_id /sys/power/suspend_stats/success /sys/power/suspend_stats/fail", display=False).decode().splitlines()
    if len(value) != 3 or not re.fullmatch(r'[a-f0-9-]{36}', value[0]) or any(not n.isdigit() for n in value[1:]):
        raise ValueError('Invalid awake state')
    return dict(boot_id=value[0], success=int(value[1]), fail=int(value[2]))


def execute(config, path, sleep=False, smoke=False):
    address = str(ipaddress.IPv4Address(config.get('GAMESHELL_USB_IP', '192.168.10.1')))
    source = (ROOT/'tools/tcp_metadata.py').read_bytes()
    supervisor = (ROOT/'tools/tcp_supervisor.py').read_bytes()
    manifest = dict(schema=1, run_id=uuid.uuid4().hex, address=address, source_sha256=hashlib.sha256(source).hexdigest(),
                    supervisor_sha256=hashlib.sha256(supervisor).hexdigest(),
                    mode='sleep' if sleep else 'smoke' if smoke else 'awake', mac_clocks=[], operation_passed=False)
    (path/'tcp_metadata.py').write_bytes(source)
    (path/'tcp_supervisor.py').write_bytes(supervisor)
    save(path/'tcp-run.json', manifest)
    original_error = None
    try:
        with connect_mac(config) as mac:
            route = run(mac, shlex.join(['/sbin/route', '-n', 'get', address]), display=False).decode()
            names = re.findall(r'^\s*interface: (en[0-9]+)\s*$', route, re.M)
            if len(names) != 1:
                raise ValueError('No unique Ethernet route to GameShell USB')
            prepare(config, mac, manifest, 'mac', names[0])
            manifest['mac_clocks'].append(mac_clock(config, mac, manifest))
            manifest['mac']['launch_requested'] = True
            save(path/'tcp-run.json', manifest)
            start(config, mac, manifest, 'mac')
            save(path/'tcp-run.json', manifest)
        with device(config, 'usb') as board:
            manifest['before'] = inspect_boot(board)
            prepare(config, board, manifest, 'device', 'usb0')
            manifest['device']['sleep_unit'] = sleep or smoke
            if not sleep:
                manifest['device']['launch_requested'] = True
                save(path/'tcp-run.json', manifest)
                if smoke:
                    start_smoke(config, board, manifest)
                else:
                    start(config, board, manifest, 'device')
            save(path/'tcp-run.json', manifest)
        if sleep:
            runner = module('check-sleep-rtc.py')
            proof = Path(os.environ['NEO_SLEEP_QUALIFICATION'])
            manifest['device']['launch_requested'] = True
            save(path/'tcp-run.json', manifest)
            value = runner.experiment(config, path, proof, 'rtc-wake', os.environ['NEO_SLEEP_REHEARSAL'],
                                      observer=observer(manifest))
            continuation = json.loads(proof.read_text())
            continuation.setdefault('sleeps', []).append(dict(capture=str((path/'result.json').relative_to(ROOT)), run_id=value['run_id']))
            save(path/'qualification-next.json', continuation)
        else:
            module('check-ssh-timing.py').probe(config, path, 3)
        manifest['operation_passed'] = True
    except BaseException as error:
        original_error = error
        manifest['operation_error_type'] = type(error).__name__
        raise
    finally:
        save(path/'tcp-run.json', manifest)
        try:
            collect(config, path, manifest)
        except Exception:
            if original_error is None:
                raise
            print('Metadata collection also incomplete; primary failure preserved.', file=sys.stderr)
    with device(config, 'usb') as board:
        after = inspect_boot(board)
    manifest['after'] = after
    expected = dict(manifest['before'], success=manifest['before']['success']+int(sleep))
    if after != expected:
        save(path/'tcp-run.json', manifest)
        raise ValueError('Boot/PM state differs from the intended operation')
    save(path/'tcp-run.json', manifest)
    result = tcp_report.report(path)
    save(path/'tcp-report.json', result)
    if not sleep and result['matched_greeting_flows'] < 4:
        raise ValueError('Awake smoke requires four uniquely matched USB flows with greetings at both ends')
    print('TCP metadata valid; matched greeting flows:', result['matched_greeting_flows'])
    print('This validates observation, not the SSH root cause or uninstrumented timing.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--sleep', action='store_true')
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--collect', action='store_true')
    mode.add_argument('--report', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.collect or args.report:
        path = Path(os.environ.get('NEO_SSH_CAPTURE', '')).resolve(strict=True)
        if not path.is_dir() or not path.is_relative_to((LOCAL/'diagnostics').resolve()):
            raise ValueError('CAPTURE must identify a private diagnostic directory')
        if args.collect:
            collect(load_env(), path, json.loads((path/'tcp-run.json').read_text()))
        result = tcp_report.report(path)
        save(path/'tcp-report.json', result)
        print('Valid metadata; matched greeting flows:', result['matched_greeting_flows'])
        return
    if args.sleep and (os.environ.get('NEO_SLEEP_ATTENDED') != '1' or
                      not os.environ.get('NEO_SLEEP_QUALIFICATION') or not os.environ.get('NEO_SLEEP_REHEARSAL')):
        raise ValueError('Fresh ATTENDED=1, QUALIFICATION and REHEARSAL are required')
    with (LOCAL/'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = evidence_directory()
        print('Private two-ended TCP evidence:', path, flush=True)
        execute(load_env(), path, args.sleep, args.smoke)


if __name__ == '__main__':
    main()
