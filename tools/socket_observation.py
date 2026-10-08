"""Opt-in, best-effort Mac socket state after the original SSH setup outcome."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import shlex
import threading
import time

import forward_socket
import host_timing

_active = ContextVar('socket_observation', default=None)
MAX_ATTEMPTS = 32
MAX_RECORD_BYTES = 256*1024
SOURCES = ('forward_socket.py', 'socket_observation.py', 'host_timing.py', 'remote.py')
BOOTSTRAP = '''import hashlib,json,sys
source=sys.stdin.buffer.read(65537)
if len(source)>65536: raise ValueError('Observer source limit')
scope={'__name__':'socket_observer_inline'}
exec(compile(source,'socket_observer_inline','exec'),scope)
print(json.dumps(scope['snapshot'](hashlib.sha256(source).hexdigest())))
'''


def write_private(path, data):
    if len(data) > MAX_RECORD_BYTES:
        raise ValueError('Socket observation file limit')
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd,'wb') as output:
        output.write(data)


def inline_snapshot(mac, source):
    """A watchdog bounds request/read waits as well as the remote helper itself."""
    deadline = time.monotonic()+15
    channel = mac.get_transport().open_session(timeout=15)
    timer = threading.Timer(max(0.01,deadline-time.monotonic()), channel.close)
    timer.daemon = True
    timer.start()
    try:
        channel.settimeout(max(0.01,deadline-time.monotonic()))
        channel.set_combine_stderr(True)
        channel.exec_command(shlex.join(['/usr/bin/python3','-B','-c',BOOTSTRAP]))
        channel.sendall(source)
        channel.shutdown_write()
        data = bytearray()
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Socket observation deadline')
            channel.settimeout(remaining)
            part = channel.recv(4096)
            if not part:
                break
            data.extend(part)
            if len(data) > forward_socket.MAX_BYTES:
                raise ValueError('Socket observation output limit')
        if time.monotonic() >= deadline or channel.recv_exit_status() != 0:
            raise ValueError('Socket observation did not complete')
        result = json.loads(data)
        if result.get('schema') != 1 or result.get('source_sha256') != hashlib.sha256(source).hexdigest():
            raise ValueError('Socket observation source mismatch')
        return result
    finally:
        timer.cancel()
        channel.close()


class Capture:
    def __init__(self, path):
        self.path = path/'socket-observations'
        self.path.mkdir(mode=0o700)
        self.source = Path(forward_socket.__file__).read_bytes()
        for name in SOURCES:
            write_private(self.path/name, Path(__file__).with_name(name).read_bytes())
        self.attempts = 0
        self.limited = False
        self.write_failed = False
        self.records = []

    def save(self, name, value):
        try:
            write_private(self.path/name, (json.dumps(value,indent=2)+'\n').encode())
        except Exception:
            self.write_failed = True

    def begin(self, mac, target):
        if self.attempts >= MAX_ATTEMPTS:
            self.limited = True
            return None
        self.attempts += 1
        item = Observation(self, mac, target, self.attempts)
        item.prepare()
        return item

    def finish(self):
        files = (*SOURCES, *(r['file'] for r in self.records))
        hashes = {}
        for name in files:
            try:
                hashes[name] = hashlib.sha256((self.path/name).read_bytes()).hexdigest()
            except OSError:
                self.write_failed = True
        self.save('index.json',dict(schema=1,attempts=self.attempts,limited=self.limited,
                                   write_failed=self.write_failed,records=self.records,
                                   source_sha256=hashlib.sha256(self.source).hexdigest(),artifact_sha256=hashes))


@contextmanager
def capture(path, enabled=True):
    if not enabled:
        yield None
        return
    value = Capture(path)
    token = _active.set(value)
    try:
        yield value
    finally:
        _active.reset(token)
        try:
            value.finish()
        except Exception:
            value.write_failed = True  # Preserve the original connection outcome.


def prepare(mac, address, port):
    value = _active.get()
    # Never enable silently outside a host timing capture. The first SSH/byte
    # state and completed setup span are part of this evidence contract.
    if value is None or host_timing._active.get() is None:
        return None
    try:
        return value.begin(mac, [address,port])
    except Exception:
        value.write_failed = True
        return None


def enabled():
    flag = os.environ.get('NEO_SOCKET_STATE', '0')
    if flag not in ('0', '1'):
        raise ValueError('Use SOCKET_STATE=0/1')
    return flag == '1'


@contextmanager
def workflow_capture(path):
    """Honor the opt-in for an ordinary PM workflow, or reuse its outer owner."""
    requested = enabled()  # Reject invalid configuration before any PM work.
    active = _active.get()
    if active is not None:
        if active.path.parent.resolve() != Path(path).resolve():
            raise ValueError('Socket observer belongs to another capture')
        yield active
        return
    with capture(path, requested) as value:
        yield value


class Observation:
    def __init__(self, capture, mac, target, number):
        self.capture, self.mac, self.target = capture, mac, target
        self.name = f'{number:04d}.json'
        self.value = dict(schema=1,number=number,target=target,status='unavailable',
                          outcome='not-started',independently_confirmed=False)
        self.finished = False

    def snapshot(self, label):
        start = time.monotonic_ns()
        result = inline_snapshot(self.mac,self.capture.source)
        self.value[label] = dict(host_before_ns=start,host_after_ns=time.monotonic_ns(),snapshot=result)
        return result

    def prepare(self):
        try:
            with host_timing.phase('socket.prepare'):
                before = self.snapshot('baseline')
                if any(row['remote'] == self.target for row in before['sockets']):
                    raise ValueError('Pre-existing target socket')
            self.value['prepared'] = True
        except Exception:
            self.value['prepared'] = False
        # Diagnostic unavailability does not prevent or retry the connection.

    def finish(self, outcome, states):
        if self.finished:
            return
        self.finished = True
        self.value.update(outcome=outcome,setup_finished_host_ns=time.monotonic_ns(),states=states)
        try:
            if self.value.get('prepared'):
                with host_timing.phase('socket.collect'):
                    after = self.snapshot('after-setup')
                    found = forward_socket.candidates(self.value['baseline']['snapshot'],after,self.target)
                    if len(found) == 1:
                        self.value.update(status='unique-worker-candidate',candidate=found[0])
                    else:
                        self.value['status'] = 'missing' if not found else 'ambiguous'
        except Exception:
            self.value['status'] = 'unavailable'
        self.value['observation_finished_host_ns'] = time.monotonic_ns()
        self.capture.save(self.name,self.value)
        self.capture.records.append(dict(file=self.name,status=self.value['status'],outcome=outcome))


def finish(observer, outcome, states):
    if observer is not None:
        # Do not replace a result even if an observer implementation fails.
        try:
            observer.finish(outcome,states)
        except Exception:
            observer.capture.write_failed = True


def report(path):
    """Recheck original timing/state binding; never promote a candidate to proof."""
    root = path/'socket-observations'
    def read(name):
        with (root/name).open('rb') as stream:
            raw = stream.read(MAX_RECORD_BYTES+1)
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError('Oversized socket evidence')
        return raw
    index = json.loads(read('index.json'))
    count = index.get('attempts')
    if (index.get('schema') != 1 or type(count) is not int or not 1 <= count <= MAX_ATTEMPTS or
            index.get('write_failed') is not False or index.get('limited') is not False or
            len(index.get('records', [])) != count):
        raise ValueError('Incomplete socket observations')
    files = set(SOURCES) | {f'{n:04d}.json' for n in range(1,count+1)}
    if set(index.get('artifact_sha256', {})) != files:
        raise ValueError('Incomplete socket evidence manifest')
    for name in files:
        if hashlib.sha256(read(name)).hexdigest() != index['artifact_sha256'][name]:
            raise ValueError('Socket artifact changed')
    if index['source_sha256'] != index['artifact_sha256']['forward_socket.py']:
        raise ValueError('Socket helper identity mismatch')
    host_timing.summarize(path)  # Validate nesting, completion, states and bounds.
    events = [json.loads(line) for line in (path/'host-timing.jsonl').read_bytes().splitlines()]
    result, seen_spans = [], set()
    for number, entry in enumerate(index['records'], 1):
        name = f'{number:04d}.json'
        if entry.get('file') != name:
            raise ValueError('Socket record order mismatch')
        item = json.loads(read(name))
        if (item.get('schema') != 1 or item.get('number') != number or
                item.get('independently_confirmed') is not False or
                item.get('status') != entry.get('status') or item.get('outcome') != entry.get('outcome') or
                item.get('outcome') not in ('ok', 'ssh-error', 'tunnel-error', 'not-started') or
                item.get('status') not in ('unique-worker-candidate','missing','ambiguous','unavailable')):
            raise ValueError('Invalid socket observation outcome')
        ended = item['setup_finished_host_ns']
        if type(ended) is not int or item['observation_finished_host_ns'] < ended:
            raise ValueError('Invalid socket observation window')
        states = item['states']
        if item['outcome'] in ('ok','ssh-error'):
            if set(states) != {'ssh','forward'} or any(not isinstance(v,dict) for v in states.values()):
                raise ValueError('Missing original connection state')
            span = states['ssh']['span']
            if span in seen_spans or states['forward']['span'] != span:
                raise ValueError('Repeated or mismatched setup span')
            seen_spans.add(span)
            for kind,state in states.items():
                matches = [e for e in events if e.get('span') == span and e['event'] == kind+'_state']
                if len(matches) != 1 or state != {k:v for k,v in matches[0].items()
                                                 if k not in ('schema','host_monotonic_ns','host_utc')}:
                    raise ValueError('Original SSH/byte state changed')
            end = [e for e in events if e.get('span') == span and e['event'] == 'end']
            if (len(end) != 1 or end[0]['phase'] != 'device.ssh' or end[0]['host_monotonic_ns'] > ended or
                    end[0]['outcome'] != ('ok' if item['outcome']=='ok' else 'error')):
                raise ValueError('Socket observation precedes original setup outcome')
            if 'baseline' in item:
                start = next(e['host_monotonic_ns'] for e in events if e.get('span')==span and e['event']=='begin')
                baseline_end = item['baseline']['host_after_ns']
                opened = [e for e in events if e['event']=='forward_state' and e['stage']=='opened' and
                          baseline_end <= e['host_monotonic_ns'] <= start]
                if len(opened) != 1:
                    raise ValueError('Baseline did not precede one forwarded setup')
        elif states:
            raise ValueError('Unexpected inner SSH state')
        for label in ('baseline', 'after-setup'):
            wrapper = item.get(label)
            if wrapper is None:
                continue
            snap = wrapper['snapshot']
            start, stop = wrapper['host_before_ns'], wrapper['host_after_ns']
            if (type(start) is not int or type(stop) is not int or start > stop or
                    snap['source_sha256'] != index['source_sha256'] or
                    (label == 'baseline' and stop > ended) or
                    (label == 'after-setup' and start < ended)):
                raise ValueError('Invalid socket snapshot identity/window')
            outer = snap['outer']
            if not any(r['local']==outer['server'] and r['remote']==outer['client'] and
                       r['state']=='ESTABLISHED' for r in snap['sockets']):
                raise ValueError('Snapshot does not own its outer transport')
        status = item['status']
        if status != 'unavailable':
            if item.get('prepared') is not True:
                raise ValueError('Socket result has no usable baseline')
            if any(r['remote']==item['target'] for r in item['baseline']['snapshot']['sockets']):
                raise ValueError('Pre-existing socket in baseline')
            found = forward_socket.candidates(item['baseline']['snapshot'],item['after-setup']['snapshot'],item['target'])
            expected = 'unique-worker-candidate' if len(found)==1 else 'missing' if not found else 'ambiguous'
            if status != expected or (len(found)==1 and item.get('candidate') != found[0]):
                raise ValueError('Socket candidate mismatch')
        result.append(dict(number=number,outcome=item['outcome'],status=status,
                           independently_confirmed=False))
    return dict(schema=1,complete=True,observations=result,
                limits='Point-in-time worker candidates only; missing is not proof no TCP socket existed. '
                       'Snapshots add wall time outside SSH setup; no latency comparison.')
