#!/usr/bin/env python3
"""Awake, bounded forwarding identity controls; never integrated into PM yet."""
from contextlib import ExitStack, contextmanager
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import time

import paramiko
import forward_socket as observer
from private_config import load_env
from remote import (ROOT, LOCAL, connect_mac, device, run, upload, authenticate_device,
                    evidence_directory, python_command)

PROBE = '''
import json
from pathlib import Path
stats=Path('/sys/power/suspend_stats')
print(json.dumps(dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                     pm={k:int((stats/k).read_text()) for k in ('success','fail')})))
'''
PEER = 'printf "%s\\n" "$SSH_CONNECTION"'
ARTIFACTS = ('baseline.json', 'opened.json', 'two-forwards.json', 'other-transport.json',
             'board-identity.json', 'other-board-identity.json', 'forward_socket.py', 'check-forward-socket.py')


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


@contextmanager
def helper(mac, cleanup_errors):
    directory = run(mac, 'umask 077; mktemp -d /tmp/gameshellneo-socket.XXXXXXXX', display=False).decode().strip()
    if not re.fullmatch(r'/tmp/gameshellneo-socket\.[A-Za-z0-9]+', directory):
        raise ValueError('Unexpected socket helper directory')
    failed = False
    try:
        with mac.open_sftp() as sftp:
            upload(sftp, ROOT/'tools/forward_socket.py', directory+'/forward_socket.py')
        yield directory+'/forward_socket.py'
    except BaseException:
        failed = True
        raise
    finally:
        try:
            with mac.open_sftp() as sftp:
                for name in ('forward_socket.py', 'forward_socket.py.part'):
                    try:
                        sftp.remove(directory+'/'+name)
                    except OSError as error:
                        if error.errno != 2:
                            raise
                sftp.rmdir(directory)
        except Exception:
            cleanup_errors.append('mac-helper-cleanup-failed')
            if not failed:
                raise


def snapshot(mac, script, capture, label):
    start = time.monotonic_ns()
    raw = run(mac, shlex.join(['/usr/bin/python3', '-B', script]), display=False, timeout=15)
    if len(raw) > observer.MAX_BYTES:
        raise ValueError('Oversized socket snapshot')
    value = json.loads(raw)
    if value.get('schema') != 1 or value.get('source_sha256') != hashlib.sha256((ROOT/'tools/forward_socket.py').read_bytes()).hexdigest():
        raise ValueError('Socket observer source mismatch')
    save(capture/(label+'.json'), dict(host_before_ns=start, host_after_ns=time.monotonic_ns(), snapshot=value))
    return value


def sample(board, initial=None):
    value = json.loads(run(board, **python_command(PROBE), display=False, timeout=10))
    if (set(value) != {'boot_id', 'pm'} or set(value['pm']) != {'success','fail'} or
            any(type(v) is not int or v < 0 for v in value['pm'].values()) or
            (initial is not None and value != initial)):
        raise ValueError('Boot/PM identity changed during awake socket controls')
    return value


