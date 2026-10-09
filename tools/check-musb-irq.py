#!/usr/bin/env python3
"""Test actual MUSB core IRQ teardown boundaries without device access."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess

from kernel_checks import ROOT, archive_for, compile_objects, run, sha256
from kernel_sources import atomic_json, locked
from musb_irq_checks import PATCHES, extract_source, mutations, test_functions

WORK = ROOT / '.local/build/musb-irq-tests'
EXPECTED = 'MUSB core retirement: 43 source scenarios passed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with locked(WORK / '.lock'):
        receipt = WORK / ('compile-evidence.json' if args.compile_drivers else 'evidence.json')
        receipt.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        spec = importlib.util.spec_from_file_location('kernel_inputs', ROOT / 'tools/kernel-inputs.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        extract_source(archive, lock, list(module.patches()), module.apply_queue, WORK / 'patched')
        core = WORK / 'patched/drivers/usb/musb/musb_core.c'
        functions = test_functions(core.read_text())
        timer = '\ttimer_setup(&musb->otg_timer, musb_otg_timer_func, 0);\n'
        without_timer = core.read_text().replace(timer, '')
        source_controls = {
            'missing-timer-init': without_timer,
            'late-timer-init': without_timer.replace('\t/* attach to the IRQ */',
                                                     timer + '\t/* attach to the IRQ */'),
            'extra-terminal-caller': core.read_text() + '\n\tmusb_shutdown_work(musb);\n',
            'extra-pm-caller': core.read_text() + '\n\tmusb_disable_runtime_pm(musb);\n',
        }
        for name, text in source_controls.items():
            try:
                test_functions(text)
            except ValueError:
                print(name + ': expected source-boundary rejection', flush=True)
            else:
                raise RuntimeError('Source control was not rejected: ' + name)
        header = WORK / 'musb_irq_functions.h'
        harness = ROOT / 'kernel/tests/musb_irq_retirement_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                 '-Wno-unused-function', '-Wno-unused-label']
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, content in {'candidate': functions, **mutations(functions)}.items():
                header.write_text(content)
                binary = WORK / name
                run(['cc', *flags, '-I', str(WORK), str(harness), '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                if name == 'candidate':
                    result.check_returncode()
                    if result.stdout.strip() != EXPECTED:
                        raise ValueError('Incomplete native IRQ result')
                elif result.returncode != -6 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control did not assert: ' + name)
                results[name] = dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
                                     source_sha256=sha256(header), binary_sha256=sha256(binary))
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            header.write_text(functions)
        builder = lock['builder']
        relative = WORK.relative_to(ROOT).as_posix()
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--network', 'none', '--entrypoint', 'bash',
            '-e', 'NEO_CROSS=' + builder['cross_compile'],
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n"${NEO_CROSS}gcc" ' + ' '.join(flags) +
            f' -static -I{relative} kernel/tests/musb_irq_retirement_test.c -o {relative}/arm\n'
            f'qemu-arm {relative}/arm'], text=True)
        if arm.strip() != EXPECTED:
            raise ValueError('Incomplete ARM32 IRQ result')
        print(arm, end='', flush=True)
        inputs = [ROOT / 'kernel/patches' / name for name in PATCHES]
        inputs += [Path(__file__), harness, ROOT / 'tools/musb_irq_checks.py',
                   ROOT / 'tools/kernel_checks.py', ROOT / 'tools/kernel_sources.py',
                   ROOT / 'tools/kernel-inputs.py', ROOT / 'build/sources.lock.json']
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive), builder=builder,
            inputs={str(p.relative_to(ROOT)): sha256(p) for p in inputs},
            core_sha256=sha256(core), native=results, arm32=arm.strip(),
            source_controls=list(source_controls),
            arm32_binary_sha256=sha256(WORK / 'arm'),
            limits='Actual IRQ/work helpers, remove body and probe failure tails with controlled '
                   'MMIO/client/DMA/PM/IRQ/work/timer boundaries. No real synchronization, '
                   'complete probe execution, independent producer retirement or hardware result.')
        if args.compile_drivers:
            prefix = 'drivers/usb/musb/'
            gadget = ('musb_core.o', 'musb_gadget.o', 'musb_gadget_ep0.o', 'sunxi.o')
            evidence['arm_configurations'] = {}
            for name, config, objects in (
                ('project', (), gadget),
                ('host', ('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_DUAL_ROLE=n', 'CONFIG_USB_MUSB_HOST=y'),
                 ('musb_core.o', 'musb_host.o', 'sunxi.o')),
                ('dual-role', ('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_HOST=n', 'CONFIG_USB_MUSB_DUAL_ROLE=y'),
                 (*gadget, 'musb_host.o')),
                ('module', ('CONFIG_USB_MUSB_HDRC=m', 'CONFIG_USB_MUSB_SUNXI=m'), (*gadget, 'musb_hdrc.o')),
                ('no-pm', ('CONFIG_PM=n', 'CONFIG_PM_SLEEP=n', 'CONFIG_SUSPEND=n', 'CONFIG_HIBERNATION=n'), gadget),
            ):
                print('Compiling MUSB IRQ configuration:', name, flush=True)
                evidence['arm_configurations'][name] = compile_objects(
                    archive, lock, WORK, [prefix + obj for obj in objects],
                    extra_config=config, project_config=name == 'project')
                atomic_json(WORK / 'compile-progress.json', evidence)
        atomic_json(receipt, evidence)
        print('Evidence:', receipt.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
