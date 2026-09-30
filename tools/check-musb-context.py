#!/usr/bin/env python3
"""Check actual MUSB context functions, preserving supported register accesses."""
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
WORK = ROOT / '.local/build/musb-context-tests'
PREFIX = 'drivers/usb/musb/'
FILES = ('musb_core.c', 'musb_core.h', 'musb_regs.h', 'sunxi.c')


def functions(source):
    return 'static void musb_save_context(' + source.split(
        'static void musb_save_context(', 1)[1].split('static int musb_suspend(', 1)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = WORK / ('compile-evidence.json' if args.compile_drivers else 'evidence.json')
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        target = WORK / 'patched' / PREFIX
        target.mkdir(parents=True, exist_ok=True)
        originals = {}
        archive_prefix = 'linux-' + lock['linux']['tag'][1:] + '/' + PREFIX
        with tarfile.open(archive, mode='r|xz') as source:
            for member in source:
                if member.name in [archive_prefix + name for name in FILES]:
                    name = member.name.removeprefix(archive_prefix)
                    originals[name] = source.extractfile(member).read().decode()
                    (target / name).write_text(originals[name])
                    if len(originals) == len(FILES):
                        break
        if len(originals) != len(FILES):
            raise RuntimeError('Missing locked MUSB source')
        patch = ROOT / 'kernel/patches/0011-musb-sunxi-context.patch'
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
        core = (target / 'musb_core.h').read_text()
        good = functions((target / 'musb_core.c').read_text())
        original = functions(originals['musb_core.c'])
        baseline = original.replace('musb_save_context(', 'original_musb_save_context(').replace(
            'musb_restore_context(', 'original_musb_restore_context(')
        # Use real register values and context layouts, not copied definitions.
        tokens = sorted(set(re.findall(r'\bMUSB_[A-Z0-9_]+', good)) |
                        {'MUSB_INDEXED_EP'})
        defs = ''
        for token in tokens:
            match = re.search(r'^#define\s+' + token + r'\s+(.+)$',
                              core + '\n' + originals['musb_regs.h'], re.M)
            if not match:
                raise RuntimeError('Missing source definition: ' + token)
            defs += '#define ' + token + ' ' + match[1] + '\n'
        defs += re.search(r'struct musb_csr_regs \{.*?\n\};', core, re.S)[0] + '\n'
        defs += re.search(r'struct musb_context_registers \{.*?\n\};', core, re.S)[0] + '\n'
        sunxi = (target / 'sunxi.c').read_text()
        quirks = re.search(r'sunxi_musb_ops = \{\s*\.quirks\s*=\s*([^,]+),', sunxi)[1]
        defs += '#define SUNXI_QUIRKS (' + quirks + ')\n'
        # Keep every accessor and its unsupported-access diagnostics intact.
        if sunxi.replace(quirks, 'MUSB_INDEXED_EP', 1) != originals['sunxi.c']:
            raise RuntimeError('Unexpected Sunxi change outside capability declaration')
        (WORK / 'musb_context_defs.h').write_text(defs)
        header = WORK / 'musb_context_functions.h'
        harness = ROOT / 'kernel/tests/musb_context_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK), str(harness)]
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        guard_line = '\tif (!(musb->ops->quirks & MUSB_NO_ULPI_BUSCONTROL))\n'
        variants = dict(candidate=good, original=original,
                        lost_read_guard=good.replace(guard_line, '', 1),
                        lost_write_guard=good.rsplit(guard_line, 1)[0] + good.rsplit(guard_line, 1)[1],
                        skip_all=good.replace(guard_line, '\tif (0)\n'))
        results = {}
        try:
            for name, text in variants.items():
                if name != 'candidate' and text == good:
                    raise RuntimeError('Mutation did not match: ' + name)
                header.write_text(baseline + text)
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
            header.write_text(baseline + good)
        builder = lock['builder']
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n'
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
            '-I.local/build/musb-context-tests kernel/tests/musb_context_test.c '
            '-o .local/build/musb-context-tests/arm\n'
            'qemu-arm .local/build/musb-context-tests/arm'], text=True)
        print(arm, end='', flush=True)
        inputs = (patch, harness, Path(__file__), ROOT / 'tools/kernel_checks.py')
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        inputs={str(p.relative_to(ROOT)): sha256(p) for p in inputs},
                        native=results, arm32=arm.strip(), builder=builder,
                        limits='Actual context functions with register/API shims. '
                               'No physical MMIO, USB traffic or resume timing measured.')
        if args.compile_drivers:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [
                PREFIX + 'musb_core.o', PREFIX + 'sunxi.o'])
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
