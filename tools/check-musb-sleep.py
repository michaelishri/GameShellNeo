#!/usr/bin/env python3
"""Exercise actual MUSB system-PM/connection functions with deterministic interleavings."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tarfile

from kernel_checks import ROOT, archive_for, compile_objects, run, sha256

WORK = ROOT / '.local/build/musb-sleep-tests'
PREFIX = 'drivers/usb/musb/'
FILES = ('musb_core.c', 'musb_core.h', 'musb_regs.h', 'musb_gadget.c', 'musb_gadget.h', 'sunxi.c')


def function(text, name):
    match = re.search(r'^(?:static\s+)?(?:inline\s+)?(?:void|int|bool)\s+' + name + r'\([^;{]*\)\n\{', text, re.M)
    if not match:
        raise ValueError('Missing function: ' + name)
    return text[match.start():text.index('\n}', match.end()) + 3] + '\n'


def probe_checks(core, irq_source, builder):
    functions = ''.join(function(irq_source, name) for name in (
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
    }
    header = WORK / 'musb_wake_probe_functions.h'
    harness = ROOT / 'kernel/tests/musb_wake_probe_test.c'
    results = {}
    try:
        for name, value in variants.items():
            if name != 'candidate' and value == functions:
                raise ValueError('Probe negative control did not mutate: ' + name)
            header.write_text(value)
            binary = WORK / ('probe-' + name)
            run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                 '-I', str(WORK), str(harness), '-o', str(binary)])
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            (WORK / ('probe-' + name + '.txt')).write_text(result.stdout + result.stderr)
            if name == 'candidate':
                result.check_returncode()
            elif result.returncode == 0 or 'Assertion' not in result.stderr:
                raise RuntimeError('Probe negative control did not fail: ' + name)
            results[name] = dict(returncode=result.returncode, output=result.stdout.strip(), error=result.stderr.strip())
            print('probe-' + name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
    finally:
        header.write_text(functions)
    arm = subprocess.check_output([
        'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
        '--platform', builder['platform'], '--entrypoint', 'bash',
        '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
        'set -euo pipefail\n'
        'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
        '-I.local/build/musb-sleep-tests kernel/tests/musb_wake_probe_test.c '
        '-o .local/build/musb-sleep-tests/probe-arm\n'
        'qemu-arm .local/build/musb-sleep-tests/probe-arm'], text=True)
    print(arm, end='', flush=True)
    return dict(native=results, arm32=arm.strip(), harness_sha256=sha256(harness))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    parser.add_argument('--compile-matrix', action='store_true',
                        help='Also compile isolated host/dual-role/module and PM stub configurations')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = WORK / ('matrix-evidence.json' if args.compile_matrix else
                         'compile-evidence.json' if args.compile_drivers else 'evidence.json')
        output.unlink(missing_ok=True)
        if args.compile_matrix:
            (WORK / 'matrix-progress.json').unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        target = WORK / 'patched' / PREFIX
        target.mkdir(parents=True, exist_ok=True)
        prefix = 'linux-' + lock['linux']['tag'][1:] + '/' + PREFIX
        found = set()
        with tarfile.open(archive, mode='r|xz') as source:
            for entry in source:
                if entry.name in [prefix + name for name in FILES]:
                    name = entry.name.removeprefix(prefix)
                    (target / name).write_bytes(source.extractfile(entry).read())
                    found.add(name)
                    if len(found) == len(FILES):
                        break
        if found != set(FILES):
            raise ValueError('Incomplete locked source')
        irq_sources = {}
        irq_prefix = 'linux-' + lock['linux']['tag'][1:] + '/kernel/irq/'
        with tarfile.open(archive, mode='r|xz') as source:
            for entry in source:
                if entry.name in [irq_prefix + name for name in ('manage.c', 'pm.c', 'chip.c')]:
                    irq_sources[entry.name.removeprefix(irq_prefix)] = source.extractfile(entry).read().decode()
                    if len(irq_sources) == 3:
                        break
        if len(irq_sources) != 3:
            raise ValueError('Missing locked IRQ-core source')
        irq_source = irq_sources['manage.c']
        patches = [ROOT / 'kernel/patches' / name for name in (
            '0011-musb-sunxi-context.patch', '0025-musb-system-sleep-pullup.patch',
            '0026-musb-wake-irq-policy.patch')]
        for patch in patches:
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
        core = (target / 'musb_core.c').read_text()
        gadget = (target / 'musb_gadget.c').read_text()
        functions = ''.join(function(irq_source, name) for name in (
            'set_irq_wake_real', 'irq_set_irq_wake', '__disable_irq', '__enable_irq'))
        functions += ''.join(function(irq_sources['pm.c'], name) for name in (
            'irq_pm_handle_wakeup', 'suspend_device_irq', 'resume_irq'))
        functions += ''.join(function(irq_sources['chip.c'], name) for name in (
            'irq_can_handle_pm', 'irq_can_handle_actions', 'irq_can_handle'))
        functions += ''.join(function(gadget, name) for name in (
            'musb_pullup', 'musb_gadget_suspend', 'musb_gadget_resume',
            'musb_gadget_work', 'musb_gadget_pullup', 'musb_gadget_cleanup',
            'musb_gadget_stop'))
        functions += ''.join(function(core, name) for name in (
            'musb_disarm_wake', 'musb_init_wakeup', 'musb_cleanup_wakeup', 'musb_free',
            'musb_save_context', 'musb_restore_context', 'musb_run_resume_work',
            'musb_suspend', 'musb_resume'))
        definitions = (target / 'musb_core.h').read_text() + (target / 'musb_regs.h').read_text()
        constants = (set(re.findall(r'\bMUSB_[A-Z0-9_]+', functions)) |
                     {'MUSB_POWER_HSENAB'}) - {'MUSB_HOST', 'MUSB_PERIPHERAL'}
        defs = ''
        for name in sorted(constants):
            match = re.search(r'^#define\s+' + name + r'\s+(.+)$', definitions, re.M)
            if not match:
                raise ValueError('Missing register definition: ' + name)
            defs += '#define ' + name + ' ' + match[1] + '\n'
        for name in ('musb_csr_regs', 'musb_context_registers'):
            defs += re.search(r'struct ' + name + r' \{.*?\n\};', definitions, re.S)[0] + '\n'
        (WORK / 'musb_sleep_defs.h').write_text(defs)
        header = WORK / 'musb_sleep_functions.h'
        harness = ROOT / 'kernel/tests/musb_sleep_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK), str(harness)]
        variants = dict(
            candidate=functions,
            no_detach=functions.replace('\tmusb_pullup(musb, 0);', '\t/* lost detach */', 1),
            stale_intent=functions.replace('musb->softconnect && musb->gadget_driver', '!!musb->gadget_driver'),
            ungated_work=functions.replace('\tif (!musb->gadget_suspended)\n\t\tmusb_pullup', '\tmusb_pullup', 1),
            early_restore=functions.replace('\tif (musb->gadget_suspended)\n\t\tpower &= ~MUSB_POWER_SOFTCONN;\n', ''),
            failed_resume_connects=functions.replace('musb->gadget_suspended && !error', 'musb->gadget_suspended'),
            loses_first_error=functions.replace('\t\t\t\tif (!error)\n\t\t\t\t\terror = ret;', '\t\t\t\terror = ret;'),
            enqueue_during_sleep=functions.replace('\t\tif (!musb->gadget_suspended)\n\t\t\tschedule', '\t\tschedule'),
            stop_keeps_pullup=functions.rsplit('\tmusb_pullup(musb, 0);', 1)[0] +
                functions.rsplit('\tmusb_pullup(musb, 0);', 1)[1],
            keeps_probe_wake=functions.replace(
                '\tmusb->irq_wake = true;\n\tret = musb_disarm_wake(musb);',
                '\tmusb->irq_wake = true;\n\tret = 0;', 1),
            loses_failed_disarm=functions.replace(
                '\tif (!ret)\n\t\tmusb->irq_wake = false;', '\tmusb->irq_wake = false;', 1),
            disarm_rereads_policy=functions.replace(
                '\tif (!musb->irq_wake)', '\tif (!device_may_wakeup(musb->controller) || !musb->irq_wake)', 1),
            ignores_arm_error=functions.replace(
                '\t\tif (ret)\n\t\t\tgoto err_pm_put;', '\t\t/* lost arm error */', 1),
            loses_disarm_error=functions.replace(
                '\t\tif (!error)\n\t\t\terror = ret;', '\t\t/* lost disarm error */', 1),
            clears_foreign_source=functions.replace(
                '\tif (musb->wakeup_initialized) {', '\tif (true) {', 1),
            no_wake_arm=functions.replace(
                '\t\tirqd_set(irqd, IRQD_WAKEUP_ARMED);', '\t\t/* no wake arm */', 1),
            wake_handler_runs_early=functions.replace(
                '\tif (!irq_can_handle_pm(desc))\n\t\treturn false;',
                '\tif (!irq_can_handle_pm(desc))\n\t\treturn true;', 1),
        )
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, value in variants.items():
                if name != 'candidate' and value == functions:
                    raise ValueError('Negative control did not mutate: ' + name)
                header.write_text(value)
                binary = WORK / name
                run(['cc', *flags, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control did not fail: ' + name)
                results[name] = dict(returncode=result.returncode, output=result.stdout.strip(), error=result.stderr.strip())
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            header.write_text(functions)
        builder = lock['builder']
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n'
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
            '-I.local/build/musb-sleep-tests kernel/tests/musb_sleep_test.c '
            '-o .local/build/musb-sleep-tests/arm\n'
            'qemu-arm .local/build/musb-sleep-tests/arm'], text=True)
        print(arm, end='', flush=True)
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        inputs={str(p.relative_to(ROOT)): sha256(p) for p in
                                (*patches, harness, Path(__file__), ROOT / 'tools/kernel_checks.py')},
                        native=results, arm32=arm.strip(), builder=builder,
                        limits='Actual source functions, deterministic boundary interleavings. '
                               'No electrical USB timing, host enumeration or scheduler concurrency qualification.')
        evidence['probe_remove'] = probe_checks(core, irq_source, builder)
        if args.compile_drivers or args.compile_matrix:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [
                PREFIX + 'musb_core.o', PREFIX + 'musb_gadget.o', PREFIX + 'sunxi.o'])
        if args.compile_matrix:
            # These are compile-only alternatives, never board image configurations.
            matrices = {
                'host': (('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_DUAL_ROLE=n',
                          'CONFIG_USB_MUSB_HOST=y'), ('musb_core.o', 'musb_host.o', 'sunxi.o')),
                'dual-role': (('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_HOST=n',
                               'CONFIG_USB_MUSB_DUAL_ROLE=y'),
                              ('musb_core.o', 'musb_host.o', 'musb_gadget.o', 'sunxi.o')),
                'module': (('CONFIG_USB_MUSB_HDRC=m', 'CONFIG_USB_MUSB_SUNXI=m'),
                           ('musb_core.o', 'musb_gadget.o', 'sunxi.o')),
                'no-system-sleep': (('CONFIG_SUSPEND=n', 'CONFIG_HIBERNATION=n',
                                     'CONFIG_PM_SLEEP=n', 'CONFIG_PM=y'),
                                    ('musb_core.o', 'musb_gadget.o', 'sunxi.o')),
                'no-pm': (('CONFIG_SUSPEND=n', 'CONFIG_HIBERNATION=n',
                          'CONFIG_PM_SLEEP=n', 'CONFIG_PM=n'),
                         ('musb_core.o', 'musb_gadget.o', 'sunxi.o')),
            }
            evidence['arm_configurations'] = {}
            for name, (config, objects) in matrices.items():
                print('Compile-only MUSB configuration:', name, flush=True)
                evidence['arm_configurations'][name] = compile_objects(
                    archive, lock, WORK, [PREFIX + obj for obj in objects],
                    extra_config=config, project_config=False)
                (WORK / 'matrix-progress.json').write_text(json.dumps(evidence, indent=2) + '\n')
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
