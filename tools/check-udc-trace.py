#!/usr/bin/env python3
"""Execute the pinned endpoint trace format, including its old shadowed-return bug."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import resource
import subprocess
import tarfile

from kernel_checks import ROOT, archive_for, compile_objects, run, sha256

WORK = ROOT / '.local/build/udc-trace-tests'
TARGET = 'drivers/usb/gadget/udc/trace.h'


def expression(source):
    event = source.split('DECLARE_EVENT_CLASS(udc_log_ep,', 1)[1].split('\nDEFINE_EVENT(', 1)[0]
    value = event.split('\tTP_printk(', 1)[1].rsplit('\n);', 1)[0].strip()
    return 'TP_printk(' + value + ';\n'


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
        member = 'linux-' + lock['linux']['tag'][1:] + '/' + TARGET
        original = None
        with tarfile.open(archive, mode='r|xz') as source:
            for entry in source:
                if entry.name == member:
                    original = source.extractfile(entry).read().decode()
                    break
        if original is None:
            raise RuntimeError('Missing locked UDC trace source')
        target = WORK / 'patched' / TARGET
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(original)
        patch = ROOT / 'kernel/patches/0024-usb-gadget-endpoint-trace-result.patch'
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
        patched = target.read_text()
        good = expression(patched)
        old = expression(original)
        if patched.replace(good.removesuffix(';\n'), old.removesuffix(';\n'), 1) != original:
            raise RuntimeError('Unexpected change outside the endpoint print expression')
        header = WORK / 'udc_ep_format.h'
        harness = ROOT / 'kernel/tests/udc_trace_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK), str(harness)]
        variants = dict(candidate=good, original=old,
                        constant_success=good.replace('__entry->ret)', '0)'),
                        wrong_sign=good.replace('__entry->ret)', '-__entry->ret)'))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, value in variants.items():
                if name != 'candidate' and value == good:
                    raise RuntimeError('Negative control did not change the expression')
                header.write_text(value)
                binary = WORK / name
                run(['cc', *flags, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control did not fail: ' + name)
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
            '-I.local/build/udc-trace-tests kernel/tests/udc_trace_test.c '
            '-o .local/build/udc-trace-tests/arm\n'
            'qemu-arm .local/build/udc-trace-tests/arm'], text=True)
        print(arm, end='', flush=True)
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        inputs={str(p.relative_to(ROOT)): sha256(p) for p in
                                (patch, harness, Path(__file__), ROOT / 'tools/kernel_checks.py')},
                        native=results, arm32=arm.strip(), builder=builder,
                        limits='Actual trace expression with synthetic records; no live endpoint operation.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, ['drivers/usb/gadget/udc/core.o'])
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
