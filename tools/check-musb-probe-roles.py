#!/usr/bin/env python3
"""Check MUSB probe registration ownership using the patched source helper."""
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

WORK = ROOT / '.local/build/musb-probe-roles'
PREFIX = 'drivers/usb/musb/'
PRIOR = ('0011-musb-sunxi-context.patch', '0025-musb-system-sleep-pullup.patch',
         '0030-musb-gadget-callback-lifetime.patch',
         '0033-musb-sleep-session-retirement.patch',
         '0037-musb-resume-request-ownership.patch')
PATCH = ROOT / 'kernel/patches/0038-musb-probe-role-unwind.patch'
LATER = ('0039-musb-core-irq-retirement.patch', '0040-musb-core-work-retirement.patch',
         '0041-musb-runtime-pm-retirement.patch', '0042-musb-resume-work-retirement.patch')
HARNESS = ROOT / 'kernel/tests/musb_probe_roles_test.c'
EXPECTED = 'MUSB probe roles: 25 cases passed (17 successful retries)'


def replace_once(text, before, after):
    if text.count(before) != 1 or before == after:
        raise ValueError('Expected a unique changed source anchor')
    return text.replace(before, after, 1)


def role_sources(before, after):
    """Require the sole caller change to preserve all other probe cleanup."""
    marker = 'static int musb_init_roles(struct musb *musb, int power)\n{'
    if after.count(marker) != 1:
        raise ValueError('Missing or duplicate production role initializer')
    start = after.index(marker)
    helper = after[start:after.index('\n}', start) + 2] + '\n'
    init = before.index('musb_init_controller(struct')
    start = before.index('\tswitch (musb->port_mode) {', init)
    end = before.index('\n\tmusb_init_debugfs(musb);', start)
    block = before[start:end]
    replaced = replace_once(before, block,
        '\tstatus = musb_init_roles(musb, plat->power);\n'
        '\tif (status < 0)\n\t\tgoto fail3;\n')
    anchor = '/*\n * Perform generic per-controller initialization.'
    expected = replace_once(replaced, anchor,
        '/* Unwind only roles whose registration completed successfully. */\n' + helper + '\n' + anchor)
    if after != expected:
        raise ValueError('Unexpected changes outside the role setup boundary')
    baseline = ('static int musb_init_roles(struct musb *musb, int power)\n{\n'
                '\tstruct musb_hdrc_platform_data pdata = { .power = power };\n'
                '\tstruct musb_hdrc_platform_data *plat = &pdata;\n'
                '\tint status = 0;\n' + block.replace('goto fail3;', 'return status;') +
                '\treturn status;\n}\n')
    return helper, baseline


def variants(helper, baseline):
    tail = ('\tif (gadget_registered)\n\t\tmusb_gadget_cleanup(musb);\n'
            '\tif (host_registered)\n\t\tmusb_host_cleanup(musb);')
    return {
        'candidate': helper,
        'missing-resume-close': replace_once(helper, '\tmusb_shutdown_resume_work(musb);\n', ''),
        'original-leaks-registration': baseline,
        'misses-host-cleanup': replace_once(helper, '\t\tmusb_host_cleanup(musb);', '\t\t(void)0;'),
        'misses-gadget-cleanup': replace_once(helper, '\t\tmusb_gadget_cleanup(musb);', '\t\t(void)0;'),
        'reversed-cleanup': replace_once(helper, tail,
            '\tif (host_registered)\n\t\tmusb_host_cleanup(musb);\n'
            '\tif (gadget_registered)\n\t\tmusb_gadget_cleanup(musb);'),
        'unregistered-host': replace_once(helper, 'host_registered = false;', 'host_registered = true;'),
        'unregistered-gadget': replace_once(helper, 'gadget_registered = false;', 'gadget_registered = true;'),
        'masks-mode-error': replace_once(helper, '\treturn status;\n}', '\treturn 0;\n}'),
        'cleans-success': replace_once(helper, 'if (status >= 0)', 'if (false)'),
    }


