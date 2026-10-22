"""Real IRQ and sleeping wake-source teardown for the explicit combined profile."""
import difflib

from musb_restart_kunit import checked_cases as validate_cases
from musb_terminal_wake_source import CORE, prepare

CASES = ('terminal_unowned_test', 'terminal_owned_wake_test', 'terminal_shared_peer_test',
         'terminal_failed_disarm_test', 'terminal_wakeup_reader_test',
         'terminal_running_handler_test', 'terminal_foreign_state_test',
         'terminal_unsupported_wake_test')
LIMITS = ('Complete MUSB core with actual terminal helper, real shared IRQ actions, '
          'IRQ-core wake-depth/failure accounting and device wakeup-source allocation/teardown '
          'under UML KASAN/lockdep. Held SRCU reader and threaded IRQ handler prove blocking '
          'boundaries. Synthetic controller and simulated IRQ chip wake callback; explicit '
          'fixture recovery occurs only after retained-debt assertions. No complete probe/remove, '
          'system suspend, MMIO/source masking, independent backend/DMA producers, SMP or hardware qualification.')


def checked_cases(report, log):
    return validate_cases(report, log, suite_name='musb-terminal-wake', expected_cases=CASES)


def test_patch(root, archive, lock, scratch):
    paths, _ = prepare(root, archive, lock, scratch)
    core = paths[CORE].read_text()
    kconfig_path = 'drivers/usb/musb/Kconfig'
    kconfig = paths[kconfig_path].read_text()
    filename = 'musb-terminal-wake-kunit.c'
    changed = core + '\n#ifdef CONFIG_MUSB_TERMINAL_WAKE_KUNIT_TEST\n#include "' + filename + '"\n#endif\n'
    config = kconfig + '''
config MUSB_TERMINAL_WAKE_KUNIT_TEST
	bool "MUSB terminal IRQ/wake ownership tests (isolated test kernel only)"
	depends on KUNIT=y && USB_MUSB_HDRC=y && USB_MUSB_GADGET && PM_SLEEP
	select IRQ_SIM
'''
    replacements = {CORE: (core, changed), kconfig_path: (kconfig, config),
                    'drivers/usb/musb/' + filename: ('', (root / 'kernel/tests' / filename).read_text())}
    patch = ''.join(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        for name, (before, after) in replacements.items())
    return '9999-musb-terminal-wake-test-only.patch', patch.encode()
