#!/usr/bin/env python3
"""Qualify an isolated AXP223 control diagnostic in a real UML kernel and ARM build."""
import argparse
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from kernel_checks import ROOT, archive_for, build_objects, check_overrides, run, sha256
from kernel_sources import atomic_json, ensure_source, locked

WORK = ROOT / '.local/build/axp223-controls-tests'
CANDIDATE = ROOT / 'kernel/candidates/axp223-controls'
CASES = ('control_snapshot_test', 'control_error_flags_test', 'control_admission_test',
         'control_map_lock_test', 'control_pm_core_test', 'control_remove_test', 'control_file_test')


def added_file(name, text):
    return ''.join(difflib.unified_diff([], text.splitlines(True),
                                       fromfile='/dev/null', tofile='b/' + name)).encode()


def manifest(queue):
    return [dict(name=n, sha256=hashlib.sha256(data).hexdigest()) for n, data in queue]


def results_checked(report, log):
    counts = dict(tests=len(CASES), passed=len(CASES), failed=0, crashed=0, skipped=0, errors=0)
    if re.search(r'WARNING:|BUG:|possible circular locking|suspicious RCU|'
                 r'sleeping function called|Kernel panic|not ok |'
                 r'rcu:.*detected .*stalls|INFO: task .*blocked for more than', log):
        raise ValueError('Kernel diagnostic or failing TAP result')
    if (report.get('name') != 'KUnit Test Group' or report.get('arch') != 'um' or
            report.get('misc') != counts or report.get('test_cases') != [] or
            len(report.get('sub_groups', [])) != 1):
        raise ValueError('Expected exactly the requested UML group')
    suite = report['sub_groups'][0]
    cases = suite.get('test_cases', [])
    if (suite.get('name') != 'axp223-controls' or suite.get('arch') != 'um' or suite.get('misc') != counts or
            suite.get('sub_groups') != [] or len(cases) != len(CASES) or
            {c.get('name') for c in cases} != set(CASES) or
            any(c.get('status') != 'PASS' for c in cases) or
            any(name not in log for name in CASES)):
        raise ValueError('Missing, duplicated or failing diagnostic cases')
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-driver', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with locked(WORK / '.lock'):
        evidence = WORK / ('compile-evidence.json' if args.compile_driver else 'evidence.json')
        evidence.unlink(missing_ok=True)
        config = ROOT / 'kernel/tests/axp223-control-kunit.config'
        harness = ROOT / 'kernel/tests/axp223-control-kunit.c'
        inputs = [Path(__file__), config, harness, CANDIDATE / 'driver.patch',
                  CANDIDATE / 'axp223-control-diag.h', ROOT / 'tools/kernel_checks.py',
                  ROOT / 'tools/kernel_sources.py', ROOT / 'tools/kernel-inputs.py',
                  ROOT / 'tools/check-kernel-config.py', ROOT / 'kernel/gameshellneo.config',
                  ROOT / 'build/sources.lock.json']
        input_hashes = {str(p.relative_to(ROOT)): sha256(p) for p in inputs}
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        version = lock['linux']['tag'].removeprefix('v')
        if not (ROOT / f'.local/downloads/linux-{version}.tar.xz').is_file():
            raise ValueError('Offline check needs the locked Linux archive already downloaded')
        archive = archive_for(lock)
        spec = importlib.util.spec_from_file_location('control_inputs', ROOT / 'tools/kernel-inputs.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        queue = list(module.patches())
        active_manifest = manifest(queue)
        if any('axp223-controls' in name for name, _ in queue):
            raise ValueError('Diagnostic unexpectedly in active queue')
        patch = (CANDIDATE / 'driver.patch').read_bytes() + added_file(
            'drivers/mfd/axp223-control-diag.h', (CANDIDATE / 'axp223-control-diag.h').read_text())
        queue.append(('0040-axp223-controls-candidate.patch', patch))
        with locked(WORK / '.source-lock'):
            source, _, metadata = ensure_source(ROOT, WORK, archive, lock, manifest(queue), recorded_patches=queue)
        test_config = '''
config AXP223_CONTROL_KUNIT_TEST
	bool "AXP223 control diagnostic test (isolated kernel only)"
	depends on KUNIT=y && DEBUG_FS && PM_SLEEP
	select REGMAP
'''
        test_patch = added_file('drivers/mfd/axp223-control-kunit.c', harness.read_text())
        for name, extra in [('drivers/mfd/Kconfig', test_config),
                            ('drivers/mfd/Makefile', '\nobj-$(CONFIG_AXP223_CONTROL_KUNIT_TEST) += axp223-control-kunit.o\n')]:
            original = (source / name).read_text()
            test_patch += ''.join(difflib.unified_diff(original.splitlines(True),
                (original + extra).splitlines(True), fromfile='a/' + name, tofile='b/' + name)).encode()
        test_queue = queue + [('9999-axp223-controls-kunit-only.patch', test_patch)]
        with locked(WORK / '.source-lock'):
            test_source, _, test_metadata = ensure_source(ROOT, WORK, archive, lock,
                manifest(test_queue), recorded_patches=test_queue)
        if (test_source / 'drivers/mfd/axp223-control-diag.h').read_bytes() != (CANDIDATE / 'axp223-control-diag.h').read_bytes():
            raise ValueError('KUnit helper differs from candidate')
        builder = lock['builder']
        text = config.read_text()
        identity = hashlib.sha256((test_metadata['tree_sha256'] + text + builder['image']).encode()).hexdigest()[:16]
        scratch = WORK / ('uml-' + identity)
        scratch.mkdir(exist_ok=True)
        (scratch / 'kunit.config').write_text(text)
        relative = scratch.relative_to(ROOT).as_posix()
        output = scratch / 'output'
        if (output / 'test.log').exists():
            previous = scratch / 'previous-runs' / uuid.uuid4().hex
            previous.mkdir(parents=True)
            for path in (output / 'test.log', scratch / 'results.json'):
                if path.exists():
                    shutil.copyfile(path, previous / path.name)
        run(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
             '--platform', builder['platform'], '--network', 'none', '--pull', 'never',
             '--tmpfs', '/uml-tmp:rw,exec,size=2g,mode=1777', '-e', 'TMPDIR=/uml-tmp',
             '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
             '--entrypoint', 'bash', '-v', f'{ROOT}:/project', '-v', f'{test_source}:/kernel-source:ro',
             '-w', '/kernel-source', builder['image'], '-c',
             'set -euo pipefail\nulimit -c 0\n'
             'python3 -u tools/testing/kunit/kunit.py run --arch=um '
             f'--jobs={builder["jobs"]} --build_dir=/project/{relative}/output '
             f'--kunitconfig=/project/{relative}/kunit.config --timeout=120 '
             f'--json=/project/{relative}/results.json --kernel_args=uml_dir=/uml-tmp/state '
             'axp223-controls'])
        check_overrides(output / '.config', [s for s in text.splitlines() if s.startswith('CONFIG_')])
        cases = results_checked(json.loads((scratch / 'results.json').read_text()),
                                (output / 'test.log').read_text(errors='replace'))
        retained = scratch / 'accepted-runs' / uuid.uuid4().hex
        retained.mkdir(parents=True)
        artifacts = {}
        for name, path in {'linux': output / 'linux', 'config': output / '.config',
                           'test.log': output / 'test.log', 'results.json': scratch / 'results.json'}.items():
            digest = sha256(path)
            shutil.copyfile(path, retained / name)
            if sha256(retained / name) != digest:
                raise ValueError('Artifact changed during retention')
            artifacts[name] = digest
        record = dict(schema_version=1, suite='axp223-controls', linux=lock['linux']['tag'],
            builder=builder, inputs=input_hashes,
            source=metadata, test_source=test_metadata, candidate_patches=manifest(queue),
            test_patches=manifest(test_queue), cases=cases,
            artifact_dir=str(retained.relative_to(ROOT)), artifacts=artifacts,
            limits='Real regmap/Maple, kernel mutexes/threads, debugfs open/removal and device PM '
                   'prepare/complete under UML KASAN/lockdep with a scripted register bus. '
                   'No physical RSB, actual sleep, charger write or electrical calibration qualification.')
        if args.compile_driver:
            identity = hashlib.sha256((metadata['tree_sha256'] +
                sha256(ROOT / 'kernel/gameshellneo.config') + builder['image']).encode()).hexdigest()[:16]
            arm = WORK / ('arm-' + identity)
            arm.mkdir(exist_ok=True)
            (arm / 'extra.config').write_text('')
            record['arm_build'] = build_objects(source, arm, lock,
                ['drivers/mfd/axp20x-rsb.o'], (), True, metadata, offline=True)
        if input_hashes != {str(p.relative_to(ROOT)): sha256(p) for p in inputs}:
            raise ValueError('Diagnostic inputs changed during validation')
        if active_manifest != manifest(list(module.patches())):
            raise ValueError('Active patch queue changed during validation')
        atomic_json(retained / 'evidence.json', record)
        atomic_json(evidence, record)
        print('Evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
