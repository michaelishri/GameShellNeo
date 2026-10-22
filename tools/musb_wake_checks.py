"""Optional wake/startup actual-source probe and UDC-start qualification."""
import os
import subprocess

from kernel_checks import ROOT, run, sha256


def probe_checks(work, core, irq_source, pm_source, builder, function):
    functions = ''.join(function(pm_source, name) for name in (
        'pm_runtime_get_active', 'pm_runtime_resume_and_get'))
    functions += ''.join(function(irq_source, name) for name in (
        'set_irq_wake_real', 'irq_set_irq_wake'))
    functions += ''.join(function(core, name) for name in (
        'musb_disarm_wake', 'musb_init_wakeup', 'musb_cleanup_wakeup', 'musb_free',
        'musb_init_controller', 'musb_remove'))
    variants = {
        'candidate': functions,
        'missing_probe_unwind': functions.replace('fail3:\n\tmusb_cleanup_wakeup(musb);', 'fail3:'),
        'cleanup_after_platform_exit': functions.replace(
            '\tmusb_cleanup_wakeup(musb);\n\tmusb_platform_exit(musb);',
            '\tmusb_platform_exit(musb);\n\tmusb_cleanup_wakeup(musb);'),
        'ignored_source_allocation': functions.replace(
            '\treturn device_init_wakeup(dev, true);', '\tdevice_init_wakeup(dev, true);\n\treturn 0;'),
        'missing_partial_capability_owner': functions.replace(
            '\tmusb->wakeup_initialized = true;', '\t/* omitted ownership */'),
        'free_before_wake_cleanup': functions.replace(
            'fail3:\n\tmusb_cleanup_wakeup(musb);', 'fail3:\n\tmusb_free(musb);\n\tmusb_cleanup_wakeup(musb);'),
        'probe_drops_foreign_state': functions.replace(
            '\tif (musb->wakeup_initialized) {', '\tif (true) {'),
        'ignored_probe_power_failure': functions.replace(
            '\tif (status < 0) {\n\t\tpm_runtime_disable',
            '\tif (false) {\n\t\tpm_runtime_disable'),
        'failed_get_keeps_reference': functions.replace(
            '\t\tpm_runtime_put_noidle(dev);', '\t\t/* lost error balance */'),
        'failed_probe_leaves_runtime_enabled': functions.replace(
            '\t\tpm_runtime_disable(musb->controller);', '\t\t/* lost disable */'),
        'failed_probe_idles_before_disable': functions.replace(
            '\t\tpm_runtime_disable(musb->controller);\n\t\tpm_runtime_dont_use_autosuspend(musb->controller);',
            '\t\tpm_runtime_dont_use_autosuspend(musb->controller);\n\t\tpm_runtime_disable(musb->controller);'),
        'failed_probe_skips_platform_exit': functions.replace(
            '\t\tgoto fail2;\n\t}\n\n\tstatus = usb_phy_init',
            '\t\tgoto fail1;\n\t}\n\n\tstatus = usb_phy_init'),
    }
    header = work / 'musb_wake_probe_functions.h'
    harness = ROOT / 'kernel/tests/musb_wake_probe_test.c'
    results = {}
    try:
        for name, value in variants.items():
            if name != 'candidate' and value == functions:
                raise ValueError('Probe negative control did not mutate: ' + name)
            header.write_text(value)
            binary = work / ('probe-' + name)
            run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                 '-I', str(work), str(harness), '-o', str(binary)])
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            (work / ('probe-' + name + '.txt')).write_text(result.stdout + result.stderr)
            if name == 'candidate':
                result.check_returncode()
            elif result.returncode == 0 or 'Assertion' not in result.stderr:
                raise RuntimeError('Probe negative control did not fail: ' + name)
            results[name] = dict(returncode=result.returncode, output=result.stdout.strip(), error=result.stderr.strip())
            print('probe-' + name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
    finally:
        header.write_text(functions)
    relative = work.relative_to(ROOT).as_posix()
    arm = subprocess.check_output([
        'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
        '--platform', builder['platform'], '--entrypoint', 'bash',
        '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
        'set -euo pipefail\n'
        'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
        f'-I{relative} kernel/tests/musb_wake_probe_test.c '
        f'-o {relative}/probe-arm\n'
        f'qemu-arm {relative}/probe-arm'], text=True)
    print(arm, end='', flush=True)
    return dict(native=results, arm32=arm.strip(), harness_sha256=sha256(harness))


def startup_checks(work, gadget, pm_source, udc_source, builder, function):
    functions = ''.join(function(pm_source, name) for name in (
        'pm_runtime_get_active', 'pm_runtime_resume_and_get'))
    functions += function(gadget, 'musb_gadget_start')
    functions += function(udc_source, 'usb_gadget_udc_start_locked')
    variants = {
        'candidate': functions,
        'ignored_start_power_failure': functions.replace(
            '\tif (retval < 0)\n\t\tgoto err;', '\t/* ignored startup error */'),
        'failed_get_keeps_reference': functions.replace(
            '\t\tpm_runtime_put_noidle(dev);', '\t\t/* lost error balance */'),
        'udc_publishes_failed_start': functions.replace(
            '\tif (!ret)\n\t\tudc->started = true;', '\tudc->started = true;'),
        'lost_success_put': functions.replace(
            '\tpm_runtime_put_autosuspend(musb->controller);', '\t/* lost success balance */'),
        'positive_resume_is_error': functions.replace(
            '\tif (ret < 0) {', '\tif (ret) {'),
    }
    header = work / 'musb_startup_functions.h'
    harness = ROOT / 'kernel/tests/musb_startup_test.c'
    results = {}
    try:
        for name, value in variants.items():
            if name != 'candidate' and value == functions:
                raise ValueError('Startup negative control did not mutate: ' + name)
            header.write_text(value)
            binary = work / ('startup-' + name)
            run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                 '-I', str(work), str(harness), '-o', str(binary)])
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            (work / ('startup-' + name + '.txt')).write_text(result.stdout + result.stderr)
            if name == 'candidate':
                result.check_returncode()
            elif result.returncode == 0 or 'Assertion' not in result.stderr:
                raise RuntimeError('Startup negative control did not fail: ' + name)
            results[name] = dict(returncode=result.returncode, output=result.stdout.strip(), error=result.stderr.strip())
            print('startup-' + name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
    finally:
        header.write_text(functions)
    relative = work.relative_to(ROOT).as_posix()
    arm = subprocess.check_output([
        'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
        '--platform', builder['platform'], '--entrypoint', 'bash',
        '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
        'set -euo pipefail\n'
        'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
        f'-I{relative} kernel/tests/musb_startup_test.c '
        f'-o {relative}/startup-arm\n'
        f'qemu-arm {relative}/startup-arm'], text=True)
    print(arm, end='', flush=True)
    return dict(native=results, arm32=arm.strip(), harness_sha256=sha256(harness))


