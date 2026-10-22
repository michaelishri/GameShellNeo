"""Real sysfs/SRCU qualification and exact compiling frontend-error control."""
from collections import Counter
import difflib
import re
import tarfile

from musb_restart_kunit import checked_cases as validate_cases
from wakeup_sysfs_source import FILE, PATCH, changed

CASES = ('sysfs_enable_test', 'sysfs_disable_test', 'sysfs_enabled_idempotent_test',
         'sysfs_disabled_idempotent_test', 'sysfs_invalid_request_test',
         'sysfs_object_alloc_error_test', 'sysfs_name_alloc_error_test',
         'sysfs_id_alloc_error_test', 'sysfs_registration_error_test',
         'sysfs_two_enables_test', 'sysfs_disable_enable_srcu_test',
         'sysfs_unregister_active_write_test')
CONTROL_CASES = CASES[5:9]
LIMITS = ('Actual wakeup frontend/allocation/IDA/registration/attachment, real private sysfs '
          'VFS/kernfs writes, SRCU source lifetime and generic device removal in disposable '
          'single-CPU UML with KASAN/lockdep. Unique dynamic fixture names and targeted '
          'test-only call boundaries; no production body replacement or held-spinlock gates. '
          'Incapable subvariant verifies absent real attribute then calls actual frontend '
          'through a test-only accessor. No driver-unbind/manual capability-change '
          'concurrency, MUSB IRQ/DPM, terminal composition, image or hardware qualification.')
TARGETS = (FILE, 'drivers/base/power/wakeup.c', 'kernel/power/Kconfig')


def checked_cases(report, log):
    return validate_cases(report, log, suite_name='wakeup-sysfs', expected_cases=CASES)


def checked_control(report, log):
    counts = dict(tests=12, passed=8, failed=4, crashed=0, skipped=0, errors=0)
    if re.search(r'WARNING:|BUG:|possible circular locking|suspicious RCU|'
                 r'sleeping function called|Kernel panic|rcu:.*detected .*stalls|'
                 r'INFO: task .*blocked for more than', log):
        raise ValueError('Kernel diagnostic invalidates wakeup sysfs control')
    if (not isinstance(report, dict) or report.get('name') != 'KUnit Test Group' or
            report.get('arch') != 'um' or report.get('misc') != counts or
            report.get('test_cases') != [] or len(report.get('sub_groups', [])) != 1):
        raise ValueError('Expected complete executed wakeup sysfs control')
    suite = report['sub_groups'][0]
    cases = suite.get('test_cases', [])
    if (suite.get('name') != 'wakeup-sysfs' or suite.get('arch') != 'um' or
            suite.get('misc') != counts or suite.get('sub_groups') != [] or
            len(cases) != len(CASES) or {case.get('name') for case in cases} != set(CASES) or
            any(case.get('status') != ('FAIL' if case.get('name') in CONTROL_CASES else 'PASS')
                for case in cases) or any(name not in log for name in CASES)):
        raise ValueError('Different or incomplete sysfs control outcomes')
    failures, active = [], None
    for line in log.splitlines():
        marker = re.match(r'\s*#\s*(\w+_test): (?:ASSERTION|EXPECTATION) FAILED', line)
        if marker:
            active = dict(case=marker[1], expression=None, lines=[])
            failures.append(active)
        elif re.match(r'\s*(?:not )?ok\s+\d+', line):
            active = None
        if active is not None:
            active['lines'].append(line)
            expected = re.match(r'\s*Expected (.*), but\s*$', line)
            if expected:
                active['expression'] = expected[1]
    wanted = Counter((name, 'result == -ENOMEM') for name in CONTROL_CASES)
    if Counter((failure['case'], failure['expression']) for failure in failures) != wanted:
        raise ValueError('Unexpected or missing sysfs control assertion')
    for failure in failures:
        block = '\n'.join(failure['lines'])
        if 'result == 8' not in block or '-ENOMEM == -12' not in block:
            raise ValueError('Missing actual write/error value in sysfs control')
    observations = re.findall(r'#\s*(\w+_test): fault-observation '
        r'result=(-?\d+) disabled=([01]) hits=(\d+) objects=(\d+) names=(\d+) ids=(\d+)', log)
    expected_observations = Counter((name, '8', '1', '1', '0', '0', '0') for name in CONTROL_CASES)
    if Counter(observations) != expected_observations:
        raise ValueError('Fault gate/readback/exact ownership observation differs')
    return cases


