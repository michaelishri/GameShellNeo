#!/usr/bin/env python3
"""Check locked Sun4i PHY worker/PM lifecycle and optionally compile its ARM driver."""
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
WORK = ROOT / '.local/build/usb-phy-suspend-tests'
DRIVER = 'drivers/phy/allwinner/phy-sun4i-usb.c'


def functions(source):
    scan = 'static void sun4i_usb_phy0_id_vbus_det_scan(' + source.split(
        'static void sun4i_usb_phy0_id_vbus_det_scan(', 1)[1].split('\nstatic struct phy *sun4i_usb_phy_xlate', 1)[0]
    if 'static int sun4i_usb_phy_suspend(' in source:
        pm = 'static int sun4i_usb_phy_suspend(' + source.split(
            'static int sun4i_usb_phy_suspend(', 1)[1].split('\nstatic DEFINE_SIMPLE_DEV_PM_OPS', 1)[0]
    else:
        # Model the upstream absence of provider system-PM callbacks.
        pm = ('static int sun4i_usb_phy_suspend(struct device *dev) { (void)dev; return 0; }\n'
              'static int sun4i_usb_phy_resume(struct device *dev) { (void)dev; return 0; }\n')
    definitions = '\n'.join(re.search(r'^#define\s+' + n + r'\s+.+$', source, re.M)[0]
                            for n in ('DEBOUNCE_TIME', 'POLL_TIME'))
    return definitions + '\n' + scan + '\n' + pm


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
                raise RuntimeError('Missing locked USB PHY driver')
        patch = ROOT / 'kernel/patches/0012-sun4i-usb-phy-suspend-work.patch'
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
        source = target.read_text()
        if ('.pm = pm_sleep_ptr(&sun4i_usb_phy_pm_ops)' not in source or
                not re.search(r'DEFINE_SIMPLE_DEV_PM_OPS\(sun4i_usb_phy_pm_ops, sun4i_usb_phy_suspend,\s*'
                              r'sun4i_usb_phy_resume\);', source)):
            raise RuntimeError('Missing provider system-PM callback registration')
        good = functions(source)
        header = WORK / 'usb_phy_suspend_functions.h'
        harness = ROOT / 'kernel/tests/usb_phy_suspend_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK), str(harness)]
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        reads = '\tid_det = sun4i_usb_phy0_get_id_det(data);\n\tvbus_det = sun4i_usb_phy0_get_vbus_det(data);\n'
        if good.count(reads) != 1:
            raise RuntimeError('Unexpected getter structure')
        cases = {
            'candidate': good,
            'original': functions(original),
            'cancel_only': good.replace('disable_delayed_work_sync(', 'cancel_delayed_work_sync('),
            'missing_suspend': good.replace('\tdisable_delayed_work_sync(&data->detect);', '\t(void)data;'),
            'lost_rearm': good.replace('\tenable_delayed_work(&data->detect);', ''),
            'lost_rescan': good.replace('\tmod_delayed_work(system_wq, &data->detect, DEBOUNCE_TIME);\n\n\treturn 0;',
                                        '\treturn 0;'),
            'reads_before_guard': good.replace(reads, '').replace('\tmutex_lock(&phy0->mutex);',
                                                                   reads + '\n\tmutex_lock(&phy0->mutex);', 1),
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
            '-I.local/build/usb-phy-suspend-tests kernel/tests/usb_phy_suspend_test.c '
            '-o .local/build/usb-phy-suspend-tests/arm\n'
            'qemu-arm .local/build/usb-phy-suspend-tests/arm'], text=True)
        print(arm, end='', flush=True)
        inputs = (patch, harness, Path(__file__), ROOT / 'tools/kernel_checks.py')
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        inputs={str(p.relative_to(ROOT)): sha256(p) for p in inputs},
                        native=results, arm32=arm.strip(), builder=builder,
                        limits='Actual scan/IRQ/notifier/PM source with deterministic workqueue/mutex/API shims. '
                               'Not kernel concurrency, physical PMIC access or full suspend qualification.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [DRIVER.replace('.c', '.o')])
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
