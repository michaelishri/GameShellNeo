"""Optional wake/startup actual-source probe and UDC-start qualification."""
import os
import subprocess

from kernel_checks import ROOT, sha256
from native_source_variants import run_variants


def _run_fixture(work, stem, functions, variants, builder, expected):
    """Share execution only; each fixture keeps its own source and mutations."""
    directory = work / stem
    directory.mkdir(exist_ok=True)
    for name, value in variants.items():
        if name != 'candidate' and value == functions:
            raise ValueError('Negative control did not mutate: ' + name)
    header = directory / (stem + '_functions.h')
    harness = ROOT / 'kernel/tests' / (stem + '_test.c')
    flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror']
    print('Actual-source fixture:', stem, flush=True)
    results = run_variants(directory, header, functions, variants, harness, flags, expected)
    relative = directory.relative_to(ROOT).as_posix()
    arm = subprocess.check_output([
        'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
        '--platform', builder['platform'], '--entrypoint', 'bash',
        '-v', f'{ROOT}:/project', '-w', '/project',
        '-e', f'NEO_MUSB_CHECK_WORK=/project/{relative}',
        '-e', f'NEO_MUSB_CHECK_SOURCE=/project/{harness.relative_to(ROOT).as_posix()}',
        '-e', f'NEO_MUSB_CHECK_CROSS={builder["cross_compile"]}',
        builder['image'], '-c',
        'set -euo pipefail\n'
        '"${NEO_MUSB_CHECK_CROSS}gcc" -std=gnu11 -O2 -Wall -Wextra -Werror -static '
        '-I"$NEO_MUSB_CHECK_WORK" "$NEO_MUSB_CHECK_SOURCE" '
        '-o "$NEO_MUSB_CHECK_WORK/arm"\n'
        'qemu-arm "$NEO_MUSB_CHECK_WORK/arm"'], text=True).strip()
    if arm != expected:
        raise ValueError('Incomplete ARM source scenario result: ' + stem)
    print(arm, flush=True)
    return dict(native=results, arm32=arm, harness_sha256=sha256(harness),
                extracted_sha256=sha256(header), arm_binary_sha256=sha256(directory / 'arm'))


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
    return _run_fixture(work, 'musb_wake_probe', functions, variants, builder,
                        'MUSB probe/remove wake: 141 actual-source scenarios passed')


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
    return _run_fixture(work, 'musb_startup', functions, variants, builder,
                        'MUSB UDC startup: 42 actual-source scenarios passed')
