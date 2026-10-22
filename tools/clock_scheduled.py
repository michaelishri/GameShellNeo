"""Finite guard/RAW brackets with separately identified relative pause evidence."""
import ctypes
import json
import struct

from clock_boundary import NativeObservation, decoded_ns
from clock_deployment import context, save, validate_snapshot
from clock_provenance import NS, integer, loads, replay, signed
from development_clock import require, validate_development_contract

ROUNDS = 32
ROUND = ((1, 'python'), (7, 'python'), (1, 'python'), (4, 'python'),
         (4, 'syscall64'), (4, 'python'), (4, 'syscall64'), (4, 'python'))
PLAN = ROUND * ROUNDS
PAUSE_NS = 100_000_000
REQUEST = struct.pack('<qq', 0, PAUSE_NS).hex()
FILES = ('clock_scheduled.py', 'capture-scheduled-clock.py', 'clock-pause.so')
OPERATION = 'clock-scheduled-guard-raw-capture'


def schedule():
    return dict(schema=1, mode='guard-raw-relative-pause', rounds=ROUNDS,
        round=[dict(clock=c, route=r) for c, r in ROUND], clock_calls=len(PLAN),
        pause_count=ROUNDS - 1, pause_syscall=407, pause_clock=1, pause_flags=0,
        relative_pause_ns=PAUSE_NS, recorder_call_limit=1024, recorder_writer_limit=2048)


def validate_schedule(value):
    require(type(value) is dict and json.dumps(value, sort_keys=True) == json.dumps(schedule(), sort_keys=True),
            'Scheduled plan differs from the exact finite declaration')


class PauseObservation(ctypes.Structure):
    _fields_ = [('rc', ctypes.c_int32), ('error', ctypes.c_int32), ('clock', ctypes.c_int32),
                ('syscall', ctypes.c_uint32), ('flags', ctypes.c_uint32), ('calls', ctypes.c_uint32),
                ('request_before', ctypes.c_ubyte * 16), ('request_after', ctypes.c_ubyte * 16),
                ('remaining', ctypes.c_ubyte * 16)]


class NativePause:
    def __init__(self, path):
        self.library = ctypes.PyDLL(str(path))
        self.layout = self.library.neo_clock_pause_layout
        self.layout.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32]
        self.layout.restype = ctypes.c_int
        values = (ctypes.c_uint32 * 12)()
        require(not self.layout(values, len(values)) and list(values) ==
                [1, 72, 24, 40, 56, 16, 407, 1, 0, PAUSE_NS, 4, 4], 'Pause library ABI differs')
        require((ctypes.sizeof(PauseObservation), PauseObservation.request_before.offset,
                 PauseObservation.request_after.offset, PauseObservation.remaining.offset) == (72, 24, 40, 56),
                'ctypes pause ABI differs')
        self.call = self.library.neo_clock_pause
        self.call.argtypes = [ctypes.POINTER(PauseObservation)]
        self.call.restype = ctypes.c_int

    def __call__(self, out):
        code = self.call(ctypes.byref(out))
        require(code == 0, 'Pause library rejected preallocated result: ' + str(code))


def pause_record(out, ordinal, returned):
    return dict(ordinal=ordinal, after_clock_ordinal=ordinal * len(ROUND), returned=returned,
        rc=out.rc, errno=out.error, clock=out.clock, syscall=out.syscall, flags=out.flags, calls=out.calls,
        **{name: bytes(getattr(out, name)).hex() for name in ('request_before', 'request_after', 'remaining')})


def validate_pause(value):
    integer(value['ordinal'], 1, ROUNDS - 1)
    integer(value['after_clock_ordinal'], 8, len(PLAN) - 8)
    require(value['after_clock_ordinal'] == value['ordinal'] * len(ROUND) and
            type(value['returned']) is bool, 'Pause ordinal/completion differs')
    for key in ('clock', 'syscall', 'flags', 'calls'):
        integer(value[key], 0, 4095)
    require((value['clock'], value['syscall'], value['flags'], value['calls']) == (1, 407, 0, 1),
            'Pause syscall/clock/flags/invocation count differs')
    integer(value['rc'], -1, 0); integer(value['errno'], 0, 4095)
    for key in ('request_before', 'request_after', 'remaining'):
        raw = value[key]
        require(isinstance(raw, str) and len(raw) == 32 and
                all(c in '0123456789abcdef' for c in raw), 'Malformed original pause buffer')
    require(value['request_before'] == REQUEST, 'Pause was not the fixed relative request')
    require(value['request_after'] == REQUEST, 'Kernel/helper changed the original pause request')
    require((value['rc'] == 0) == (value['errno'] == 0), 'Pause return/errno disagree')
    return value['returned'] and value['rc'] == 0


