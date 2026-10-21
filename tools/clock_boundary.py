"""Exact-call clock boundary capture/replay. No standalone live-device entrypoint.

The deployment wrapper must qualify the image, binaries and absent vDSO exports
before giving this workload a recorder descriptor. These routines do not admit
PM or establish that a clock is healthy, even when a capture is complete.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import struct

from clock_provenance import NS, integer, loads, replay, signed

ROUTES = ('syscall64', 'syscall32', 'libc64', 'python')
PLAN = tuple((clock, route) for _ in range(32) for clock in (1, 4, 7) for route in ROUTES)
LIMIT = 1024  # Headroom exposes incidental calls instead of truncating to the plan.
MAX_BYTES = 16 * 1024 * 1024


class ExportError(OSError):
    def __init__(self, message, partial):
        super().__init__(message)
        self.partial = partial


class NativeObservation(ctypes.Structure):
    _fields_ = [('rc', ctypes.c_int32), ('error', ctypes.c_int32),
                ('size', ctypes.c_int32), ('converted', ctypes.c_int32),
                ('sec', ctypes.c_int64), ('nsec', ctypes.c_int64),
                ('native_ns', ctypes.c_int64), ('bytes', ctypes.c_ubyte * 16)]


class NativeReader:
    def __init__(self, path):
        # PyDLL retains the GIL: releasing it can add unrelated clock syscalls
        # in this very task. This perturbs scheduling and is recorded as a limit.
        self.library = ctypes.PyDLL(str(path))
        self.layout = self.library.neo_clock_layout
        self.layout.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32]
        self.layout.restype = ctypes.c_int
        layout = (ctypes.c_uint32 * 9)()
        if self.layout(layout, len(layout)) or list(layout) != [1, 56, 16, 40, 16, 8, 4, 4, 4]:
            raise ValueError('Native reader is not the ARM libc time64 layout')
        if (ctypes.sizeof(NativeObservation), NativeObservation.sec.offset,
                NativeObservation.bytes.offset) != (56, 16, 40):
            raise ValueError('ctypes observation layout differs')
        self.call = self.library.neo_clock_read
        self.call.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(NativeObservation)]
        self.call.restype = ctypes.c_int

    def vdso(self):
        function = self.library.neo_clock_vdso
        function.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32]
        function.restype = ctypes.c_int
        out = (ctypes.c_uint32 * 4)()
        if function(out, 4):
            raise ValueError('vDSO inventory failed')
        return dict(zip(('mapping_found', 'handle_verified', 'time32_exported', 'time64_exported'), out))

    def __call__(self, route, clock, out):
        if route not in ROUTES[:3] or clock not in (1, 4, 7):
            raise ValueError('Unsupported clock request')
        rc = self.call(ROUTES.index(route), clock, ctypes.byref(out))
        if rc:
            raise ValueError('Native reader rejected request: ' + str(rc))


class KernelControl:
    """Owns an already opened debugfs fd; all calls must stay on its opener task."""
    def __init__(self, fd):
        self.fd = fd

    def command(self, data):
        if os.write(self.fd, data) != len(data):
            raise OSError('Short kernel recorder command; do not retry')

    def start(self):
        self.command(b'start 1024\n')

    def stop(self):
        self.command(b'stop\n')

    def read(self):
        data = bytearray()
        try:
            while True:
                part = os.read(self.fd, min(65536, MAX_BYTES + 1 - len(data)))
                if not part:
                    return bytes(data)
                data.extend(part)
                if len(data) > MAX_BYTES:
                    raise ValueError('Oversized kernel capture')
        except BaseException as error:
            raise ExportError(type(error).__name__ + ': ' + str(error), bytes(data)) from error

    def close(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            # Do not retry an interrupted close: the descriptor may already
            # have been released and reused. The failed close remains evidence.
            os.close(fd)


def collect(control, native, public, context):
    """One fixed plan; always attempt stop/export/close, preserving partial data.

    The caller persists the returned raw stream before replay. No printing,
    file export, sleep or metadata gathering occurs between start and stop.
    A host-side independent timeout must supervise live use; no clock under
    investigation provides the bound. No automatic second capture is allowed.
    """
    slots = [NativeObservation() if route != 'python' else None for _, route in PLAN]
    values = [None] * len(PLAN)
    errors, kernel = [], b''
    attempted = completed = 0
    started = stopped = closed = False
    try:
        control.start()
        started = True
        for i, (clock, route) in enumerate(PLAN):
            attempted = i + 1
            if route == 'python':
                values[i] = public[clock]()
            else:
                native(route, clock, slots[i])
            completed = i + 1
    except BaseException as error:
        errors.append(dict(stage='workload' if started else 'start', type=type(error).__name__,
                           message=str(error), errno=getattr(error, 'errno', None)))
    finally:
        # Also stop after an ambiguous/failed start; don't assume it didn't arm.
        try:
            control.stop()
            stopped = True
        except BaseException as error:
            errors.append(dict(stage='stop', type=type(error).__name__, message=str(error)))
        try:
            kernel = control.read()
        except BaseException as error:
            kernel = getattr(error, 'partial', b'')
            errors.append(dict(stage='export', type=type(error).__name__, message=str(error)))
        try:
            control.close()
            closed = True
        except BaseException as error:
            errors.append(dict(stage='close', type=type(error).__name__, message=str(error)))
    calls = []
    for i in range(attempted):
        clock, route = PLAN[i]
        c = dict(ordinal=i + 1, clock=clock, route=route, returned=i < completed)
        if route == 'python':
            c.update(python_ns=values[i], raw=None)
        else:
            out = slots[i]
            c.update(rc=out.rc, errno=out.error, size=out.size, converted=out.converted,
                     sec=out.sec, nsec=out.nsec, native_ns=out.native_ns,
                     raw=bytes(out.bytes).hex())
            # Independent Python decode, never derived from native_ns.
            c['python_ns'] = decoded_ns(c)[2] if i < completed else None
        calls.append(c)
    return dict(schema=1, operation='clock-boundary-capture', context=context,
                started=started, stopped=stopped, closed=closed, errors=errors, calls=calls), kernel


def decoded_ns(c):
    raw = c['raw']
    if not isinstance(raw, str) or len(raw) != 32 or any(x not in '0123456789abcdef' for x in raw):
        raise ValueError('Expected the entire 16-byte native buffer in lowercase hex')
    formats = {'syscall64': '<qq', 'syscall32': '<ii', 'libc64': '<qi'}
    sec, nsec = struct.unpack_from(formats[c['route']], bytes.fromhex(raw))
    valid = c['rc'] == 0 and sec >= 0 and 0 <= nsec < NS
    value = sec * NS + nsec if valid else None
    return sec, nsec, value


def join(records, users):
    """Reject ambiguous alignment; keep arithmetic mismatches as explicit findings."""
    kernel = replay(records)
    if (users.get('schema') != 1 or type(users['schema']) is not int or
            users.get('operation') != 'clock-boundary-capture'):
        raise ValueError('Unexpected userspace record schema')
    context = users['context']
    for key in ('tid', 'tgid'):
        integer(context[key], 1, (1 << 31) - 1)
    integer(context['namespace_id'], 0, (1 << 32) - 1)
    integer(context['source_id'], 0, (1 << 32) - 1)
    affinity = context['affinity']
    if not isinstance(affinity, list) or not affinity or affinity != sorted(set(affinity)):
        raise ValueError('Missing or inconsistent affinity')
    for cpu in affinity:
        integer(cpu, 0, 3)
    if context['clocksource'] != 'arch_sys_counter':
        raise ValueError('This workload requires the qualified architectural clocksource')
    incomplete = list(kernel['incomplete'])
    for key in ('started', 'stopped', 'closed'):
        if type(users[key]) is not bool:
            raise ValueError('Malformed collector state')
        if not users[key]:
            incomplete.append('collector-' + key + '-false')
    if not isinstance(users['errors'], list):
        raise ValueError('Malformed collector errors')
    if users['errors']:
        incomplete.append('collector-error')
    h = records[0]
    calls = users['calls']
    if not isinstance(calls, list) or len(calls) > len(PLAN):
        raise ValueError('Unexpected userspace call count')
    # Partial streams may be saved/replayed, but cannot establish alignment.
    aligned = (len(calls) == len(PLAN) == kernel['calls'] and h['reason'] == 1 and
               h['limit'] == LIMIT and h['time_ns'] == context['namespace_id'])
    if not aligned:
        incomplete.append('call-plan-or-session-mismatch')
    findings, comparisons = [], []
    previous, generation = {}, None
    if aligned:
        for ordinal, ((clock, route), u, k) in enumerate(zip(PLAN, calls, records[1:]), 1):
            abi = 32 if route == 'syscall32' else 64
            if (type(u['ordinal']) is not int or u['ordinal'] != ordinal or
                    type(u['clock']) is not int or u['clock'] != clock or u['route'] != route or
                    k['clock'] != clock or k['abi'] != abi or k['syscall'] != (263 if abi == 32 else 403) or
                    any(k[key] != context[key] for key in ('tid', 'tgid', 'namespace_id'))):
                raise ValueError('Call ownership, order, clock or ABI does not match the fixed plan')
            if type(u['returned']) is not bool:
                raise ValueError('Malformed call completion')
            if not u['returned'] or not all(k[key] for key in ('accepted', 'valid', 'complete')):
                incomplete.append(f'call-{ordinal}-boundary-incomplete')
                continue
            if k['cpu'] not in affinity or k['end_cpu'] not in affinity:
                raise ValueError('Recorded task CPU outside its affinity')
            t = k['tuple']
            current = (t['source_changed'], t['mono']['source_id'], t['raw']['source_id'])
            if generation is None:
                generation = current
            if current != generation or current[1:] != (context['source_id'],) * 2:
                incomplete.append(f'call-{ordinal}-clocksource-context-changed')
            expected = k['sec'] * NS + k['nsec']
            value = u['python_ns']
            if route == 'python':
                if u.get('raw') is not None:
                    raise ValueError('Python public API does not expose a raw timespec')
                signed(value)
                if k['error']:
                    incomplete.append(f'call-{ordinal}-python-syscall-error')
                elif value != expected:
                    findings.append(dict(ordinal=ordinal, boundary='kernel-to-python',
                                         expected_ns=expected, observed_ns=value))
            else:
                integer(u['rc'], -1, 0)
                integer(u['errno'], 0, 4095)
                integer(u['size'], 8, 16)
                integer(u['converted'], 0, 1)
                for key in ('sec', 'nsec', 'native_ns'):
                    signed(u[key])
                if u['size'] != (8 if route == 'syscall32' else 16):
                    raise ValueError('Raw buffer ABI size mismatch')
                sec, nsec, independent = decoded_ns(u)
                expected_conversion = int(independent is not None and independent <= (1 << 63) - 1)
                if (sec, nsec) != (u['sec'], u['nsec']):
                    findings.append(dict(ordinal=ordinal, boundary='raw-to-native-fields'))
                if (u['converted'] != expected_conversion or
                        u['native_ns'] != (independent if expected_conversion else -1)):
                    findings.append(dict(ordinal=ordinal, boundary='native-integer-conversion'))
                if value != independent or (value is not None and type(value) is not int):
                    findings.append(dict(ordinal=ordinal, boundary='python-integer-conversion'))
                if (u['rc'], u['errno']) != ((-1, -k['error']) if k['error'] else (0, 0)):
                    findings.append(dict(ordinal=ordinal, boundary='syscall-return-status'))
                if u['rc'] or k['error'] or independent is None:
                    incomplete.append(f'call-{ordinal}-unsuccessful-read')
                elif (sec, nsec) != (k['sec'], k['nsec']):
                    findings.append(dict(ordinal=ordinal, boundary='kernel-to-raw',
                                         expected_ns=expected, observed_ns=independent))
            if type(value) is int:
                prior = previous.get(clock)
                if prior is not None and value < prior['ns']:
                    comparisons.append(dict(ordinal=ordinal, previous=prior['ordinal'], clock=clock,
                                            delta_ns=value - prior['ns']))
                previous[clock] = dict(ordinal=ordinal, ns=value)
    return dict(schema=1, operation='clock-boundary-replay', complete=aligned and not incomplete,
                aligned=aligned, incomplete=incomplete, calls=kernel['calls'],
                boundary_findings=findings, userspace_regressions=comparisons, kernel=kernel,
                scope='Exact-call replay only. Python has no raw buffer; provenance/deployment and PM admission are separate.')


def read_bounded(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Oversized boundary evidence')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', default=os.environ.get('NEO_CLOCK_KERNEL'))
    parser.add_argument('--users', default=os.environ.get('NEO_CLOCK_USERS'))
    args = parser.parse_args()
    if not args.kernel or not args.users:
        parser.error('Supply both --kernel/--users or task KERNEL=<ndjson> USERS=<json>')
    raw, users = read_bounded(args.kernel), read_bounded(args.users)
    result = join([loads(line) for line in raw.decode().splitlines()], loads(users))
    result['input_sha256'] = dict(kernel=hashlib.sha256(raw).hexdigest(), users=hashlib.sha256(users).hexdigest())
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
