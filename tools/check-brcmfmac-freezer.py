#!/usr/bin/env python3
"""Exercise actual brcmfmac freezer/worker/PM code with controlled concurrent callers."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tarfile

from kernel_checks import archive_for, compile_objects, run, sha256

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/build/brcmfmac-freezer-tests'
BASE = 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/'
DRIVERS = tuple(BASE + name for name in ('bcmsdh.c', 'sdio.c', 'sdio.h'))
CONTRACT = ('include/linux/completion.h', 'kernel/sched/completion.c',
            'include/linux/wait.h', 'kernel/workqueue.c')
PATCHES = tuple(ROOT / 'kernel/patches' / name for name in (
    '0014-brcmfmac-sdio-sleep-errors.patch', '0015-brcmfmac-freezer-lifecycle.patch'))


def function(source, declaration):
    start = source.index(declaration)
    return source[start:source.index('\n}', start) + 2] + '\n'


def mutate_once(source, before, after):
    if source.count(before) != 1:
        raise RuntimeError('Missing or ambiguous mutation: ' + before)
    return source.replace(before, after, 1)


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
        with tarfile.open(archive, mode='r|xz') as source:
            prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
            remaining = {*DRIVERS, *CONTRACT}
            for member in source:
                name = member.name.removeprefix(prefix)
                if name not in remaining:
                    continue
                target = WORK / 'patched' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.extractfile(member).read())
                remaining.remove(name)
                if not remaining:
                    break
            if remaining:
                raise RuntimeError('Missing locked sources: ' + repr(remaining))
        original = {name: sha256(WORK / 'patched' / name) for name in DRIVERS}
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCHES[0])], cwd=WORK / 'patched')
        before = (WORK / 'patched' / (BASE + 'sdio.c')).read_text()
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCHES[1])], cwd=WORK / 'patched')
        bcmsdh, sdio = ((WORK / 'patched' / name).read_text() for name in DRIVERS[:2])
        # Patch 0014's existing SDIO fault-injection regression remains applicable.
        low_level = ('static int\nbrcmf_sdio_kso_control(', 'static int brcmf_sdio_htclk(',
                     'static int brcmf_sdio_sdclk(', 'static int brcmf_sdio_clkctl(',
                     'static int\nbrcmf_sdio_bus_sleep(')
        for declaration in low_level:
            if function(before, declaration) != function(sdio, declaration):
                raise RuntimeError('Previously tested sleep helper changed: ' + declaration)
        definitions = re.search(r'#define BRCMF_SDIO_FREEZE_TIMEOUT_MS[^\n]+\n', bcmsdh)[0]
        definitions += bcmsdh[bcmsdh.index('struct brcmf_sdiod_freezer {'):
                             bcmsdh.index('\n};', bcmsdh.index('struct brcmf_sdiod_freezer {')) + 4]
        (WORK / 'brcmfmac_freezer_types.h').write_text(definitions)
        good = bcmsdh[bcmsdh.index('static int brcmf_sdiod_freezer_attach('):
                      bcmsdh.index('\nint brcmf_sdiod_remove(')]
        good += function(bcmsdh, 'static int brcmf_ops_sdio_suspend(')
        good += function(bcmsdh, 'static int brcmf_ops_sdio_resume(')
        good += function(sdio, 'static void brcmf_sdio_dataworker(')
        good += function(sdio, 'static int\nbrcmf_sdio_watchdog_thread(')
        header = WORK / 'brcmfmac_freezer_functions.h'
        harness = ROOT / 'kernel/tests/brcmfmac_freezer_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread',
                 '-I', str(WORK), str(harness)]
        uncount = function(good, 'void brcmf_sdiod_freezer_uncount(')
        cases = {
            'candidate': (good, []),
            'pm_disabled': (good, ['-DCONFIG_PM_SLEEP=0']),
            'lost_admission_count': (mutate_once(good, '\tfreezer->frozen_count++;', ''), []),
            'lost_withdrawal_wakeup': (mutate_once(good, uncount,
                uncount.replace('\twake_up(&freezer->thread_freeze);\n', '')), []),
            'lost_timeout_thaw': (mutate_once(good,
                '\t\tbrcmf_sdiod_freezer_thaw(freezer);\n', ''), []),
            'premature_reuse': (mutate_once(good,
                'freezer->freezing || freezer->frozen_count', 'freezer->freezing'), []),
            'lost_retirement': (mutate_once(good, '\tfreezer->frozen_count--;', ''), []),
            'lost_resume_guard': (mutate_once(good,
                '\t\tif (!brcmf_sdiod_freezing(sdiodev))\n\t\t\treturn 0;\n', ''), []),
            'worker_state_writes': (mutate_once(good,
                '\tbus->dpc_running = false;\n\tbrcmf_sdiod_try_freeze(bus->sdiodev);',
                '\tbus->dpc_running = false;\n'
                '\tbrcmf_sdiod_change_state(bus->sdiodev, BRCMF_SDIOD_DOWN);\n'
                '\tbrcmf_sdiod_try_freeze(bus->sdiodev);\n'
                '\tbrcmf_sdiod_change_state(bus->sdiodev, BRCMF_SDIOD_DATA);'), []),
            'early_watchdog_restart': (mutate_once(good,
                '\tbrcmf_sdiod_change_state(sdiodev, BRCMF_SDIOD_DATA);\n'
                '\tbrcmf_sdio_wd_timer(sdiodev->bus, true);',
                '\tbrcmf_sdio_wd_timer(sdiodev->bus, true);\n'
                '\tbrcmf_sdiod_change_state(sdiodev, BRCMF_SDIOD_DATA);'), []),
            'lost_watchdog_exit_uncount': (mutate_once(good,
                '\tbrcmf_sdiod_freezer_uncount(bus->sdiodev);\n\treturn 0;',
                '\treturn 0;'), []),
            'lost_collection_error': (mutate_once(good,
                '\t\tret = brcmf_sdiod_freezer_on(sdiodev);\n\t\tif (ret)\n\t\t\treturn ret;',
                '\t\tbrcmf_sdiod_freezer_on(sdiodev);'), []),
        }
        results = {}
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            for name, (text, defines) in cases.items():
                positive = name in {'candidate', 'pm_disabled'}
                if not positive and text == good:
                    raise RuntimeError('Negative control did not change source: ' + name)
                header.write_text(text)
                binary = WORK / name
                run(['cc', *flags, *defines, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=50)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if positive:
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control did not fail by assertion: ' + name)
                results[name] = dict(returncode=result.returncode, output=result.stdout.strip(),
                                     error=result.stderr.strip())
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            header.write_text(good)
        builder = lock['builder']
        arm = {}
        for name, defines in [('candidate', ''), ('pm_disabled', '-DCONFIG_PM_SLEEP=0')]:
            arm[name] = subprocess.check_output([
                'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
                '--platform', builder['platform'], '--entrypoint', 'bash',
                '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
                'set -euo pipefail\n'
                'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -pthread -static '
                + defines + ' -I.local/build/brcmfmac-freezer-tests '
                'kernel/tests/brcmfmac_freezer_test.c '
                '-o .local/build/brcmfmac-freezer-tests/arm-' + name + '\n'
                'qemu-arm .local/build/brcmfmac-freezer-tests/arm-' + name],
                text=True, timeout=120).strip()
            if arm[name] != results[name]['output']:
                raise RuntimeError('Native and ARM32 results differ: ' + name)
            print('ARM32 ' + name + ': ' + arm[name], flush=True)
        inputs = (*PATCHES, harness, Path(__file__), ROOT / 'tools/kernel_checks.py',
                  ROOT / 'tools/check-kernel-config.py')
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        original=original,
                        patched={name: sha256(WORK / 'patched' / name) for name in DRIVERS},
                        inputs={str(p.relative_to(ROOT)): sha256(p) for p in inputs},
                        contract={name: sha256(WORK / 'patched' / name) for name in CONTRACT},
                        native=results, arm32=arm, builder=builder,
                        limits='Actual freezer, PM callbacks, dataworker and watchdog thread; pthread '
                               'lock/wait/completion and SDIO shims with controlled interleavings. '
                               'Expiry is injected, not a measurement of Linux scheduling or 5s latency. '
                               'Not exhaustive concurrency, hardware, PM bus-error recovery or teardown validation.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK,
                                                    [name.replace('.c', '.o') for name in DRIVERS[:2]])
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
