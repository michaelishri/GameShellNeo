#!/usr/bin/env python3
"""Actual MUSB deferred-restart ownership regressions with negative controls."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import tarfile

from kernel_checks import ROOT, archive_for, compile_objects, run, sha256

WORK = ROOT / '.local/build/musb-request-resume-tests'
PREFIX = 'drivers/usb/musb/'
FILES = ('musb_core.c', 'musb_core.h', 'musb_regs.h', 'musb_gadget.c',
          'musb_gadget.h', 'musb_gadget_ep0.c', 'sunxi.c')
# Earlier queue patches already changed these sources; the audit baseline is
# the queue-applied state 0037 will actually be applied to.
PRIOR_PATCHES = ('0011-musb-sunxi-context.patch', '0025-musb-system-sleep-pullup.patch',
                  '0030-musb-gadget-callback-lifetime.patch',
                  '0033-musb-sleep-session-retirement.patch')
CORE_FUNCTIONS = ('musb_queue_resume_work', 'musb_run_resume_work')
GADGET_FUNCTIONS = ('musb_ep_restart_resume_work', 'musb_free_request',
                    'musb_g_giveback', 'musb_gadget_dequeue', 'musb_gadget_queue')
PATCH = ROOT / 'kernel/patches/0037-musb-resume-request-ownership.patch'
HARNESS = ROOT / 'kernel/tests/musb_request_resume_test.c'


def function(text, name):
    match = re.search(r'^(?:static\s+)?[A-Za-z_][\w \t\*]*\b' + name + r'\s*\(', text, re.M)
    if not match:
        raise ValueError('Missing function: ' + name)
    body = text.index('{', match.start())
    depth = 0
    for index in range(body, len(text)):
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1] + '\n'
    raise ValueError('Unbalanced function body: ' + name)


def header_functions(core, gadget):
    parts = [function(core, name) for name in CORE_FUNCTIONS]
    parts += [function(gadget, name) for name in GADGET_FUNCTIONS[:3]]
    parts += [function(gadget, name) for name in GADGET_FUNCTIONS[3:]]
    return ''.join(parts)


def splice(source, name, body):
    original = function(source, name)
    assert source.count(original) == 1
    assert body != original
    return source.replace(original, body)


def mutate(queue, callback, resume):
    gadget = callback
    def queue_body():
        return function(queue, 'musb_gadget_queue')

    def callback_body():
        return function(callback, 'musb_ep_restart_resume_work')

    def resume_body():
        return function(resume, 'musb_run_resume_work')

    def splice(source, name, body):
        original = function(source, name)
        assert source.count(original) == 1 and body != original
        return source.replace(original, body)

    ignore = queue_body().replace(
        '\t\tif (!musb_ep->restart_pending) {\n\t\t\tmusb_ep->restart_pending = true;\n',
        '\t\tif (true) {\n\t\t\tmusb_ep->restart_pending = true;\n')
    assert ignore != queue_body()
    drop = resume_body().replace(
        '\t\tret = callback(musb, data);',
        '\t\tret = 0; (void)callback; (void)data; /* dropped work */')
    assert drop != resume_body()
    holds = resume_body().replace(
        '\t\tspin_unlock_irqrestore(&musb->list_lock, flags);\n\n'
        '\t\tret = callback(musb, data);',
        '\t\tret = callback(musb, data);')
    assert holds != resume_body()
    holds = holds.replace(
        '\t\tspin_lock_irqsave(&musb->list_lock, flags);\n\t}\n',
        '\t}\n')
    assert holds != resume_body()
    busy = callback_body().replace(
        '\tif (musb_ep->busy || !musb_ep->desc)\n\t\treturn 0;',
        '\tif (!musb_ep->desc)\n\t\treturn 0;')
    assert busy != callback_body()
    flag = callback_body().replace(
        '\n\tmusb_ep->restart_pending = false;\n\n\t/*',
        '\n\n\t/*')
    assert flag != callback_body()
    failed = queue_body().replace(
        '\t\t\t\tmusb_ep->restart_pending = false;\n', '')
    assert failed != queue_body()
    return dict(ignores_coalescing=(resume, splice(queue, 'musb_gadget_queue', ignore)),
                drops_pending_work=(splice(resume, 'musb_run_resume_work', drop), gadget),
                holds_list_lock_through_callbacks=(
                    splice(resume, 'musb_run_resume_work', holds), gadget),
                restarts_while_busy=(resume, splice(queue, 'musb_ep_restart_resume_work', busy)),
                skips_flag_reset=(resume, splice(queue, 'musb_ep_restart_resume_work', flag)),
                queue_failure_keeps_flag=(resume, splice(queue, 'musb_gadget_queue', failed)))


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
        shutil.rmtree(WORK / 'locked', ignore_errors=True)
        shutil.rmtree(WORK / 'patched', ignore_errors=True)
        target = WORK / 'locked' / PREFIX
        patched = WORK / 'patched' / PREFIX
        target.mkdir(parents=True, exist_ok=True)
        patched.mkdir(parents=True, exist_ok=True)
        prefix = 'linux-' + lock['linux']['tag'][1:] + '/' + PREFIX
        found = set()
        with tarfile.open(archive, mode='r|xz') as source:
            for entry in source:
                if entry.name in [prefix + name for name in FILES]:
                    name = entry.name.removeprefix(prefix)
                    data = source.extractfile(entry).read()
                    (target / name).write_bytes(data)
                    (patched / name).write_bytes(data)
                    found.add(name)
                    if len(found) == len(FILES):
                        break
        if found != set(FILES):
            raise ValueError('Incomplete locked source')
        for name in PRIOR_PATCHES:
            for tree in (WORK / 'locked', WORK / 'patched'):
                run(['patch', '--batch', '--fuzz=0', '-p1', '-i',
                     str(ROOT / 'kernel/patches' / name)], cwd=tree)
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCH)], cwd=WORK / 'patched')

        locked_core = (target / 'musb_core.c').read_text()
        locked_gadget = (target / 'musb_gadget.c').read_text()
        patched_core = (patched / 'musb_core.c').read_text()
        patched_gadget = (patched / 'musb_gadget.c').read_text()
        # The candidate must change exactly the audited ownership functions.
        assert function(locked_core, 'musb_run_resume_work') != function(patched_core, 'musb_run_resume_work')
        assert function(locked_core, 'musb_queue_resume_work') == function(patched_core, 'musb_queue_resume_work')
        for name in ('musb_ep_restart_resume_work', 'musb_gadget_queue'):
            assert function(locked_gadget, name) != function(patched_gadget, name), name
        for name in ('musb_free_request', 'musb_g_giveback', 'musb_gadget_dequeue'):
            assert function(locked_gadget, name) == function(patched_gadget, name), name

        good = header_functions(patched_core, patched_gadget)
        original = header_functions(locked_core, locked_gadget)
        cases = {'candidate': good, 'unfixed': original}
        cases.update({name: header_functions(core, gadget)
                      for name, (core, gadget)
                      in mutate(patched_gadget, patched_gadget, patched_core).items()})
        for name, value in cases.items():
            if name != 'candidate' and value == good:
                raise RuntimeError('Negative control did not mutate: ' + name)
        header = WORK / 'musb_request_resume_functions.h'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                 '-Wno-unused-parameter', '-I', str(WORK), str(HARNESS)]
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, value in cases.items():
                header.write_text(value)
                binary = WORK / name
                run(['cc', *flags, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=40)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Expected assertion failure: ' + name)
                results[name] = dict(returncode=result.returncode,
                                     output=result.stdout.strip(),
                                     error=result.stderr.strip())
                print(name + ': ' + ('passed' if name == 'candidate'
                                     else 'expected assertion failure'), flush=True)
            # With real allocation lifetimes the fixed paths must not touch
            # freed requests anywhere in the audited scenarios.
            header.write_text(good)
            binary = WORK / 'candidate-real-free'
            run(['cc', *flags, '-DREAL_FREE', '-o', str(binary)])
            real = subprocess.run([str(binary)], capture_output=True, text=True, timeout=40)
            (WORK / 'candidate-real-free.txt').write_text(real.stdout + real.stderr)
            real.check_returncode()
            results['candidate_real_free'] = dict(returncode=real.returncode,
                                                  output=real.stdout.strip())
            print('candidate-real-free: ' + real.stdout.strip(), flush=True)
        finally:
            header.write_text(good)
        builder = lock['builder']
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n'
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror '
            '-Wno-unused-parameter -static '
            '-I.local/build/musb-request-resume-tests kernel/tests/musb_request_resume_test.c '
            '-o .local/build/musb-request-resume-tests/arm\n'
            'qemu-arm .local/build/musb-request-resume-tests/arm'], text=True)
        print(arm, end='', flush=True)
        inputs = (PATCH, HARNESS, Path(__file__), ROOT / 'tools/kernel_checks.py',
                  ROOT / 'tools/kernel_sources.py', ROOT / 'tools/kernel-inputs.py',
                  ROOT / 'build/sources.lock.json')
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
            inputs={str(path.relative_to(ROOT)): sha256(path) for path in inputs},
            extracted={name: sha256(WORK / 'patched' / PREFIX / name) for name in FILES},
            generated={'musb_request_resume_functions.h': sha256(header)},
            native=results, arm32=arm.strip(), builder=builder,
            limits='Actual queue/dequeue/giveback/queue-resume-work/resume-run functions with '
                'modeled DMA, MMIO, completion-callback and PM boundaries under one fixture '
                'thread. Not SMP, hard-IRQ, ARM driver concurrency or hardware USB '
                'qualification. A completion re-queued from inside a deferred restart still '
                'lands in the busy window and waits for the next queue event, like the pinned '
                'dequeue path; tracked separately in FOLLOW-UP.md.')
        if args.compile_drivers:
            evidence['arm_build'] = compile_objects(archive, lock, WORK,
                ['drivers/usb/musb/musb_core.o', 'drivers/usb/musb/musb_gadget.o'])
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()