"""Isolated real-IRQ tests of the production MUSB action-release helper."""
import difflib

from musb_restart_kunit import checked_cases as validate_cases

CASES = ('irq_unowned_test', 'irq_shared_release_test',
         'irq_running_handler_test', 'irq_request_again_test')
EXTRA_INPUTS = ('tools/musb_irq_checks.py',)
LIMITS = ('Full MUSB driver under single-CPU UML/KASAN/lockdep. Actual production '
          'IRQ release helper, Linux shared IRQ actions, simulated interrupt source '
          'and controlled threaded handler. No physical MUSB handler/MMIO, hardware '
          'source masking, wake disarm, complete probe/removal, SMP or board qualification.')


def checked_cases(report, log):
    return validate_cases(report, log, suite_name='musb-irq', expected_cases=CASES)


def test_patch(root, archive, lock, queue, apply_queue, scratch):
    return core_test_patch(root, archive, lock, queue, apply_queue, scratch,
                           suite='irq', extra_config='\tselect IRQ_SIM\n')


def core_test_patch(root, archive, lock, queue, apply_queue, scratch, *, suite, extra_config=''):
    # Append only test declarations; no production function is replaced.
    from musb_irq_checks import extract_source
    extract_source(archive, lock, queue, apply_queue, scratch)
    prefix = 'drivers/usb/musb/'
    core = (scratch / prefix / 'musb_core.c').read_text()
    kconfig = (scratch / prefix / 'Kconfig').read_text()
    symbol = 'MUSB_' + suite.upper() + '_KUNIT_TEST'
    filename = 'musb-' + suite + '-kunit.c'
    changed = core + f'\n#ifdef CONFIG_{symbol}\n#include "{filename}"\n#endif\n'
    config = (kconfig + f'\nconfig {symbol}\n'
              f'\tbool "MUSB {suite} lifetime tests (isolated test kernel only)"\n'
              '\tdepends on KUNIT=y && USB_MUSB_HDRC=y && USB_MUSB_GADGET\n' + extra_config)
    replacements = {prefix + 'musb_core.c': (core, changed),
                    prefix + 'Kconfig': (kconfig, config),
                    prefix + filename: ('', (root / 'kernel/tests' / filename).read_text())}
    patch = ''.join(''.join(difflib.unified_diff(
        before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        for name, (before, after) in replacements.items())
    return ('9999-musb-' + suite + '-test-only.patch', patch.encode())