def collect(control, native, public, pause, owner):
    """One predeclared plan; never restart a pause or recorder after an error."""
    slots = [NativeObservation() if route == 'syscall64' else None for _, route in PLAN]
    values = [None] * len(PLAN)
    pauses = [PauseObservation() for _ in range(ROUNDS - 1)]
    attempted = completed = pause_attempted = pause_returned = 0
    started = stopped = closed = False
    errors, raw, stage = [], b'', 'start'
    try:
        control.start(); started = True
        for round_number in range(ROUNDS):
            for clock, route in ROUND:
                i = attempted
                attempted += 1
                stage = 'workload'
                if route == 'python':
                    values[i] = public[clock]()
                else:
                    native(route, clock, slots[i])
                completed += 1
            if round_number != ROUNDS - 1:
                stage = 'pause'
                pause_attempted += 1
                pause(pauses[round_number])
                pause_returned += 1
                if pauses[round_number].rc or pauses[round_number].error:
                    raise OSError(pauses[round_number].error, 'Fixed relative pause failed; no retry')
    except BaseException as error:
        errors.append(dict(stage=stage, type=type(error).__name__, message=str(error),
                           errno=getattr(error, 'errno', None)))
    finally:
        for name in ('stop', 'read', 'close'):
            try:
                result = getattr(control, name)()
                if name == 'read': raw = result
                elif name == 'stop': stopped = True
                else: closed = True
            except BaseException as error:
                if name == 'read': raw = getattr(error, 'partial', b'')
                errors.append(dict(stage='export' if name == 'read' else name,
                                   type=type(error).__name__, message=str(error)))
    calls = []
    for i in range(attempted):
        clock, route = PLAN[i]
        value = dict(ordinal=i + 1, clock=clock, route=route, returned=i < completed)
        if route == 'python':
            value.update(python_ns=values[i], raw=None)
        else:
            out = slots[i]
            value.update(rc=out.rc, errno=out.error, size=out.size, converted=out.converted,
                         sec=out.sec, nsec=out.nsec, native_ns=out.native_ns, raw=bytes(out.bytes).hex())
            value['python_ns'] = decoded_ns(value)[2] if i < completed else None
        calls.append(value)
    return dict(schema=1, operation=OPERATION, schedule=schedule(), context=owner,
        started=started, stopped=stopped, closed=closed, errors=errors, calls=calls,
        pauses=[pause_record(pauses[i], i + 1, i < pause_returned) for i in range(pause_attempted)]), raw


def join(records, users):
    """Replay exact declared call/pause evidence; retain discrepancies as findings."""
    kernel = replay(records)
    require(type(users.get('schema')) is int and users['schema'] == 1 and
            users.get('operation') == OPERATION, 'Unknown scheduled operation')
    validate_schedule(users['schedule'])
    owner, header = users['context'], records[0]
    for key in ('tid', 'tgid'): integer(owner[key], 1, (1 << 31) - 1)
    integer(owner['namespace_id'], 0, (1 << 32) - 1)
    integer(owner['source_id'], 0, (1 << 32) - 1)
    affinity = owner['affinity']
    require(isinstance(affinity, list) and affinity and affinity == sorted(set(affinity)) and
            owner['clocksource'] == 'arch_sys_counter', 'Invalid clock/CPU context')
    for cpu in affinity: integer(cpu, 0, 3)
    incomplete = list(kernel['incomplete'])
    for key in ('started', 'stopped', 'closed'):
        require(type(users[key]) is bool, 'Malformed collector state')
        if not users[key]: incomplete.append('collector-' + key + '-false')
    require(isinstance(users['errors'], list), 'Malformed collector errors')
    if users['errors']: incomplete.append('collector-error')
    calls, pauses = users['calls'], users['pauses']
    require(isinstance(calls, list) and len(calls) <= len(PLAN) and isinstance(pauses, list) and
            len(pauses) <= ROUNDS - 1, 'Too many scheduled calls/pauses')
    for ordinal, value in enumerate(pauses, 1):
        require(value['ordinal'] == ordinal, 'Pause records are not the declared sequence')
        if not validate_pause(value): incomplete.append('pause-' + str(ordinal) + '-incomplete')
    aligned = (len(calls) == len(PLAN) == kernel['calls'] and len(pauses) == ROUNDS - 1 and
               header['reason'] == 1 and header['limit'] == 1024 and header['time_ns'] == owner['namespace_id'])
    if not aligned: incomplete.append('scheduled-plan-or-session-mismatch')
    findings, regressions, previous, generation = [], [], {}, None
    if aligned:
        for ordinal, ((clock, route), user, call) in enumerate(zip(PLAN, calls, records[1:]), 1):
            integer(user['ordinal'], 1, len(PLAN)); integer(user['clock'], 1, 7)
            require(user['ordinal'] == ordinal and user['clock'] == clock and
                user['route'] == route and call['clock'] == clock and call['abi'] == 64 and call['syscall'] == 403 and
                all(call[k] == owner[k] for k in ('tid', 'tgid', 'namespace_id')), 'Scheduled call ownership/order/ABI differs')
            require(type(user['returned']) is bool, 'Malformed call return state')
            if not user['returned'] or not all(call[k] for k in ('accepted', 'valid', 'complete')):
                incomplete.append(f'call-{ordinal}-boundary-incomplete'); continue
            require(call['cpu'] in affinity and call['end_cpu'] in affinity, 'Read CPU outside captured affinity')
            t = call['tuple']; current = (t['source_changed'], t['mono']['source_id'], t['raw']['source_id'])
            if generation is None: generation = current
            if current != generation or current[1:] != (owner['source_id'],) * 2:
                incomplete.append(f'call-{ordinal}-source-changed')
            expected, value = call['sec'] * NS + call['nsec'], user['python_ns']
            if route == 'python':
                require(user.get('raw') is None, 'Python API cannot supply raw bytes'); signed(value)
                if call['error']: incomplete.append(f'call-{ordinal}-python-syscall-error')
                elif value != expected:
                    findings.append(dict(ordinal=ordinal, boundary='kernel-to-python', expected_ns=expected, observed_ns=value))
            else:
                integer(user['rc'], -1, 0); integer(user['errno'], 0, 4095)
                integer(user['converted'], 0, 1)
                require(type(user['size']) is int and user['size'] == 16, 'Wrong native raw ABI size')
                for key in ('sec', 'nsec', 'native_ns'): signed(user[key])
                sec, nsec, independent = decoded_ns(user)
                converted = int(independent is not None and independent <= (1 << 63) - 1)
                for boundary, wrong in (
                    ('raw-to-native-fields', (sec, nsec) != (user['sec'], user['nsec'])),
                    ('native-integer-conversion', user['converted'] != converted or
                        user['native_ns'] != (independent if converted else -1)),
                    ('python-integer-conversion', value != independent or (value is not None and type(value) is not int)),
                    ('syscall-return-status', (user['rc'], user['errno']) != ((-1, -call['error']) if call['error'] else (0, 0)))):
                    if wrong: findings.append(dict(ordinal=ordinal, boundary=boundary))
                if user['rc'] or call['error'] or independent is None:
                    incomplete.append(f'call-{ordinal}-unsuccessful-read')
                elif (sec, nsec) != (call['sec'], call['nsec']):
                    findings.append(dict(ordinal=ordinal, boundary='kernel-to-raw', expected_ns=expected, observed_ns=independent))
            if type(value) is int:
                prior = previous.get(clock)
                if prior and value < prior['ns']:
                    regressions.append(dict(ordinal=ordinal, previous=prior['ordinal'], clock=clock, delta_ns=value - prior['ns']))
                previous[clock] = dict(ordinal=ordinal, ns=value)
    return dict(schema=1, operation='clock-scheduled-guard-raw-replay', complete=aligned and not incomplete,
        aligned=aligned, incomplete=incomplete, calls=kernel['calls'], pauses=len(pauses),
        boundary_findings=findings, userspace_regressions=regressions, kernel=kernel,
        scope='Finite scheduled exact-call evidence only; no fault clearance or PM admission.')


