#!/usr/bin/env python3
"""Qualify managed-wakeup initialization with actual inline source and ARM32."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from kernel_checks import ROOT, archive_for, sha256
from kernel_sources import atomic_json, locked
from managed_container import execute
from managed_wakeup_init_source import LIMITS, PATCH, checked_native, prepare, variants

FLAGS = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
         '-Wno-unused-parameter', '-Wno-sign-compare']


def native(work, texts, harness):
    records = {}
    compiler = subprocess.check_output(['cc', '--version'], text=True)
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=0:halt_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')
    for name, source in texts.items():
        directory = work / 'variants' / name
        directory.mkdir(parents=True)
        header = directory / 'managed-wakeup-inline.h'
        header.write_text(source)
        records[name] = {}
        for mode, flags in (('native', FLAGS), ('sanitizer', [*FLAGS, '-O1', '-g',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie'])):
            binary = directory / mode
            command = ['cc', *flags, '-I', str(directory), str(harness), '-o', str(binary)]
            subprocess.run(command, check=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True,
                                    timeout=30, env=environment)
            (directory / (mode + '.stdout')).write_text(result.stdout)
            (directory / (mode + '.stderr')).write_text(result.stderr)
            record = dict(command=command, returncode=result.returncode, compiler=compiler,
                          binary_sha256=sha256(binary), extracted_sha256=sha256(header))
            atomic_json(directory / (mode + '-result.json'), record)
            record['cases'] = checked_native(name, result)
            records[name][mode] = record
            failures = sum(bool(row['failures']) for row in record['cases'])
            print(f'{name}/{mode}: five cases, {failures} expected failures', flush=True)
    return records


def arm_reference(work, lock, texts, harness):
    """Run only the finite source references inside one positive managed command."""
    program = '''import json,pathlib,subprocess,sys
sys.path.insert(0,'tools')
from managed_wakeup_init_source import checked_native
from kernel_checks import sha256
from kernel_sources import atomic_json
root=pathlib.Path('/project')
work=root/sys.argv[1]
harness=root/sys.argv[2]
cross=sys.argv[3]
flags=json.loads(sys.argv[4])
compiler=subprocess.check_output([cross+'gcc','--version'],text=True)
emulator=subprocess.check_output(['qemu-arm','--version'],text=True)
records={}
for name in ('return-ignored','candidate'):
    directory=work/'variants'/name
    binary=directory/'arm'
    command=[cross+'gcc',*flags,'-static','-I',str(directory),str(harness),'-o',str(binary)]
    subprocess.run(command,check=True)
    result=subprocess.run(['qemu-arm',str(binary)],capture_output=True,text=True,timeout=30)
    (directory/'arm.stdout').write_text(result.stdout)
    (directory/'arm.stderr').write_text(result.stderr)
    record=dict(command=command,returncode=result.returncode,compiler=compiler,
                emulator=emulator,binary_sha256=sha256(binary))
    atomic_json(directory/'arm-result.json',record)
    record['cases']=checked_native(name,result)
    records[name]=record
atomic_json(work/'arm-evidence.json',records)
'''
    builder = lock['builder']
    result = execute('managed-wakeup-init-arm', ['--pull=never', '--user', f'{os.getuid()}:{os.getgid()}',
        '--platform', builder['platform'], '--network', 'none', '--entrypoint', 'python3',
        '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c', program,
        work.relative_to(ROOT).as_posix(), harness.relative_to(ROOT).as_posix(),
        builder['cross_compile'], json.dumps(FLAGS)], work / 'arm-attempt', timeout=300)
    evidence = json.loads((work / 'arm-evidence.json').read_text())
    if set(evidence) != set(texts):
        raise ValueError('ARM reference omitted a source variant')
    return dict(managed_result=result, variants=evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-only', action='store_true', help='Native/sanitizer references only')
    parser.add_argument('--compile-drivers', action='store_true', help='Only complete selected ARM objects')
    args = parser.parse_args()
    if args.host_only and args.compile_drivers:
        parser.error('--host-only and --compile-drivers are separate qualifications')
    base = ROOT / '.local/build/managed-wakeup-init-tests'
    base.mkdir(parents=True, exist_ok=True)
    with locked(base / '.lock'):
        evidence = base / ('driver-evidence.json' if args.compile_drivers else 'evidence.json')
        evidence.unlink(missing_ok=True)
        work = base / 'runs' / uuid.uuid4().hex
        work.mkdir(parents=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        harness = ROOT / 'kernel/tests/managed_wakeup_init_test.c'
        paths = [Path(__file__), ROOT / 'tools/managed_wakeup_init_source.py', harness, ROOT / PATCH,
                 ROOT / 'tools/kernel_checks.py', ROOT / 'tools/kernel_sources.py',
                 ROOT / 'tools/kernel-inputs.py', ROOT / 'tools/managed_container.py',
                 ROOT / 'tools/docker-stage.py', ROOT / 'tools/tests/test_managed_wakeup_init.py',
                 ROOT / 'build/sources.lock.json', ROOT / 'Taskfile.yml']
        if args.compile_drivers:
            paths += [ROOT / 'tools/managed_wakeup_init_kunit.py',
                      ROOT / 'kernel/tests/managed-wakeup-init-kunit.c',
                      ROOT / 'kernel/tests/managed-wakeup-init-kunit.h',
                      ROOT / 'kernel/tests/managed-wakeup-init-kunit.config',
                      ROOT / 'kernel/gameshellneo.config']
        inputs = {str(path.relative_to(ROOT)): sha256(path) for path in paths}
        before, after, devres, patches = prepare(ROOT, archive, lock, work / 'source')
        inputs.update({str(path.relative_to(ROOT)): sha256(path) for path in patches})
        texts = variants(before, after, devres)
        atomic_json(work / 'plan.json', dict(inputs=inputs, host_only=args.host_only,
                    compile_drivers=args.compile_drivers,
                    source_variants={name: hashlib.sha256(text.encode()).hexdigest()
                                     for name, text in texts.items()}))
        record = dict(schema_version=1, inputs=inputs, linux=lock['linux']['tag'],
                      archive_sha256=sha256(archive), limits=LIMITS)
        if args.compile_drivers:
            from managed_wakeup_init_kunit import driver_objects
            record['driver_objects'] = driver_objects(ROOT, lock, archive, work, texts['candidate'])
        else:
            record['native'] = native(work, texts, harness)
            if not args.host_only:
                record['arm_reference'] = arm_reference(work, lock, texts, harness)
        if any(sha256(ROOT / name) != digest for name, digest in inputs.items()):
            raise RuntimeError('Managed-wakeup inputs changed during qualification')
        atomic_json(work / 'evidence.json', record)
        atomic_json(evidence, record)
        print('Managed-wakeup evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
