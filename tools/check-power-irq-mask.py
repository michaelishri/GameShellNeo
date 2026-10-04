#!/usr/bin/env python3
"""Reproduce masked AXP223 edge loss using the locked regmap IRQ functions."""
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tarfile

from kernel_checks import ROOT, archive_for, run, sha256

WORK = ROOT / '.local/build/power-irq-mask-tests'
PATHS = ('drivers/base/regmap/regmap-irq.c', 'drivers/mfd/axp20x.c')


def function(source, name):
    match = re.search(r'^static void ' + name + r'\([^;{]*\)\n\{', source, re.M)
    if not match:
        raise ValueError('Missing locked function: ' + name)
    return source[match.start():source.index('\n}', match.end()) + 3] + '\n'


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        evidence = WORK / 'evidence.json'
        evidence.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
        sources = {}
        with tarfile.open(archive, 'r|xz') as stream:
            for item in stream:
                name = item.name.removeprefix(prefix)
                if name in PATHS:
                    sources[name] = stream.extractfile(item).read().decode()
                    if len(sources) == len(PATHS):
                        break
        if set(sources) != set(PATHS):
            raise ValueError('Incomplete locked sources')
        mfd = sources[PATHS[1]]
        chip = mfd[mfd.index('static const struct regmap_irq_chip axp22x_regmap_irq_chip ='):]
        chip = chip[:chip.index('\n};')]
        if not re.search(r'\.init_ack_masked\s*= true', chip):
            raise ValueError('AXP223 masked acknowledgement contract changed')
        definitions = ''
        for name in ('ACIN_PLUGIN', 'ACIN_REMOVAL', 'VBUS_PLUGIN', 'VBUS_REMOVAL'):
            match = re.search(r'INIT_REGMAP_IRQ\(AXP22X, ' + name + r',\s*0, (\d)\)', mfd)
            if not match:
                raise ValueError('Cable IRQ mapping changed')
            definitions += '#define ' + name + ' (1U << ' + match[1] + ')\n'
        (WORK / 'power_irq_mask_defs.h').write_text(definitions)
        functions = ''.join(function(sources[PATHS[0]], name) for name in
                            ('regmap_irq_sync_unlock', 'regmap_irq_enable', 'regmap_irq_disable'))
        variants = {'candidate': functions,
                    'no_masked_ack': functions.replace('if (!d->chip->init_ack_masked)', 'if (true)'),
                    'does_not_mask': functions.replace(' |= irq_data->mask;', ' |= 0;')}
        header = WORK / 'power_irq_mask_functions.h'
        harness = ROOT / 'kernel/tests/power_irq_mask_test.c'
        results = {}
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            for name, text in variants.items():
                if name != 'candidate' and text == functions:
                    raise ValueError('Mutation missed: ' + name)
                header.write_text(text)
                binary = WORK / name
                run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK),
                     str(harness), '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise ValueError('Mutation did not fail an assertion: ' + name)
                results[name] = dict(returncode=result.returncode, stdout=result.stdout.strip(), stderr=result.stderr.strip())
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            header.write_text(functions)
        builder = lock['builder']
        arm = subprocess.check_output(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash', '-v', f'{ROOT}:/project',
            '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\narm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
            '-I.local/build/power-irq-mask-tests kernel/tests/power_irq_mask_test.c '
            '-o .local/build/power-irq-mask-tests/arm\nqemu-arm .local/build/power-irq-mask-tests/arm'], text=True)
        evidence.write_text(json.dumps(dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
            inputs={str(p.relative_to(ROOT)): sha256(p) for p in (harness, Path(__file__))},
            native=results, arm32=arm.strip(),
            limits='Actual regmap mask/sync functions and AXP223 bit mappings; simulated W1C registers and nested IRQ delivery. '
                   'Demonstrates loss is permitted, not that a particular physical edge latched.'), indent=2) + '\n')
        print(arm, end='')
        print('Evidence:', evidence.relative_to(ROOT))


if __name__ == '__main__':
    main()
