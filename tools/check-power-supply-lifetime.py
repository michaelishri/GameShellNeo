#!/usr/bin/env python3
"""Compare original and candidate deferred-notification teardown core functions."""
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tarfile

from kernel_checks import archive_for, run, sha256

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/build/power-supply-lifetime-tests'
DRIVER = 'drivers/power/supply/power_supply_core.c'


def function(source, name):
    match = re.search(r'^(?:static )?void ' + name + r'\([^;{]*\)\n\{', source, re.M)
    if not match:
        raise ValueError('Missing locked function: ' + name)
    return source[match.start():source.index('\n}', match.end()) + 3] + '\n'


def functions(source):
    return '\n'.join(function(source, name) for name in
                     ('power_supply_changed', 'power_supply_deferred_register_work',
                      'power_supply_unregister'))


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = WORK / 'evidence.json'
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
        with tarfile.open(archive, 'r|xz') as stream:
            for item in stream:
                if item.name == prefix + DRIVER:
                    source = stream.extractfile(item).read()
                    break
            else:
                raise ValueError('Locked power-supply core missing')
        driver = WORK / 'source' / DRIVER
        driver.parent.mkdir(parents=True, exist_ok=True)
        driver.write_bytes(source)
        patch = ROOT / 'kernel/patches/0013-power-supply-freezable-notifications.patch'
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'source')
        texts = {'original': functions(driver.read_text())}
        fix = ROOT / 'kernel/patches/0037-power-supply-unregister-producer.patch'
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(fix)], cwd=WORK / 'source')
        texts['reordered'] = functions(driver.read_text())
        harness = ROOT / 'kernel/tests/power_supply_lifetime_test.c'
        results = {}
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for name, text in texts.items():
            directory = WORK / name
            directory.mkdir(exist_ok=True)
            (directory / 'power_supply_lifetime_functions.h').write_text(text)
            expected = int(name == 'reordered')
            for negative in (False, True):
                label = name + ('_opposite_expectation' if negative else '')
                binary = directory / ('negative' if negative else 'native')
                run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                     '-DEXPECT_REORDERED=' + str(1 - expected if negative else expected),
                     '-I', str(directory), str(harness), '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                if not negative:
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise ValueError('Opposite-order negative control did not fail: ' + label)
                results[label] = dict(returncode=result.returncode, stdout=result.stdout.strip(),
                                      stderr=result.stderr.strip())
                print(label + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        builder = lock['builder']
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n'
            'for variant in original reordered; do\n'
            '  expected=0\n'
            '  if [ "$variant" = reordered ]; then expected=1; fi\n'
            '  directory=".local/build/power-supply-lifetime-tests/$variant"\n'
            '  arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
            '-DEXPECT_REORDERED="$expected" -I"$directory" '
            'kernel/tests/power_supply_lifetime_test.c -o "$directory/arm"\n'
            '  qemu-arm "$directory/arm"\n'
            'done'], text=True)
        output.write_text(json.dumps(dict(
            linux=lock['linux']['tag'], archive_sha256=sha256(archive),
            core_sha256=sha256(driver),
            inputs={str(p.relative_to(ROOT)): sha256(p) for p in
                    (patch, fix, harness, Path(__file__), ROOT / 'tools/kernel_checks.py')},
            native=results, arm32=arm.strip(), builder=builder,
            limits='Actual producer, deferred callback and unregister functions; deterministic '
                   'queue/lock/refcount/device API shims. Candidate patch 0037 compared with original. '
                   'No real scheduler, kref release, AXP detach, PM or hardware result.'
        ), indent=2) + '\n')
        print(arm, end='')
        print('Evidence:', output.relative_to(ROOT))


if __name__ == '__main__':
    main()