def execute(config, capture, route):
    if route not in ('usb', 'wifi'):
        raise ValueError('Use ROUTE=usb/wifi')
    for name in ('forward_socket.py', 'check-forward-socket.py'):
        with (capture/name).open('xb') as output:
            output.write((ROOT/'tools'/name).read_bytes())
    result = dict(schema=1, passed=False, route=route, controls={}, cleanup_errors=[],
                  limits='Awake snapshots only; not continuous capture or failed-session attribution. '
                         'Extra diagnostic commands perturb timing; no latency claim or PM integration.')
    try:
        with device(config, 'usb') as discovery:
            initial = sample(discovery)
            status = run(discovery, 'sudo -n wpa_cli -i wlan0 status', display=False, timeout=10).decode()
        addresses = re.findall(r'^ip_address=(.+)$', status, re.M)
        if len(addresses) != 1:
            raise ValueError('Connected Wi-Fi address required')
        usb = str(ipaddress.IPv4Address(config.get('GAMESHELL_USB_IP','192.168.10.1')))
        wifi = str(ipaddress.IPv4Address(addresses[0]))
        if wifi == usb:
            raise ValueError('USB and Wi-Fi must be distinct')
        config = dict(config, GAMESHELL_IP=wifi, GAMESHELL_WIFI_VIA_MAC='1')
        target = [usb if route == 'usb' else wifi, 22]
        result['before'] = initial
        with connect_mac(config) as mac, helper(mac, result['cleanup_errors']) as script, ExitStack() as stack:
            before = snapshot(mac, script, capture, 'baseline')
            if any(row['remote'] == target for row in before['sockets']):
                raise ValueError('Fresh transport already has target sockets')
            channel = mac.get_transport().open_channel('direct-tcpip', tuple(target), ('127.0.0.1',0), timeout=10)
            stack.callback(channel.close)
            opened = snapshot(mac, script, capture, 'opened')
            board = stack.enter_context(paramiko.SSHClient())
            authenticate_device(board, config, target[0], channel)
            peer = run(board, PEER, display=False, timeout=10).decode().strip()
            observer.connection(peer)
            save(capture/'board-identity.json', dict(connection=peer, health=sample(board, initial)))
            result['binding'] = observer.correlate(before, opened, target, peer)
            result['controls']['board_endpoint_confirmed'] = True

            # A second forward to the same target makes request attribution
            # ambiguous even though both sockets belong to the right worker.
            second = mac.get_transport().open_channel('direct-tcpip', tuple(target), ('127.0.0.1',0), timeout=10)
            try:
                ambiguous = snapshot(mac, script, capture, 'two-forwards')
                if len(observer.candidates(before, ambiguous, target)) != 2:
                    raise ValueError('Second forward was not observed')
                try:
                    observer.correlate(before, ambiguous, target, peer)
                except ValueError:
                    result['controls']['same_worker_ambiguity_rejected'] = True
                else:
                    raise ValueError('Ambiguous forwarding identity was accepted')
            finally:
                second.close()

            # Concurrent same-target traffic on another independently opened
            # SSH transport must not enter this worker's candidate set.
            with device(config, route) as other:
                other_text = run(other, PEER, display=False, timeout=10).decode().strip()
                other_peer = observer.connection(other_text)
                save(capture/'other-board-identity.json', dict(connection=other_text, health=sample(other, initial)))
                live = snapshot(mac, script, capture, 'other-transport')
                binding = observer.correlate(before, live, target, peer)
                if binding['local'] == other_peer['client']:
                    raise ValueError('Other transport mistaken for this socket')
                result['controls']['other_transport_excluded'] = True
            result['after'] = sample(board, initial)
        result['passed'] = True
        print('Awake socket controls passed: board endpoint confirmed, duplicate forward rejected, other transport excluded.')
        print('Same boot and unchanged PM counters; no sleep or display action.')
    finally:
        result['source_sha256'] = hashlib.sha256((ROOT/'tools/forward_socket.py').read_bytes()).hexdigest()
        result['artifact_sha256'] = {name: hashlib.sha256((capture/name).read_bytes()).hexdigest()
                                    for name in ARTIFACTS if (capture/name).exists()}
        save(capture/'socket-smoke.json', result)
    return result


def report(capture):
    """Recheck saved independent endpoint evidence, without contacting either host."""
    raw = (capture/'socket-smoke.json').read_bytes()
    result = json.loads(raw)
    if (result.get('passed') is not True or result.get('cleanup_errors') != [] or
            set(result.get('artifact_sha256', {})) != set(ARTIFACTS)):
        raise ValueError('Incomplete original socket controls')
    for name, expected in result['artifact_sha256'].items():
        data = (capture/name).read_bytes()
        if len(data) > observer.MAX_BYTES or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Socket evidence hash/size mismatch')
    values = {}
    for label in ('baseline', 'opened', 'two-forwards', 'other-transport'):
        wrapped = json.loads((capture/(label+'.json')).read_text())
        value = wrapped['snapshot']
        if (value['source_sha256'] != result['source_sha256'] or
                value['source_sha256'] != result['artifact_sha256']['forward_socket.py'] or
                wrapped['host_before_ns'] > wrapped['host_after_ns']):
            raise ValueError('Snapshot source or clock mismatch')
        values[label] = value
    board = json.loads((capture/'board-identity.json').read_text())
    other = json.loads((capture/'other-board-identity.json').read_text())
    if not result['before'] == result['after'] == board['health'] == other['health']:
        raise ValueError('Inconsistent awake boot/PM state')
    target = observer.connection(board['connection'])['server']
    binding = observer.correlate(values['baseline'], values['opened'], target, board['connection'])
    if binding != result['binding'] or len(observer.candidates(values['baseline'], values['two-forwards'], target)) != 2:
        raise ValueError('Missing socket controls')
    try:
        observer.correlate(values['baseline'], values['two-forwards'], target, board['connection'])
    except ValueError:
        pass
    else:
        raise ValueError('Ambiguous observation accepted')
    second = observer.correlate(values['baseline'], values['other-transport'], target, board['connection'])
    other_pair = observer.connection(other['connection'])
    if other_pair['server'] != target or second['local'] == other_pair['client']:
        raise ValueError('Other transport not distinguished')
    return dict(schema=1, awake_controls_passed=True, route=result['route'], health=result['after'],
                result_sha256=hashlib.sha256(raw).hexdigest(), source_sha256=result['source_sha256'],
                limits=result['limits'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.report:
        capture = Path(os.environ.get('NEO_SSH_CAPTURE','')).resolve(strict=True)
        if not capture.is_dir() or not capture.is_relative_to((LOCAL/'diagnostics').resolve()):
            raise ValueError('Use a private socket diagnostic CAPTURE')
        print(json.dumps(report(capture), indent=2))
        return
    capture = evidence_directory()
    print('Private awake socket evidence:', capture, flush=True)
    execute(load_env(), capture, os.environ.get('NEO_ROUTE','usb'))
    save(capture/'socket-report.json', report(capture))


if __name__ == '__main__':
    main()