def validate_contract(contract):
    validate_development_contract(contract)
    value = contract['scheduled']
    require(type(value.get('schema')) is int and value['schema'] == 1 and
            value.get('operation') == OPERATION and
            set(value['files']) == set(FILES), 'Missing explicit scheduled operation/inputs')
    validate_schedule(value['schedule'])
    for digest in (*value['files'].values(), value['pause_receipt_sha256']):
        require(isinstance(digest, str) and len(digest) == 64 and
                all(c in '0123456789abcdef' for c in digest), 'Malformed scheduled input digest')
    require(value.get('pm_admission') is False and value.get('clock_reliability_qualified') is False,
            'Scheduled capture must retain unresolved clock/PM gates')


def execute(directory, contract, observe, reader, public, pause, open_control):
    """Persist originals before replay/postflight, retaining every failed stage."""
    result = dict(schema=1, operation='scheduled-clock-deployment', complete=False,
        pm_admission=False, clock_reliability_qualified=False, errors=[])
    stage = 'preflight'
    try:
        validate_contract(contract)
        before = observe(); save(directory, 'before.json', before); validate_snapshot(before, contract)
        require(before.get('scheduled') == contract['scheduled'], 'Scheduled source/operation snapshot differs')
        stage = 'capture'; control = open_control()
        try: users, raw = collect(control, reader, public, pause, context(before))
        finally: control.close()
        save(directory, 'kernel.ndjson', raw, raw=True); save(directory, 'users.json', users)
        stage = 'postflight'; after = observe(); save(directory, 'after.json', after)
        validate_snapshot(after, contract)
        require(after.get('scheduled') == contract['scheduled'], 'Scheduled source/operation snapshot differs')
        require(before == after, 'Boot, owner, provenance or awake state changed')
        stage = 'replay'; analysis = join([loads(line) for line in raw.decode().splitlines()], users)
        save(directory, 'analysis.json', analysis)
        result.update(complete=analysis['complete'], state_unchanged=True,
            boundary_findings=len(analysis['boundary_findings']), kernel_regressions=len(analysis['kernel']['regressions']),
            userspace_regressions=len(analysis['userspace_regressions']))
        if not analysis['complete']:
            result['errors'].append(dict(stage='replay', type='IncompleteEvidence', message='Original records retained'))
    except BaseException as error:
        result['errors'].append(dict(stage=stage, type=type(error).__name__, message=str(error)))
    save(directory, 'result.json', result)
    return result
