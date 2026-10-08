"""Build test-only MUSB hooks and reject incomplete kernel test results."""
import difflib
import hashlib
import re
import tarfile

CASES = ('restart_busy_giveback_test', 'restart_empty_requeue_test',
         'restart_same_endpoint_test', 'restart_other_endpoint_test',
         'restart_follower_test', 'restart_nuke_test', 'restart_first_error_test')


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('MUSB test hook anchor changed: ' + before)
    return text.replace(before, after)


def test_patch(root, archive, lock, queue, apply_queue, scratch):
    prefix = 'drivers/usb/musb/'
    names = ('musb_core.c', 'musb_core.h', 'musb_gadget.c', 'musb_gadget.h',
             'musb_gadget_ep0.c', 'musb_regs.h', 'sunxi.c', 'Kconfig')
    version = 'linux-' + lock['linux']['tag'].removeprefix('v') + '/'
    with tarfile.open(archive, 'r:xz') as stream:
        for name in names:
            path = scratch / prefix / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(stream.extractfile(version + prefix + name).read())
    selected = [p for p in queue if p[0] in (
        '0011-musb-sunxi-context.patch', '0025-musb-system-sleep-pullup.patch',
        '0030-musb-gadget-callback-lifetime.patch', '0033-musb-sleep-session-retirement.patch',
        '0037-musb-resume-request-ownership.patch')]
    if len(selected) != 5:
        raise ValueError('Incomplete MUSB candidate queue')
    apply_queue(scratch, selected)
    core = (scratch / prefix / 'musb_core.c').read_text()
    gadget = (scratch / prefix / 'musb_gadget.c').read_text()
    kconfig = (scratch / prefix / 'Kconfig').read_text()
    changed_core = replace_once(core, 'static void musb_deassert_reset(struct work_struct *work)', '''
#ifdef CONFIG_MUSB_RESTART_KUNIT_TEST
int musb_restart_test_run(struct musb *musb);
int musb_restart_test_run(struct musb *musb)
{
	lockdep_assert_held(&musb->lock);
	return musb_run_resume_work(musb);
}
#endif

static void musb_deassert_reset(struct work_struct *work)''')
    changed_gadget = replace_once(gadget, '#include "musb_trace.h"', '''#include "musb_trace.h"
#ifdef CONFIG_MUSB_RESTART_KUNIT_TEST
static struct musb *musb_restart_test_controller;
static void (*musb_restart_test_hook)(struct musb *, struct musb_request *);
#endif''')
    changed_gadget = replace_once(changed_gadget,
        '\tu16 csr;\n\tvoid __iomem *epio = req->ep->hw_ep->regs;', '''	u16 csr;
	void __iomem *epio;

#ifdef CONFIG_MUSB_RESTART_KUNIT_TEST
	if (musb == musb_restart_test_controller && musb_restart_test_hook) {
		musb_restart_test_hook(musb, req);
		return;
	}
#endif
	epio = req->ep->hw_ep->regs;''')
    changed_gadget += '\n#ifdef CONFIG_MUSB_RESTART_KUNIT_TEST\n#include "musb-restart-kunit.c"\n#endif\n'
    changed_kconfig = kconfig + '''
config MUSB_RESTART_KUNIT_TEST
	bool "MUSB restart integration tests (isolated test kernel only)"
	depends on KUNIT=y && USB_MUSB_HDRC=y && USB_MUSB_GADGET && PM
'''
    replacements = {prefix + 'musb_core.c': (core, changed_core),
                    prefix + 'musb_gadget.c': (gadget, changed_gadget),
                    prefix + 'Kconfig': (kconfig, changed_kconfig),
                    prefix + 'musb-restart-kunit.c': ('', (root / 'kernel/tests/musb-restart-kunit.c').read_text())}
    patch = ''.join(''.join(difflib.unified_diff(
        before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        for name, (before, after) in replacements.items())
    return ('9999-musb-restart-test-only.patch', patch.encode())


def manifest_for(queue):
    return [dict(name=name, sha256=hashlib.sha256(data).hexdigest()) for name, data in queue]


def checked_cases(report, log):
    counts = dict(tests=len(CASES), passed=len(CASES), failed=0, crashed=0, skipped=0, errors=0)
    if re.search(r'WARNING:|BUG:|possible circular locking|suspicious RCU|'
                 r'sleeping function called|Kernel panic|not ok |'
                 r'rcu:.*detected .*stalls|INFO: task .*blocked for more than', log):
        raise ValueError('Kernel diagnostic or failing TAP entry')
    if (not isinstance(report, dict) or report.get('name') != 'KUnit Test Group' or
            report.get('arch') != 'um' or report.get('misc') != counts or
            report.get('test_cases') != [] or len(report.get('sub_groups', [])) != 1):
        raise ValueError('Expected exactly the requested UML KUnit group')
    suite = report['sub_groups'][0]
    if (suite.get('name') != 'musb-restart' or suite.get('arch') != 'um' or
            suite.get('misc') != counts or suite.get('sub_groups') != []):
        raise ValueError('Wrong or incomplete MUSB suite')
    cases = suite.get('test_cases', [])
    if (len(cases) != len(CASES) or {c.get('name') for c in cases} != set(CASES) or
            any(c.get('status') != 'PASS' for c in cases)):
        raise ValueError('Expected every MUSB case exactly once, all passing')
    if 'musb-restart' not in log or any(name not in log for name in CASES):
        raise ValueError('Kernel log missing requested output')
    return cases
