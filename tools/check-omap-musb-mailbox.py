#!/usr/bin/env python3
"""Qualify the explicit OMAP mailbox lifetime references and candidate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from kernel_checks import ROOT, archive_for, build_objects, sha256
from kernel_sources import atomic_json, attach_source, ensure_source, locked
from native_source_variants import run_variants
from omap_musb_mailbox_source import (CORE, OMAP, candidate_definitions, candidate_functions,
    handoff_contract, prepare, queue_for, reference_definitions, reference_functions, variants)

EXPECTED_REFERENCE = 'OMAP mailbox baseline: 4 actual-source schedules reproduced'
EXPECTED = 'OMAP mailbox candidate: 32 bounded lifetime scenarios passed'


def reference(work, archive, lock):
    paths, queue = prepare(ROOT, archive, lock, work / 'patched', reference=True)
    sources = {name: path.read_text() for name, path in paths.items()}
    header = work / 'omap_mailbox_reference_functions.h'
    declarations = work / 'omap_mailbox_reference_definitions.h'
    header.write_text(reference_functions(sources))
    declarations.write_text(reference_definitions(sources[OMAP]))
    harness = ROOT / 'kernel/tests/omap_musb_mailbox_reference_test.c'
    binary = work / 'reference'
    subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-pthread', '-I', str(work), str(harness), '-o', str(binary)], check=True)
    result = subprocess.check_output([str(binary)], text=True, timeout=30).strip()
    if result != EXPECTED_REFERENCE:
        raise ValueError('Incomplete OMAP baseline schedule evidence')
    maintained = (Path(__file__), ROOT / 'tools/omap_musb_mailbox_source.py', harness,
                  ROOT / 'tools/kernel_candidates.py', ROOT / 'tools/kernel-inputs.py',
                  ROOT / 'tools/kernel_checks.py', ROOT / 'build/sources.lock.json')
    record = dict(schema_version=1, suite='omap-musb-mailbox-reference',
        linux=lock['linux']['tag'], archive_sha256=sha256(archive), result=result,
        sources={name: sha256(path) for name, path in paths.items()},
        inputs={str(path.relative_to(ROOT)): sha256(path) for path in maintained},
        queue=[dict(name=name, sha256=hashlib.sha256(data).hexdigest()) for name, data in queue],
        binary_sha256=sha256(binary), functions_sha256=sha256(header),
        definitions_sha256=sha256(declarations),
        limits='Unchanged core mailbox and OMAP mailbox/worker/exit/remove bodies with actual '
               'publication/fail2 statements wrapped from probe. Surrounding probe acquisition, '
               'workqueue/device/PM/PHY/MMIO effects modeled, deterministic pthread schedules. '
               'Stale accesses observed on retained static fixture storage, not freed memory. '
               'No complete probe, real Linux work/device scheduling or hardware claim.')
    atomic_json(work / 'reference-evidence.json', record)
    print(result, flush=True)


def compile_configuration(work, archive, lock, extra, objects):
    queue = queue_for(ROOT)
    manifest = [dict(name=name, sha256=hashlib.sha256(data).hexdigest()) for name, data in queue]
    identity = hashlib.sha256((json.dumps(manifest, sort_keys=True) + json.dumps(lock, sort_keys=True) +
                              (ROOT / 'kernel/gameshellneo.config').read_text() + '\n'.join(extra)).encode()).hexdigest()[:16]
    scratch = work / ('kernel-' + identity)
    scratch.mkdir(exist_ok=True)
    (scratch / 'extra.config').write_text(''.join(value + '\n' for value in extra))
    with locked(work / '.source-lock'):
        source, entries, metadata = ensure_source(ROOT, work, archive, lock, manifest, recorded_patches=queue)
        attach_source(scratch, source, entries)
        result = build_objects(source, scratch, lock, objects, extra, False, metadata, offline=True)
    result.update(compiler_sha256=sha256(scratch / 'compiler.txt'),
                  elf_info_sha256=sha256(scratch / 'elf-info.txt'))
    config = (scratch / 'output/.config').read_text().splitlines()
    if not any('CONFIG_' + flavor + '=y' in config for flavor in ('TREE_SRCU', 'TINY_SRCU')):
        raise ValueError('Pinned kernel has no selected SRCU implementation')
    return result


def candidate(work, archive, lock, compile_drivers):
    output = work / ('compile-evidence.json' if compile_drivers else 'evidence.json')
    output.unlink(missing_ok=True)
    paths, queue = prepare(ROOT, archive, lock, work / 'patched-candidate')
    sources = {name: path.read_text() for name, path in paths.items()}
    body = candidate_functions(sources)
    (work / 'omap_mailbox_definitions.h').write_text(candidate_definitions(sources))
    header = work / 'omap_mailbox_functions.h'
    harness = ROOT / 'kernel/tests/omap_musb_mailbox_test.c'
    maintained = (Path(__file__), ROOT / 'tools/omap_musb_mailbox_source.py', harness,
                  ROOT / 'tools/kernel_candidates.py', ROOT / 'tools/kernel-inputs.py',
                  ROOT / 'tools/kernel_checks.py', ROOT / 'tools/kernel_sources.py',
                  ROOT / 'tools/native_source_variants.py', ROOT / 'kernel/gameshellneo.config',
                  ROOT / 'build/sources.lock.json')
    inputs = {str(path.relative_to(ROOT)): sha256(path) for path in maintained}
    flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread']
    record = dict(schema_version=1, suite='omap-musb-mailbox', linux=lock['linux']['tag'],
        archive_sha256=sha256(archive),
        queue=[dict(name=name, sha256=hashlib.sha256(data).hexdigest()) for name, data in queue],
        sources={name: sha256(path) for name, path in paths.items()},
        definitions_sha256=sha256(work / 'omap_mailbox_definitions.h'),
        inputs=inputs, handoff_contract=handoff_contract(sources),
        native=run_variants(work, header, body, variants(body), harness, flags, EXPECTED))
    sanitize = work / 'candidate-sanitize'
    subprocess.run(['cc', *flags, '-O1', '-g', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer', '-fno-pie', '-no-pie', '-I', str(work),
                    str(harness), '-o', str(sanitize)], check=True)
    # Fixture state is static; host ptrace prevents LSan, not ASan/UBSan.
    record['sanitized'] = subprocess.check_output([str(sanitize)], text=True,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1')).strip()
    record['sanitizer_binary_sha256'] = sha256(sanitize)
    builder, relative = lock['builder'], work.relative_to(ROOT).as_posix()
    record['arm32'] = subprocess.check_output([
        'docker', 'run', '--rm', '--network', 'none', '--pull', 'never',
        '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
        '--entrypoint', 'bash', '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
        'set -euo pipefail\narm-linux-gnueabihf-gcc ' + ' '.join(flags) +
        f' -static -I{relative} kernel/tests/omap_musb_mailbox_test.c -o {relative}/candidate-arm\n'
        f'qemu-arm {relative}/candidate-arm'], text=True).strip()
    if record['sanitized'] != EXPECTED or record['arm32'] != EXPECTED:
        raise ValueError('Incomplete OMAP mailbox sanitizer/ARM result')
    record.update(arm32_binary_sha256=sha256(work / 'candidate-arm'), builder=builder, builds={})
    if compile_drivers:
        common = ('CONFIG_COMPILE_TEST=y', 'CONFIG_USB=y', 'CONFIG_USB_GADGET=y',
                  'CONFIG_USB_MUSB_SUNXI=n', 'CONFIG_USB_MUSB_HDRC=y',
                  'CONFIG_USB_MUSB_OMAP2PLUS=y', 'CONFIG_OMAP_CONTROL_PHY=n',
                  'CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_HOST=n',
                  'CONFIG_USB_MUSB_DUAL_ROLE=y', 'CONFIG_MUSB_PIO_ONLY=y',
                  'CONFIG_USB_INVENTRA_DMA=n')
        configurations = (
            ('gadget-pio', ('CONFIG_USB_MUSB_DUAL_ROLE=n', 'CONFIG_USB_MUSB_GADGET=y')),
            ('host-pio', ('CONFIG_USB_MUSB_DUAL_ROLE=n', 'CONFIG_USB_MUSB_HOST=y')),
            ('dual-dma', ('CONFIG_MUSB_PIO_ONLY=n', 'CONFIG_USB_INVENTRA_DMA=y')),
            ('modules-pio', ('CONFIG_MODULES=y', 'CONFIG_USB_MUSB_HDRC=m', 'CONFIG_USB_MUSB_OMAP2PLUS=m')),
            ('pm-without-sleep', ('CONFIG_PM=y', 'CONFIG_PM_SLEEP=n', 'CONFIG_SUSPEND=n', 'CONFIG_HIBERNATION=n')),
            ('no-pm', ('CONFIG_PM=n', 'CONFIG_PM_SLEEP=n', 'CONFIG_SUSPEND=n', 'CONFIG_HIBERNATION=n')),
        )
        for name, overrides in configurations:
            values = dict(setting.split('=', 1) for setting in common)
            values.update(setting.split('=', 1) for setting in overrides)
            extra = tuple(key + '=' + value for key, value in values.items())
            names = ['musb_core.o', 'omap2430.o']
            if values['CONFIG_USB_MUSB_GADGET'] == 'y' or values['CONFIG_USB_MUSB_DUAL_ROLE'] == 'y':
                names += ['musb_gadget.o', 'musb_gadget_ep0.o']
            if values['CONFIG_USB_MUSB_HOST'] == 'y' or values['CONFIG_USB_MUSB_DUAL_ROLE'] == 'y':
                names.append('musb_host.o')
            if name == 'modules-pio':
                names.append('musb_hdrc.o')
            objects = ['drivers/usb/musb/' + n for n in names]
            if name == 'dual-dma':
                objects.append('drivers/usb/musb/musbhsdma.o')
            record['builds'][name] = compile_configuration(work, archive, lock, extra, objects)
            atomic_json(work / 'compile-progress.json', record)
    if inputs != {name: sha256(ROOT / name) for name in inputs}:
        raise ValueError('OMAP mailbox inputs changed during the owned run')
    record['limits'] = ('Actual mailbox registration/dispatch/quiesce and OMAP work/init/exit/parent-PM bodies; '
        'modeled SRCU/work/device/PM/PHY/MMIO effects and deterministic pthread waits. '
        'Probe failure cases execute a bounded handoff reachability wrapper, not full probe. '
        'Native atomic context is a model; real Linux PM/dispatch/work/device qualification remains separate. '
        'No full system PM, DMA retirement, fresh physical-level guarantee or hardware claim.')
    atomic_json(output, record)
    print('OMAP mailbox evidence:', output.relative_to(ROOT), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', action='store_true')
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    if args.reference and args.compile_drivers:
        parser.error('Reference and candidate compilation are distinct Tasks')
    work = ROOT / '.local/build/omap-musb-mailbox-tests'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        if args.reference:
            reference(work, archive, lock)
        else:
            candidate(work, archive, lock, args.compile_drivers)


if __name__ == '__main__':
    main()
