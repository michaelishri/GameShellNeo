"""Bounded, sequence-checked printk evidence; no PM entry or journal mutation.

Live snapshots never fall back to journalctl. A protected checkpoint preserves
the initial boot prefix and subsequent records; a ring overrun, storage failure
or changed source stops admission. No background reader or automatic reset.
"""
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

STORE = Path('/var/lib/gameshellneo/kernel-evidence')
KMSG = '/dev/kmsg'
BOOT = Path('/proc/sys/kernel/random/boot_id')
OWNER_UID = 0
MAX_BYTES = 4 * 1024 * 1024
MAX_RECORD = 64 * 1024
MAX_RECORDS = 65536
READ_SECONDS = 5
KEY = 'kernel_evidence'


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def loaded_source(namespace):
    # Standalone helpers have a file; stdin bundles supply its exact source hash.
    value = namespace.get('__source_sha256__')
    if value is None and '__file__' in namespace:
        value = hashlib.sha256(Path(namespace['__file__']).read_bytes()).hexdigest()
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Missing kernel-evidence source identity')
    return value


def source_hash():
    return loaded_source(globals())


def context(snapshot):
    return dict(boot_id=snapshot['boot_id'], kernel=snapshot['kernel'],
                image_sha256=digest(snapshot['image']),
                firmware_sha256=snapshot['firmware_sha256'],
                nvram_sha256=snapshot['nvram_sha256'], collector_sha256=source_hash(),
                producer_sha256=snapshot['pm_source_sha256'])


def parse(raw):
    if not isinstance(raw, str) or not 0 < len(raw) <= MAX_RECORD or not raw.endswith('\n'):
        raise ValueError('Incomplete or oversized printk record')
    if any(ord(c) > 126 or (ord(c) < 32 and c != '\n') for c in raw):
        raise ValueError('Unexpected printk encoding')
    header, separator, body = raw.partition(';')
    fields = header.split(',')
    if (not separator or len(fields) < 4 or
            any(not re.fullmatch('[0-9]{1,20}', v) for v in fields[:3])):
        raise ValueError('Malformed printk header')
    priority, sequence, timestamp = map(int, fields[:3])
    if priority > 2047 or sequence >= 2**64 or timestamp >= 2**64:
        raise ValueError('Printk numeric field out of range')
    lines = body.splitlines()
    if not lines or any(not line.startswith(' ') for line in lines[1:]):
        raise ValueError('Malformed printk context')
    # Do not silently join possibly interleaved fragments and miss a fault.
    if priority < 8 and fields[3] != '-':
        raise ValueError('Unsupported fragmented kernel message')
    return sequence, priority, timestamp, lines[0]


def text(records):
    output = []
    for raw in records:
        _, priority, timestamp, message = parse(raw)
        # Userspace cannot inject LOG_KERN records through /dev/kmsg. Account
        # for every sequence, but never use userspace text as kernel identity.
        if priority < 8:
            output.append(f'[{timestamp // 1000000:5d}.{timestamp % 1000000:06d}] {message}\n')
    return ''.join(output)


def validate(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'context', 'anchor', 'records', 'sha256'} or
            value['schema'] != 1 or type(value['schema']) is not int or
            len(encoded(value)) > MAX_BYTES):
        raise ValueError('Invalid or oversized kernel evidence')
    ctx, anchor, records = value['context'], value['anchor'], value['records']
    if (not isinstance(ctx, dict) or set(ctx) != {'boot_id', 'kernel', 'image_sha256',
            'firmware_sha256', 'nvram_sha256', 'collector_sha256', 'producer_sha256'} or
            not isinstance(ctx['boot_id'], str) or
            not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', ctx['boot_id']) or
            not isinstance(ctx['kernel'], str) or not 1 <= len(ctx['kernel']) <= 128 or
            any(not isinstance(ctx[k], str) or not re.fullmatch('[0-9a-f]{64}', ctx[k])
                for k in ctx if k.endswith('_sha256'))):
        raise ValueError('Invalid kernel evidence identity')
    if (not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS or
            not isinstance(anchor, dict) or set(anchor) != {'count', 'sha256'} or
            type(anchor['count']) is not int or not 1 <= anchor['count'] <= len(records)):
        raise ValueError('Invalid kernel evidence anchor')
    for sequence, raw in enumerate(records):
        if parse(raw)[0] != sequence:
            raise ValueError('Kernel evidence sequence gap or missing boot prefix')
    if (anchor['sha256'] != digest(records[:anchor['count']]) or
            value['sha256'] != digest({k: v for k, v in value.items() if k != 'sha256'})):
        raise ValueError('Kernel evidence digest mismatch')
    if 'brcmf_c_preinit_dcmds: Firmware: ' not in text(records[:anchor['count']]):
        raise ValueError('Boot anchor lacks kernel firmware identity')
    return text(records)


def validate_snapshot(snapshot):
    """Legacy records remain reviewable; a live snapshot always has KEY."""
    if KEY not in snapshot:
        return
    value = snapshot[KEY]
    rendered = validate(value)
    if value['context'] != context(snapshot) or snapshot['journal'] != rendered:
        raise ValueError('Kernel evidence source, snapshot identity or rendered text differs')


