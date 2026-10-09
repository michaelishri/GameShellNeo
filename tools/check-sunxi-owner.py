#!/usr/bin/env python3
"""Exercise actual Sunxi child hooks against controlled lifetime boundaries."""
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

EXPECTED = 'Sunxi child ownership: 240 actual-source scenarios passed'

WORK = ROOT / '.local/build/sunxi-owner-tests'
FILE = 'drivers/usb/musb/sunxi.c'


def function(source, name):
    match = re.search(r'^static (?:int|void) ' + name + r'\([^;{]*\)\n\{', source, re.M)
    if not match:
        raise ValueError('Missing actual function: ' + name)
    return source[match.start():source.index('\n}', match.end()) + 3] + '\n'


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Expected one source anchor: ' + old)
    return source.replace(old, new, 1)


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
        target = patched / FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, mode='r|xz') as stream:
            name = 'linux-' + lock['linux']['tag'][1:] + '/' + FILE
            for entry in stream:
                if entry.name == name:
                    target.write_bytes(stream.extractfile(entry).read())
                    break
            else:
                raise ValueError('Missing pinned Sunxi source')
        patches = []
        for patch in sorted((ROOT / 'kernel/patches').glob('*.patch')):
            content = patch.read_text()
            chunks = re.split(r'(?=^diff --git )', content, flags=re.M)
            selected = [chunk for chunk in chunks if chunk.startswith('diff --git a/' + FILE + ' ')]
            if selected:
                subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], cwd=patched,
                               input=''.join(selected), text=True, check=True)
                patches.append(patch)
        source = target.read_text()
        definitions = '\n'.join(line for line in source.splitlines()
                                if line.startswith('#define SUNXI_MUSB_')) + '\n'
        start = source.index('struct sunxi_glue {')
        definitions += source[start:source.index('\n};', start) + 4] + '\n'
        functions = ''.join(function(source, name) for name in (
            'sunxi_musb_work', 'sunxi_musb_set_vbus', 'sunxi_musb_host_notifier',
            'sunxi_musb_init', 'sunxi_musb_exit', 'sunxi_musb_enable',
            'sunxi_musb_disable', 'sunxi_musb_set_mode', 'sunxi_musb_recover'))
        probe = function(source, 'sunxi_musb_probe')
        # Execute the exact parent-side worker and default-role initialization,
        # without pretending to model its platform/DT/resource acquisition.
        parent = '\tglue->initial_phy_mode = glue->phy_mode;\n'
        work = ('\tINIT_WORK(&glue->work, sunxi_musb_work);\n'
                '\tdisable_work(&glue->work);\n'
                '\tglue->host_nb.notifier_call = sunxi_musb_host_notifier;\n')
        if probe.count(parent) != 1 or probe.count(work) != 1:
            raise ValueError('Parent ownership initialization changed')
        functions += ('static void parent_work_init(struct sunxi_glue *glue)\n{\n' +
                      parent + work + '}\n')
        unregister = ('\tWARN_ON(extcon_unregister_notifier_sync(glue->extcon, EXTCON_USB_HOST,\n'
                      '\t\t\t\t\t\t&glue->host_nb));\n')
        variants = {
            'candidate': functions,
            'phy-failure-leaks-notifier': replace_once(functions,
                'error_unregister_notifier:\n' + unregister, 'error_unregister_notifier:\n'),
            'exit-async-unlink': replace_once(functions,
                '\tclear_bit(SUNXI_MUSB_FL_ENABLED, &glue->flags);\n' + unregister,
                '\tclear_bit(SUNXI_MUSB_FL_ENABLED, &glue->flags);\n' +
                unregister.replace('extcon_unregister_notifier_sync', 'extcon_unregister_notifier')),
            'exit-cancel-only': replace_once(functions,
                '\tdisable_work_sync(&glue->work);\n\n\tpm_runtime_put',
                '\tcancel_work_sync(&glue->work);\n\n\tpm_runtime_put'),
            'no-work-reenable': replace_once(functions, '\tenable_work(&glue->work);\n', ''),
            'no-role-reset': replace_once(functions,
                '\tglue->phy_mode = glue->initial_phy_mode;\n', ''),
            'no-initial-state': replace_once(functions,
                '\tset_bit(SUNXI_MUSB_FL_HOSTMODE_PEND, &glue->flags);\n\tenable_work',
                '\tenable_work'),
            'stale-host-state': replace_once(functions,
                '\t\thost = extcon_get_state(glue->extcon, EXTCON_USB_HOST);', '\t\thost = 0;'),
        }
        harness = ROOT / 'kernel/tests/sunxi_owner_test.c'
        (WORK / 'sunxi_owner_definitions.h').write_text(definitions)
        header = WORK / 'sunxi_owner_functions.h'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter']
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        native = {}
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
                    raise RuntimeError('Negative control did not fail an assertion: ' + name)
                native[name] = dict(returncode=result.returncode, stdout=result.stdout.strip(),
                                    stderr=result.stderr.strip(), extracted_sha256=sha256(header),
                                    binary_sha256=sha256(binary),
                                    log_sha256=sha256(WORK / (name + '.log')))
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            header.write_text(functions)
        relative = WORK.relative_to(ROOT).as_posix()
        builder = lock['builder']
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--network', 'none', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-e', f'NEO_DRIVER_CROSS={builder["cross_compile"]}',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n"${NEO_DRIVER_CROSS}gcc" ' + ' '.join(flags) +
            f' -static -I{relative} kernel/tests/sunxi_owner_test.c -o {relative}/candidate-arm\n'
            f'timeout 30 qemu-arm {relative}/candidate-arm'], text=True).strip()
        if arm != native['candidate']['stdout']:
            raise RuntimeError('Native and ARM32 results differ')
        print('ARM32: ' + arm, flush=True)
        builds = {}
        if args.compile_drivers:
            for mode, extra, project in (
                ('gadget', (), True),
                ('host', ('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_HOST=y'), False),
                ('dual', ('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_DUAL_ROLE=y'), False),
            ):
                builds[mode] = compile_objects(archive, lock, WORK,
                    ['drivers/usb/musb/sunxi.o', 'drivers/extcon/extcon.o'],
                    extra_config=extra, project_config=project)
        atomic_json(evidence, dict(schema_version=1, linux=lock['linux']['tag'],
            archive_sha256=sha256(archive), source_sha256=sha256(target), builder=builder,
            definitions_sha256=sha256(WORK / 'sunxi_owner_definitions.h'),
            inputs={str(p.relative_to(ROOT)): sha256(p) for p in (
                *patches, harness, Path(__file__), ROOT / 'tools/kernel_checks.py',
                ROOT / 'tools/kernel_sources.py', ROOT / 'build/sources.lock.json')},
            native=native, arm32=arm, arm32_binary_sha256=sha256(WORK / 'candidate-arm'), builds=builds,
            limits='Actual Sunxi child/worker hooks and parent initialization slice; '
                   'modeled workqueue, notifier selection/drain, power, register and PHY boundaries. '
                   'No actual concurrency, provider lifetime, complete core removal or hardware qualification.'))
        print('Evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
