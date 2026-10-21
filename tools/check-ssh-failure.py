#!/usr/bin/env python3
"""Awake SSH failure controls and offline reports for opt-in socket snapshots."""
from contextlib import contextmanager
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import threading

import paramiko
import forward_socket
import host_timing
import socket_observation as observation
from private_config import load_env
from remote import (ROOT, LOCAL, connect_mac, device, forwarded_device,
                    evidence_directory, python_command, run)

HEALTH = '''import json
from pathlib import Path
stats=Path('/sys/power/suspend_stats')
print(json.dumps(dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                     pm={k:int((stats/k).read_text()) for k in ('success','fail')})))
'''


def sample(client):
    return json.loads(run(client, **python_command(HEALTH),display=False,timeout=10))


def line(channel):
    data = bytearray()
    while len(data) < 4096:
        part = channel.recv(1)
        if not part:
            raise ValueError('Incomplete fixture record')
        data.extend(part)
        if part == b'\n':
            return json.loads(data)
    raise ValueError('Fixture output bound')


@contextmanager
def fixture(mac, mode):
    source = (ROOT/'tools/ssh_failure_peer.py').read_bytes()
    channel = mac.get_transport().open_session(timeout=10)
    timer = threading.Timer(65,channel.close)
    timer.daemon = True
    timer.start()
    try:
        channel.settimeout(20)
        channel.set_combine_stderr(True)
        bootstrap = "import sys;exec(compile(sys.stdin.buffer.read(65537),'awake_fixture','exec'))"
        channel.exec_command(shlex.join(['/usr/bin/python3','-B','-u','-c',bootstrap,mode]))
        channel.sendall(source)
        channel.shutdown_write()
        ready = line(channel)
        target = ready['target']
        if (ready.get('event') != 'ready' or ready.get('mode') != mode or len(target) != 2 or
                target[0] != '127.0.0.1' or type(target[1]) is not int or not 1024 <= target[1] <= 65535):
            raise ValueError('Unexpected fixture endpoint')
        yield channel, ready
    finally:
        timer.cancel()
        channel.close()


def execute(config, path):
    result = dict(schema=1,passed=False,cases=[])
    for name in ('ssh_failure_peer.py','check-ssh-failure.py'):
        observation.write_private(path/name,(ROOT/'tools'/name).read_bytes())
    try:
        with device(config,'usb') as client:
            result['before'] = sample(client)
            status = run(client,'sudo -n wpa_cli -i wlan0 status',display=False,timeout=10).decode()
        addresses = re.findall(r'^ip_address=(.+)$',status,re.M)
        if len(addresses) != 1:
            raise ValueError('Connected Wi-Fi required for awake controls')
        address = str(ipaddress.IPv4Address(addresses[0]))
        if address == config.get('GAMESHELL_USB_IP','192.168.10.1'):
            raise ValueError('Wi-Fi must use a distinct address')
        config = dict(config,GAMESHELL_IP=address,GAMESHELL_WIFI_VIA_MAC='1')
        with observation.capture(path), host_timing.capture_timing(path) as timing:
            for mode in ('silent','greeting-only'):
                with host_timing.phase('awake.probe'), connect_mac(config) as mac, fixture(mac,mode) as (channel,ready):
                    try:
                        with forwarded_device(config,mac,*ready['target']):
                            raise ValueError('Incomplete SSH peer unexpectedly authenticated')
                    except paramiko.SSHException:
                        # The production path re-raises its original exception.
                        # Retain only the fixed category; never exception text.
                        error = 'ssh'
                    closed = line(channel)
                    if closed.get('event') != 'closed' or channel.recv_exit_status() != 0:
                        raise ValueError('Fixture did not close normally')
                    result['cases'].append(dict(mode=mode,error=error,ready=ready,peer=closed))
                print('Awake failure control completed:',mode,flush=True)
            for route in ('usb','wifi'):
                with device(config,route) as client:
                    health = sample(client)
                    peer = run(client,'printf "%s\\n" "$SSH_CONNECTION"',display=False,timeout=10).decode().strip()
                result['cases'].append(dict(mode=route,health=health,connection=forward_socket.connection(peer)))
            result['after'] = health
        if timing.failed:
            raise ValueError('Incomplete host timing')
        result['passed'] = True
    finally:
        result['artifact_sha256'] = {name:hashlib.sha256((path/name).read_bytes()).hexdigest()
                                    for name in ('ssh_failure_peer.py','check-ssh-failure.py','host-timing.jsonl')
                                    if (path/name).exists()}
        observation.write_private(path/'ssh-failure-smoke.json',(json.dumps(result,indent=2)+'\n').encode())
    return report(path)


def report(path):
    report = observation.report(path)
    if not (path/'ssh-failure-smoke.json').exists():
        return report
    result = json.loads((path/'ssh-failure-smoke.json').read_text())
    if (result.get('passed') is not True or result.get('schema') != 1 or
            result['before'] != result['after'] or len(result['cases']) != 4 or
            len(report['observations']) != 4):
        raise ValueError('Incomplete awake failure controls')
    files = {'ssh_failure_peer.py','check-ssh-failure.py','host-timing.jsonl'}
    if set(result['artifact_sha256']) != files or any(hashlib.sha256((path/name).read_bytes()).hexdigest()!=digest
                                                     for name,digest in result['artifact_sha256'].items()):
        raise ValueError('Awake control artifacts changed')
    from ssh_failure_peer import GREETING
    for number,(mode,case) in enumerate(zip(('silent','greeting-only','usb','wifi'),result['cases']),1):
        item = json.loads((path/'socket-observations'/f'{number:04d}.json').read_text())
        if case['mode'] != mode:
            raise ValueError('Wrong control order')
        ssh, forward = item['states']['ssh'], item['states']['forward']
        if mode in ('silent','greeting-only'):
            if (case['error'] != 'ssh' or item['outcome'] != 'ssh-error' or
                    ssh['banner_received'] is not (mode=='greeting-only') or
                    ssh['initial_kex_complete'] is not False or ssh['authenticated'] is not False or
                    forward['received_bytes'] != (len(GREETING) if mode=='greeting-only' else 0) or
                    case['peer']['sent_bytes'] != forward['received_bytes'] or
                    not 0 < forward['sent_bytes'] <= case['peer']['received_bytes'] or
                    case['ready']['target'] != item['target']):
                raise ValueError('Failure control did not retain its original byte/SSH state')
            peer = case['peer']['connection']
            # The SSH library can retire a failed socket before the snapshot.
            # Missing remains missing, never a guessed endpoint or healthy pass.
            if item['status'] not in ('missing','unique-worker-candidate'):
                raise ValueError('Unusable failure socket observation')
        else:
            if (case['health'] != result['before'] or item['outcome'] != 'ok' or
                    item['status'] != 'unique-worker-candidate' or ssh['authenticated'] is not True):
                raise ValueError('Healthy control failed')
            peer = case['connection']
        if item['status'] == 'unique-worker-candidate' and any(
                r['local'] != peer['client'] or r['remote'] != peer['server'] for r in item['candidate']):
            raise ValueError('Independent control peer disagrees with socket candidate')
    report['awake_controls_passed'] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.report:
        path = Path(os.environ.get('NEO_SSH_CAPTURE','')).resolve(strict=True)
        if not path.is_dir() or not path.is_relative_to((LOCAL/'diagnostics').resolve()):
            raise ValueError('CAPTURE must identify private diagnostic evidence')
        result = report(path)
    else:
        path = evidence_directory()
        print('Private awake failure controls:',path,flush=True)
        result = execute(load_env(),path)
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
