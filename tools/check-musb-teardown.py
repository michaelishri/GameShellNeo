#!/usr/bin/env python3
"""Audit actual MUSB teardown ordering; passing means reproduction, not safe removal."""
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tarfile

from kernel_checks import ROOT, archive_for, run, sha256
from kernel_sources import atomic_json, locked

WORK = ROOT / '.local/build/musb-teardown-tests'
PREFIX = 'drivers/usb/musb/'
MUSB_FILES = ('musb_core.c', 'musb_core.h', 'musb_regs.h', 'musb_gadget.c',
              'musb_gadget.h', 'musb_gadget_ep0.c', 'sunxi.c')
FILES = tuple(PREFIX + name for name in MUSB_FILES) + (
    'include/linux/pm_runtime.h', 'drivers/usb/gadget/udc/core.c')


def function(text, name):
    match = re.search(r'^(?:static\s+)?(?:inline\s+)?(?:void|int|irqreturn_t)\s+' +
                      name + r'\([^;{]*\)\n\{', text, re.M)
    if not match:
        raise ValueError('Missing source function: ' + name)
    return text[match.start():text.index('\n}', match.end()) + 3] + '\n'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Audit transformation must have exactly one source anchor')
    return text.replace(old, new, 1)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    with locked(WORK / '.lock'):
        output = WORK / 'evidence.json'
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        patched = WORK / 'patched'
        prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
        found = set()
        with tarfile.open(archive, mode='r|xz') as source:
            for entry in source:
                relative = entry.name.removeprefix(prefix)
                if entry.name.startswith(prefix) and relative in FILES:
                    target = patched / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.extractfile(entry).read())
                    found.add(relative)
                    if found == set(FILES):
                        break
        if found != set(FILES):
            raise ValueError('Incomplete pinned-source extraction')
        patches = [ROOT / 'kernel/patches' / name for name in (
            '0011-musb-sunxi-context.patch', '0025-musb-system-sleep-pullup.patch',
            '0026-musb-wake-irq-policy.patch', '0029-musb-startup-runtime-pm.patch',
            '0030-musb-gadget-callback-lifetime.patch')]
        for patch in patches:
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=patched)
        core = (patched / PREFIX / 'musb_core.c').read_text()
        gadget = (patched / PREFIX / 'musb_gadget.c').read_text()
        sunxi = (patched / PREFIX / 'sunxi.c').read_text()
        pm = (patched / 'include/linux/pm_runtime.h').read_text()
        udc = (patched / 'drivers/usb/gadget/udc/core.c').read_text()
        functions = ''.join(function(text, name) for text, names in (
            (pm, ('pm_runtime_get_sync', 'pm_runtime_put_sync')),
            (sunxi, ('sunxi_musb_disable',)),
            (core, ('musb_disable_interrupts', 'musb_stop', 'musb_free')),
            (gadget, ('musb_gadget_disable', 'musb_gadget_cleanup', 'musb_gadget_stop')),
            (udc, ('usb_gadget_udc_stop_locked',)),
            (sunxi, ('sunxi_musb_exit', 'sunxi_musb_interrupt')),
            (core, ('musb_remove',)),
        ) for name in names)
        constants = ''
        names = set(re.findall(r'\b(?:MUSB|SUNXI_MUSB)_[A-Z0-9_]+', functions)) - {'MUSB_HOST'}
        definitions = sunxi + (patched / PREFIX / 'musb_regs.h').read_text()
        for name in sorted(names):
            match = re.search(r'^#define\s+' + name + r'\s+(.+)$', definitions, re.M)
            if not match:
                raise ValueError('Missing register/flag definition: ' + name)
            constants += '#define ' + name + ' ' + match[1] + '\n'
        header = WORK / 'musb_teardown_functions.h'
        cancel = '\tcancel_delayed_work_sync(&musb->irq_work);\n'
        drained = replace_once(replace_once(functions, cancel, ''),
            '\tmusb_gadget_cleanup(musb);\n', '\tmusb_gadget_cleanup(musb);\n' + cancel)
        def early_irq(value):
            return replace_once(value, '\tmusb_platform_exit(musb);',
                                 '\tfree_irq(musb->nIrq, musb);\n\tmusb->nIrq = -1;\n'
                                 '\tmusb_platform_exit(musb);')
        variants = {
            'observed-source': (functions, []),
            'control-drain-after-cleanup': (drained, ['-DDRAIN_AFTER_CLEANUP=1']),
            'control-irq-before-clock': (early_irq(functions), ['-DFREE_IRQ_EARLY=1']),
            'control-both-orderings': (early_irq(drained), ['-DDRAIN_AFTER_CLEANUP=1', '-DFREE_IRQ_EARLY=1']),
        }
        stop = function(gadget, 'musb_gadget_stop')
        early_stop = replace_once(stop,
                '\tpm_runtime_get_sync(musb->controller);',
                '\tif (pm_runtime_get_sync(musb->controller) < 0) {\n'
                '\t\tpm_runtime_put_noidle(musb->controller);\n\t\treturn -EIO;\n\t}')
        mutations = {
            'naive-stop-early-return': (replace_once(functions, stop, early_stop),
                '!udc.started && !instance.gadget_driver && !instance.softconnect && !instance.is_active'),
            'missing-final-irq-release': (replace_once(functions,
                '\t\tfree_irq(musb->nIrq, musb);', '\t\t(void)0;'),
                '!irq_live && !accessible && !rpm_enabled && !instance.lock && unbinds == 1'),
        }
        harness = ROOT / 'kernel/tests/musb_teardown_audit.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter']
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results, negative = {}, {}
        builder = lock['builder']
        try:
            for name, (value, defines) in variants.items():
                if name != 'observed-source' and value == functions:
                    raise ValueError('Audit control did not change source')
                header.write_text(constants + value)
                binary = WORK / name
                run(['cc', *flags, *defines, '-I', str(WORK), str(harness), '-o', str(binary)])
                native = subprocess.check_output([str(binary)], text=True).strip()
                relative = WORK.relative_to(ROOT).as_posix()
                arm = subprocess.check_output([
                    'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
                    '--platform', builder['platform'], '--entrypoint', 'bash',
                    '-e', f'NEO_DRIVER_CROSS={builder["cross_compile"]}',
                    '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
                    'set -euo pipefail\n"${NEO_DRIVER_CROSS}gcc" ' + ' '.join(flags + defines) +
                    f' -static -I{relative} kernel/tests/musb_teardown_audit.c -o {relative}/{name}-arm\n'
                    f'qemu-arm {relative}/{name}-arm'], text=True).strip()
                if native != arm:
                    raise RuntimeError('Native/ARM audit disagreement')
                results[name] = dict(native=native, arm32=arm,
                                     extracted_sha256=sha256(header), native_sha256=sha256(binary),
                                     arm_sha256=sha256(WORK / (name + '-arm')))
                print(name + ': ' + native, flush=True)
            for name, (value, expected_assertion) in mutations.items():
                if value == functions:
                    raise ValueError('Negative control did not mutate')
                header.write_text(constants + value)
                binary = WORK / name
                run(['cc', *flags, '-I', str(WORK), str(harness), '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                if (result.returncode == 0 or 'Assertion' not in result.stderr or
                        expected_assertion not in result.stderr):
                    raise RuntimeError('Expected audit assertion failure: ' + name)
                negative[name] = dict(returncode=result.returncode, stderr=result.stderr.strip())
                print(name + ': expected assertion failure', flush=True)
        finally:
            header.write_text(constants + functions)
        atomic_json(output, dict(
            schema_version=1, linux=lock['linux']['tag'], archive_sha256=sha256(archive), builder=builder,
            inputs={str(p.relative_to(ROOT)): sha256(p) for p in (
                *patches, harness, Path(__file__), ROOT / 'tools/kernel_checks.py',
                ROOT / 'tools/kernel_sources.py', ROOT / 'build/sources.lock.json')},
            patched_sources={name: sha256(patched / name) for name in FILES},
            extracted_sha256=sha256(header), cases=results, negative_controls=negative,
            limits='Audit reproduces source ordering, not safe removal. UDC/function-driver, '
                   'PM, PHY, request completion, locks and scheduling are controlled boundaries. '
                   'Injected IRQ represents an already dispatched/shared handler, not electrical '
                   'delivery or Linux IRQ scheduling. Error return and register accessibility '
                   'are varied independently; no board fault reachability is established. '
                   'Controls are diagnostic source transformations, not proposed production patches.'))
        print('Audit evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
