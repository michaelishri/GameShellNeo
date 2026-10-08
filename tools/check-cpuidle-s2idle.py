#!/usr/bin/env python3
"""Test locked CPU-idle entry, scheduler and tick coordination without hardware."""
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

WORK = ROOT / '.local/build/cpuidle-s2idle-tests'
PATCHES = [ROOT / 'kernel/patches' / name for name in (
    '0027-cpuidle-state-zero-s2idle.patch', '0028-cpuidle-cpi-wfi-integration.patch')]
DRIVER = ROOT / 'kernel/overlay/drivers/cpuidle/cpuidle-cpi-wfi.c'
FILES = ('drivers/cpuidle/cpuidle.c', 'drivers/cpuidle/Kconfig.arm',
         'drivers/cpuidle/Makefile', 'kernel/sched/idle.c', 'kernel/time/tick-common.c',
         'arch/arm/kernel/cpuidle.c', 'include/linux/cpuidle.h')


def function(source, marker):
    if source.count(marker) != 1:
        raise ValueError('Review changed function marker: ' + marker)
    start = source.index(marker)
    return source[start:source.index('\n}', start) + 3] + '\n'


def prepare(archive, lock):
    original = {}
    with tarfile.open(archive, mode='r|xz') as source:
        for entry in source:
            name = entry.name.removeprefix('linux-' + lock['linux']['tag'][1:] + '/')
            if name in FILES:
                original[name] = source.extractfile(entry).read().decode()
            if len(original) == len(FILES):
                break
    if set(original) != set(FILES):
        raise ValueError('Incomplete locked CPU-idle source')
    for name, text in original.items():
        path = WORK / 'patched' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for patch in PATCHES:
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
    source = {name: (WORK / 'patched' / name).read_text() for name in FILES}
    # No changes to ordinary selection, the noinstr entry body, or tick ordering.
    for name, markers in {
        'drivers/cpuidle/cpuidle.c': ('static int find_deepest_state(',
                                    'static noinstr void enter_s2idle_proper('),
        'kernel/time/tick-common.c': ('void tick_freeze(', 'void tick_unfreeze('),
        'arch/arm/kernel/cpuidle.c': ('__cpuidle int arm_cpuidle_simple_enter(',),
    }.items():
        for marker in markers:
            if function(original[name], marker) != function(source[name], marker):
                raise ValueError('Unexpected change outside entry contract: ' + marker)
    cpuidle = source['drivers/cpuidle/cpuidle.c']
    header = source['include/linux/cpuidle.h']
    defs = ''.join(line + '\n' for line in header.splitlines()
                   if re.match(r'#define CPUIDLE_(?:FLAG_|STATE_DISABLED_|NAME_LEN|DESC_LEN)', line))
    for name in ('cpuidle_state', 'cpuidle_state_usage'):
        defs += re.search(r'struct ' + name + r' \{.*?\n\};', header, re.S)[0] + '\n'
    (WORK / 'cpuidle_defs.h').write_text(defs)
    pieces = []
    for name, markers in {
        'kernel/time/tick-common.c': ('void tick_freeze(', 'void tick_unfreeze('),
        'arch/arm/kernel/cpuidle.c': ('__cpuidle int arm_cpuidle_simple_enter(',),
        'drivers/cpuidle/cpuidle.c': ('bool cpuidle_not_available(', 'static int find_deepest_state(',
                                    'int cpuidle_find_deepest_state(',
                                    'static noinstr void enter_s2idle_proper(',
                                    'int cpuidle_enter_s2idle(', 'void cpuidle_unregister(',
                                    'int cpuidle_register('),
        'kernel/sched/idle.c': ('static int call_cpuidle_s2idle(', 'static int call_cpuidle(',
                              'static void idle_call_stop_or_retain_tick(',
                              'static void cpuidle_idle_call('),
    }.items():
        pieces.extend(function(source[name], marker) for marker in markers)
    pieces.append(re.sub(r'^#include[^\n]*\n', '', DRIVER.read_text(), flags=re.M))
    return '\n'.join(pieces)


