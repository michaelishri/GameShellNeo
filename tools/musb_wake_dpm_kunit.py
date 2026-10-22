"""Append-only qualification of MUSB wake ownership through Linux device PM."""
from collections import Counter
import difflib
import re
import tarfile

from musb_restart_kunit import checked_cases as validate_cases

CASES = ('dpm_policy_disabled_test', 'dpm_policy_enabled_test', 'dpm_shared_peer_test',
         'dpm_prepare_error_test', 'dpm_arm_error_test', 'dpm_runtime_resume_error_test',
         'dpm_late_error_test', 'dpm_noirq_error_test', 'dpm_resume_disarm_error_test')
CONTROL_CASE = 'dpm_policy_enabled_test'
# Omit only this case's type registration: Linux still walks the device, while
# every owned PM callback is absent. Exact assertions make a different failure
# or an incomplete/merely compiled control inconclusive.
CONTROL_ASSERTIONS = {
    'f->calls.prepare == 1U': ('f->calls.prepare == 0',),
    'f->prepare_usage == walk->before.usage + 1': ('f->prepare_usage == 0',),
    'f->calls.suspend == 1U': ('f->calls.suspend == 0',),
    'walk->after_start.usage == walk->before.usage + 2': ('walk->after_start.usage == 2',),
    'f->calls.resume == 1U': ('f->calls.resume == 0',),
    'f->calls.complete == 1U': ('f->calls.complete == 0',),
    'f->complete_usage == walk->before.usage + 1': ('f->complete_usage == 0',),
    'f->calls.late == 1U': ('f->calls.late == 0',),
    'f->calls.noirq == 1U': ('f->calls.noirq == 0',),
    'f->calls.resume_noirq == 1U': ('f->calls.resume_noirq == 0',),
    'f->calls.early == 1U': ('f->calls.early == 0',),
    'walk->after_end.armed == wake': ('walk->after_end.armed == 0', 'wake == 1'),
    'walk->after_end.disabled == !wake': ('walk->after_end.disabled == 1', '!wake == 0'),
    'walk->after_end.references == wake ? 1U : 0U': ('walk->after_end.references == 0',),
}
PATCHES = ('0011-musb-sunxi-context.patch', '0025-musb-system-sleep-pullup.patch',
           '0026-musb-wake-irq-policy.patch', '0029-musb-startup-runtime-pm.patch',
           '0030-musb-gadget-callback-lifetime.patch', '0033-musb-sleep-session-retirement.patch',
           '0037-musb-resume-request-ownership.patch')
LIMITS = ('Separate exact wake/startup0026/0029 profile, actual Linux device-DPM '
          'prepare/suspend/late/noirq/resume/complete traversal and global IRQ restoration '
          'in single-CPU UML with KASAN/lockdep. Unchanged MUSB suspend/resume callbacks; '
          'synthetic register bank/level irqchip/counting shared handlers and staged runtime '
          'failure boundary. GFP observations cover the invoked DPM helpers only. '
          'No physical MUSB ISR, freezer/platform/CPU sleep, allocation/sysfs concurrency, '
          'terminal destruction/retirement composition, SMP, image or board qualification.')


def checked_cases(report, log):
    return validate_cases(report, log, suite_name='musb-wake-dpm', expected_cases=CASES)


