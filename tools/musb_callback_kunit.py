"""Actual MUSB/UDC callback races in an isolated SMP ARM guest."""
import difflib
import re
import tarfile

from musb_restart_kunit import replace_once

CASES = tuple(f'{kind}_{context}' for kind in ('resume', 'suspend', 'disconnect', 'reset', 'setup')
              for context in ('irq', 'timer', 'process')) + (
                  'two_callbacks_irq', 'rebind_cycles', 'unstarted_unbinder')


def test_patch(root, archive, lock, queue, apply_queue, scratch):
    prefix = 'drivers/usb/musb/'
    version = 'linux-' + lock['linux']['tag'].removeprefix('v') + '/'
    with tarfile.open(archive, 'r:xz') as stream:
        for member in stream.getmembers():
            if member.isfile() and member.name.startswith(version + prefix):
                relative = member.name.removeprefix(version)
                path = scratch / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(stream.extractfile(member).read())
    # Match the full production MUSB queue, without unrelated source subtrees.
    selected = [(name, patch) for name, patch in queue if b'drivers/usb/musb/' in patch]
    apply_queue(scratch, selected)
    originals = {name: (scratch / prefix / name).read_text()
                 for name in ('musb_gadget.c', 'musb_gadget_ep0.c', 'Kconfig')}
    changed = dict(originals)
    changed['musb_gadget.c'] += '\n#ifdef CONFIG_MUSB_CALLBACK_KUNIT_TEST\n#include "musb-callback-kunit.c"\n#endif\n'
    changed['musb_gadget_ep0.c'] = replace_once(originals['musb_gadget_ep0.c'],
        '/*\n * Handle peripheral ep0 interrupt', '''#ifdef CONFIG_MUSB_CALLBACK_KUNIT_TEST
int musb_callback_test_setup(struct musb *musb);
int musb_callback_test_setup(struct musb *musb)
{
	const struct usb_ctrlrequest request = { .bRequestType = USB_TYPE_VENDOR };
	return forward_to_driver(musb, &request);
}
#endif

/*
 * Handle peripheral ep0 interrupt''')
    changed['Kconfig'] += '''
config MUSB_CALLBACK_KUNIT_TEST
	bool "MUSB callback SMP tests (isolated test kernel only)"
	depends on KUNIT=y && SMP && USB_MUSB_HDRC=y && USB_MUSB_GADGET && PM
'''
    originals['musb-callback-kunit.c'] = ''
    changed['musb-callback-kunit.c'] = (root / 'kernel/tests/musb-callback-kunit.c').read_text()
    patch = ''.join(''.join(difflib.unified_diff(before.splitlines(True), changed[name].splitlines(True),
                    fromfile='a/' + prefix + name if before else '/dev/null', tofile='b/' + prefix + name))
                    for name, before in originals.items())
    return '9999-musb-callback-test-only.patch', patch.encode()


def checked_cases(report, log):
    counts = dict(tests=len(CASES), passed=len(CASES), failed=0, crashed=0, skipped=0, errors=0)
    if re.search(r'WARNING:|BUG:|possible circular locking|suspicious RCU|'
                 r'sleeping function called|Kernel panic|not ok |'
                 r'rcu:.*detected .*stalls|INFO: task .*blocked for more than', log):
        raise ValueError('Kernel diagnostic or failing TAP entry')
    if (report.get('name') != 'KUnit Test Group' or report.get('arch') != 'arm' or
            report.get('misc') != counts or report.get('test_cases') != [] or
            len(report.get('sub_groups', [])) != 1):
        raise ValueError('Expected only the ARM SMP callback suite')
    suite = report['sub_groups'][0]
    if (suite.get('name') != 'musb-callback-smp' or suite.get('arch') != 'arm' or
            suite.get('misc') != counts or suite.get('sub_groups') != []):
        raise ValueError('Wrong or incomplete callback suite')
    cases = suite.get('test_cases', [])
    if (len(cases) != len(CASES) or {c.get('name') for c in cases} != set(CASES) or
            any(c.get('status') != 'PASS' for c in cases)):
        raise ValueError('Every callback/context case must pass exactly once')
    passed = re.findall(r'\bok [0-9]+ (' + '|'.join(CASES) + r')\s*$', log, re.M)
    if 'musb-callback-smp' not in log or len(passed) != len(CASES) or set(passed) != set(CASES):
        raise ValueError('Raw serial TAP does not contain each passing callback case')
    markers = re.findall(r'SMP callback=(\d+) unbind=(\d+) observer=(\d+) online=(\d+) '
                         r'kind=(\d+) context=(\d+) drained=(\d+) completions=(\d+)', log)
    expected = {(1, 2, 0, 4, kind, context, 0, 1) for kind in range(5) for context in range(3)}
    expected.add((1, 2, 0, 4, 0, 3, 0, 1))
    if len(markers) != len(expected) or {tuple(map(int, m)) for m in markers} != expected:
        raise ValueError('Missing distinct-CPU, context or completed-drain evidence')
    for marker in ('Second callback CPU=3 remaining after first=1',
                   'Rebind cycles=4 admitted callbacks=20',
                   'Unstarted actor: cleanup unregister=0'):
        if log.count(marker) != 1:
            raise ValueError('Missing or duplicate lifecycle evidence: ' + marker)
    return cases
