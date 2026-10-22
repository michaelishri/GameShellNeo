#!/usr/bin/env python3
"""Qualify actual MPFS acquisition/removal and explicitly selected ARM objects."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

from kernel_candidates import include_candidates
from kernel_checks import ROOT, archive_for, build_objects, sha256
from kernel_sources import atomic_json, attach_source, ensure_source, locked
from mpfs_ownership_source import MPFS, declarations, functions, prepare, variants
from native_source_variants import run_variants

EXPECTED = 'MPFS backend ownership: 42 actual-source scenarios passed'


def compile_mpfs(archive, lock, work, extra):
    specification = importlib.util.spec_from_file_location('mpfs_kernel_inputs', ROOT / 'tools/kernel-inputs.py')
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    queue = include_candidates(ROOT, 'musb-retirement', module.patches())
    manifest = [dict(name=name, sha256=hashlib.sha256(data).hexdigest()) for name, data in queue]
    identity = hashlib.sha256((json.dumps(manifest, sort_keys=True) + json.dumps(lock, sort_keys=True) +
                              (ROOT / 'kernel/gameshellneo.config').read_text() + '\n'.join(extra)).encode()).hexdigest()[:16]
    scratch = work / ('kernel-' + identity)
    scratch.mkdir(exist_ok=True)
    (scratch / 'extra.config').write_text(''.join(value + '\n' for value in extra))
    with locked(work / '.source-lock'):
        source, entries, metadata = ensure_source(ROOT, work, archive, lock, manifest, recorded_patches=queue)
        attach_source(scratch, source, entries)
        result = build_objects(source, scratch, lock, [MPFS.replace('.c', '.o')], extra, False,
                               metadata, offline=True)
    result.update(compiler_sha256=sha256(scratch / 'compiler.txt'),
                  elf_info_sha256=sha256(scratch / 'elf-info.txt'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    work = ROOT / '.local/build/mpfs-ownership-tests'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        output = work / ('compile-evidence.json' if args.compile_drivers else 'evidence.json')
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        paths, patches, original = prepare(ROOT, archive, lock, work / 'patched')
        sources = {name: path.read_text() for name, path in paths.items()}
        body = functions(sources)
        (work / 'mpfs_ownership_definitions.h').write_text(declarations(sources[MPFS]))
        header = work / 'mpfs_ownership_functions.h'
        harness = ROOT / 'kernel/tests/mpfs_ownership_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror']
        native = run_variants(work, header, body, variants(body, original[MPFS]), harness, flags, EXPECTED)
        sanitized_binary = work / 'candidate-sanitize'
        subprocess.run(['cc', *flags, '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-fno-pie', '-no-pie', '-I', str(work),
                        str(harness), '-o', str(sanitized_binary)], check=True)
        # This static fixture allocates no heap; LSan cannot run under host ptrace.
        sanitized = subprocess.check_output([str(sanitized_binary)], text=True,
            env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                     UBSAN_OPTIONS='halt_on_error=1')).strip()
        if sanitized != EXPECTED:
            raise ValueError('Incomplete sanitized MPFS scenario result')
        builder, relative = lock['builder'], work.relative_to(ROOT).as_posix()
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--network', 'none', '--pull', 'never',
            '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
            '--entrypoint', 'bash', '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\narm-linux-gnueabihf-gcc ' + ' '.join(flags) +
            f' -static -I{relative} kernel/tests/mpfs_ownership_test.c -o {relative}/candidate-arm\n'
            f'qemu-arm {relative}/candidate-arm'], text=True).strip()
        if arm != EXPECTED:
            raise ValueError('Incomplete ARM32 MPFS scenario result')
        builds = {}
        if args.compile_drivers:
            common = ('CONFIG_COMPILE_TEST=y', 'CONFIG_USB=y', 'CONFIG_USB_GADGET=y',
                      'CONFIG_USB_MUSB_SUNXI=n', 'CONFIG_USB_MUSB_HOST=n',
                      'CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_DUAL_ROLE=y')
            for name, extra in (
                ('builtin-pio', ('CONFIG_USB_MUSB_HDRC=y', 'CONFIG_USB_MUSB_POLARFIRE_SOC=y',
                                 'CONFIG_NOP_USB_XCEIV=y', 'CONFIG_MUSB_PIO_ONLY=y', 'CONFIG_USB_INVENTRA_DMA=n')),
                ('builtin-dma', ('CONFIG_USB_MUSB_HDRC=y', 'CONFIG_USB_MUSB_POLARFIRE_SOC=y',
                                 'CONFIG_NOP_USB_XCEIV=y', 'CONFIG_MUSB_PIO_ONLY=n', 'CONFIG_USB_INVENTRA_DMA=y')),
                ('modules-dma', ('CONFIG_MODULES=y', 'CONFIG_USB_MUSB_HDRC=m', 'CONFIG_USB_MUSB_POLARFIRE_SOC=m',
                                 'CONFIG_NOP_USB_XCEIV=m', 'CONFIG_MUSB_PIO_ONLY=n', 'CONFIG_USB_INVENTRA_DMA=y')),
            ):
                builds[name] = compile_mpfs(archive, lock, work, common + extra)
        maintained = (*patches, harness, Path(__file__), ROOT / 'tools/mpfs_ownership_source.py',
                      ROOT / 'tools/kernel_candidates.py', ROOT / 'tools/kernel_checks.py',
                      ROOT / 'tools/kernel_sources.py', ROOT / 'tools/native_source_variants.py',
                      ROOT / 'tools/kernel-inputs.py', ROOT / 'kernel/gameshellneo.config',
                      ROOT / 'build/sources.lock.json')
        atomic_json(output, dict(schema_version=1, suite='mpfs-ownership', linux=lock['linux']['tag'],
            archive_sha256=sha256(archive), sources={name: sha256(path) for name, path in paths.items()},
            inputs={str(path.relative_to(ROOT)): sha256(path) for path in maintained}, native=native,
            sanitized=sanitized, sanitizer_binary_sha256=sha256(sanitized_binary), arm32=arm,
            arm32_binary_sha256=sha256(work / 'candidate-arm'), builder=builder, builds=builds,
            limits='Actual MPFS probe/remove plus actual generic and platform unregister helper bodies; '
                   'modeled acquisition/device callbacks and clock effects. No Linux scheduling, '
                   'controller IRQ/DMA/timer retirement or physical MPFS qualification.'))
        print('MPFS evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