def checked_control(report, log):
    counts = dict(tests=len(CASES), passed=len(CASES) - 1, failed=1,
                  crashed=0, skipped=0, errors=0)
    if re.search(r'WARNING:|BUG:|possible circular locking|suspicious RCU|'
                 r'sleeping function called|Kernel panic|'
                 r'rcu:.*detected .*stalls|INFO: task .*blocked for more than', log):
        raise ValueError('Kernel diagnostic invalidates missing-callback control')
    if (not isinstance(report, dict) or report.get('name') != 'KUnit Test Group' or
            report.get('arch') != 'um' or report.get('misc') != counts or
            report.get('test_cases') != [] or len(report.get('sub_groups', [])) != 1):
        raise ValueError('Expected complete executed DPM callback control')
    suite = report['sub_groups'][0]
    cases = suite.get('test_cases', [])
    if (suite.get('name') != 'musb-wake-dpm' or suite.get('arch') != 'um' or
            suite.get('misc') != counts or suite.get('sub_groups') != [] or
            len(cases) != len(CASES) or {c.get('name') for c in cases} != set(CASES) or
            any(c.get('status') != ('FAIL' if c.get('name') == CONTROL_CASE else 'PASS')
                for c in cases) or any(name not in log for name in CASES)):
        raise ValueError('Wrong or incomplete missing-callback outcomes')
    failures = []
    active = None
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
    if (Counter(failure['expression'] for failure in failures) != Counter(CONTROL_ASSERTIONS.keys()) or
            any(failure['case'] != CONTROL_CASE for failure in failures)):
        raise ValueError('Unexpected or missing control assertion')
    for failure in failures:
        block = '\n'.join(failure['lines'])
        if any(value not in block for value in CONTROL_ASSERTIONS[failure['expression']]):
            raise ValueError('Missing observed callback/IRQ value')
    return cases


def selected_patches(queue):
    selected = [patch for patch in queue if patch[0] in PATCHES]
    if tuple(name for name, _ in selected) != PATCHES:
        raise ValueError('Incomplete or reordered wake/startup inputs')
    if any(re.search(r'^00(?:3[8-9]|4[0-5]|6[0-2])-(?:musb|extcon|sunxi|sun4i|mpfs)-', name)
           for name, _ in queue):
        raise ValueError('Retirement cannot qualify the separate wake/startup profile')
    return selected


def test_patch(root, archive, lock, queue, apply_queue, scratch, *, control=None):
    selected = selected_patches(queue)
    targets = {'drivers/usb/musb/Kconfig'}
    for _, data in selected:
        targets.update(re.findall(r'^\+\+\+ b/([^\t\n]+)', data.decode(), re.M))
    prefix = 'linux-' + lock['linux']['tag'].removeprefix('v') + '/'
    found = set()
    with tarfile.open(archive, 'r|xz') as stream:
        for entry in stream:
            name = entry.name.removeprefix(prefix)
            if entry.name.startswith(prefix) and name in targets:
                path = scratch / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(stream.extractfile(entry).read())
                found.add(name)
                if found == targets:
                    break
    if found != targets:
        raise ValueError('Incomplete pinned MUSB extraction')
    apply_queue(scratch, selected)
    prefix = 'drivers/usb/musb/'
    core = (scratch / prefix / 'musb_core.c').read_text()
    kconfig = (scratch / prefix / 'Kconfig').read_text()
    fixture = (root / 'kernel/tests/musb-wake-dpm-kunit.c').read_text()
    if control is not None:
        if control != 'callbacks-unregistered':
            raise ValueError('Unknown DPM callback control')
        anchor = '\tf->device.type = &wake_dpm_device_type;'
        if fixture.count(anchor) != 1:
            raise ValueError('DPM registration control anchor changed')
        fixture = fixture.replace(anchor,
            '\tif (strcmp(test->name, "' + CONTROL_CASE + '"))\n\t' + anchor, 1)
    changed = core + '\n#ifdef CONFIG_MUSB_WAKE_DPM_KUNIT_TEST\n#include "musb-wake-dpm-kunit.c"\n#endif\n'
    config = kconfig + '''
config MUSB_WAKE_DPM_KUNIT_TEST
\tbool "MUSB device-PM wake tests (isolated test kernel only)"
\tdepends on KUNIT=y && USB_MUSB_HDRC=y && USB_MUSB_GADGET && PM_SLEEP
'''
    replacements = {prefix + 'musb_core.c': (core, changed),
                    prefix + 'Kconfig': (kconfig, config),
                    prefix + 'musb-wake-dpm-kunit.c': ('', fixture)}
    patch = ''.join(''.join(difflib.unified_diff(
        before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        for name, (before, after) in replacements.items())
    return ('9999-musb-wake-dpm-test-only.patch', patch.encode())
