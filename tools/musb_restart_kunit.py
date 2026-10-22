"""Build test-only MUSB hooks and reject incomplete kernel test results."""
import difflib
import hashlib
import re
from musb_irq_checks import extract_source

EXTRA_INPUTS = ('tools/musb_irq_checks.py',)

CASES = ('restart_busy_giveback_test', 'restart_empty_requeue_test',
         'restart_same_endpoint_test', 'restart_other_endpoint_test',
         'restart_follower_test', 'restart_nuke_test', 'restart_first_error_test',
         'resume_cancel_test', 'resume_active_gate_test', 'resume_suspended_gate_test',
         'resume_immediate_running_test', 'resume_queued_running_test',
         'resume_deferred_handoff_test', 'resume_restart_running_test',
         'resume_handoff_running_test', 'resume_nested_test', 'resume_fresh_instance_test')

LIMITS = ('Actual full MUSB driver and USB giveback, real spinlocks and runtime-PM '
          'accounting under Linux UML with KASAN/lockdep. Only the hardware restart '
          'is intercepted. Controller runtime state is staged; a baseline PM reference '
          'prevents real hardware power transitions. Single virtual CPU with controlled kthread '
          'interleavings: no SMP, DMA, electrical USB, actual suspend or board qualification.')


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('MUSB test hook anchor changed: ' + before)
    return text.replace(before, after)


def test_patch(root, archive, lock, queue, apply_queue, scratch):
    prefix = 'drivers/usb/musb/'
    extract_source(archive, lock, queue, apply_queue, scratch)
    core = (scratch / prefix / 'musb_core.c').read_text()
    gadget = (scratch / prefix / 'musb_gadget.c').read_text()
    kconfig = (scratch / prefix / 'Kconfig').read_text()
    changed_core = replace_once(core, 'static void musb_deassert_reset(struct work_struct *work)', '''
#ifdef CONFIG_MUSB_RESTART_KUNIT_TEST
int musb_restart_test_run(struct musb *musb);
void musb_restart_test_stop(struct musb *musb);
void musb_restart_test_stop(struct musb *musb)
{
	musb_shutdown_resume_work(musb);
}
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


def checked_cases(report, log, *, suite_name='musb-restart', expected_cases=CASES):
    counts = dict(tests=len(expected_cases), passed=len(expected_cases), failed=0, crashed=0, skipped=0, errors=0)
    if re.search(r'WARNING:|BUG:|possible circular locking|suspicious RCU|'
                 r'sleeping function called|Kernel panic|not ok |'
                 r'rcu:.*detected .*stalls|INFO: task .*blocked for more than', log):
        raise ValueError('Kernel diagnostic or failing TAP entry')
    if (not isinstance(report, dict) or report.get('name') != 'KUnit Test Group' or
            report.get('arch') != 'um' or report.get('misc') != counts or
            report.get('test_cases') != [] or len(report.get('sub_groups', [])) != 1):
        raise ValueError('Expected exactly the requested UML KUnit group')
    suite = report['sub_groups'][0]
    if (suite.get('name') != suite_name or suite.get('arch') != 'um' or
            suite.get('misc') != counts or suite.get('sub_groups') != []):
        raise ValueError('Wrong or incomplete MUSB suite')
    cases = suite.get('test_cases', [])
    if (len(cases) != len(expected_cases) or {c.get('name') for c in cases} != set(expected_cases) or
            any(c.get('status') != 'PASS' for c in cases)):
        raise ValueError('Expected every MUSB case exactly once, all passing')
    if suite_name not in log or any(name not in log for name in expected_cases):
        raise ValueError('Kernel log missing requested output')
    return cases
