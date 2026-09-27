#!/usr/bin/env python3
"""Test actual AXP USB probe lifetime; optionally compile the isolated ARM driver."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/build/usb-lifecycle-tests'
DRIVER = 'drivers/power/supply/axp20x_usb_power.c'
PATCH = ROOT / 'kernel/patches/0006-axp-usb-work-lifetime.patch'


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(command, **kwargs):
    subprocess.run(command, check=True, **kwargs)


def archive_for(lock):
    version = lock['linux']['tag'].removeprefix('v')
    archive = ROOT / f'.local/downloads/linux-{version}.tar.xz'
    expected = lock['linux']['tarball_sha256']
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=archive.parent) as temporary:
            with urllib.request.urlopen(lock['linux']['tarball_url'], timeout=60) as source:
                shutil.copyfileobj(source, temporary)
            temporary.flush()
            if sha256(Path(temporary.name)) != expected:
                raise RuntimeError('Downloaded Linux archive hash mismatch')
            shutil.copyfile(temporary.name, archive)
    if sha256(archive) != expected:
        raise RuntimeError('Locked Linux archive hash mismatch')
    return archive


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


def compile_driver(archive, lock):
    # Content-addressed scratch source/output; never overwrite diagnostic.3's
    # source tree, kernel objects, installed modules or completed image.
    queue = WORK / 'patches'
    run(['python3', str(ROOT / 'tools/kernel-inputs.py'), '--export', str(queue)])
    identity = hashlib.sha256((queue / 'manifest.json').read_bytes() +
                              (ROOT / 'kernel/gameshellneo.config').read_bytes() +
                              json.dumps(lock, sort_keys=True).encode()).hexdigest()[:16]
    scratch = WORK / ('kernel-' + identity)
    scratch.mkdir(exist_ok=True)
    source = scratch / 'source'
    if not source.exists():
        print('Extracting verified kernel to isolated driver-check scratch...', flush=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temporary:
            run(['tar', '-xJf', str(archive), '--strip-components=1', '-C', temporary])
            run(['python3', str(ROOT / 'tools/kernel-inputs.py'), '--apply', temporary])
            Path(temporary).rename(source)
    else:
        run(['python3', str(ROOT / 'tools/kernel-inputs.py'), '--apply', str(source)])
    builder = lock['builder']
    relative = scratch.relative_to(ROOT).as_posix()
    run(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
         '--platform', builder['platform'], '--entrypoint', 'bash', '-v', f'{ROOT}:/project',
         '-e', f'NEO_DRIVER_SCRATCH=/project/{relative}',
         '-e', f'NEO_DRIVER_CROSS={builder["cross_compile"]}',
         '-e', f'LOCALVERSION={lock["linux"]["localversion"]}',
         '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
         builder['image'], '-c',
         'set -euo pipefail\n'
         'export ARCH=arm CROSS_COMPILE="$NEO_DRIVER_CROSS"\n'
         'cd "$NEO_DRIVER_SCRATCH/source"\n'
         'output="$NEO_DRIVER_SCRATCH/output"\n'
         'make O="$output" sunxi_defconfig\n'
         'scripts/kconfig/merge_config.sh -m -O "$output" "$output/.config" '
         '/project/kernel/gameshellneo.config\n'
         'make O="$output" olddefconfig\n'
         'python3 /project/tools/check-kernel-config.py "$output/.config"\n'
         'make O="$output" -j1 drivers/power/supply/axp20x_usb_power.o\n'
         '"${NEO_DRIVER_CROSS}gcc" --version > "$NEO_DRIVER_SCRATCH/compiler.txt"\n'
         '"${NEO_DRIVER_CROSS}readelf" -h "$output/drivers/power/supply/axp20x_usb_power.o" '
         '> "$NEO_DRIVER_SCRATCH/elf-info.txt"\n'])
    obj = scratch / 'output' / DRIVER.replace('.c', '.o')
    return dict(scratch=relative, object_sha256=sha256(obj),
                config_sha256=sha256(scratch / 'output/.config'), builder=builder)


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
                        regression=regression(archive, lock),
                        limits='Actual driver probe/IRQ/poll code with deterministic lifetime shims; '
                               'not a running-kernel concurrency or hardware test.')
        if args.compile_driver:
            evidence['arm_build'] = compile_driver(archive, lock)
        evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', evidence_path.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
