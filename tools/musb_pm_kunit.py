"""Real runtime-PM dispatch and drain checks of MUSB's terminal PM helper."""
from musb_irq_kunit import core_test_patch
from musb_restart_kunit import checked_cases as validate_cases

CASES = ('pm_active_retirement_test', 'pm_no_session_control_test',
         'pm_running_suspend_test', 'pm_running_resume_test', 'pm_failed_resume_test',
         'pm_future_requests_test', 'pm_reenable_test', 'pm_autosuspend_policy_test')
EXTRA_INPUTS = ('tools/musb_irq_checks.py', 'tools/musb_irq_kunit.py')
LIMITS = ('Production MUSB PM retirement helper under single-CPU UML/KASAN/lockdep, '
          'real runtime-PM dispatch, counters, disable and drain. Synthetic device '
          'callbacks model resource access. No physical MMIO, complete probe/remove, '
          'backend or pending-resume producer retirement, parent PM or failed-power qualification.')


def checked_cases(report, log):
    return validate_cases(report, log, suite_name='musb-pm', expected_cases=CASES)


def test_patch(root, archive, lock, queue, apply_queue, scratch):
    return core_test_patch(root, archive, lock, queue, apply_queue, scratch, suite='pm')
