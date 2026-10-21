"""Clock capture admission and persistence shared by the host and device runner."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct

from clock_provenance import integer, loads

FILES = ('capture-clock-boundary.py', 'clock_deployment.py', 'clock_boundary.py',
         'clock_provenance.py', 'clock-boundary.so')
SOURCE_ID = 1  # Locked include/linux/clocksource_ids.h: CSID_ARM_ARCH_COUNTER.
VDSO = dict(mapping_found=1, handle_verified=1, time32_exported=0, time64_exported=0)
SERVICES = ('gameshellneo-battery.service', 'gameshellneo-usb.service', 'gameshellneo-ready.service',
            'ssh.service', 'systemd-networkd.service', 'wpa_supplicant@wlan0.service')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def bounded(path, maximum=2 * 1024 * 1024):
    with Path(path).open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('Evidence exceeds file limit: ' + str(path))
    return data


def build_id(notes):
    """Parse the running ARM kernel's little-endian /sys/kernel/notes bytes."""
    offset, found = 0, []
    while offset < len(notes):
        if len(notes) - offset < 12:
            raise ValueError('Truncated ELF note header')
        namesize, size, kind = struct.unpack_from('<III', notes, offset)
        offset += 12
        end_name = offset + ((namesize + 3) & ~3)
        end = end_name + ((size + 3) & ~3)
        if end > len(notes):
            raise ValueError('Truncated ELF note payload')
        name, value = notes[offset:offset + namesize], notes[end_name:end_name + size]
        if name == b'GNU\0' and kind == 3:
            if not 16 <= len(value) <= 64:
                raise ValueError('Unexpected kernel build-ID size')
            found.append(value.hex())
        offset = end
    if len(found) != 1:
        raise ValueError('Expected exactly one GNU kernel build ID')
    return found[0]


def configuration(raw):
    text = raw.decode()
    values = dict(re.findall(r'^(CONFIG_\w+)=(.*)$', text, re.M))
    for key in ('CONFIG_NEO_CLOCK_DIAG', 'CONFIG_DEBUG_FS', 'CONFIG_ARM_ARCH_TIMER',
                'CONFIG_IKCONFIG', 'CONFIG_IKCONFIG_PROC', 'CONFIG_ARM', 'CONFIG_AEABI'):
        if values.get(key) != 'y':
            raise ValueError('Required instrumented configuration is absent: ' + key)
    if values.get('CONFIG_NEO_CLOCK_DIAG_KUNIT_TEST', 'n') != 'n':
        raise ValueError('Test-only recorder must not run on the board')
    return values


def validate_contract(c):
    if type(c.get('schema')) is not int or c['schema'] != 1 or c.get('operation') != 'clock-boundary-contract':
        raise ValueError('Unexpected deployment contract')
    if (not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', c['boot_id']) or
            not re.fullmatch(r'[a-f0-9]{32,128}', c['build_id']) or len(c['build_id']) % 2 or
            not isinstance(c['kernel'], str) or not c['kernel'] or
            type(c['time_namespaces']) is not bool or type(c['source_id']) is not int or c['source_id'] != SOURCE_ID):
        raise ValueError('Invalid boot/kernel/namespace/source identity')
    hashes = [c['image_sha256'], c['config_sha256']]
    if set(c['files']) != set(FILES) or set(c['runtime']) != {'python', 'libc'}:
        raise ValueError('Incomplete deployment inputs')
    hashes.extend(c['files'].values())
    for key in ('python', 'libc'):
        item = c['runtime'][key]
        pattern = r'/usr/bin/python3\.13' if key == 'python' else r'/(?:usr/)?lib/arm-linux-gnueabihf/libc\.so\.6'
        if not re.fullmatch(pattern, item['path']):
            raise ValueError('Unexpected runtime path')
        integer(item['size'], 1, 32 * 1024 * 1024)
        hashes.append(item['sha256'])
    if any(not isinstance(h, str) or not re.fullmatch('[0-9a-f]{64}', h) for h in hashes):
        raise ValueError('Malformed input hash')


def validate_files(directory, contract):
    validate_contract(contract)
    for name, expected in contract['files'].items():
        p = Path(directory) / name
        if p.is_symlink() or digest(bounded(p, 32 * 1024 * 1024)) != expected:
            raise ValueError('Staged input changed: ' + name)


