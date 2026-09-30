#!/usr/bin/env python3
"""Check locked brcmfmac sleep/clock helpers with SDIO faults; optional full ARM object build."""
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
WORK = ROOT / '.local/build/brcmfmac-sleep-tests'
BASE = 'drivers/net/wireless/broadcom/brcm80211/'
DRIVER = BASE + 'brcmfmac/sdio.c'
CONTRACT = (BASE + 'brcmfmac/sdio.h', BASE + 'include/chipcommon.h',
            BASE + 'include/brcm_hw_ids.h')
PATCH = ROOT / 'kernel/patches/0014-brcmfmac-sdio-sleep-errors.patch'


def functions(source):
    begin = source.index('static int\nbrcmf_sdio_kso_control(')
    end = source.index('\n#ifdef DEBUG\nstatic inline bool brcmf_sdio_valid_shared_address(', begin)
    return source[begin:end]


def constants(sources):
    selected = {}
    exact = {'PMU_MAX_TRANSITION_DLY', 'CY_CC_43012_CHIP_ID', 'KSO_WAIT_US',
             'MAX_KSO_ATTEMPTS', 'BRCMF_SDIO_MAX_ACCESS_ERRORS',
             'CLK_NONE', 'CLK_SDONLY', 'CLK_PENDING', 'CLK_AVAIL'}
    for source in sources:
        lines = iter(source.splitlines(keepends=True))
        for line in lines:
            undef = re.match(r'#undef\s+(\w+)', line)
            if undef:
                selected.pop(undef[1], None)
                continue
            match = re.match(r'#define\s+(\w+)', line)
            if not match:
                continue
            name = match[1]
            while line.endswith('\\\n'):
                line += next(lines)
            if name in exact or name.startswith('SBSDIO_'):
                if name in selected:
                    raise RuntimeError('Duplicate extracted macro: ' + name)
                selected[name] = line
    if not exact <= selected.keys():
        raise RuntimeError('Missing locked macros: ' + repr(exact - selected.keys()))
    return ''.join(selected.values())


def mutate_once(source, before, after):
    if source.count(before) != 1:
        raise RuntimeError('Ambiguous or missing negative-control anchor: ' + before)
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
            remaining = {DRIVER, *CONTRACT}
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
        target = WORK / 'patched' / DRIVER
        original = target.read_text()
        original_hash = sha256(target)
        (WORK / 'brcmfmac_sleep_constants.h').write_text(constants(
            [*((WORK / 'patched' / name).read_text() for name in CONTRACT), original]))
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCH)], cwd=WORK / 'patched')
        good = functions(target.read_text())
        header = WORK / 'brcmfmac_sleep_functions.h'
        harness = ROOT / 'kernel/tests/brcmfmac_sleep_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK), str(harness)]
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        cases = {
            'original_happy': (functions(original), ['-DNEO_BASELINE']),
            'candidate': (good, []),
            'candidate_debug': (good, ['-DDEBUG']),
            'original_errors': (functions(original), []),
            'lost_kso_timeout': (mutate_once(good, 'err = -ETIMEDOUT;', 'err = 0;'), []),
            'lost_special_cleanup': (mutate_once(good, '\t\tgoto out;', '\t\treturn err;')
                                     .replace('out:\n', ''), []),
            'lost_clkctl_error': (mutate_once(good, '\treturn err;\n}\n\nstatic int\n',
                                            '\treturn 0;\n}\n\nstatic int\n'), []),
            'lost_sleep_clock_error': (good.replace('err = brcmf_sdio_clkctl(', 'brcmf_sdio_clkctl('), []),
            'early_clock_off_state': (mutate_once(good,
                '\t\tbrcmf_sdiod_writeb(bus->sdiodev, SBSDIO_FUNC1_CHIPCLKCSR,\n'
                '\t\t\t\t   clkreq, &err);\n\t\tif (err) {\n'
                '\t\t\tbrcmf_err("Failed access turning clock off:',
                '\t\tbus->clkstate = CLK_SDONLY;\n'
                '\t\tbrcmf_sdiod_writeb(bus->sdiodev, SBSDIO_FUNC1_CHIPCLKCSR,\n'
                '\t\t\t\t   clkreq, &err);\n\t\tif (err) {\n'
                '\t\t\tbrcmf_err("Failed access turning clock off:'), []),
            'lost_pending_write_error': (mutate_once(good,
                '\t\t\tif (err)\n\t\t\t\treturn -EBADE;\n'
                '\t\t\tbrcmf_dbg(SDIO, "CLKCTL: set PENDING',
                '\t\t\tbrcmf_dbg(SDIO, "CLKCTL: set PENDING'), []),
            'lost_poll_read_error': (mutate_once(good,
                '\t\t\tif (err)\n\t\t\t\tbreak;\n\t\t\tif (time_after',
                '\t\t\tif (time_after'), []),
            'lost_sleep_precheck': (mutate_once(good,
                '\t\t\tif (err)\n\t\t\t\tgoto done;\n\t\t\tif ((clkcsr',
                '\t\t\tif ((clkcsr'), []),
            'lost_sleep_cache_invalidation': (good.replace('bus->sleep_state_unknown = true;',
                                                         'bus->sleep_state_unknown = false;'), []),
            'lost_clock_cache_invalidation': (mutate_once(good, 'bus->clkstate_unknown = true;',
                                                        'bus->clkstate_unknown = false;'), []),
            'lost_unknown_filter_cleanup': (good.replace(' || unknown)', ')')
                                           .replace('bool unknown = bus->clkstate_unknown;\n', ''), []),
        }
        results = {}
        try:
            for name, (text, defines) in cases.items():
                positive = name in {'original_happy', 'candidate', 'candidate_debug'}
                if not positive and text == good:
                    raise RuntimeError('Negative control did not change source: ' + name)
                header.write_text(text)
                binary = WORK / name
                run(['cc', *flags, *defines, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if positive:
                    result.check_returncode()
                    if name != 'original_happy' and result.stdout.splitlines()[0] != results['original_happy']['output']:
                        raise RuntimeError('Successful transfer/delay/state behavior changed')
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control did not fail by assertion: ' + name)
                results[name] = dict(returncode=result.returncode, output=result.stdout.strip(),
                                     error=result.stderr.strip())
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            header.write_text(good)
        builder = lock['builder']
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n'
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
            '-I.local/build/brcmfmac-sleep-tests kernel/tests/brcmfmac_sleep_test.c '
            '-o .local/build/brcmfmac-sleep-tests/arm\n'
            'qemu-arm .local/build/brcmfmac-sleep-tests/arm'], text=True, timeout=120)
        if arm.strip() != results['candidate']['output']:
            raise RuntimeError('Native and ARM32 outputs differ')
        print(arm, end='', flush=True)
        inputs = (PATCH, harness, Path(__file__), ROOT / 'tools/kernel_checks.py',
                  ROOT / 'tools/check-kernel-config.py')
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        original_driver_sha256=original_hash, patched_driver_sha256=sha256(target),
                        inputs={str(p.relative_to(ROOT)): sha256(p) for p in inputs},
                        contract={name: sha256(WORK / 'patched' / name) for name in CONTRACT},
                        native=results, arm32=arm.strip(), builder=builder,
                        limits='Actual five sleep/clock helpers with scripted SDIO and time/retune/watchdog '
                               'shims. Not electrical, concurrent PM, reset/reprobe or hardware validation.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [DRIVER.replace('.c', '.o')])
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
