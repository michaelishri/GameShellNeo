#!/usr/bin/env python3
"""Reproduce PEK/input-core suspend release semantics from locked C source."""
import fcntl
import json
import os
from pathlib import Path
import resource
import subprocess
import tarfile

from kernel_checks import ROOT, archive_for, run, sha256

WORK = ROOT / '.local/build/power-key-event-tests'
PATHS = ('drivers/input/input.c', 'drivers/input/misc/axp20x-pek.c',
         'include/uapi/linux/input-event-codes.h')


def function(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        evidence = WORK / 'evidence.json'
        evidence.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        texts = {}
        with tarfile.open(archive, 'r|xz') as stream:
            prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
            for member in stream:
                name = member.name.removeprefix(prefix)
                if name in PATHS:
                    texts[name] = stream.extractfile(member).read().decode()
                    if len(texts) == len(PATHS):
                        break
        if set(texts) != set(PATHS):
            raise ValueError('Locked event source missing')
        core, pek = texts[PATHS[0]], texts[PATHS[1]]
        good = '\n'.join(function(core, sig) for sig in (
            'static int input_get_disposition(', 'static bool input_dev_release_keys(',
            'static int input_dev_suspend(', 'static int input_dev_resume('))
        good += function(pek, 'static irqreturn_t axp20x_pek_irq(')
        # The deployed wake patch changes other callbacks, not these functions.
        installed = ROOT / '.local/sources' / ('linux-' + lock['linux']['tag'][1:])
        if installed.exists():
            for name, signatures in ((PATHS[0], ('static int input_get_disposition(',
                    'static bool input_dev_release_keys(', 'static int input_dev_suspend(',
                    'static int input_dev_resume(')),
                    (PATHS[1], ('static irqreturn_t axp20x_pek_irq(',))):
                current = (installed / name).read_text()
                for sig in signatures:
                    if function(current, sig) != function(texts[name], sig):
                        raise ValueError('Built source changes the tested event semantics: ' + sig)
        (WORK / 'input-event-codes.h').write_text(texts[PATHS[2]])
        header = WORK / 'power_key_event_functions.h'
        harness = ROOT / 'kernel/tests/power_key_events_test.c'
        cases = dict(candidate=good,
            missing_suspend_clear=good.replace('if (input_dev_release_keys(input_dev))',
                                              'if (false && input_dev_release_keys(input_dev))'),
            missing_duplicate_filter=good.replace('if (!!test_bit(code, dev->key) != !!value)', 'if (true)'),
            wrong_release_edge=good.replace('input_report_key(idev, KEY_POWER, false);',
                                           'input_report_key(idev, KEY_POWER, true);'))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, text in cases.items():
                if name != 'candidate' and text == good:
                    raise ValueError('Negative control did not modify source')
                header.write_text(text)
                binary = WORK / name
                run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                     '-I', str(WORK), str(harness), '-o', str(binary)])
                p = subprocess.run([str(binary)], capture_output=True, text=True)
                if name == 'candidate':
                    p.check_returncode()
                elif p.returncode == 0 or 'Assertion' not in p.stderr:
                    raise ValueError('Negative control failed to reject: ' + name)
                results[name] = dict(returncode=p.returncode, stdout=p.stdout.strip(), stderr=p.stderr.strip())
                print(name + ': ' + (p.stdout.strip() or 'expected assertion rejection'), flush=True)
        finally:
            header.write_text(good)
        builder = lock['builder']
        arm = subprocess.check_output(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash', '-v', f'{ROOT}:/project',
            '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\narm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
            '-I.local/build/power-key-event-tests kernel/tests/power_key_events_test.c '
            '-o .local/build/power-key-event-tests/arm\nqemu-arm .local/build/power-key-event-tests/arm'], text=True)
        evidence.write_text(json.dumps(dict(linux=lock['linux'], archive_sha256=sha256(archive),
            native=results, arm32=arm.strip(),
            inputs={str(p.relative_to(ROOT)):sha256(p) for p in (harness, Path(__file__))},
            limits='Locked actual PEK IRQ, input disposition and suspend/resume functions; deterministic delivery/bitset/lock shims. Not live IRQ chronology, coalescing, locking, physical state or hardware PM qualification.'), indent=2)+'\n')
        print('Evidence:', evidence, flush=True)


if __name__ == '__main__':
    main()
