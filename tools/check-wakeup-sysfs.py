#!/usr/bin/env python3
"""Qualify the actual wakeup sysfs frontend with native, ARM and PM object checks."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import uuid

from kernel_checks import ROOT, archive_for, check_overrides, sha256
from kernel_sources import atomic_json, ensure_source, locked
from managed_container import execute
from wakeup_sysfs_source import FILE, PATCH, checked_native, frontend, prepare, variants

FLAGS = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
         '-Wno-unused-parameter', '-Wno-sign-compare']
OBJECTS = ('drivers/base/power/sysfs.o', 'drivers/base/power/wakeup.o',
           'drivers/base/power/wakeup_stats.o')


def native(work, texts, harness):
    records = {}
    for name, source in texts.items():
        directory = work / 'variants' / name
        directory.mkdir(parents=True)
        header = directory / 'wakeup-sysfs-functions.h'
        header.write_text(source)
        records[name] = {}
        for mode, flags in (('native', FLAGS), ('sanitizer', [*FLAGS, '-O1', '-g',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie'])):
            binary = directory / mode
            command = ['cc', *flags, '-I', str(directory), str(harness), '-o', str(binary)]
            subprocess.run(command, check=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            (directory / (mode + '.stdout')).write_text(result.stdout)
            (directory / (mode + '.stderr')).write_text(result.stderr)
            record = dict(command=command, returncode=result.returncode,
                          binary_sha256=sha256(binary), extracted_sha256=sha256(header))
            atomic_json(directory / (mode + '-result.json'), record)
            record['cases'] = checked_native(name, result)
            records[name][mode] = record
            failures = sum(case['status'] == 'FAIL' for case in record['cases'])
            print(f'{name}/{mode}: {len(record["cases"])} cases, {failures} expected failures', flush=True)
    return records


def arm_reference(work, lock, texts, harness):
    """A fresh managed attempt; expected fixture exits stay inside its positive command."""
    relative = work.relative_to(ROOT).as_posix()
    program = '''import json, pathlib, subprocess, sys
sys.path.insert(0, 'tools')
from wakeup_sysfs_source import NATIVE_FAILURES, checked_native
from kernel_checks import sha256
from kernel_sources import atomic_json
root=pathlib.Path('/project')
work=root/sys.argv[1]
harness=root/sys.argv[2]
cross=sys.argv[3]
flags=json.loads(sys.argv[4])
records={}
for name in NATIVE_FAILURES:
    directory=work/'variants'/name
    binary=directory/'arm'
    subprocess.run([cross+'gcc', *flags, '-static', '-I', str(directory), str(harness), '-o', str(binary)], check=True)
    result=subprocess.run(['qemu-arm', str(binary)], capture_output=True, text=True, timeout=30)
    (directory/'arm.stdout').write_text(result.stdout)
    (directory/'arm.stderr').write_text(result.stderr)
    record=dict(returncode=result.returncode, binary_sha256=sha256(binary))
    atomic_json(directory/'arm-result.json', record)
    record['cases']=checked_native(name,result)
    records[name]=record
atomic_json(work/'arm-evidence.json',records)
'''
    builder = lock['builder']
    result = execute('wakeup-sysfs-arm', ['--pull=never', '--user', f'{os.getuid()}:{os.getgid()}',
        '--platform', builder['platform'], '--network', 'none', '--entrypoint', 'python3',
        '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c', program,
        relative, harness.relative_to(ROOT).as_posix(), builder['cross_compile'], json.dumps(FLAGS)],
        work / 'arm-attempt', timeout=300)
    evidence = json.loads((work / 'arm-evidence.json').read_text())
    if set(evidence) != set(texts):
        raise ValueError('ARM reference omitted a source variant')
    return dict(managed_result=result, variants=evidence)


def arm_objects(work, lock, archive, expected_frontend):
    spec = importlib.util.spec_from_file_location('wakeup_object_inputs', ROOT / 'tools/kernel-inputs.py')
    inputs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inputs)
    queue = inputs.patches()
    patch = ROOT / PATCH
    queue.append((patch.name, patch.read_bytes()))
    manifest = [dict(name=name, sha256=hashlib.sha256(data).hexdigest()) for name, data in queue]
    with locked(work / '.source-lock'):
        source, _, metadata = ensure_source(ROOT, work, archive, lock, manifest, recorded_patches=queue)
    if frontend((source / FILE).read_text()) != expected_frontend:
        raise ValueError('Full PM compiler source differs from the tested frontend')
    scratch = work / 'pm-objects'
    scratch.mkdir()
    extra = ('CONFIG_PM=y', 'CONFIG_PM_SLEEP=y', 'CONFIG_PM_SLEEP_DEBUG=y')
    (scratch / 'extra.config').write_text('\n'.join(extra) + '\n')
    builder = lock['builder']
    relative = scratch.relative_to(ROOT).as_posix()
    arguments = ['--pull=never', '--user', f'{os.getuid()}:{os.getgid()}',
        '--platform', builder['platform'], '--network', 'none', '--entrypoint', 'bash',
        '-v', f'{ROOT}:/project', '-v', f'{source}:/kernel-source:ro',
        '-e', f'NEO_WAKEUP_OUTPUT=/project/{relative}/output',
        '-e', f'NEO_WAKEUP_EXTRA=/project/{relative}/extra.config',
        '-e', 'ARCH=arm', '-e', f'CROSS_COMPILE={builder["cross_compile"]}',
        '-e', f'LOCALVERSION={lock["linux"]["localversion"]}',
        '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
        builder['image'], '-c',
        'set -euo pipefail\n'
        'make -C /kernel-source O="$NEO_WAKEUP_OUTPUT" sunxi_defconfig\n'
        'cd "$NEO_WAKEUP_OUTPUT"\n'
        '/kernel-source/scripts/kconfig/merge_config.sh -m -O "$NEO_WAKEUP_OUTPUT" '
        '"$NEO_WAKEUP_OUTPUT/.config" /project/kernel/gameshellneo.config "$NEO_WAKEUP_EXTRA"\n'
        'make -C /kernel-source O="$NEO_WAKEUP_OUTPUT" olddefconfig\n'
        'python3 /project/tools/check-kernel-config.py "$NEO_WAKEUP_OUTPUT/.config"\n'
        'make -C /kernel-source O="$NEO_WAKEUP_OUTPUT" -j1 ' + ' '.join(OBJECTS)]
    result = execute('wakeup-sysfs-pm-objects', arguments, work / 'pm-object-attempt', timeout=3600)
    check_overrides(scratch / 'output/.config', extra)
    return dict(managed_result=result, source=metadata,
                config_sha256=sha256(scratch / 'output/.config'),
                objects={name: sha256(scratch / 'output' / name) for name in OBJECTS})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-only', action='store_true', help='Run native/sanitizer source references only')
    args = parser.parse_args()
    base = ROOT / '.local/build/wakeup-sysfs-tests'
    base.mkdir(parents=True, exist_ok=True)
    with locked(base / '.lock'):
        evidence = base / 'evidence.json'
        evidence.unlink(missing_ok=True)
        work = base / 'runs' / uuid.uuid4().hex
        work.mkdir(parents=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        harness = ROOT / 'kernel/tests/wakeup-sysfs-reference.c'
        paths = [Path(__file__), ROOT / 'tools/wakeup_sysfs_source.py', harness, ROOT / PATCH,
                 ROOT / 'tools/kernel_checks.py', ROOT / 'tools/kernel_sources.py',
                 ROOT / 'tools/kernel-inputs.py', ROOT / 'tools/managed_container.py',
                 ROOT / 'tools/docker-stage.py', ROOT / 'kernel/gameshellneo.config',
                 ROOT / 'tools/tests/test_wakeup_sysfs.py',
                 ROOT / 'build/sources.lock.json', ROOT / 'Taskfile.yml']
        inputs = {str(path.relative_to(ROOT)): sha256(path) for path in paths}
        before, after, patches = prepare(ROOT, archive, lock, work / 'source')
        inputs.update({str(path.relative_to(ROOT)): sha256(path) for path in patches})
        texts = variants(before, after)
        atomic_json(work / 'plan.json', dict(inputs=inputs, host_only=args.host_only,
                    source_variants={name: hashlib.sha256(text.encode()).hexdigest()
                                     for name, text in texts.items()}))
        record = dict(inputs=inputs, linux=lock['linux']['tag'], archive_sha256=sha256(archive),
                      native=native(work, texts, harness),
                      limits='Exact extracted frontend; API/lock shims for source references. '
                             'Real allocation/kernfs/SRCU/lifetime requires the separate kernel suite.')
        if not args.host_only:
            record['arm_reference'] = arm_reference(work, lock, texts, harness)
            record['arm_objects'] = arm_objects(work, lock, archive, texts['candidate'])
        if any(sha256(ROOT / name) != digest for name, digest in inputs.items()):
            raise RuntimeError('Wakeup frontend inputs changed during qualification')
        atomic_json(work / 'evidence.json', record)
        atomic_json(evidence, record)
        print('Wakeup frontend evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
