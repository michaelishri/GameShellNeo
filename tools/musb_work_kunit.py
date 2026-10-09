"""Real workqueue, timer and PM accounting tests of terminal MUSB core cleanup."""
from musb_irq_kunit import core_test_patch
from musb_restart_kunit import checked_cases as validate_cases

CASES = ('work_pending_test', 'work_irq_running_test', 'work_resume_running_test',
         'work_reset_running_test', 'work_session_accounting_test', 'work_fresh_instance_test')
EXTRA_INPUTS = ('tools/musb_irq_checks.py', 'tools/musb_irq_kunit.py')
LIMITS = ('Full MUSB driver under single-CPU UML/KASAN/lockdep. Production terminal '
          'work helper, real delayed-work/timer shutdown and runtime-PM usage accounting. '
          'Controlled callbacks replace hardware work. No running-timer/SMP race, physical '
          'MMIO, complete probe/removal, backend producer or runtime-PM retirement qualification.')


def checked_cases(report, log):
    return validate_cases(report, log, suite_name='musb-work', expected_cases=CASES)


def test_patch(root, archive, lock, queue, apply_queue, scratch):
    return core_test_patch(root, archive, lock, queue, apply_queue, scratch, suite='work')