def test_patch(root, archive, lock, queue, apply_queue, scratch, *, control=None):
    """Append test-only boundaries; actual Linux production functions remain present."""
    if control not in (None, 'errors-ignored'):
        raise ValueError('Unknown wakeup sysfs source control')
    if [name for name, _ in queue].count(PATCH.rsplit('/', 1)[-1]) != 1:
        raise ValueError('Exactly one explicit 0071 frontend candidate is required')
    prefix = 'linux-' + lock['linux']['tag'].removeprefix('v') + '/'
    found = set()
    with tarfile.open(archive, 'r|xz') as stream:
        for entry in stream:
            name = entry.name.removeprefix(prefix)
            if entry.name.startswith(prefix) and name in TARGETS:
                path = scratch / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(stream.extractfile(entry).read())
                found.add(name)
                if found == set(TARGETS):
                    break
    if found != set(TARGETS):
        raise ValueError('Incomplete pinned PM/sysfs/Kconfig extraction')
    relevant = []
    for name, data in queue:
        text = data.decode()
        if name == PATCH.rsplit('/', 1)[-1]:
            relevant.append((name, data))
            continue
        chunks = re.split(r'(?=^diff --git )', text, flags=re.M)
        selected = [chunk for chunk in chunks if any(
            chunk.startswith('diff --git a/' + target + ' ') for target in TARGETS)]
        if selected:
            relevant.append((name, ''.join(selected).encode()))
    apply_queue(scratch, relevant)
    originals = {name: (scratch / name).read_text() for name in TARGETS}
    wakeup = originals['drivers/base/power/wakeup.c']
    wakeup = changed(wakeup, 'static DEFINE_IDA(wakeup_ida);\n',
                     'static DEFINE_IDA(wakeup_ida);\n\n#include "wakeup-sysfs-kunit.h"\n')
    substitutions = (
        ('\tws = kzalloc(sizeof(*ws), GFP_KERNEL);', '\tws = wakeup_sysfs_object_alloc(name);'),
        ('\tws_name = kstrdup_const(name, GFP_KERNEL);', '\tws_name = wakeup_sysfs_name_alloc(name);'),
        ('\tid = ida_alloc(&wakeup_ida, GFP_KERNEL);', '\tid = wakeup_sysfs_id_alloc(name);'),
        ('\tida_free(&wakeup_ida, ws->id);', '\twakeup_sysfs_id_free(ws);'),
        ('\t\t\tret = wakeup_source_sysfs_add(dev, ws);',
         '\t\t\tret = wakeup_sysfs_source_add(dev, ws);'),
        ('\tret = device_wakeup_attach(dev, ws);',
         '\twakeup_sysfs_before_attach(dev, ws);\n\tret = device_wakeup_attach(dev, ws);\n'
         '\twakeup_sysfs_after_attach(dev, ws, ret);'),
        ('\tsynchronize_srcu(&wakeup_srcu);', '\twakeup_sysfs_srcu_wait(ws);'),
    )
    for old, new in substitutions:
        wakeup = changed(wakeup, old, new)
    for old, new in (('\tkfree_const(ws->name);', '\twakeup_sysfs_name_free(ws->name);'),
                     ('\tkfree(ws);', '\twakeup_sysfs_object_free(ws);')):
        if wakeup.count(old) != 2:
            raise ValueError('Expected both exact allocation unwind/free boundaries: ' + old)
        wakeup = wakeup.replace(old, new)
    wakeup += '\n#ifdef CONFIG_NEO_WAKEUP_SYSFS_KUNIT_TEST\n#include "wakeup-sysfs-kunit.c"\n#endif\n'
    sysfs = originals[FILE]
    if control:
        sysfs = changed(sysfs, '\treturn ret < 0 ? ret : n;\n}\n\nstatic DEVICE_ATTR_RW(wakeup);',
                        '\t(void)ret;\n\treturn n;\n}\n\nstatic DEVICE_ATTR_RW(wakeup);')
    accessor = '''
#ifdef CONFIG_NEO_WAKEUP_SYSFS_KUNIT_TEST
ssize_t wakeup_sysfs_kunit_store(struct device *dev, const char *buf, size_t n);
ssize_t wakeup_sysfs_kunit_store(struct device *dev, const char *buf, size_t n)
{
\treturn wakeup_store(dev, NULL, buf, n);
}
#endif
'''
    sysfs = changed(sysfs, 'static DEVICE_ATTR_RW(wakeup);\n',
                     'static DEVICE_ATTR_RW(wakeup);\n' + accessor)
    kconfig = originals['kernel/power/Kconfig'] + '''
config NEO_WAKEUP_SYSFS_KUNIT_TEST
\tbool "Wakeup sysfs error and lifetime tests (isolated kernel only)"
\tdepends on KUNIT=y && PM_SLEEP && SYSFS
'''
    replacements = {'drivers/base/power/wakeup.c': (originals['drivers/base/power/wakeup.c'], wakeup),
                    FILE: (originals[FILE], sysfs),
                    'kernel/power/Kconfig': (originals['kernel/power/Kconfig'], kconfig)}
    for name in ('wakeup-sysfs-kunit.h', 'wakeup-sysfs-kunit.c'):
        replacements['drivers/base/power/' + name] = ('', (root / 'kernel/tests' / name).read_text())
    patch = ''.join(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        for name, (before, after) in replacements.items())
    return '9999-wakeup-sysfs-test-only.patch', patch.encode()
