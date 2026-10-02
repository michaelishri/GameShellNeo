#!/usr/bin/env python3
"""Check locked Sunxi/MMC SDIO reference ownership; optionally compile ARM objects."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import resource
import subprocess
import tarfile

from kernel_checks import ROOT, archive_for, compile_objects, run, sha256

WORK = ROOT / '.local/build/sunxi-sdio-ref-tests'
DRIVER = 'drivers/mmc/host/sunxi-mmc.c'
SIGNATURES = {
    DRIVER: ('static void sunxi_mmc_enable_sdio_irq(',),
    'include/linux/mmc/host.h': ('static inline void mmc_signal_sdio_irq(',),
    'drivers/mmc/core/sdio.c': ('static int mmc_sdio_suspend(', 'static int mmc_sdio_resume('),
    'drivers/mmc/core/sdio_irq.c': ('static int sdio_irq_thread(', 'static int sdio_card_irq_get(',
                                  'static int sdio_card_irq_put('),
}


def function(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-driver', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = WORK / ('compile-evidence.json' if args.compile_driver else 'evidence.json')
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        texts = {}
        with tarfile.open(archive, 'r|xz') as stream:
            prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
            for member in stream:
                name = member.name.removeprefix(prefix)
                if name in SIGNATURES:
                    texts[name] = stream.extractfile(member).read().decode()
                    if len(texts) == len(SIGNATURES):
                        break
        if texts.keys() != SIGNATURES.keys():
            raise ValueError('Missing locked SDIO source')
        target = WORK / 'patched' / DRIVER
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(texts[DRIVER])
        patch = ROOT / 'kernel/patches/0023-sunxi-mmc-sdio-reference-ownership.patch'
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
        callback = SIGNATURES[DRIVER][0]
        original = function(texts[DRIVER], callback)
        good = function(target.read_text(), callback)
        core = '\n'.join(function(texts[name], signature) for name, signatures in SIGNATURES.items()
                         if name != DRIVER for signature in signatures)
        header = WORK / 'sunxi_sdio_ref_functions.h'
        harness = ROOT / 'kernel/tests/sunxi_sdio_refs_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK), str(harness)]
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        # Do not skip duplicate writes: a controller reset may have lost IMASK.
        cases = dict(candidate=good, original=original,
            repeated_get=good.replace('if (enable && !was_enabled)', 'if (enable)'),
            repeated_put=good.replace('if (!enable && was_enabled)', 'if (!enable)'),
            no_get=good.replace('pm_runtime_get_noresume(host->dev);', '(void)pm_runtime_get_noresume;'),
            no_put=good.replace('pm_runtime_put_noidle(host->dev);', '(void)pm_runtime_put_noidle;'),
            lost_other_irqs=good.replace('imask = mmc_readl(host, REG_IMASK);',
                                         'imask = mmc_readl(host, REG_IMASK) & SDXC_SDIO_INTERRUPT;'),
            skipped_rearm=good.replace('mmc_writel(host, REG_IMASK, imask);',
                                       'if (!!enable != was_enabled)\n\t\tmmc_writel(host, REG_IMASK, imask);'),
            unlocked_put=good.replace('\tspin_unlock_irqrestore(&host->lock, flags);', '').replace(
                '\tif (!enable && was_enabled)', '\tspin_unlock_irqrestore(&host->lock, flags);\n\tif (!enable && was_enabled)'))
        results = {}
        try:
            for name, code in cases.items():
                if name != 'candidate' and code == good:
                    raise ValueError('Mutation failed to match: ' + name)
                header.write_text(code + '\n' + core)
                binary = WORK / name
                run(['cc', *flags, '-o', str(binary)])
                if name == 'original':
                    characterization = subprocess.check_output([str(binary), '--characterize-original'], text=True)
                    print(characterization, end='', flush=True)
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise ValueError('Negative control did not reject: ' + name)
                results[name] = dict(returncode=result.returncode, stdout=result.stdout.strip(), stderr=result.stderr.strip())
                print(name + ': ' + (result.stdout.strip() or 'expected assertion rejection'), flush=True)
        finally:
            header.write_text(good + '\n' + core)
        builder = lock['builder']
        arm = subprocess.check_output(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash', '-v', f'{ROOT}:/project',
            '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\narm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
            '-I.local/build/sunxi-sdio-ref-tests kernel/tests/sunxi_sdio_refs_test.c '
            '-o .local/build/sunxi-sdio-ref-tests/arm\nqemu-arm .local/build/sunxi-sdio-ref-tests/arm'], text=True)
        print(arm, end='', flush=True)
        inputs = (patch, harness, Path(__file__), ROOT / 'tools/kernel_checks.py')
        evidence = dict(linux=lock['linux'], archive_sha256=sha256(archive),
            inputs={str(p.relative_to(ROOT)): sha256(p) for p in inputs}, native=results,
            original_characterization=characterization.strip(), arm32=arm.strip(), builder=builder,
            limits='Actual host callback, MMC thread, IRQ signal, card IRQ get/put and suspend/resume functions '
                   'with deterministic scheduler, runtime-PM, MMIO and lock shims. Not kernel concurrency, '
                   'physical register access, complete removal, hardware suspend or energy qualification.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK,
                ['drivers/mmc/host/sunxi-mmc.o', 'drivers/mmc/core/sdio.o', 'drivers/mmc/core/sdio_irq.o'])
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
