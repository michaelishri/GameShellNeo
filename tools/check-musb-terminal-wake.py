#!/usr/bin/env python3
"""Qualify the explicit MUSB terminal IRQ/wake composition without devices."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from kernel_checks import ROOT, archive_for, build_objects, sha256
from kernel_sources import atomic_json, attach_source, ensure_source, locked
from musb_terminal_wake_source import (CORE, GADGET, PROFILE, compare_semantics, function,
                                       mutations, prepare, queue_for, reference_functions,
                                       test_functions)
from native_source_variants import run_variants

EXPECTED = 'MUSB terminal wake: 147 actual-source scenarios passed'


def reference_checks(work, archive, lock):
    wake, _ = prepare(ROOT, archive, lock, work / 'wake-reference', 'musb-wake-startup')
    retirement, _ = prepare(ROOT, archive, lock, work / 'retirement-reference', 'musb-retirement')
    header = work / 'musb_terminal_wake_reference_functions.h'
    header.write_text(reference_functions(wake[CORE].read_text(), retirement[CORE].read_text(),
                                          wake['kernel/irq/manage.c'].read_text()))
    harness = ROOT / 'kernel/tests/musb_terminal_wake_reference_test.c'
    binary = work / 'reference'
    subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I', str(work), str(harness), '-o', str(binary)], check=True)
    result = subprocess.check_output([str(binary)], text=True).strip()
    if result != 'MUSB naive terminal composition: 4 actual-source references reproduced':
        raise ValueError('Incomplete naive-composition reference result')
    print(result, flush=True)
    return dict(result=result, functions_sha256=sha256(header), binary_sha256=sha256(binary)), wake


def compile_configuration(work, archive, lock, extra, objects, project):
    queue = queue_for(ROOT, PROFILE)
    manifest = [dict(name=name, sha256=hashlib.sha256(data).hexdigest()) for name, data in queue]
    identity = hashlib.sha256((json.dumps(manifest, sort_keys=True) + json.dumps(lock, sort_keys=True) +
                              (ROOT / 'kernel/gameshellneo.config').read_text() + '\n'.join(extra) +
                              str(project)).encode()).hexdigest()[:16]
    scratch = work / ('kernel-' + identity)
    scratch.mkdir(exist_ok=True)
    (scratch / 'extra.config').write_text(''.join(value + '\n' for value in extra))
    with locked(work / '.source-lock'):
        source, entries, metadata = ensure_source(ROOT, work, archive, lock, manifest, recorded_patches=queue)
        attach_source(scratch, source, entries)
        result = build_objects(source, scratch, lock, objects, extra, project, metadata, offline=True)
    result.update(compiler_sha256=sha256(scratch / 'compiler.txt'),
                  elf_info_sha256=sha256(scratch / 'elf-info.txt'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-only', action='store_true')
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    work = ROOT / '.local/build/musb-terminal-wake-tests'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        reference, wake = reference_checks(work, archive, lock)
        record = dict(schema_version=1, suite=PROFILE, linux=lock['linux']['tag'],
                      archive_sha256=sha256(archive), reference=reference, builder=lock['builder'])
        maintained = (Path(__file__), ROOT / 'tools/musb_terminal_wake_source.py',
                      ROOT / 'kernel/tests/musb_terminal_wake_reference_test.c',
                      ROOT / 'tools/kernel_candidates.py', ROOT / 'build/sources.lock.json',
                      ROOT / 'tools/kernel_checks.py', ROOT / 'tools/kernel_sources.py',
                      ROOT / 'tools/kernel-inputs.py', ROOT / 'tools/native_source_variants.py',
                      ROOT / 'kernel/gameshellneo.config')
        queues = {profile: [dict(name=name, sha256=hashlib.sha256(data).hexdigest())
                           for name, data in queue_for(ROOT, profile)]
                  for profile in ('musb-wake-startup', 'musb-retirement', PROFILE)}
        record['queues'] = queues
        if not args.reference_only:
            paths, _ = prepare(ROOT, archive, lock, work / 'combined')
            core = paths[CORE].read_text()
            compared = compare_semantics(core, wake[CORE].read_text())
            if function(paths[GADGET].read_text(), 'musb_gadget_start') != function(
                    wake[GADGET].read_text(), 'musb_gadget_start'):
                raise ValueError('Unchanged 0029 UDC startup semantics differ')
            record['equivalent_policy_functions'] = {
                name: hashlib.sha256(body.encode()).hexdigest() for name, body in compared.items()}
            body = test_functions(paths)
            header = work / 'musb_terminal_wake_functions.h'
            harness = ROOT / 'kernel/tests/musb_terminal_wake_test.c'
            flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror']
            record['native'] = run_variants(work, header, body,
                {'candidate': body, **mutations(body)}, harness, flags, EXPECTED)
            sanitized = work / 'candidate-sanitize'
            subprocess.run(['cc', *flags, '-O1', '-g', '-fsanitize=address,undefined',
                            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie', '-I', str(work),
                            str(harness), '-o', str(sanitized)], check=True)
            # Static no-heap fixture; host ptrace prevents LSan, not ASan/UBSan.
            record['sanitized'] = subprocess.check_output([str(sanitized)], text=True,
                env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                         UBSAN_OPTIONS='halt_on_error=1')).strip()
            record['sanitizer_binary_sha256'] = sha256(sanitized)
            relative, builder = work.relative_to(ROOT).as_posix(), lock['builder']
            record['arm32'] = subprocess.check_output([
                'docker', 'run', '--rm', '--network', 'none', '--pull', 'never',
                '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
                '--entrypoint', 'bash', '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
                'set -euo pipefail\narm-linux-gnueabihf-gcc ' + ' '.join(flags) +
                f' -static -I{relative} kernel/tests/musb_terminal_wake_test.c -o {relative}/candidate-arm\n'
                f'qemu-arm {relative}/candidate-arm'], text=True).strip()
            if record['sanitized'] != EXPECTED or record['arm32'] != EXPECTED:
                raise ValueError('Incomplete terminal wake sanitizer/ARM result')
            record['arm32_binary_sha256'] = sha256(work / 'candidate-arm')
            record['sources'] = {name: sha256(path) for name, path in paths.items()}
            maintained += (harness,)
            if args.compile_drivers:
                gadget = ('musb_core.o', 'musb_gadget.o', 'musb_gadget_ep0.o', 'sunxi.o')
                builds = record['builds'] = {}
                for name, extra, objects in (
                    ('project', (), gadget),
                    ('host', ('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_DUAL_ROLE=n', 'CONFIG_USB_MUSB_HOST=y'),
                     ('musb_core.o', 'musb_host.o', 'sunxi.o')),
                    ('dual-role', ('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_HOST=n', 'CONFIG_USB_MUSB_DUAL_ROLE=y'),
                     (*gadget, 'musb_host.o')),
                    ('module', ('CONFIG_USB_MUSB_HDRC=m', 'CONFIG_USB_MUSB_SUNXI=m'), (*gadget, 'musb_hdrc.o')),
                    ('pm-without-sleep', ('CONFIG_PM=y', 'CONFIG_PM_SLEEP=n', 'CONFIG_SUSPEND=n', 'CONFIG_HIBERNATION=n'), gadget),
                    ('no-pm', ('CONFIG_PM=n', 'CONFIG_PM_SLEEP=n', 'CONFIG_SUSPEND=n', 'CONFIG_HIBERNATION=n'), gadget),
                ):
                    builds[name] = compile_configuration(work, archive, lock, extra,
                        ['drivers/usb/musb/' + name for name in objects] +
                        ['drivers/extcon/extcon.o', 'drivers/extcon/devres.o'], name == 'project')
                    atomic_json(work / 'compile-progress.json', record)
        record['inputs'] = {str(path.relative_to(ROOT)): sha256(path) for path in maintained}
        record['limits'] = ('Actual full probe/remove and terminal IRQ/wake bodies, actual IRQ/PM '
            'accounting functions; modeled MMIO, clients, source allocation and barriers. '
            'Naive composition is a reference risk, not a shipping defect. Failed final '
            'disarm debt remains explicit. No Linux scheduling, complete backend/DMA retirement or hardware result.')
        name = 'reference-evidence.json' if args.reference_only else (
            'compile-evidence.json' if args.compile_drivers else 'evidence.json')
        atomic_json(work / name, record)
        print('Terminal wake evidence:', work / name, flush=True)


if __name__ == '__main__':
    main()
