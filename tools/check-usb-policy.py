#!/usr/bin/env python3
"""Run actual USB policy/probe callbacks with OF, register and workqueue shims."""
import argparse
import fcntl
import importlib.util
import json
import os
import resource
from pathlib import Path
import subprocess
import tarfile

from kernel_checks import archive_for, compile_objects, run, sha256

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/build/usb-policy-tests'
DRIVER = 'drivers/power/supply/axp20x_usb_power.c'
HEADER = ROOT / 'kernel/overlay/drivers/power/supply/axp20x_usb_gameshellneo.h'


def capture(command):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, end='', flush=True)
    result.check_returncode()
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-driver', action='store_true')
    parser.add_argument('--dtb', type=Path)
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = WORK / ('board-evidence.json' if args.dtb else
                         'compile-evidence.json' if args.compile_driver else 'evidence.json')
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        target = WORK / 'patched' / DRIVER
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, mode='r|xz') as source:
            for member in source:
                if member.name == 'linux-' + lock['linux']['tag'][1:] + '/' + DRIVER:
                    target.write_bytes(source.extractfile(member).read())
                    break
            else:
                raise RuntimeError('Missing locked USB driver')
        patches = [ROOT / 'kernel/patches' / name for name in
                   ('0006-axp-usb-work-lifetime.patch', '0008-axp-usb-absent-poll.patch')]
        for patch in patches:
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
        spec = importlib.util.spec_from_file_location('lifecycle', ROOT / 'tools/check-usb-lifecycle.py')
        lifecycle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lifecycle)
        source = target.read_text()
        include = '#include "axp20x_usb_gameshellneo.h"\n'
        if source.count(include) != 1:
            raise RuntimeError('Unexpected policy inclusion')
        lifecycle.headers(source.replace(include, ''), WORK)
        callbacks = WORK / 'usb_callbacks.h'
        callbacks.write_text(HEADER.read_text() + '\n' + callbacks.read_text())
        harness = ROOT / 'kernel/tests/usb_lifecycle_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-DNEO_USB_POLL_TEST']
        builder = lock['builder']
        if args.dtb:
            relative_dtb = args.dtb.resolve().relative_to(ROOT)
            board = subprocess.check_output([
                'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
                '--platform', builder['platform'], '--entrypoint', 'python3',
                '-e', 'PYTHONPATH=/armbian-pip/base/lib/python3.13/site-packages',
                '-v', f'{ROOT}:/project', '-w', '/project', builder['image'],
                'tools/usb_policy_dtb.py', str(relative_dtb)], text=True)
            (WORK / 'usb_board_fixture.h').write_text(board)
            flags.append('-DNEO_USB_BOARD_TEST')
        run(['cc', *flags, '-I', str(WORK), str(harness), '-o', str(WORK / 'native')])
        native = capture([str(WORK / 'native')])
        # Deliberately break each essential change: the harness must reject it.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        good = callbacks.read_text()
        mutations = {
            'absent_interval': good.replace('msecs_to_jiffies(250)', 'msecs_to_jiffies(50)', 1),
            'irq_deadline': good.replace(
                'queue_delayed_work(system_power_efficient_wq, &power->vbus_detect,',
                'mod_delayed_work(system_power_efficient_wq, &power->vbus_detect,', 1),
        }
        controls = {}
        try:
            for name, broken in mutations.items():
                if broken == good:
                    raise RuntimeError('Mutation no longer matches candidate: ' + name)
                callbacks.write_text(broken)
                binary = WORK / ('negative-' + name)
                run(['cc', *flags, '-I', str(WORK), str(harness), '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                if result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control did not fail as intended: ' + name)
                controls[name] = {'returncode': result.returncode, 'diagnostic': result.stderr.strip()}
        finally:
            callbacks.write_text(good)
        arm = capture(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
                       '--platform', builder['platform'], '--entrypoint', 'bash',
                       '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
                       'set -euo pipefail\n'
                       'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror '
                       '-DNEO_USB_POLL_TEST ' + ('-DNEO_USB_BOARD_TEST ' if args.dtb else '') +
                       '-static -I.local/build/usb-policy-tests '
                       'kernel/tests/usb_lifecycle_test.c -o .local/build/usb-policy-tests/arm\n'
                       'qemu-arm .local/build/usb-policy-tests/arm'])
        inputs = [*patches, HEADER, harness, ROOT / 'kernel/tests/usb_poll_of_shims.h',
                  ROOT / 'kernel/tests/usb_poll_cases.h', Path(__file__),
                  ROOT / 'tools/check-usb-lifecycle.py', ROOT / 'tools/kernel_checks.py']
        if args.dtb:
            inputs.extend([args.dtb.resolve(), ROOT / 'tools/usb_policy_dtb.py', WORK / 'usb_board_fixture.h'])
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        inputs={str(p.relative_to(ROOT)): sha256(p) for p in inputs},
                        native=native, arm32=arm, negative_controls=controls, builder=builder,
                        limits='Actual source with deterministic OF/register/workqueue shims; '
                               'not kernel concurrency, physical timing or battery qualification.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [DRIVER.replace('.c', '.o')])
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