def delta(before, after):
    if (KEY in before) != (KEY in after):
        raise ValueError('Legacy and sequence-checked evidence cannot be mixed')
    if KEY in before:
        for snapshot in (before, after):
            validate_snapshot(snapshot)
        a, b = before[KEY], after[KEY]
        if (a['context'] != b['context'] or a['anchor'] != b['anchor'] or
                b['records'][:len(a['records'])] != a['records']):
            raise ValueError('Kernel evidence lineage changed or records lost')
    if not after['journal'].startswith(before['journal']):
        raise ValueError('Kernel evidence lost or rotated during stage')
    return after['journal'][len(before['journal']):]


def extend(previous, ctx, incoming):
    """Reconcile exact overlap before appending; never repair a sequence gap."""
    if previous is not None:
        validate(previous)
        if previous['context'] != ctx:
            raise ValueError('Kernel checkpoint source/image changed within this boot')
    records = list(previous['records']) if previous else []
    prior_sequence = None
    total = 0
    count = 0
    for raw in incoming:
        count += 1
        total += len(raw)
        if total > MAX_BYTES or count > MAX_RECORDS:
            raise ValueError('Printk read exceeds bounded capture')
        sequence = parse(raw)[0]
        if prior_sequence is not None and sequence != prior_sequence + 1:
            raise ValueError('Printk sequence gap, reordering or duplicate')
        prior_sequence = sequence
        if sequence < len(records):
            if records[sequence] != raw:
                raise ValueError('Printk overlap differs from protected checkpoint')
        elif sequence == len(records):
            records.append(raw)
        else:
            raise ValueError('Printk records lost before collection; fresh boot required')
    if prior_sequence is None or prior_sequence < len(records) - 1:
        raise ValueError('Empty or regressed printk stream')
    anchor = previous['anchor'] if previous else dict(count=len(records), sha256=digest(records))
    result = dict(schema=1, context=ctx, anchor=anchor, records=records)
    result['sha256'] = digest(result)
    validate(result)
    return result


def read_records():
    fd = os.open(KMSG, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        if not stat.S_ISCHR(os.fstat(fd).st_mode):
            raise ValueError('Expected printk character device')
        deadline = time.monotonic() + READ_SECONDS
        while True:
            if time.monotonic() >= deadline:
                raise ValueError('Printk capture deadline exceeded')
            try:
                raw = os.read(fd, MAX_RECORD)
            except BlockingIOError as error:
                if error.errno != errno.EAGAIN:
                    raise
                return
            # EPIPE (overrun), EINVAL (short read buffer) and other errors are
            # fatal. Never seek/retry after them or clear the ring.
            if not raw:
                raise ValueError('Unexpected printk end of stream')
            try:
                yield raw.decode('ascii')
            except UnicodeDecodeError:
                raise ValueError('Unexpected printk byte encoding') from None
    finally:
        os.close(fd)


def secure(fd, directory=False):
    info = os.fstat(fd)
    if (info.st_uid != OWNER_UID or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600) or
            not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) or
            (not directory and info.st_nlink != 1)):
        raise ValueError('Kernel evidence storage has unsafe ownership/type/permissions')


def read_checkpoint(directory):
    try:
        fd = os.open('checkpoint.json', os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=directory)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as stream:
        secure(stream.fileno())
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Oversized kernel checkpoint')
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError('Unreadable kernel checkpoint; preserve evidence') from None
    validate(value)
    return value


def commit(directory, value):
    raw = encoded(value)
    if len(raw) > MAX_BYTES:
        raise ValueError('Kernel checkpoint capacity exceeded')
    # Exclusive fixed staging file leaves a visible interruption marker. No
    # silent deletion/retry if an earlier writer failed before publication.
    fd = os.open('checkpoint.new', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=directory)
    with os.fdopen(fd, 'wb') as stream:
        secure(stream.fileno())
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.rename('checkpoint.new', 'checkpoint.json', src_dir_fd=directory, dst_dir_fd=directory)
    os.fsync(directory)


def capture(snapshot):
    """Update one protected checkpoint. Bounded old-boot replacement, no PM."""
    if os.geteuid() != OWNER_UID:
        raise PermissionError('Root is required for kernel evidence')
    parent = STORE.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != OWNER_UID or parent.st_mode & 0o022):
        raise ValueError('Unsafe kernel evidence parent directory')
    STORE.mkdir(mode=0o700, exist_ok=True)
    directory = os.open(STORE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        secure(directory, directory=True)
        guard = os.open('lock', os.O_RDWR | os.O_NONBLOCK | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                        0o600, dir_fd=directory)
        try:
            secure(guard)
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if os.path.lexists(STORE / 'checkpoint.new'):
                raise ValueError('Interrupted kernel checkpoint; preserve evidence before recovery')
            ctx = context(snapshot)
            if BOOT.read_text().strip() != ctx['boot_id']:
                raise ValueError('Boot changed before kernel collection')
            previous = read_checkpoint(directory)
            # Never carry records into another boot. Only a complete fresh
            # sequence starting at zero can replace the one old checkpoint.
            same_boot = previous is not None and previous['context']['boot_id'] == ctx['boot_id']
            records = read_records()
            try:
                value = extend(previous if same_boot else None, ctx, records)
            finally:
                records.close()
            if BOOT.read_text().strip() != ctx['boot_id']:
                raise ValueError('Boot changed during kernel collection')
            if value != previous:
                commit(directory, value)
            return value
        finally:
            os.close(guard)
    finally:
        os.close(directory)
