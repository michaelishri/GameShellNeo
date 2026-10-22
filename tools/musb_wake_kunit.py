"""Test-only integration of the separate MUSB wake/startup source profile."""
import difflib
import re
import tarfile

from musb_restart_kunit import checked_cases as validate_cases

CASES = ('wake_initialization_test', 'wake_unsupported_irq_test',
         'wake_foreign_capability_test', 'wake_probe_disarm_error_test',
         'wake_policy_disabled_test', 'wake_policy_enabled_test',
         'wake_peer_first_test', 'wake_peer_last_test',
         'wake_arm_error_test', 'wake_disarm_error_test',
         'wake_runtime_resume_error_test')
CONTROL_ASSERTIONS = {
    'wake_unsupported_irq_test': ('musb_suspend(f->device) == -6',),
    'wake_policy_disabled_test': ('before.armed == 1', 'after.references == 1'),
    'wake_peer_first_test': ('state.references == 2',),
    'wake_peer_last_test': ('state.references == 2',),
    'wake_disarm_error_test': ('wake_snapshot(f).references == 1', 'f->arms == 3',
                               'Expected f->musb.irq_wake to be false, but is true'),
}
CONTROL_FAILURES = tuple(CONTROL_ASSERTIONS)
PATCHES = ('0011-musb-sunxi-context.patch', '0025-musb-system-sleep-pullup.patch',
           '0026-musb-wake-irq-policy.patch', '0029-musb-startup-runtime-pm.patch',
           '0030-musb-gadget-callback-lifetime.patch', '0033-musb-sleep-session-retirement.patch',
           '0037-musb-resume-request-ownership.patch')
LIMITS = ('Separate exact wake/startup profile under single-CPU UML/KASAN/lockdep. '
          'Actual MUSB wake initialization and system-PM callbacks, Linux shared IRQ '
          'actions, wake reference accounting and global suspend_device_irqs/resume_device_irqs '
          'traversal. A guest-local level irqchip, register bank and counting shared '
          'handlers model the hardware boundary; the physical MUSB ISR is not invoked. '
          'No full device-DPM walk, allocation/sysfs race, terminal destruction, retirement '
          'composition, physical IRQ/MMIO, deep sleep, SMP or board qualification.')


def checked_cases(report, log):
    return validate_cases(report, log, suite_name='musb-wake', expected_cases=CASES)


def checked_control(report, log):
    """A compiler/setup failure cannot pass the source mutation control."""
    counts = dict(tests=len(CASES), passed=len(CASES) - len(CONTROL_FAILURES),
                  failed=len(CONTROL_FAILURES), crashed=0, skipped=0, errors=0)
    if re.search(r'WARNING:|BUG:|possible circular locking|suspicious RCU|'
                 r'sleeping function called|Kernel panic|'
                 r'rcu:.*detected .*stalls|INFO: task .*blocked for more than', log):
        raise ValueError('Kernel diagnostic invalidates wake source control')
    if (not isinstance(report, dict) or report.get('name') != 'KUnit Test Group' or
            report.get('arch') != 'um' or report.get('misc') != counts or
            report.get('test_cases') != [] or len(report.get('sub_groups', [])) != 1):
        raise ValueError('Expected complete executed wake source control')
    suite = report['sub_groups'][0]
    cases = suite.get('test_cases', [])
    if (suite.get('name') != 'musb-wake' or suite.get('arch') != 'um' or
            suite.get('misc') != counts or suite.get('sub_groups') != [] or
            len(cases) != len(CASES) or {c.get('name') for c in cases} != set(CASES) or
            any(c.get('status') != ('FAIL' if c.get('name') in CONTROL_FAILURES else 'PASS')
                for c in cases)):
        raise ValueError('Wrong or incomplete wake source control failures')
    if any(name not in log for name in CASES):
        raise ValueError('Kernel log missing requested control output')
    blocks = {name: [] for name in CONTROL_ASSERTIONS}
    current = None
    for line in log.splitlines():
        failure = re.match(r'\s*#\s*(\w+_test): (?:ASSERTION|EXPECTATION) FAILED', line)
        if failure:
            current = failure[1]
        elif re.match(r'\s*(?:not )?ok\s+\d+', line):
            current = None
        if current in blocks:
            blocks[current].append(line)
    for name, required in CONTROL_ASSERTIONS.items():
        if any(text not in '\n'.join(blocks[name]) for text in required):
            raise ValueError('Missing source-justified control assertion: ' + name)
    return cases


def selected_patches(queue):
    selected = [patch for patch in queue if patch[0] in PATCHES]
    if tuple(name for name, _ in selected) != PATCHES:
        raise ValueError('Incomplete or reordered MUSB wake/startup source queue')
    # Retirement is an independent source profile, never an implicit addition.
    if any(re.search(r'^00(?:3[8-9]|4[0-5])-(?:musb|extcon|sunxi)-', name) for name, _ in queue):
        raise ValueError('Retirement source cannot qualify the separate wake/startup profile')
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
        raise ValueError('Incomplete pinned MUSB wake source extraction')
    apply_queue(scratch, selected)
    prefix = 'drivers/usb/musb/'
    core = (scratch / prefix / 'musb_core.c').read_text()
    kconfig = (scratch / prefix / 'Kconfig').read_text()
    changed = core
    if control is not None:
        if control != 'policy-ignored':
            raise ValueError('Unknown wake source control')
        start = core.index('static int musb_suspend(struct device *dev)\n')
        end = core.index('\nstatic int musb_resume(', start)
        suspend = core[start:end]
        anchor = '\tif (device_may_wakeup(dev)) {'
        if suspend.count(anchor) != 1:
            raise ValueError('Wake control source anchor changed')
        changed = core[:start] + suspend.replace(anchor, '\tif (true) {', 1) + core[end:]
    changed += '\n#ifdef CONFIG_MUSB_WAKE_KUNIT_TEST\n#include "musb-wake-kunit.c"\n#endif\n'
    config = kconfig + '''
config MUSB_WAKE_KUNIT_TEST
\tbool "MUSB wake IRQ tests (isolated test kernel only)"
\tdepends on KUNIT=y && USB_MUSB_HDRC=y && USB_MUSB_GADGET && PM_SLEEP
'''
    replacements = {prefix + 'musb_core.c': (core, changed),
                    prefix + 'Kconfig': (kconfig, config),
                    prefix + 'musb-wake-kunit.c': ('', (root / 'kernel/tests/musb-wake-kunit.c').read_text())}
    patch = ''.join(''.join(difflib.unified_diff(
        before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        for name, (before, after) in replacements.items())
    return ('9999-musb-wake-test-only.patch', patch.encode())
