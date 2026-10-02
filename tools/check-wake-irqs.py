#!/usr/bin/env python3
"""Exercise locked IRQ-core/regmap/wake clients; optionally compile complete ARM drivers."""
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
WORK = ROOT / '.local/build/wake-irq-tests'
PATHS = ('drivers/base/regmap/regmap-irq.c', 'drivers/input/misc/axp20x-pek.c',
         'drivers/rtc/rtc-sun6i.c', 'drivers/power/supply/axp20x_ac_power.c', 'kernel/irq/manage.c')


def section(source, first, last):
    return source[source.index(first):source.index(last, source.index(first))]


def functions(tree):
    texts = {p: (tree / p).read_text() for p in PATHS}
    reg = texts[PATHS[0]]
    return '\n'.join((section(texts[PATHS[4]], 'static int set_irq_wake_real(', 'EXPORT_SYMBOL(irq_set_irq_wake);'),
        section(reg, 'static bool regmap_irq_wake_parent_atomic(', 'static const struct irq_chip regmap_irq_chip'),
        section(texts[PATHS[1]], 'static int axp20x_pek_disarm_wake(', 'static int __maybe_unused axp20x_pek_resume_noirq'),
        section(texts[PATHS[2]], 'static int sun6i_rtc_disarm_wake(', '\n#endif'),
        section(texts[PATHS[3]], 'static int axp20x_ac_power_disarm_wake(', '\n#endif')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = WORK / ('compile-evidence.json' if args.compile_drivers else 'evidence.json')
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text()); archive = archive_for(lock)
        tree = WORK / 'patched'
        with tarfile.open(archive, 'r|xz') as source:
            remaining = set(PATHS); prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
            for item in source:
                name = item.name.removeprefix(prefix)
                if name in remaining:
                    p = tree / name; p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(source.extractfile(item).read()); remaining.remove(name)
                    if not remaining: break
            if remaining: raise ValueError('Missing locked sources')
        patch = ROOT / 'kernel/patches/0019-wake-irq-error-ownership.patch'
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=tree)
        good = functions(tree); header = WORK / 'wake_irq_functions.h'
        harness = ROOT / 'kernel/tests/wake_irq_test.c'
        cases = {'candidate': good,
            'lost_parent_error': good.replace('return irq_set_irq_wake(d->irq, on);', '{ irq_set_irq_wake(d->irq, on); return 0; }'),
            'slow_parent_selected': good.replace('!parent->irq_bus_lock &&', 'true &&'),
            'lost_pek_ownership': good.replace('pek->wake_dbf = true;', 'pek->wake_dbf = false;'),
            'lost_rtc_ownership': good.replace('chip->wake_armed = true;', 'chip->wake_armed = false;'),
            'lost_ac_cleanup': good.replace('power->wake_armed = false;', 'power->wake_armed = true;')}
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); results = {}
        try:
            for name, text in cases.items():
                if name != 'candidate' and text == good: raise ValueError('Mutation missed: ' + name)
                header.write_text(text); binary = WORK / name
                run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK), str(harness), '-o', str(binary)])
                p = subprocess.run([str(binary)], capture_output=True, text=True)
                (WORK / (name + '.txt')).write_text(p.stdout + p.stderr)
                if name == 'candidate': p.check_returncode()
                elif p.returncode == 0 or 'Assertion' not in p.stderr: raise ValueError('Negative control did not reject: ' + name)
                results[name] = dict(returncode=p.returncode, stdout=p.stdout.strip(), stderr=p.stderr.strip())
                print(name + ': ' + (p.stdout.strip() or 'expected assertion rejection'), flush=True)
        finally: header.write_text(good)
        builder = lock['builder']
        arm = subprocess.check_output(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash', '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\narm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
            '-I.local/build/wake-irq-tests kernel/tests/wake_irq_test.c -o .local/build/wake-irq-tests/arm\n'
            'qemu-arm .local/build/wake-irq-tests/arm'], text=True)
        evidence = dict(linux=lock['linux'], archive_sha256=sha256(archive), native=results, arm32=arm.strip(),
            inputs={str(p.relative_to(ROOT)): sha256(p) for p in (patch, harness, Path(__file__))},
            limits='Actual core and callbacks with deterministic IRQ/device shims. Not kernel lockdep, real wake, bus I/O failure or concurrency qualification.')
        if args.compile_drivers:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [p.replace('.c', '.o') for p in PATHS[:-1]])
        output.write_text(json.dumps(evidence, indent=2) + '\n'); print('Evidence:', output, flush=True)


if __name__ == '__main__': main()