def inspect_arm_wfi(build, lock):
    """Save the real ARM callback and aliased ARMv7 idle instruction sequence."""
    builder = lock['builder']
    paths = ('arch/arm/kernel/cpuidle.o', 'arch/arm/mm/proc-v7.o')
    outputs = []
    for index, path in enumerate(paths):
        command = ['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
                   '--platform', builder['platform'], '--entrypoint', 'arm-linux-gnueabihf-objdump',
                   '-v', f'{ROOT}:/project', builder['image']]
        text = subprocess.check_output(command + ['-drt', '/project/' + build['scratch'] + '/output/' + path], text=True)
        target = WORK / ('wfi-callback.txt' if index == 0 else 'wfi-instruction.txt')
        target.write_text(text)
        outputs.append((text, target))
    callback = re.search(r'<arm_cpuidle_simple_enter>:\n(.*?)(?:\n\n|\Z)', outputs[0][0], re.S)[1]
    if ('processor' not in callback or not re.search(r'\bldr\s+r3, \[r3, #24\]', callback) or
            not re.search(r'\bblx\s+r3\b', callback) or re.search(r'\b(?:cpsie|msr|psci)\b', callback)):
        raise RuntimeError('Review changed ARM processor idle dispatch')
    # Several processor families alias this function. objdump may label its body
    # cpu_ca15_do_idle even though cpu_v7_do_idle is at the same address.
    symbol = re.search(r'^([0-9a-f]+)\s+.*\bF\s+\.text\s+[0-9a-f]+\s+cpu_v7_do_idle$', outputs[1][0], re.M)
    if not symbol:
        raise RuntimeError('ARMv7 WFI symbol missing')
    address = int(symbol[1], 16)
    body = re.search(r'^0*' + format(address, 'x') + r' <[^>]+>:\n(.*?)(?:\n\n|\Z)', outputs[1][0], re.M | re.S)
    instructions = re.findall(r'^\s*[0-9a-f]+:\s+[0-9a-f]+\s+([a-z]+)\b', body[1], re.M) if body else []
    if instructions != ['dsb', 'wfi', 'bx']:
        raise RuntimeError('Review changed ARMv7 idle instruction sequence')
    return dict(instructions=instructions,
                outputs={str(path.relative_to(ROOT)): sha256(path) for _, path in outputs},
                limits='Compiled processor-table dispatch and ARMv7 implementation; '
                       'does not identify the live processor table or measure hardware residency.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-kernel', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        evidence_path = WORK / ('compile-evidence.json' if args.compile_kernel else 'evidence.json')
        evidence_path.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        functions = prepare(archive, lock)
        header = WORK / 'cpuidle_functions.h'
        harness = ROOT / 'kernel/tests/cpuidle_s2idle_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                 '-Wno-unused-parameter', '-Wno-sign-compare', '-I', str(WORK), str(harness)]
        variants = dict(
            candidate=functions,
            scheduler_rejects_zero=functions.replace('entered_state >= 0', 'entered_state > 0'),
            no_entry_is_success=functions.replace('\t\treturn -ENODEV;', '\t\treturn 0;', 1),
            disabled_zero_enters=functions.replace('dev->states_usage[0].disable ||', 'false ||'),
            coupled_zero_enters=functions.replace('(drv->states[0].flags & CPUIDLE_FLAG_COUPLED)', 'false'),
            irq_enabled_before_unfreeze=functions.replace('\ttick_unfreeze();', '\tlocal_irq_enable();\n\ttick_unfreeze();'),
            missing_tick_unfreeze=functions.replace('\ttick_unfreeze();', '\t/* missing unfreeze */'),
            no_all_cpu_freeze=functions.replace('tick_freeze_depth == num_online_cpus()', 'false', 1),
            early_timekeeping_freeze=functions.replace('tick_freeze_depth == num_online_cpus()', 'tick_freeze_depth == 1', 1),
            board_gate_inverted=functions.replace('!of_machine_is_compatible(', 'of_machine_is_compatible('),
            registration_error_ignored=functions.replace('return cpuidle_register(&cpi_wfi_driver, NULL);',
                                                         'cpuidle_register(&cpi_wfi_driver, NULL);\n\treturn 0;'),
            rollback_missing=functions.replace('\t\tcpuidle_unregister(drv);', '\t\t/* lost rollback */'),
        )
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, text in variants.items():
                if name != 'candidate' and text == functions:
                    raise ValueError('Negative control did not mutate: ' + name)
                header.write_text(text)
                binary = WORK / name
                run(['cc', *flags, '-o', str(binary)])
                result = subprocess.run([str(binary)], text=True, capture_output=True)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control did not fail by assertion: ' + name)
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
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -Wno-unused-parameter -Wno-sign-compare -static '
            '-I.local/build/cpuidle-s2idle-tests kernel/tests/cpuidle_s2idle_test.c '
            '-o .local/build/cpuidle-s2idle-tests/arm\n'
            'qemu-arm .local/build/cpuidle-s2idle-tests/arm'], text=True)
        print(arm, end='', flush=True)
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        inputs={str(path.relative_to(ROOT)): sha256(path) for path in
                                (*PATCHES, DRIVER, harness, Path(__file__), ROOT / 'tools/kernel_checks.py')},
                        native=results, arm32=arm.strip(), builder=builder,
                        limits='Actual entry, scheduler, registration loop and tick-freeze functions '
                               'with modeled CPU/IRQ/timer, registration and RCU boundaries. '
                               'Not full-kernel concurrency, actual WFI or hardware qualification.')
        if args.compile_kernel:
            # idle.c is included by build_policy.c; it is not a standalone Kbuild unit.
            objects = ['drivers/cpuidle/cpuidle.o', 'kernel/sched/build_policy.o',
                       'kernel/time/tick-common.o', 'arch/arm/kernel/cpuidle.o',
                       'arch/arm/mm/proc-v7.o']
            evidence['arm_builds'] = {
                'enabled': compile_objects(archive, lock, WORK,
                                           objects + ['drivers/cpuidle/cpuidle-cpi-wfi.o'],
                                           extra_config=('CONFIG_ARM_CPI_WFI_CPUIDLE=y',)),
                'disabled': compile_objects(archive, lock, WORK, objects,
                                            extra_config=('CONFIG_ARM_CPI_WFI_CPUIDLE=n',),
                                            project_config=False),
                'no_suspend': compile_objects(archive, lock, WORK, objects,
                                              extra_config=('CONFIG_SUSPEND=n', 'CONFIG_ARM_CPI_WFI_CPUIDLE=n'),
                                              project_config=False),
                'no_cpuidle': compile_objects(archive, lock, WORK, ['kernel/sched/build_policy.o'],
                                              extra_config=('CONFIG_CPU_IDLE=n', 'CONFIG_ARM_CPI_WFI_CPUIDLE=n'),
                                              project_config=False),
            }
            evidence['wfi_disassembly'] = inspect_arm_wfi(evidence['arm_builds']['enabled'], lock)
        evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', evidence_path.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
