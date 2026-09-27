#!/usr/bin/env python3
"""Test actual AXP USB probe lifetime; optionally compile the isolated ARM driver."""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import tarfile

from kernel_checks import archive_for, compile_objects, run, sha256

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/build/usb-lifecycle-tests'
DRIVER = 'drivers/power/supply/axp20x_usb_power.c'
PATCH = ROOT / 'kernel/patches/0006-axp-usb-work-lifetime.patch'


def probe_parts(source):
    marker = 'static int axp20x_usb_power_probe(struct platform_device *pdev)'
    prefix, tail = source.split(marker, 1)
    probe, suffix = tail.split('\nstatic const struct of_device_id axp20x_usb_power_match[]', 1)
    return prefix, marker + probe, suffix


def headers(source, directory):
    prefix, probe, _ = probe_parts(source)
    structures = prefix.split('struct axp20x_usb_power;', 1)[1].split(
        'static bool axp20x_usb_vbus_needs_polling', 1)[0]
    callbacks = prefix.split('static bool axp20x_usb_vbus_needs_polling', 1)[1].split(
        'static void axp717_usb_power_poll_vbus', 1)[0]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'usb_structs.h').write_text('struct axp20x_usb_power;\n' + structures)
    (directory / 'usb_callbacks.h').write_text('static bool axp20x_usb_vbus_needs_polling' + callbacks)
    (directory / 'usb_probe.h').write_text(probe)


def regression(archive, lock):
    version = lock['linux']['tag'].removeprefix('v')
    print('Reading the driver from the hash-verified Linux archive...', flush=True)
    with tarfile.open(archive, mode='r|xz') as source:
        for member in source:
            if member.name == f'linux-{version}/{DRIVER}':
                with source.extractfile(member) as stream:
                    original = stream.read().decode()
                break
        else:
            raise RuntimeError('Locked driver absent from archive')
    target = WORK / 'patched' / DRIVER
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(original)
    run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCH)], cwd=WORK / 'patched')
    candidate = target.read_text()
    old_prefix, _, old_suffix = probe_parts(original)
    new_prefix, _, new_suffix = probe_parts(candidate)
    if old_prefix != new_prefix or old_suffix != new_suffix:
        raise RuntimeError('Lifetime patch changed code outside the tested probe')
    results = {}
    for name, text in (('original', original), ('candidate', candidate)):
        directory = WORK / name
        headers(text, directory)
        binary = directory / 'lifetime-test'
        run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(directory),
             str(ROOT / 'kernel/tests/usb_lifecycle_test.c'), '-o', str(binary)])
        result = subprocess.run([str(binary)], text=True, capture_output=True)
        (directory / 'result.txt').write_text(result.stdout + result.stderr)
        print(f'{name}: {result.stdout.strip()}', flush=True)
        results[name] = dict(returncode=result.returncode, output=result.stdout.strip())
        if name == 'original':
            if result.returncode != 1 or 'poll/IRQ accessed an unregistered supply' not in result.stderr:
                raise RuntimeError('Negative control did not reproduce the expected lifetime violation')
        elif result.returncode:
            print(result.stderr, end='', flush=True)
            raise RuntimeError('Patched driver failed lifetime regression')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-driver', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as lockfile:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        evidence_path = WORK / ('compile-evidence.json' if args.compile_driver else 'evidence.json')
        evidence_path.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                        patch_sha256=sha256(PATCH),
                        harness_sha256=sha256(ROOT / 'kernel/tests/usb_lifecycle_test.c'),
                        workflow_sha256=sha256(Path(__file__).resolve()),
                        kernel_checks_sha256=sha256(ROOT / 'tools/kernel_checks.py'),
                        regression=regression(archive, lock),
                        limits='Actual driver probe/IRQ/poll code with deterministic lifetime shims; '
                               'not a running-kernel concurrency or hardware test.')
        if args.compile_driver:
            build = compile_objects(archive, lock, WORK, [DRIVER.replace('.c', '.o')])
            build['object_sha256'] = build.pop('objects')[DRIVER.replace('.c', '.o')]
            evidence['arm_build'] = build
        evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', evidence_path.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
