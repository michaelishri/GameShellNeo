#!/usr/bin/env python3
"""Check actual extcon/notifier dispatch with a modeled SRCU lifetime boundary."""
import argparse
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tarfile

from kernel_checks import ROOT, archive_for, compile_objects, run, sha256
from kernel_sources import atomic_json, locked

EXPECTED = '29 extcon scenarios passed (modeled SRCU/IRQ boundaries)'

WORK = ROOT / '.local/build/extcon-notifier-tests'
FILES = ('drivers/extcon/Kconfig', 'drivers/extcon/extcon.c',
         'drivers/extcon/extcon.h', 'include/linux/extcon.h', 'kernel/notifier.c')


def function(text, name):
    match = re.search(r'^(?:static\s+)?(?:int|void|struct extcon_dev\s*\*)\s*' +
                      name + r'\([^;{]*\)\n\{', text, re.M)
    if not match:
        raise ValueError('Missing actual function: ' + name)
    return text[match.start():text.index('\n}', match.end()) + 3] + '\n'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Expected exactly one source anchor: ' + old)
    return text.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with locked(WORK / '.lock'):
        evidence = WORK / ('compile-evidence.json' if args.compile_drivers else 'evidence.json')
        evidence.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        patched = WORK / 'patched'
        prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
        found = set()
        with tarfile.open(archive, mode='r|xz') as source:
            for entry in source:
                relative = entry.name.removeprefix(prefix)
                if entry.name.startswith(prefix) and relative in FILES:
                    target = patched / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.extractfile(entry).read())
                    found.add(relative)
                    if found == set(FILES):
                        break
        if found != set(FILES):
            raise ValueError('Incomplete pinned-source extraction')
        patches = []
        # Apply every current queue hunk touching the extracted framework files,
        # including provider lifetime; do not silently test an older subset.
        for patch in sorted((ROOT / 'kernel/patches').glob('*.patch')):
            chunks = re.split(r'(?=^diff --git )', patch.read_text(), flags=re.M)
            selected = [chunk for chunk in chunks if any(
                chunk.startswith('diff --git a/' + name + ' ') for name in FILES)]
            if selected:
                subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], cwd=patched,
                               input=''.join(selected), text=True, check=True)
                patches.append(patch)
        extcon = (patched / 'drivers/extcon/extcon.c').read_text()
        notifier = (patched / 'kernel/notifier.c').read_text()
        functions = ''.join(function(notifier, name) for name in (
            'notifier_chain_register', 'notifier_chain_unregister', 'notifier_call_chain',
            'raw_notifier_chain_register', 'raw_notifier_chain_unregister', 'raw_notifier_call_chain'))
        functions += ''.join(function(extcon, name) for name in (
            'find_cable_index_by_id', 'extcon_sync', 'extcon_register_notifier',
            'extcon_unregister_notifier', 'extcon_unregister_notifier_sync',
            'extcon_register_notifier_all', 'extcon_unregister_notifier_all',
            'extcon_dev_allocate', 'extcon_dev_free'))
        enter = '\tsrcu_idx = srcu_read_lock(&edev->notifier_srcu);\n'
        leave = '\tsrcu_read_unlock(&edev->notifier_srcu, srcu_idx);\n'
        call_all = '\traw_notifier_call_chain(&edev->nh_all, state, edev);\n'
        sync = '\t\tsynchronize_srcu(&edev->notifier_srcu);'
        variants = {
            'candidate': functions,
            'missing-drain': replace_once(functions, sync,
                '\t\tif (0) synchronize_srcu(&edev->notifier_srcu);'),
            'first-chain-outside-reader': replace_once(replace_once(functions, enter, ''),
                                                      call_all, enter + call_all),
            'all-chain-outside-reader': replace_once(replace_once(functions, leave, ''),
                                                    call_all, leave + call_all),
            'wait-under-extcon-lock': replace_once(functions, sync,
                '\t{\n\t\tunsigned long flags;\n\t\tspin_lock_irqsave(&edev->lock, flags);\n' +
                sync + '\n\t\tspin_unlock_irqrestore(&edev->lock, flags);\n\t}'),
            'allocation-failure-leaks': replace_once(functions, '\t\tkfree(edev);\n', ''),
            'missing-srcu-cleanup': replace_once(functions,
                '\tcleanup_srcu_struct(&edev->notifier_srcu);\n',
                '\tif (0) cleanup_srcu_struct(&edev->notifier_srcu);\n'),
            'failed-unlink-drains': replace_once(functions, '\tif (!ret)\n' + sync,
                                                '\tif (!ret || ret == -ENOENT)\n' + sync),
        }
        harness = ROOT / 'kernel/tests/extcon_notifier_test.c'
        header = WORK / 'extcon_notifier_functions.h'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread']
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, value in variants.items():
                header.write_text(value)
                binary = WORK / name
                run(['cc', *flags, '-I', str(WORK), str(harness), '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                (WORK / (name + '.log')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                    if result.stdout.strip() != EXPECTED:
                        raise ValueError('Incomplete source scenario result')
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control must fail an assertion: ' + name)
                results[name] = dict(returncode=result.returncode, stdout=result.stdout.strip(),
                                     stderr=result.stderr.strip(), extracted_sha256=sha256(header),
                                    binary_sha256=sha256(binary),
                                    log_sha256=sha256(WORK / (name + '.log')))
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            header.write_text(functions)
        builder = lock['builder']
        relative = WORK.relative_to(ROOT).as_posix()
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-e', f'NEO_DRIVER_CROSS={builder["cross_compile"]}',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n"${NEO_DRIVER_CROSS}gcc" ' + ' '.join(flags) +
            f' -static -I{relative} kernel/tests/extcon_notifier_test.c -o {relative}/candidate-arm\n'
            f'timeout 30 qemu-arm {relative}/candidate-arm'], text=True).strip()
        if arm != results['candidate']['stdout']:
            raise RuntimeError('Native and ARM32 results differ')
        print('ARM32: ' + arm, flush=True)
        builds = {}
        if args.compile_drivers:
            for name, config, project in (
                ('board', ('CONFIG_EXTCON=y', 'CONFIG_TREE_SRCU=y'), True),
                # USB_PHY is a hidden bool selecting EXTCON=y. Exclude that
                # stack for this framework-only module compilation check.
                ('module', ('CONFIG_USB_SUPPORT=n', 'CONFIG_EXTCON=m',
                            'CONFIG_TREE_SRCU=y'), False),
                ('tiny', ('CONFIG_EXTCON=y', 'CONFIG_SMP=n', 'CONFIG_PREEMPT_NONE=y',
                          'CONFIG_PREEMPT=n', 'CONFIG_TINY_SRCU=y'), False),
            ):
                objects = (['drivers/extcon/extcon-core.o'] if name == 'module' else
                           ['drivers/extcon/extcon.o', 'drivers/extcon/devres.o'])
                builds[name] = compile_objects(archive, lock, WORK, objects,
                    extra_config=config, project_config=project)
                combined = ROOT / builds[name]['scratch'] / 'output' / objects[0]
                symbols = subprocess.check_output(['readelf', '--wide', '--syms', str(combined)], text=True)
                (combined.parent / 'notifier-symbols.txt').write_text(symbols)
                api = [line.split() for line in symbols.splitlines()
                       if line.endswith(' extcon_unregister_notifier_sync')]
                grace = [line.split() for line in symbols.splitlines()
                         if line.endswith(' synchronize_srcu')]
                if (len(api) != 1 or api[0][4] != 'GLOBAL' or api[0][6] == 'UND' or
                        len(grace) != 1 or grace[0][6] != 'UND'):
                    raise RuntimeError('Object lacks expected notifier/SRCU linkage')
                builds[name]['symbols'] = dict(api=api[0], grace_period=grace[0],
                    scope='combined module' if name == 'module' else 'extcon core object')
        atomic_json(evidence, dict(schema_version=1, linux=lock['linux']['tag'],
            archive_sha256=sha256(archive), builder=builder,
            inputs={str(p.relative_to(ROOT)): sha256(p) for p in (
                *patches, harness, Path(__file__), ROOT / 'tools/kernel_checks.py',
                ROOT / 'tools/kernel_sources.py', ROOT / 'build/sources.lock.json')},
            sources={name: sha256(patched / name) for name in FILES},
            native=results, arm32=arm, arm32_binary_sha256=sha256(WORK / 'candidate-arm'), builds=builds,
            limits='Actual extcon/raw notifier functions, pthread-modeled SRCU and spinlocks, '
                   'simulated IRQ context and controlled sysfs/allocation. No Linux SRCU, '
                   'scheduler/IRQ or provider lifetime qualification. No Sunxi integration.'))
        print('Evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