def validate_snapshot(s, c):
    validate_contract(c)
    for key in ('boot_id', 'kernel', 'build_id', 'image_sha256', 'config_sha256'):
        if s[key] != c[key]:
            raise ValueError('Running ' + key + ' differs from the deployment contract')
    if s['runtime'] != c['runtime'] or s['files'] != c['files']:
        raise ValueError('Running binary or staged sources changed')
    if (s['clocksource'] != 'arch_sys_counter' or s['vdso'] != VDSO or
            any(type(v) is not int for v in s['vdso'].values())):
        raise ValueError('Clocksource or same-process vDSO route is unqualified')
    if (s['platform'] != dict(machine='armv7l', byteorder='little', pointer_bytes=4, long_bytes=4,
                              isolated=1, no_site=1, uid=0) or s['loader_environment'] or
            s['preload_configured'] or s['tracing'] or s['taint'] != '0'):
        raise ValueError('Unexpected runtime execution context')
    if any(type(s['platform'][key]) is not int for key in ('pointer_bytes', 'long_bytes', 'isolated', 'no_site', 'uid')):
        raise ValueError('Malformed runtime platform values')
    for key in ('tid', 'tgid'):
        integer(s[key], 1, (1 << 31) - 1)
    if (s['tid'] != s['tgid'] or s['task_ids'] != [s['tid']] or
            s['nspid'] != [s['tid']] or s['nstgid'] != [s['tgid']]):
        raise ValueError('Capture needs one task in the initial PID namespace')
    integer(s['namespace_id'], 0, (1 << 32) - 1)
    if bool(s['namespace_id']) != c['time_namespaces']:
        raise ValueError('Time namespace identity differs from kernel configuration')
    affinity = s['affinity']
    if not affinity or affinity != sorted(set(affinity)):
        raise ValueError('Invalid CPU affinity')
    for cpu in affinity:
        integer(cpu, 0, 3)
    if (s['pm_test'].split()[0] != '[none]' or s['pm_units'] or s['usb'] != ['configured'] or
            s['usb_power'] != dict(present='1', online='1')):
        raise ValueError('Capture needs an awake, USB-powered device with no active PM test')
    if (not {'success', 'fail'} <= set(s['pm_stats']) or set(s['services']) != set(SERVICES) or
            any(v['ActiveState'] != 'active' or not re.fullmatch(r'\d+', v['NRestarts'])
                for v in s['services'].values())):
        raise ValueError('Device service/PM state is incomplete')


def context(snapshot):
    return {key: snapshot[key] for key in ('tid', 'tgid', 'namespace_id', 'affinity', 'clocksource')} | {
        'source_id': SOURCE_ID}


def save(directory, name, value, raw=False):
    data = value if raw else (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    # Unique per-run staging; no overwrite/relabel of an earlier capture.
    path = Path(directory) / name
    with path.open('xb') as out:
        if os.geteuid() == 0:
            owner = Path(directory).stat()
            # The root-only recorder exports into the owner's private stage,
            # so the host can retrieve results through its existing SSH user.
            os.fchown(out.fileno(), owner.st_uid, owner.st_gid)
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def execute(directory, contract, observe, reader, public, open_control):
    """Save originals before analysis, including when capture or postflight fails."""
    from clock_boundary import collect, join
    result = dict(schema=1, operation='clock-boundary-deployment', complete=False,
                  pm_admission=False, clock_reliability_qualified=False, errors=[])
    stage = 'preflight'
    try:
        before = observe()
        save(directory, 'before.json', before)
        validate_snapshot(before, contract)
        stage = 'capture'
        control = open_control()
        try:
            users, raw = collect(control, reader, public, context(before))
        finally:
            # KernelControl.close is idempotent. Cover failures before collect's
            # internal try/finally, including preallocation or argument errors.
            control.close()
        # Do not parse/rewrite the kernel bytes before storing the original.
        save(directory, 'kernel.ndjson', raw, raw=True)
        save(directory, 'users.json', users)
        stage = 'postflight'
        after = observe()
        save(directory, 'after.json', after)
        validate_snapshot(after, contract)
        if before != after:
            raise ValueError('Boot, owner, sources, PM, service or execution context changed')
        stage = 'replay'
        analysis = join([loads(line) for line in raw.decode().splitlines()], users)
        save(directory, 'analysis.json', analysis)
        result.update(complete=analysis['complete'], state_unchanged=True,
                      boundary_findings=len(analysis['boundary_findings']),
                      kernel_regressions=len(analysis['kernel']['regressions']),
                      userspace_regressions=len(analysis['userspace_regressions']))
        if not analysis['complete']:
            result['errors'].append(dict(stage='replay', type='IncompleteEvidence', message='Original records retained'))
    except BaseException as error:
        result['errors'].append(dict(stage=stage, type=type(error).__name__, message=str(error)))
    save(directory, 'result.json', result)
    return result
