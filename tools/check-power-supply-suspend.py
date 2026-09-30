#!/usr/bin/env python3
"""Check notification freeze/replay using locked core functions; optional ARM core build."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import resource
import subprocess
import tarfile

from kernel_checks import archive_for, compile_objects, run, sha256

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/build/power-supply-suspend-tests'
DRIVER = 'drivers/power/supply/power_supply_core.c'
CONTRACT = ('kernel/workqueue.c', 'kernel/power/process.c', 'kernel/power/suspend.c',
            'kernel/power/power.h', 'include/linux/workqueue.h')


def functions(source):
    worker = 'static void power_supply_changed_work(' + source.split(
        'static void power_supply_changed_work(', 1)[1].split('\nstruct psy_for_each_psy_cb_data', 1)[0]
    producer = 'void power_supply_changed(' + source.split(
        'void power_supply_changed(', 1)[1].split('\nEXPORT_SYMBOL_GPL(power_supply_changed);', 1)[0]
    return worker + '\n' + producer


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
        paths = (DRIVER, *CONTRACT)
        with tarfile.open(archive, mode='r|xz') as source:
            prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
            remaining = set(paths)
            for member in source:
                name = member.name.removeprefix(prefix)
                if name in remaining:
                    target = WORK / 'patched' / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.extractfile(member).read())
                    remaining.remove(name)
                    if not remaining:
                        break
            if remaining:
                raise RuntimeError('Missing locked sources: ' + ', '.join(sorted(remaining)))
        target = WORK / 'patched' / DRIVER
        original = target.read_text()
        patch = ROOT / 'kernel/patches/0013-power-supply-freezable-notifications.patch'
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
        good = functions(target.read_text())
        header = WORK / 'power_supply_suspend_functions.h'
        harness = ROOT / 'kernel/tests/power_supply_suspend_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK), str(harness)]
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        cases = {
            'candidate': good,
            'original_nonfreezable': functions(original),
            'lost_queue': good.replace('queue_work(system_freezable_wq, &psy->changed_work);', '(void)psy;'),
            'lost_changed': good.replace('psy->changed = true;', 'psy->changed = false;'),
            'lost_wake_hold': good.replace('pm_stay_awake(&psy->dev);', '(void)psy;'),
            'early_relax': good.replace('if (likely(!psy->changed))', 'if (true)'),
        }
        results = {}
        try:
            for name, text in cases.items():
                if name != 'candidate' and text == good:
                    raise RuntimeError('Mutation did not match: ' + name)
                header.write_text(text)
                binary = WORK / name
                run(['cc', *flags, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control did not fail as expected: ' + name)
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
            '-I.local/build/power-supply-suspend-tests kernel/tests/power_supply_suspend_test.c '
            '-o .local/build/power-supply-suspend-tests/arm\n'
            'qemu-arm .local/build/power-supply-suspend-tests/arm'], text=True)
        print(arm, end='', flush=True)
        inputs = (patch, harness, Path(__file__), ROOT / 'tools/kernel_checks.py',
                  ROOT / 'tools/check-kernel-config.py')
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        inputs={str(p.relative_to(ROOT)): sha256(p) for p in inputs},
                        audited_contract={name: sha256(WORK / 'patched' / name) for name in CONTRACT},
                        native=results, arm32=arm.strip(), builder=builder,
                        limits='Actual notification producer/worker; deterministic queue/freezer/wake API shims. '
                               'Not scheduler concurrency, physical IRQ wake or full suspend qualification.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [DRIVER.replace('.c', '.o')])
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
