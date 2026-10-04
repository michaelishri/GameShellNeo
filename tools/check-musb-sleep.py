#!/usr/bin/env python3
"""Exercise actual MUSB system-PM/connection functions with deterministic interleavings."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tarfile

from kernel_checks import ROOT, archive_for, compile_objects, run, sha256
from musb_callback_checks import callback_checks

WORK = ROOT / '.local/build/musb-sleep-tests'
PREFIX = 'drivers/usb/musb/'
FILES = ('musb_core.c', 'musb_core.h', 'musb_regs.h', 'musb_gadget.c', 'musb_gadget.h', 'musb_gadget_ep0.c', 'sunxi.c')


def function(text, name):
    match = re.search(r'^(?:static\s+)?(?:inline\s+)?(?:void|int|bool|struct\s+usb_gadget_driver\s*\*)\s*' + name + r'\([^;{]*\)\n\{', text, re.M)
    if not match:
        raise ValueError('Missing function: ' + name)
    return text[match.start():text.index('\n}', match.end()) + 3] + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    parser.add_argument('--compile-matrix', action='store_true',
                        help='Compile host/dual-role/module and PM stub alternatives')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = WORK / ('matrix-evidence.json' if args.compile_matrix else
                         'compile-evidence.json' if args.compile_drivers else 'evidence.json')
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        target = WORK / 'patched' / PREFIX
        target.mkdir(parents=True, exist_ok=True)
        prefix = 'linux-' + lock['linux']['tag'][1:] + '/' + PREFIX
        found = set()
        with tarfile.open(archive, mode='r|xz') as source:
            for entry in source:
                if entry.name in [prefix + name for name in FILES]:
                    name = entry.name.removeprefix(prefix)
                    (target / name).write_bytes(source.extractfile(entry).read())
                    found.add(name)
                    if len(found) == len(FILES):
                        break
        if found != set(FILES):
            raise ValueError('Incomplete locked source')
        dependencies = {}
        needed = ('drivers/usb/gadget/udc/core.c', 'include/linux/wait.h')
        with tarfile.open(archive, mode='r|xz') as source:
            version_prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
            for entry in source:
                if entry.name in [version_prefix + name for name in needed]:
                    dependencies[entry.name.removeprefix(version_prefix)] = source.extractfile(entry).read().decode()
                    if len(dependencies) == len(needed):
                        break
        if len(dependencies) != len(needed):
            raise ValueError('Missing locked UDC/wait source')
        patches = [ROOT / 'kernel/patches' / name for name in (
            '0011-musb-sunxi-context.patch', '0025-musb-system-sleep-pullup.patch',
            '0030-musb-gadget-callback-lifetime.patch', '0033-musb-sleep-session-retirement.patch')]
        for patch in patches:
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
        core = (target / 'musb_core.c').read_text()
        gadget = (target / 'musb_gadget.c').read_text()
        functions = ''.join(function(gadget, name) for name in (
            'musb_gadget_get_driver', 'musb_gadget_put_driver', 'musb_g_disconnect',
            'musb_pullup', 'musb_gadget_suspend', 'musb_gadget_resume',
            'musb_gadget_work', 'musb_gadget_pullup', 'musb_gadget_cleanup',
            'musb_gadget_stop'))
        functions += ''.join(function(core, name) for name in (
            'musb_save_context', 'musb_restore_context', 'musb_run_resume_work',
            'musb_suspend', 'musb_resume'))
        definitions = (target / 'musb_core.h').read_text() + (target / 'musb_regs.h').read_text()
        constants = (set(re.findall(r'\bMUSB_[A-Z0-9_]+', functions)) |
                     {'MUSB_POWER_HSENAB'}) - {'MUSB_HOST', 'MUSB_PERIPHERAL', 'MUSB_HST_MODE'}
        defs = ''
        for name in sorted(constants):
            match = re.search(r'^#define\s+' + name + r'\s+(.+)$', definitions, re.M)
            if not match:
                raise ValueError('Missing register definition: ' + name)
            defs += '#define ' + name + ' ' + match[1] + '\n'
        for name in ('musb_csr_regs', 'musb_context_registers'):
            defs += re.search(r'struct ' + name + r' \{.*?\n\};', definitions, re.S)[0] + '\n'
        (WORK / 'musb_sleep_defs.h').write_text(defs)
        header = WORK / 'musb_sleep_functions.h'
        harness = ROOT / 'kernel/tests/musb_sleep_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK), str(harness)]
        variants = dict(
            candidate=functions,
            missing_session_retirement=functions.replace(
                '\tif (musb->gadget_suspended && musb->g.speed != USB_SPEED_UNKNOWN)\n\t\tmusb_g_disconnect(musb);', ''),
            no_irq_drain=functions.replace('\t\tsynchronize_irq(musb->nIrq);', '\t\t(void)0;'),
            duplicate_disconnect=functions.replace(
                'driver = musb->g.speed != USB_SPEED_UNKNOWN ?\n\t\t musb_gadget_get_driver(musb) : NULL;',
                'driver = musb_gadget_get_driver(musb);'),
            no_detach=functions.replace('\tmusb_pullup(musb, 0);', '\t/* lost detach */', 1),
            stale_intent=functions.replace('musb->softconnect && musb->gadget_driver', '!!musb->gadget_driver'),
            ungated_work=functions.replace('\tif (!musb->gadget_suspended)\n\t\tmusb_pullup', '\tmusb_pullup', 1),
            early_restore=functions.replace('\tif (musb->gadget_suspended)\n\t\tpower &= ~MUSB_POWER_SOFTCONN;\n', ''),
            failed_resume_connects=functions.replace('musb->gadget_suspended && !error', 'musb->gadget_suspended'),
            loses_first_error=functions.replace('\t\t\t\tif (!error)\n\t\t\t\t\terror = ret;', '\t\t\t\terror = ret;'),
            enqueue_during_sleep=functions.replace('\t\tif (!musb->gadget_suspended)\n\t\t\tschedule', '\t\tschedule'),
            stop_keeps_pullup=functions.rsplit('\tmusb_pullup(musb, 0);', 1)[0] +
                functions.rsplit('\tmusb_pullup(musb, 0);', 1)[1],
        )
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, value in variants.items():
                if name != 'candidate' and value == functions:
                    raise ValueError('Negative control did not mutate: ' + name)
                header.write_text(value)
                binary = WORK / name
                run(['cc', *flags, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control did not fail: ' + name)
                results[name] = dict(returncode=result.returncode, output=result.stdout.strip(), error=result.stderr.strip())
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            header.write_text(functions)
        builder = lock['builder']
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n'
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
            '-I.local/build/musb-sleep-tests kernel/tests/musb_sleep_test.c '
            '-o .local/build/musb-sleep-tests/arm\n'
            'qemu-arm .local/build/musb-sleep-tests/arm'], text=True)
        print(arm, end='', flush=True)
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        inputs={str(p.relative_to(ROOT)): sha256(p) for p in
                                (*patches, harness, Path(__file__), ROOT / 'tools/kernel_checks.py',
                                 ROOT / 'tools/musb_callback_checks.py')},
                        native=results, arm32=arm.strip(), builder=builder,
                        limits='Actual source functions, deterministic boundary interleavings. '
                               'No electrical USB timing, host enumeration or scheduler concurrency qualification.')
        evidence['callbacks'] = callback_checks(
            WORK, target, dependencies['drivers/usb/gadget/udc/core.c'],
            dependencies['include/linux/wait.h'], builder, function)
        if args.compile_drivers or args.compile_matrix:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [
                PREFIX + 'musb_core.o', PREFIX + 'musb_gadget.o', PREFIX + 'musb_gadget_ep0.o', PREFIX + 'sunxi.o'])
        if args.compile_matrix:
            # These are compile-only alternatives, never board image configurations.
            matrices = {
                'host': (('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_DUAL_ROLE=n',
                          'CONFIG_USB_MUSB_HOST=y'), ('musb_core.o', 'musb_host.o', 'sunxi.o')),
                'dual-role': (('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_HOST=n',
                               'CONFIG_USB_MUSB_DUAL_ROLE=y'),
                              ('musb_core.o', 'musb_host.o', 'musb_gadget.o', 'musb_gadget_ep0.o', 'sunxi.o')),
                'module': (('CONFIG_USB_MUSB_HDRC=m', 'CONFIG_USB_MUSB_SUNXI=m'),
                           ('musb_core.o', 'musb_gadget.o', 'musb_gadget_ep0.o', 'musb_hdrc.o', 'sunxi.o')),
                'no-system-sleep': (('CONFIG_SUSPEND=n', 'CONFIG_HIBERNATION=n',
                                     'CONFIG_PM_SLEEP=n', 'CONFIG_PM=y'),
                                    ('musb_core.o', 'musb_gadget.o', 'musb_gadget_ep0.o', 'sunxi.o')),
                'no-pm': (('CONFIG_SUSPEND=n', 'CONFIG_HIBERNATION=n',
                          'CONFIG_PM_SLEEP=n', 'CONFIG_PM=n'),
                         ('musb_core.o', 'musb_gadget.o', 'musb_gadget_ep0.o', 'sunxi.o')),
            }
            evidence['arm_configurations'] = {}
            for name, (config, objects) in matrices.items():
                print('Compile-only MUSB configuration:', name, flush=True)
                evidence['arm_configurations'][name] = compile_objects(
                    archive, lock, WORK, [PREFIX + obj for obj in objects],
                    extra_config=config, project_config=False)
                if name == 'module':
                    record = evidence['arm_configurations'][name]
                    linked = record['scratch'] + '/output/' + PREFIX + 'musb_hdrc.o'
                    symbols = subprocess.check_output([
                        'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
                        '--platform', builder['platform'],
                        '--entrypoint', builder['cross_compile'] + 'readelf',
                        '-v', f'{ROOT}:/project', builder['image'],
                        '--wide', '--symbols', '/project/' + linked], text=True)
                    symbol_file = WORK / 'module-symbols.txt'
                    symbol_file.write_text(symbols)
                    required = ('musb_gadget_get_driver', 'musb_gadget_put_driver')
                    for symbol in required:
                        rows = [line.split() for line in symbols.splitlines()
                                if line.split() and line.split()[-1] == symbol]
                        if len(rows) != 1 or rows[0][3:5] != ['FUNC', 'GLOBAL'] or rows[0][6] == 'UND':
                            raise RuntimeError('Callback helper is unresolved in combined module: ' + symbol)
                    record['callback_helpers'] = dict(defined=list(required),
                                                      symbols_sha256=sha256(symbol_file))
                (WORK / 'matrix-progress.json').write_text(json.dumps(evidence, indent=2) + '\n')
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
