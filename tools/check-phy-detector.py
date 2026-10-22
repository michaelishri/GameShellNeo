#!/usr/bin/env python3
"""Qualify Sun4i post-notification hardware retirement without a device."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from kernel_checks import ROOT, archive_for, compile_objects, sha256
from kernel_sources import atomic_json, locked
from native_source_variants import run_variants
from phy_detector_source import FILE, functions, prepare, variants

EXPECTED = 'Sun4i PHY detector: 162 generation/resource/poll scenarios passed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    work = ROOT / '.local/build/phy-detector-tests'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        output = work / ('compile-evidence.json' if args.compile_drivers else 'evidence.json')
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        source, patches = prepare(ROOT, archive, lock, work / 'patched')
        body = functions(source.read_text())
        header = work / 'phy_detector_functions.h'
        harness = ROOT / 'kernel/tests/phy_detector_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror']
        native = run_variants(work, header, body, variants(source.read_text()), harness, flags, EXPECTED)
        sanitize = work / 'candidate-sanitize'
        subprocess.run(['cc', *flags, '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-fno-pie', '-no-pie', '-I', str(work),
                        str(harness), '-o', str(sanitize)], check=True)
        # The host observes children with ptrace, which LeakSanitizer cannot
        # support. This static harness allocates no heap; test ASan and UBSan.
        sanitizer_env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                             UBSAN_OPTIONS='halt_on_error=1')
        sanitized = subprocess.check_output([str(sanitize)], text=True, env=sanitizer_env).strip()
        if sanitized != EXPECTED:
            raise ValueError('Incomplete sanitized detector result')
        builder, relative = lock['builder'], work.relative_to(ROOT).as_posix()
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--network', 'none', '--pull', 'never',
            '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
            '--entrypoint', 'bash', '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\narm-linux-gnueabihf-gcc ' + ' '.join(flags) +
            f' -static -I{relative} kernel/tests/phy_detector_test.c -o {relative}/candidate-arm\n'
            f'qemu-arm {relative}/candidate-arm'], text=True).strip()
        if arm != EXPECTED:
            raise ValueError('Incomplete ARM32 detector result')
        builds = {}
        if args.compile_drivers:
            for name, extra, project in (
                ('gadget', (), True),
                ('host', ('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_HOST=y'), False),
                ('dual', ('CONFIG_USB_MUSB_GADGET=n', 'CONFIG_USB_MUSB_DUAL_ROLE=y'), False),
                ('modules', ('CONFIG_PHY_SUN4I_USB=m',), False),
                ('no-pm', ('CONFIG_PM=n', 'CONFIG_PM_SLEEP=n', 'CONFIG_SUSPEND=n',
                           'CONFIG_HIBERNATION=n'), False),
            ):
                builds[name] = compile_objects(archive, lock, work, [FILE.replace('.c', '.o')],
                    extra_config=extra, project_config=project, candidate_profile='musb-retirement')
        paths = (*patches, harness, Path(__file__), ROOT / 'tools/phy_detector_source.py',
                 ROOT / 'tools/kernel_candidates.py', ROOT / 'tools/kernel_checks.py',
                 ROOT / 'tools/kernel_sources.py', ROOT / 'tools/native_source_variants.py',
                 ROOT / 'build/sources.lock.json')
        atomic_json(output, dict(schema_version=1, suite='phy-detector',
            linux=lock['linux']['tag'], archive_sha256=sha256(archive), source_sha256=sha256(source),
            inputs={str(path.relative_to(ROOT)): sha256(path) for path in paths},
            native=native, sanitized=sanitized, sanitizer_binary_sha256=sha256(sanitize),
            arm32=arm, arm32_binary_sha256=sha256(work / 'candidate-arm'), builder=builder, builds=builds,
            limits='Actual detector/exit/IRQ/notifier functions and exact init publication; '
                   'modeled clocks/reset/MMIO, generic-PHY locking, notifications and workqueues. '
                   'No kernel scheduling, complete provider/consumer graph or physical removal claim.'))
        print('Detector evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
