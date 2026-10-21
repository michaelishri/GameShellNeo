#!/usr/bin/env python3
"""Test an isolated MUSB failed-queue DMA candidate; never changes the image queue."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import tarfile

from kernel_checks import ROOT, archive_for, build_objects, run, sha256
from kernel_sources import ensure_source, locked

WORK = ROOT/'.local/build/musb-queue-dma-tests'
PATCH = ROOT/'kernel/candidates/0038-musb-queue-dma-rollback.patch'
HARNESS = ROOT/'kernel/tests/musb_queue_dma_test.c'


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


audit = module('queue_dma_extract', 'check-musb-request-resume.py')
function = audit.function


def functions(core, gadget):
    macros = re.findall(r'^#define is_buffer_mapped\(req\).*?\n[^\n]*\n', gadget, re.M)
    if len(macros) != 1:
        raise ValueError('Unexpected DMA mapping predicate')
    return (macros[0] + ''.join(function(gadget, n) for n in ('map_dma_buffer', 'unmap_dma_buffer')) +
            function(core, 'musb_queue_resume_work') +
            function(gadget, 'musb_ep_restart_resume_work') + function(gadget, 'musb_gadget_queue'))


def source_pair(archive, lock):
    baseline = WORK/'baseline'
    candidate = WORK/'candidate'
    for path in (baseline, candidate):
        shutil.rmtree(path, ignore_errors=True)
        (path/audit.PREFIX).mkdir(parents=True)
    prefix = 'linux-' + lock['linux']['tag'][1:] + '/' + audit.PREFIX
    found = set()
    with tarfile.open(archive, 'r|xz') as source:
        for entry in source:
            name = entry.name.removeprefix(prefix)
            if entry.name.startswith(prefix) and name in audit.FILES:
                data = source.extractfile(entry).read()
                for path in (baseline, candidate):
                    (path/audit.PREFIX/name).write_bytes(data)
                found.add(name)
                if found == set(audit.FILES):
                    break
    if found != set(audit.FILES):
        raise ValueError('Incomplete locked MUSB source')
    patches = [ROOT/'kernel/patches'/n for n in audit.PRIOR_PATCHES] + [audit.PATCH]
    for path in (baseline, candidate):
        for patch in patches:
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=path)
    run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCH)], cwd=candidate)
    old = (baseline/audit.PREFIX/'musb_gadget.c').read_text()
    new = (candidate/audit.PREFIX/'musb_gadget.c').read_text()
    line = '\t\t\t\tunmap_dma_buffer(request, musb);\n'
    if new.count(line) != 1 or new.replace(line, '', 1) != old:
        raise ValueError('Candidate must change only failed-queue mapping cleanup')
    core = (candidate/audit.PREFIX/'musb_core.c').read_text()
    return core, old, new, patches


def check_count(text):
    if text.strip() != 'MUSB queue DMA: 74 source scenarios passed':
        raise ValueError('Incomplete queue DMA scenario output')


def compile_drivers(archive, lock, core, gadget):
    # A separate, hash-bound queue includes this candidate only for compiler
    # scratch. The normal export and diagnostic image inputs remain unchanged.
    queue = list(module('queue_dma_inputs', 'kernel-inputs.py').patches())
    if PATCH.name in {name for name, _ in queue}:
        raise ValueError('Candidate unexpectedly entered the active patch queue')
    queue.append((PATCH.name, PATCH.read_bytes()))
    manifest = [dict(name=n, sha256=hashlib.sha256(b).hexdigest()) for n, b in queue]
    with locked(WORK/'.source-lock'):
        source, _, metadata = ensure_source(ROOT, WORK, archive, lock, manifest, recorded_patches=queue)
        if functions((source/audit.PREFIX/'musb_core.c').read_text(),
                     (source/audit.PREFIX/'musb_gadget.c').read_text()) != functions(core, gadget):
            raise ValueError('Complete compiler source differs from tested functions')
        result = {}
        profiles = dict(board=(), dma=('CONFIG_COMPILE_TEST=y', 'CONFIG_USB_MUSB_SUNXI=n',
                        'CONFIG_USB_MUSB_MEDIATEK=y', 'CONFIG_MUSB_PIO_ONLY=n',
                        'CONFIG_USB_INVENTRA_DMA=y'))
        for name, extra in profiles.items():
            identity = hashlib.sha256(json.dumps([manifest, extra, lock], sort_keys=True).encode()).hexdigest()[:16]
            scratch = WORK/('kernel-'+identity)
            scratch.mkdir(exist_ok=True)
            (scratch/'extra.config').write_text(''.join(x+'\n' for x in extra))
            result[name] = build_objects(source, scratch, lock,
                ['drivers/usb/musb/musb_gadget.o', 'drivers/usb/musb/musb_core.o'],
                extra, name == 'board', metadata)
        return dict(patches=manifest, configurations=result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK/'.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = WORK/('compile-evidence.json' if args.compile_drivers else 'evidence.json')
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT/'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        core, old, new, patches = source_pair(archive, lock)
        good = functions(core, new)
        cases = dict(candidate=good, missing_rollback=functions(core, old),
            no_mapping_reset=good.replace(function(new, 'unmap_dma_buffer'),
                function(new, 'unmap_dma_buffer').replace('request->map_state = UN_MAPPED;', '')),
            loses_driver_address_reset=good.replace('request->request.dma = DMA_ADDR_INVALID;', ''),
            skips_premapped_cpu_sync=good.replace('dma_sync_single_for_cpu(', 'dma_sync_single_for_device('),
            unmaps_caller_owned=good.replace('if (request->map_state == MUSB_MAPPED)',
                                             'if (true)'),
            wrong_direction=good.replace('? DMA_TO_DEVICE', '? DMA_FROM_DEVICE'))
        header = WORK/'musb_queue_dma_functions.h'
        flags = ['-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                 '-Wno-unused-parameter', '-I', str(WORK), str(HARNESS)]
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, source in cases.items():
                if name != 'candidate' and source == good:
                    raise ValueError('Ineffective negative control')
                header.write_text(source)
                binary = WORK/(name+'.bin')
                run(['cc', *flags, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                (WORK/(name+'.log')).write_text(result.stdout+result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                    check_count(result.stdout)
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise ValueError('Negative control did not fail an assertion: '+name)
                results[name] = dict(returncode=result.returncode, output=result.stdout.strip())
                print(name+': '+('passed' if name == 'candidate' else 'expected assertion failure'), flush=True)
        finally:
            header.write_text(good)
        binary = WORK/'sanitized.bin'
        run(['cc', *flags, '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-o', str(binary)])
        sanitized = subprocess.check_output([str(binary)], text=True, timeout=30)
        check_count(sanitized)
        builder = lock['builder']
        arm = subprocess.check_output(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash', '-v', f'{ROOT}:/project',
            '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\narm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror '
            '-Wno-unused-parameter -static -I.local/build/musb-queue-dma-tests '
            'kernel/tests/musb_queue_dma_test.c -o .local/build/musb-queue-dma-tests/arm.bin\n'
            'qemu-arm .local/build/musb-queue-dma-tests/arm.bin'], text=True, timeout=120)
        check_count(arm)
        inputs = [PATCH, HARNESS, Path(__file__), ROOT/'tools/kernel_checks.py',
                  ROOT/'tools/kernel_sources.py', ROOT/'tools/check-musb-request-resume.py',
                  ROOT/'tools/kernel-inputs.py', ROOT/'build/sources.lock.json', *patches]
        evidence = dict(archive_sha256=sha256(archive), sources={
            str(p.relative_to(ROOT)):sha256(p) for p in inputs}, generated_sha256=sha256(header),
            native=results, sanitized=sanitized.strip(), arm32=arm.strip(), builder=builder,
            limits='74 sequential source scenarios with modeled DMA, PM and hardware-start boundaries. '
                   'Not SMP/DMA hardware or teardown qualification. Candidate absent from active image queue.')
        if args.compile_drivers:
            evidence['arm_build'] = compile_drivers(archive, lock, core, new)
        output.write_text(json.dumps(evidence, indent=2)+'\n')
        print('Saved', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
