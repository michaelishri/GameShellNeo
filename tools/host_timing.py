"""Private, bounded host-side spans; never record SSH payloads or error text."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import json
import os
import re
import statistics
import sys
import time


PHASES = frozenset(('capture', 'sleep.experiment', 'pm.cycle', 'awake.probe',
    'route.usb', 'route.wifi', 'mac.connect', 'mac.tcp', 'mac.ssh',
    'device.tunnel', 'device.ssh', 'command.channel', 'command.request',
    'command.response', 'pm.submit', 'collection.wait', 'collection.attempt',
    'proof.wifi', 'proof.final', 'clock.sample'))
MAX_EVENTS = 8192
_active = ContextVar('host_timing', default=None)
# Executed only by read-only host probes. BOOTTIME shares the saved sleep
# result's clock domain, but not the host's; the enclosing span brackets it.
CLOCK_SOURCE = '''
import time
from pathlib import Path
clock = dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
             boottime_ns=time.clock_gettime_ns(time.CLOCK_BOOTTIME))
'''


class Recorder:
    def __init__(self, stream):
        self.stream = stream
        self.events = 0
        self.next_id = 0
        self.parent = None
        self.failed = False

    def emit(self, **fields):
        if self.failed:
            return
        # Timing is observational. A full disk must never interrupt collection
        # after an uncertain PM submission or replace the original exception.
        try:
            if self.events >= MAX_EVENTS:
                raise OSError('timing event limit')
            value = dict(schema=1, host_monotonic_ns=time.monotonic_ns(),
                         host_utc=datetime.now(timezone.utc).isoformat(), **fields)
            payload = (json.dumps(value, sort_keys=True)+'\n').encode()
            if self.stream.write(payload) != len(payload):
                raise OSError('short timing write')
            self.events += 1
        except OSError:
            self.failed = True
            try:
                print('Host timing incomplete; original operation continues.', file=sys.stderr, flush=True)
            except OSError:
                pass  # A redirected stderr may be on the same full disk.


@contextmanager
def capture_timing(directory):
    """Exclusive file, 0600, no symlink following. Complete only with capture end."""
    descriptor = os.open(directory/'host-timing.jsonl',
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb', buffering=0) as stream:
        recorder = Recorder(stream)
        token = _active.set(recorder)
        try:
            with phase('capture'):
                yield recorder
        finally:
            _active.reset(token)


def timed_capture(name):
    """Existing host workflows accept (config, capture, ...)."""
    def decorate(function):
        @wraps(function)
        def wrapped(config, capture, *args, **kwargs):
            with capture_timing(capture), phase(name):
                return function(config, capture, *args, **kwargs)
        return wrapped
    return decorate


@contextmanager
def phase(name):
    if name not in PHASES:
        raise ValueError('Unknown timing phase')
    recorder = _active.get()
    if recorder is None:
        yield
        return
    recorder.next_id += 1
    span, parent = recorder.next_id, recorder.parent
    recorder.parent = span
    start = time.monotonic_ns()
    recorder.emit(event='begin', phase=name, span=span, parent=parent)
    outcome, failure = 'ok', None
    try:
        yield
    except BaseException as error:
        outcome = 'error'
        # Class names, exception strings, SSH endpoints and arguments are not
        # trusted diagnostic labels. Use only fixed categories and integer codes.
        import paramiko
        if isinstance(error, paramiko.ChannelException):
            failure = 'ssh_channel'
        elif isinstance(error, paramiko.SSHException):
            failure = 'ssh'
        elif isinstance(error, TimeoutError):
            failure = 'timeout'
        elif isinstance(error, OSError):
            failure = 'os'
        elif isinstance(error, ValueError):
            failure = 'validation'
        else:
            failure = 'other'
        code = getattr(error, 'code', None) if failure == 'ssh_channel' else getattr(error, 'errno', None)
        code = code if type(code) is int and -4096 <= code <= 4096 else None
        recorder.emit(event='failure', phase=name, span=span, category=failure, code=code)
        raise
    finally:
        recorder.emit(event='end', phase=name, span=span, outcome=outcome,
                      duration_ns=time.monotonic_ns()-start)
        recorder.parent = parent


def collection_state(value):
    recorder = _active.get()
    if recorder is not None:
        state = value.get('event')
        recorder.emit(event='collection_state', span=recorder.parent,
                      state=state if state in ('started', 'complete', 'failed') else 'other')


def clock_sample(value):
    """Accept only a boot identity and integer device BOOTTIME, no payloads."""
    if (not isinstance(value, dict) or set(value) != {'boot_id', 'boottime_ns'} or
            not isinstance(value['boot_id'], str) or
            not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value['boot_id']) or
            type(value['boottime_ns']) is not int or not 0 <= value['boottime_ns'] < 2**63):
        raise ValueError('Invalid device clock sample')
    recorder = _active.get()
    if recorder is not None:
        recorder.emit(event='device_clock', span=recorder.parent, **value)


def summarize(directory):
    """Reject truncated traces; report only fixed labels and measured durations."""
    with (directory/'host-timing.jsonl').open('rb') as source:
        raw = source.read(4*1024*1024+1)
    if len(raw) > 4*1024*1024:
        raise ValueError('Timing capture exceeds size limit')
    records = [json.loads(line) for line in raw.splitlines()]
    stack, groups, previous, seen = [], {}, -1, set()
    if not records or len(records) > MAX_EVENTS:
        raise ValueError('Empty or oversized timing capture')
    for index, row in enumerate(records):
        now = row.get('host_monotonic_ns')
        if row.get('schema') != 1 or type(now) is not int or now < previous:
            raise ValueError('Invalid host clock sequence')
        previous = now
        event = row.get('event')
        if event == 'begin':
            span = row.get('span'); name = row.get('phase')
            if (type(span) is not int or span in seen or name not in PHASES or
                    row.get('parent') != (stack[-1]['span'] if stack else None) or
                    (not stack and (index != 0 or name != 'capture'))):
                raise ValueError('Invalid span nesting')
            seen.add(span); stack.append(row)
        elif event == 'end':
            if not stack or row.get('span') != stack[-1]['span'] or row.get('phase') != stack[-1]['phase']:
                raise ValueError('Unmatched timing span')
            elapsed = row.get('duration_ns'); outcome = row.get('outcome')
            if type(elapsed) is not int or elapsed < 0 or outcome not in ('ok', 'error'):
                raise ValueError('Invalid timing result')
            route = next((r['phase'][6:] for r in reversed(stack) if r['phase'].startswith('route.')), 'none')
            group = groups.setdefault((row['phase'], route), [])
            group.append((elapsed/1e6, outcome == 'error'))
            stack.pop()
        elif event not in ('failure', 'device_clock', 'collection_state') or not stack or row.get('span') != stack[-1]['span']:
            raise ValueError('Invalid timing event')
    if stack or records[-1].get('event') != 'end' or records[-1].get('phase') != 'capture':
        raise ValueError('Incomplete timing capture')
    return dict(schema=1, capture_outcome=records[-1]['outcome'], phases=[dict(
        phase=name, route=route, count=len(values), errors=sum(error for _, error in values),
        min_ms=round(min(v for v, _ in values), 3),
        median_ms=round(statistics.median(v for v, _ in values), 3),
        max_ms=round(max(v for v, _ in values), 3))
        for (name, route), values in sorted(groups.items())])