def check_output(output):
    if output.strip() != EXPECTED:
        raise ValueError('Incomplete probe role result')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with locked(WORK / '.lock'):
        receipt = WORK / ('compile-evidence.json' if args.compile_drivers else 'evidence.json')
        receipt.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        patches = [ROOT / 'kernel/patches' / name for name in PRIOR] + [PATCH]
        targets = set()
        for patch in patches:
            targets.update(re.findall(r'^\+\+\+ b/([^\t\n]+)', patch.read_text(), re.M))
        source = WORK / 'patched'
        prefix = 'linux-' + lock['linux']['tag'].removeprefix('v') + '/'
        found = set()
        with tarfile.open(archive, 'r|xz') as stream:
            for entry in stream:
                name = entry.name.removeprefix(prefix)
                if entry.name.startswith(prefix) and name in targets:
                    path = source / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(stream.extractfile(entry).read())
                    found.add(name)
                    if found == targets:
                        break
        if found != targets:
            raise ValueError('Incomplete pinned source extraction')
        for patch in patches[:-1]:
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=source)
        core = source / PREFIX / 'musb_core.c'
        before = core.read_text()
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCH)], cwd=source)
        helper, baseline = role_sources(before, core.read_text())
        for name in LATER:
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i',
                 str(ROOT / 'kernel/patches' / name)], cwd=source)
        from musb_irq_checks import function
        helper = function(core.read_text(), 'musb_init_roles')
        patches.extend(ROOT / 'kernel/patches' / name for name in LATER)
        header = WORK / 'musb_probe_roles_function.h'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function']
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, content in variants(helper, baseline).items():
                header.write_text(content)
                binary = WORK / name
                run(['cc', *flags, '-I', str(WORK), str(HARNESS), '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                if name == 'candidate':
                    result.check_returncode()
                    check_output(result.stdout)
                elif result.returncode != -6 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Negative control did not assert: ' + name)
                results[name] = dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
                                     source_sha256=sha256(header), binary_sha256=sha256(binary))
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            header.write_text(helper)
        builder = lock['builder']
        relative = WORK.relative_to(ROOT).as_posix()
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--network', 'none', '--entrypoint', 'bash',
            '-e', 'NEO_CROSS=' + builder['cross_compile'],
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n"${NEO_CROSS}gcc" ' + ' '.join(flags) +
            f' -static -I{relative} kernel/tests/musb_probe_roles_test.c -o {relative}/arm\n'
            f'qemu-arm {relative}/arm'], text=True)
        check_output(arm)
        print(arm, end='', flush=True)
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive), builder=builder,
            inputs={str(p.relative_to(ROOT)): sha256(p) for p in (*patches, HARNESS, Path(__file__),
                ROOT / 'tools/kernel_checks.py', ROOT / 'tools/kernel_sources.py',
                ROOT / 'tools/kernel-inputs.py', ROOT / 'tools/musb_irq_checks.py', ROOT / 'build/sources.lock.json')},
            native=results, arm32=arm.strip(), arm32_binary_sha256=sha256(WORK / 'arm'),
            limits='Actual probe role helper, controlled registration/mode/cleanup boundaries. '
                   'Not actual HCD/UDC registration, callback concurrency, hardware mode selection, '
                   'complete probe/remove retirement or board qualification.')
        if args.compile_drivers:
            objects = [PREFIX + name for name in ('musb_core.o', 'musb_gadget.o', 'musb_gadget_ep0.o', 'sunxi.o')]
            evidence['arm_configurations'] = {'project': compile_objects(archive, lock, WORK, objects)}
            for name, config, extra in (
                ('host', ('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_DUAL_ROLE=n', 'CONFIG_USB_MUSB_HOST=y'),
                 ('musb_core.o', 'musb_host.o', 'sunxi.o')),
                ('dual-role', ('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_HOST=n', 'CONFIG_USB_MUSB_DUAL_ROLE=y'),
                 ('musb_core.o', 'musb_host.o', 'musb_gadget.o', 'musb_gadget_ep0.o', 'sunxi.o')),
                ('module', ('CONFIG_USB_MUSB_HDRC=m', 'CONFIG_USB_MUSB_SUNXI=m'),
                 ('musb_core.o', 'musb_gadget.o', 'musb_gadget_ep0.o', 'musb_hdrc.o', 'sunxi.o')),
            ):
                print('Compiling MUSB role configuration:', name, flush=True)
                evidence['arm_configurations'][name] = compile_objects(
                    archive, lock, WORK, [PREFIX + obj for obj in extra],
                    extra_config=config, project_config=False)
        atomic_json(receipt, evidence)
        print('Evidence:', receipt.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
