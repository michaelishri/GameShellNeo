"""Own a passive recorder and one command in the existing sleep-test unit.

No PM operation lives here. The original diagnostic retains every admission,
ownership, warning, submission and recovery check. The recorder must be ready
before that command starts; both children share systemd's bounded lifecycle.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

import tcp_metadata as tcp

UNIT = 'gameshellneo-sleep-test.service'


def read_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        data = stream.read(65537)
    if len(data) > 65536:
        raise ValueError('Observer control artifact exceeds limit')
    return json.loads(data)


def cgroup(pid):
    value = Path('/proc', str(pid), 'cgroup').read_text()
    if value != '0::/system.slice/'+UNIT+'\n':
        raise ValueError('Observer must belong to the existing sleep diagnostic unit')
    return value


def prefix(observer):
    if set(observer) != {'directory', 'run_id', 'source_sha256', 'supervisor_sha256', 'address'}:
        raise ValueError('Invalid observer description')
    directory = observer['directory']
    if not re.fullmatch(r'/tmp/gameshellneo-tcp\.[A-Za-z0-9]+', directory):
        raise ValueError('Invalid remote observer directory')
    for key in ('source_sha256', 'supervisor_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}', observer[key]):
            raise ValueError('Invalid observer source hash')
    address = str(tcp.ipaddress.IPv4Address(observer['address']))
    return ['/usr/bin/python3', '-B', directory+'/tcp_supervisor.py',
            '--directory', directory, '--run-id', tcp.token(observer['run_id']),
            '--source-sha256', observer['source_sha256'],
            '--supervisor-sha256', observer['supervisor_sha256'], '--address', address, '--']


def terminate(child):
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=3)


def supervise(path, identity, source, supervisor_source, address, command):
    if not command or command[0] != '/usr/bin/systemd-inhibit':
        raise ValueError('Require the original inhibited diagnostic command')
    if hashlib.sha256((path/'tcp_metadata.py').read_bytes()).hexdigest() != source or \
            hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != supervisor_source:
        raise ValueError('Observer source mismatch')
    for name in ('ready.json', 'result.json', 'stop.json', 'supervisor.json'):
        if os.path.lexists(path/name):
            raise ValueError('Observer artifacts already exist; collect the original run')
    record = dict(run_id=identity, source_sha256=supervisor_source, passed=False,
                  command_started=False, command_returncode=None, recorder_returncode=None,
                  cgroup=cgroup(os.getpid()))
    recorder = operation = None
    try:
        recorder = subprocess.Popen(['/usr/bin/python3', '-B', str(path/'tcp_metadata.py'),
            'capture', '--directory', str(path), '--run-id', identity,
            '--interface', 'usb0', '--address', address, '--seconds', '300'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic()+5
        while not (path/'ready.json').exists():
            if recorder.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('Observer failed before command admission')
            time.sleep(0.05)
        ready = read_json(path/'ready.json')
        if (ready.get('ready') is not True or ready.get('run_id') != identity or
                ready.get('source_sha256') != source or ready.get('pid') != recorder.pid or
                ready.get('interface') != 'usb0' or ready.get('address') != address or
                recorder.poll() is not None or cgroup(recorder.pid) != record['cgroup']):
            raise ValueError('Observer readiness or unit identity mismatch')
        record['recorder_pid'] = recorder.pid
        operation = subprocess.Popen(command, stdin=subprocess.DEVNULL)
        record['command_started'] = True
        record['command_returncode'] = operation.wait(timeout=170)
        # Preserve the observation window through host result/route collection.
        # The host stops the recorder; its own deadline and systemd remain bounds.
        record['recorder_returncode'] = recorder.wait(timeout=300)
        result = read_json(path/'result.json')
        record['passed'] = (record['command_returncode'] == 0 and record['recorder_returncode'] == 0 and
                            result.get('run_id') == identity and result.get('passed') is True)
    except BaseException as error:
        record['error_type'] = type(error).__name__
        raise
    finally:
        record['cleanup_errors'] = []
        for child in (operation, recorder):
            try:
                terminate(child)
            except Exception as error:
                record['cleanup_errors'].append(type(error).__name__)
                record['passed'] = False
        tcp.save(path/'supervisor.json', record)
    return 0 if record['passed'] else 1


def smoke(path, identity):
    """Read-only child proves cgroup ownership and the admission unit set."""
    own = cgroup(os.getpid())
    if cgroup(os.getppid()) != own:
        raise ValueError('Smoke command left observer unit')
    units = subprocess.check_output(['systemctl', 'list-units', '--all', '--plain', '--no-legend',
        '--state=active,activating,deactivating', 'gameshellneo-*.service'], text=True)
    active = sorted(line.split()[0] for line in units.splitlines() if line.split())
    allowed = {'gameshellneo-usb.service', 'gameshellneo-ready.service',
               'gameshellneo-battery.service', UNIT}
    if UNIT not in active or any(unit not in allowed for unit in active):
        raise ValueError('Unexpected diagnostic during observer smoke')
    tcp.save(path/'smoke.json', dict(run_id=identity, passed=True, cgroup=own, active_units=active))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--source-sha256')
    parser.add_argument('--supervisor-sha256')
    parser.add_argument('--address')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    os.umask(0o077)
    path, identity = tcp.directory(args.directory), tcp.token(args.run_id)
    if args.smoke:
        smoke(path, identity)
        return 0
    def interrupted(*_):
        raise InterruptedError('Observer unit stopped')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if args.command[:1] != ['--']:
        raise ValueError('Missing command separator')
    return supervise(path, identity, args.source_sha256, args.supervisor_sha256,
                     args.address, args.command[1:])


if __name__ == '__main__':
    sys.exit(main())
