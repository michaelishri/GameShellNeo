"""Actual pinned wakeup sysfs frontend and opt-in candidate source controls."""
import re
import subprocess
import tarfile

FILE = 'drivers/base/power/sysfs.c'
PATCH = 'kernel/candidates/wakeup-sysfs-errors/0071-wakeup-sysfs-errors.patch'
ERROR_CASES = ('object_alloc_error', 'name_alloc_error', 'id_alloc_error', 'registration_error')
NATIVE_CASES = ('enable', 'disable', 'enabled_idempotent', 'disabled_idempotent',
                'invalid_request', *ERROR_CASES, 'concurrent_enable')
NATIVE_FAILURES = {
    'upstream': ERROR_CASES,
    'candidate': (),
    'errors-ignored': ERROR_CASES,
    'no-idempotent-snapshot': ('enabled_idempotent',),
    'no-concurrent-idempotency': ('concurrent_enable',),
}


def function(source):
    match = re.search(r'^static ssize_t wakeup_store\([^;{]*\)\n\{', source, re.M)
    if not match:
        raise ValueError('Missing actual wakeup_store definition')
    end = source.find('\n}', match.end())
    if end < 0:
        raise ValueError('Incomplete actual wakeup_store definition')
    return source[match.start():end + 3] + '\n'


def frontend(source):
    constants = []
    for name in ('enabled', 'disabled'):
        declaration = 'static const char _' + name + '[] = "' + name + '";\n'
        if source.count(declaration) != 1:
            raise ValueError('Changed wakeup policy spelling: ' + name)
        constants.append(declaration)
    return ''.join(constants) + function(source)


def changed(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Expected one wakeup frontend source anchor: ' + old)
    return source.replace(old, new)


def variants(before, after):
    old, good = frontend(before), frontend(after)
    if old == good:
        raise ValueError('Candidate did not change the actual wakeup frontend')
    without_snapshot = changed(good, '\tbool enabled;\n', '')
    without_snapshot = changed(without_snapshot,
        '\t\t/* Repeated requests must not depend on another allocation. */\n'
        '\t\tspin_lock_irq(&dev->power.lock);\n'
        '\t\tenabled = !!dev->power.wakeup;\n'
        '\t\tspin_unlock_irq(&dev->power.lock);\n'
        '\t\tif (enabled)\n\t\t\treturn n;\n\n', '')
    return {
        'upstream': old,
        'candidate': good,
        'errors-ignored': changed(good, '\treturn ret < 0 ? ret : n;\n',
                                 '\t(void)ret;\n\treturn n;\n'),
        'no-idempotent-snapshot': without_snapshot,
        'no-concurrent-idempotency': changed(good,
            '\t\tif (ret == -EEXIST)\n\t\t\tret = 0;\n', ''),
    }


def checked_native(name, result):
    """Reject compilation/crash/missing-case outcomes, even for expected failures."""
    expected = set(NATIVE_FAILURES[name])
    if result.returncode != int(bool(expected)) or result.stderr:
        raise ValueError('Inconclusive wakeup frontend execution: ' + name)
    rows = []
    for line in result.stdout.splitlines():
        match = re.fullmatch(r'(PASS|FAIL) (\w+) result=(-?\d+) expected=(-?\d+) '
                             r'policy=([01]) calls=(\d+)', line)
        if not match:
            raise ValueError('Unexpected native frontend observation: ' + line)
        status, case, actual, wanted, policy, calls = match.groups()
        rows.append(dict(name=case, status=status, result=int(actual), expected=int(wanted),
                         policy=int(policy), calls=int(calls)))
    if tuple(row['name'] for row in rows) != NATIVE_CASES:
        raise ValueError('Missing, duplicated or reordered frontend cases')
    if {row['name'] for row in rows if row['status'] == 'FAIL'} != expected:
        raise ValueError('Different frontend failure set: ' + name)
    for row in rows:
        want = {'enable': 8, 'disable': 9, 'enabled_idempotent': 8,
                'disabled_idempotent': 9, 'invalid_request': -22,
                'concurrent_enable': 8}.get(row['name'], -12)
        actual = want
        if row['name'] in ERROR_CASES:
            actual = 8 if row['name'] in expected else -12
        elif row['name'] == 'enabled_idempotent' and row['name'] in expected:
            actual = -12
        elif row['name'] == 'concurrent_enable' and row['name'] in expected:
            actual = -17
        policy = int(row['name'] in ('enable', 'enabled_idempotent', 'concurrent_enable'))
        calls = (0, 1) if row['name'] == 'enabled_idempotent' else (
                 (0,) if row['name'] == 'invalid_request' else (1,))
        if ((row['result'], row['expected'], row['policy']) != (actual, want, policy) or
                row['calls'] not in calls):
            raise ValueError('Changed frontend observation: ' + row['name'])
    return rows


def prepare(root, archive, lock, directory):
    """Apply relevant production inputs then 0071 without registering a profile."""
    target = directory / FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
    with tarfile.open(archive, 'r|xz') as stream:
        for member in stream:
            if member.name == prefix + FILE:
                target.write_bytes(stream.extractfile(member).read())
                break
        else:
            raise ValueError('Pinned wakeup sysfs source absent')
    selected = []
    for path in sorted((root / 'kernel/patches').glob('*.patch')):
        chunks = re.split(r'(?=^diff --git )', path.read_text(), flags=re.M)
        relevant = [chunk for chunk in chunks if chunk.startswith('diff --git a/' + FILE + ' ')]
        if relevant:
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], cwd=directory,
                           input=''.join(relevant), text=True, check=True)
            selected.append(path)
    before = target.read_text()
    patch = root / PATCH
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)],
                   cwd=directory, check=True)
    selected.append(patch)
    return before, target.read_text(), selected
