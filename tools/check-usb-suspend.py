#!/usr/bin/env python3
"""Exercise actual locked AXP PM/IRQ callbacks; optionally compile the ARM driver."""
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
WORK = ROOT / '.local/build/usb-suspend-tests'
DRIVER = 'drivers/power/supply/axp20x_usb_power.c'
PATCHES = ('0006-axp-usb-work-lifetime.patch', '0008-axp-usb-absent-poll.patch',
           '0009-axp-usb-diagnostics.patch', '0010-axp-usb-suspend-work.patch')


def functions(source):
    irq = source.split('static irqreturn_t axp20x_usb_power_irq(', 1)[1].split(
        '\nstatic void axp20x_usb_power_poll_vbus', 1)[0]
    pm = source.split('static int axp20x_usb_power_suspend(', 1)[1].split('\n#endif', 1)[0]
    return 'static irqreturn_t axp20x_usb_power_irq(' + irq + '\nstatic int axp20x_usb_power_suspend(' + pm


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
        target = WORK / 'patched' / DRIVER
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, mode='r|xz') as source:
            for member in source:
                if member.name == 'linux-' + lock['linux']['tag'][1:] + '/' + DRIVER:
                    original = source.extractfile(member).read().decode()
                    target.write_text(original)
                    break
            else:
                raise RuntimeError('Missing locked USB driver')
        patches = [ROOT / 'kernel/patches' / name for name in PATCHES]
        for patch in patches:
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
        good = functions(target.read_text())
        header = WORK / 'usb_suspend_functions.h'
        harness = ROOT / 'kernel/tests/usb_suspend_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK), str(harness)]
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        cases = {
            'candidate': good,
            'original': functions(original),
            'cancel_only': good.replace('disable_delayed_work_sync(', 'cancel_delayed_work_sync('),
            'lost_rearm': good.replace('\tenable_delayed_work(&power->vbus_detect);', ''),
            'policy_reread': good.replace('if (power->irq_wake_enabled) {',
                                          'if (device_may_wakeup(&power->supply->dev)) {'),
            'lost_enable_error': good.replace('if (ret)\n\t\t\tgoto restore_work;',
                                               'if (ret == 1)\n\t\t\tgoto restore_work;'),
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
            '-I.local/build/usb-suspend-tests kernel/tests/usb_suspend_test.c '
            '-o .local/build/usb-suspend-tests/arm\n'
            'qemu-arm .local/build/usb-suspend-tests/arm'], text=True)
        print(arm, end='', flush=True)
        inputs = [*patches, harness, Path(__file__), ROOT / 'tools/kernel_checks.py']
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        inputs={str(p.relative_to(ROOT)): sha256(p) for p in inputs},
                        native=results, arm32=arm.strip(), builder=builder,
                        limits='Actual PM/IRQ source, deterministic workqueue/IRQ API shims. '
                               'Not kernel concurrency, physical wake or supplier-bus qualification.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [DRIVER.replace('.c', '.o')])
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
