"""Actual MUSB callback and UDC unbind regression orchestration."""
import os
import re
import subprocess

from kernel_checks import ROOT, run, sha256


def callback_checks(work, source, udc_source, wait_source, builder, function):
    gadget = (source / 'musb_gadget.c').read_text()
    ep0 = (source / 'musb_gadget_ep0.c').read_text()
    # Keep the registration/init and completion contracts tied to real source.
    setup = function(gadget, 'musb_gadget_setup')
    assert setup.index('init_waitqueue_head') < setup.index('usb_add_gadget_udc')
    assert 'musb->gadget_callback_count = 0;' in setup
    assert 'musb->gadget_async_callbacks = false;' in setup
    assert '.udc_async_callbacks\t= musb_gadget_async_callbacks,' in gadget
    functions = ''
    for name in ('___wait_is_interruptible', '___wait_event', '__wait_event_lock_irq', 'wait_event_lock_irq'):
        match = re.search(r'^#define ' + name + r'\(', wait_source, re.M)
        if not match:
            raise ValueError('Missing wait macro: ' + name)
        lines = wait_source[match.start():].splitlines(True)
        for line in lines:
            functions += line
            if not line.rstrip().endswith('\\'):
                break
    functions += function(udc_source, 'usb_gadget_udc_reset')
    functions += ''.join(function(gadget, name) for name in (
        'musb_gadget_get_driver', 'musb_gadget_put_driver', 'musb_gadget_async_callbacks',
        'musb_g_resume', 'musb_g_suspend', 'musb_g_disconnect', 'musb_g_reset', 'musb_g_giveback'))
    functions += function(ep0, 'forward_to_driver')
    functions += ''.join(function(udc_source, name) for name in (
        'usb_gadget_disable_async_callbacks', 'usb_gadget_enable_async_callbacks',
        'usb_gadget_udc_start_locked', 'usb_gadget_udc_stop_locked',
        'gadget_bind_driver', 'gadget_unbind_driver'))
    variants = {
        'candidate': functions,
        'ignores_admission': functions.replace('!musb->gadget_async_callbacks || ', ''),
        'missing_acquisition': functions.replace(
            '\tmusb->gadget_callback_count++;', ''),
        'missing_drain': functions.replace(
            '\twait_event_lock_irq(musb->gadget_callback_wait,\n\t\t\t\t    !musb->gadget_callback_count, musb->lock);',
            '\t(void)0; /* lost drain */'),
        'missing_wakeup': functions.replace(
            '\t\twake_up_all(&musb->gadget_callback_wait);', '\t\t(void)0; /* lost wake */'),
        'missing_setup_release': functions.replace(
            '\tmusb_gadget_put_driver(musb);\n\treturn retval;', '\treturn retval;'),
        'early_callback_release': functions.replace(
            '\t\t\t\tspin_unlock(&musb->lock);\n\t\t\t\tdriver->resume',
            '\t\t\t\tmusb_gadget_put_driver(musb);\n\t\t\t\tspin_unlock(&musb->lock);\n\t\t\t\tdriver->resume'),
        'udc_skips_suppression': functions.replace(
            '\tusb_gadget_disable_async_callbacks(udc);', '\t/* lost suppression */'),
        'wait_holds_controller_lock': functions.replace(
            'spin_unlock_irq(&lock);', '(void)(&lock);'),
        'wait_does_not_reacquire_lock': functions.replace(
            'spin_lock_irq(&lock))', '(void)(&lock))'),
        'request_completion_is_suppressed': functions.replace(
            '\tusb_gadget_giveback_request(&req->ep->end_point, &req->request);',
            '\tif (musb->gadget_async_callbacks)\n\t\tusb_gadget_giveback_request(&req->ep->end_point, &req->request);'),
    }
    header = work / 'musb_callback_functions.h'
    harness = ROOT / 'kernel/tests/musb_callback_test.c'
    results = {}
    try:
        for name, value in variants.items():
            if name != 'candidate' and value == functions:
                raise ValueError('Callback negative control did not mutate: ' + name)
            header.write_text(value)
            binary = work / ('callbacks-' + name)
            run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread',
                 '-I', str(work), str(harness), '-o', str(binary)])
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=40)
            (work / ('callbacks-' + name + '.txt')).write_text(result.stdout + result.stderr)
            if name == 'candidate':
                result.check_returncode()
            elif result.returncode == 0 or 'Assertion' not in result.stderr:
                raise RuntimeError('Callback negative control did not fail: ' + name)
            results[name] = dict(returncode=result.returncode, output=result.stdout.strip(), error=result.stderr.strip())
            print('callbacks-' + name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
    finally:
        header.write_text(functions)
    arm = subprocess.check_output([
        'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
        '--platform', builder['platform'], '--entrypoint', 'bash',
        '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
        'set -euo pipefail\n'
        'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -pthread -static '
        '-I.local/build/musb-sleep-tests kernel/tests/musb_callback_test.c '
        '-o .local/build/musb-sleep-tests/callbacks-arm\n'
        'timeout 60 qemu-arm .local/build/musb-sleep-tests/callbacks-arm'], text=True)
    print(arm, end='', flush=True)
    return dict(native=results, arm32=arm.strip(), harness_sha256=sha256(harness),
                limits='Actual callbacks, UDC unbind and lock-wait macros with pthread primitives and controlled boundary APIs. '
                       'No deferred endpoint restart in this fixture (asserted boundary, covered by '
                       'the request-progress/KUnit suites). Not a Linux waitqueue, IRQ/timer '
                       'scheduler, or electrical USB qualification.')
