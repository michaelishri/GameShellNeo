"""Bounded, read-only macOS SSH-worker TCP snapshots; no traffic payloads."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time

MAX_BYTES = 65536
MAX_FILES = 128
STATES = {'CLOSED', 'LISTEN', 'SYN_SENT', 'SYN_RCVD', 'ESTABLISHED',
          'CLOSE_WAIT', 'FIN_WAIT_1', 'CLOSING', 'LAST_ACK', 'FIN_WAIT_2', 'TIME_WAIT'}


def number(value, maximum=2**31-1):
    if not re.fullmatch(r'[0-9]{1,20}', value) or not 0 <= int(value) <= maximum:
        raise ValueError('Invalid numeric socket field')
    return int(value)


def endpoint(address, port):
    return [str(ipaddress.ip_address(address)), number(port, 65535)]


def connection(value):
    fields = value.split()
    if len(fields) != 4 or len(value) > 256:
        raise ValueError('Missing or invalid SSH connection identity')
    client, server = endpoint(*fields[:2]), endpoint(*fields[2:])
    if not client[1] or not server[1]:
        raise ValueError('Zero SSH connection port')
    return dict(client=client, server=server)


def address_pair(value):
    pairs = value.split('->')
    if len(pairs) != 2:
        raise ValueError('Require a connected numeric endpoint pair')
    result = []
    for pair in pairs:
        address, port = pair.rsplit(':', 1)
        result.append(endpoint(address.removeprefix('[').removesuffix(']'), port))
    return result


def parse_lsof(data, pid):
    """Reject missing, duplicate or unexpected fields rather than infer identity."""
    if not data or len(data) > MAX_BYTES or not data.endswith(b'\0\n'):
        raise ValueError('Incomplete or oversized socket listing')
    rows, current, owner = [], None, None

    def finish():
        if current is None:
            return
        if not {'f', 'P', 'n', 'TST'} <= set(current) or current['P'] != 'TCP':
            raise ValueError('Incomplete TCP record')
        local, remote = address_pair(current['n'])
        state = current['TST']
        if state not in STATES:
            raise ValueError('Unsupported TCP state')
        rows.append(dict(fd=number(current['f']), local=local, remote=remote,
                         state=state, receive_queue=number(current['TQR']) if 'TQR' in current else None,
                         send_queue=number(current['TQS']) if 'TQS' in current else None))
        if len(rows) > MAX_FILES:
            raise ValueError('Socket record limit')

    for field in data.decode('ascii').split('\0'):
        field = field.lstrip('\n')
        if not field:
            continue
        key, value = field[:1], field[1:]
        if key == 'p':
            if owner is not None or current is not None or number(value) != pid:
                raise ValueError('Unexpected socket owner')
            owner = pid
            continue
        if owner is None:
            raise ValueError('Socket without process identity')
        if key == 'f':
            finish()
            current = {}
        if key == 'T':
            item = value.split('=', 1)
            if len(item) != 2 or item[0] not in ('ST', 'QR', 'QS'):
                raise ValueError('Unexpected TCP metadata')
            key, value = 'T'+item[0], item[1]
        if current is None or key not in ('f', 'P', 'n', 'TST', 'TQR', 'TQS') or key in current:
            raise ValueError('Unexpected or duplicate socket field')
        current[key] = value
    finish()
    if owner != pid or not rows or len({r['fd'] for r in rows}) != len(rows):
        raise ValueError('Missing or repeated socket descriptors')
    return rows


def bounded_command(arguments, deadline):
    """Bound both streams and wall time, kill/reap only our child on failure."""
    env = dict(os.environ, LC_ALL='C', TZ='UTC')
    with subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as child:
        chunks = {child.stdout: bytearray(), child.stderr: bytearray()}
        try:
            with selectors.DefaultSelector() as selector:
                for stream in chunks:
                    selector.register(stream, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Socket observer command deadline')
                    for key, _ in selector.select(min(remaining, 0.2)):
                        data = os.read(key.fd, 4096)
                        if not data:
                            selector.unregister(key.fileobj)
                        else:
                            chunks[key.fileobj].extend(data)
                            if sum(map(len, chunks.values())) > MAX_BYTES:
                                raise ValueError('Socket observer output limit')
            code = child.wait(timeout=max(0.01, deadline-time.monotonic()))
            if code != 0 or chunks[child.stderr]:
                raise ValueError('Socket observer command failed or warned')
            return bytes(chunks[child.stdout])
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()


def process(pid, deadline):
    raw = bounded_command(['/bin/ps', '-p', str(pid), '-o', 'pid=,ppid=,lstart=,comm='], deadline)
    fields = raw.decode().strip().split(None, 7)
    if len(fields) != 8 or number(fields[0]) != pid:
        raise ValueError('Missing process identity')
    return dict(pid=pid, ppid=number(fields[1]), started=' '.join(fields[2:7]),
                sshd=bool(re.match(r'^(?:.*/)?sshd(?:-session)?(?:[: ]|$)', fields[7])))


def snapshot(source_sha256=None):
    if sys.platform != 'darwin':
        raise ValueError('Mac socket observation requires macOS')
    started = time.monotonic_ns()
    deadline = time.monotonic()+10
    outer = connection(os.environ.get('SSH_CONNECTION', ''))
    pid = os.getppid()
    for _ in range(8):
        before = process(pid, deadline)
        if before['sshd']:
            break
        pid = before['ppid']
        if pid <= 1:
            raise ValueError('No SSH worker ancestor')
    else:
        raise ValueError('SSH ancestry limit')
    raw = bounded_command(['/usr/sbin/lsof', '-nP', '-a', '-p', str(pid), '-iTCP', '-F0pfnPT'], deadline)
    sockets = parse_lsof(raw, pid)
    after = process(pid, deadline)
    if before != after:
        raise ValueError('SSH worker changed during observation')
    if not any(r['local'] == outer['server'] and r['remote'] == outer['client'] and
               r['state'] == 'ESTABLISHED' for r in sockets):
        raise ValueError('SSH worker does not own this transport')
    source_sha256 = source_sha256 or hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if not re.fullmatch(r'[0-9a-f]{64}', source_sha256):
        raise ValueError('Invalid observer source identity')
    return dict(schema=1, source_sha256=source_sha256,
                started_monotonic_ns=started, finished_monotonic_ns=time.monotonic_ns(),
                worker=before, outer=outer, sockets=sockets)


def candidates(before, after, target):
    """Return new endpoint pairs only for one stable, independently bound worker.

    This is a candidate until verified against the authenticated board endpoint.
    A pair duplicated across file descriptors is one TCP flow, not two flows.
    """
    if before['worker'] != after['worker'] or before['outer'] != after['outer']:
        raise ValueError('Different SSH worker or outer transport')
    key = lambda r: (tuple(r['local']), tuple(r['remote']))
    old = {key(r) for r in before['sockets']}
    fresh = {}
    for row in after['sockets']:
        if row['remote'] == target and key(row) not in old:
            fresh.setdefault(key(row), []).append(row)
    return list(fresh.values())


def correlate(before, after, target, board_connection):
    fresh = candidates(before, after, target)
    if len(fresh) != 1:
        raise ValueError('No unique newly observed forwarded socket')
    expected = connection(board_connection)
    rows = fresh[0]
    if expected['server'] != target or any(r['local'] != expected['client'] or
            r['remote'] != expected['server'] or r['state'] != 'ESTABLISHED' for r in rows):
        raise ValueError('Board endpoint does not confirm the candidate socket')
    return dict(worker=after['worker'], outer=after['outer'], local=rows[0]['local'],
                remote=target, fds=sorted(r['fd'] for r in rows), state='ESTABLISHED',
                independently_confirmed=True)


if __name__ == '__main__':
    print(json.dumps(snapshot(), sort_keys=True))
