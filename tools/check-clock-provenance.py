#!/usr/bin/env python3
"""Qualify an isolated clock provenance diagnostic in a real UML kernel and ARM build."""
import argparse
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from clock_provenance import loads, replay
from kernel_checks import ROOT, archive_for, build_objects, check_overrides, run, sha256
from kernel_sources import atomic_json, ensure_source, locked

WORK = ROOT / '.local/build/clock-provenance-tests'
CANDIDATE = ROOT / 'kernel/candidates/clock-provenance'
CASES = ('clock_exact_counter_test', 'clock_retry_and_branches_test',
         'clock_writer_bound_test', 'clock_access_and_export_test', 'clock_stop_drain_test')


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
    if (suite.get('name') != 'neo-clock-provenance' or suite.get('arch') != 'um' or suite.get('misc') != counts or
            suite.get('sub_groups') != [] or len(cases) != len(CASES) or
            {c.get('name') for c in cases} != set(CASES) or
            any(c.get('status') != 'PASS' for c in cases) or
            any(name not in log for name in CASES)):
        raise ValueError('Missing, duplicated or failing diagnostic cases')
    return cases


REQUIRED_HOOKS = {'neo_clock_begin', 'neo_clock_end', 'neo_clock_target',
                  'neo_clock_read', 'neo_clock_accepted', 'neo_clock_writer_read',
                  'neo_clock_publish'}


def validate_symbols(off, on, definitions):
    if off:
        raise ValueError('Disabled ARM objects still reference diagnostic hooks')
    if on != REQUIRED_HOOKS or not on <= definitions:
        raise ValueError('Enabled ARM hooks are missing or unresolved')


def object_hooks(path, undefined):
    text = subprocess.check_output(['nm', '-P', '--undefined-only' if undefined else '--defined-only',
                                    str(path)], text=True)
    return {line.split()[0] for line in text.splitlines()
            if line.split() and line.split()[0].startswith('neo_clock_')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-driver', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with locked(WORK / '.lock'):
        evidence = WORK / ('compile-evidence.json' if args.compile_driver else 'evidence.json')
        evidence.unlink(missing_ok=True)
        config = ROOT / 'kernel/tests/neo-clock-diag.config'
        harness = ROOT / 'kernel/tests/neo-clock-diag-test.c'
        inputs = [Path(__file__), config, harness, CANDIDATE / 'hooks.patch',
                  CANDIDATE / 'neo-clock-diag.h', CANDIDATE / 'neo-clock-diag.c', ROOT / 'tools/kernel_checks.py',
                  ROOT / 'tools/kernel_sources.py', ROOT / 'tools/kernel-inputs.py',
                  ROOT / 'tools/check-kernel-config.py', ROOT / 'kernel/gameshellneo.config',
                  ROOT / 'build/sources.lock.json', ROOT / 'tools/clock_provenance.py']
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
        if any('clock-provenance' in name for name, _ in queue):
            raise ValueError('Diagnostic unexpectedly in active queue')
        patch = (CANDIDATE / 'hooks.patch').read_bytes()
        for name in ('neo-clock-diag.h', 'neo-clock-diag.c'):
            patch += added_file('kernel/time/' + name, (CANDIDATE / name).read_text())
        queue.append(('0040-clock-provenance-candidate.patch', patch))
        with locked(WORK / '.source-lock'):
            source, _, metadata = ensure_source(ROOT, WORK, archive, lock, manifest(queue), recorded_patches=queue)
        test_patch = added_file('kernel/time/neo-clock-diag-test.c', harness.read_text())
        test_queue = queue + [('9999-clock-provenance-kunit-only.patch', test_patch)]
        with locked(WORK / '.source-lock'):
            test_source, _, test_metadata = ensure_source(ROOT, WORK, archive, lock,
                manifest(test_queue), recorded_patches=test_queue)
        for name in ('neo-clock-diag.h', 'neo-clock-diag.c'):
            if (test_source / 'kernel/time' / name).read_bytes() != (CANDIDATE / name).read_bytes():
                raise ValueError('KUnit implementation differs from candidate')
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
             'neo-clock-provenance'])
        check_overrides(output / '.config', [s for s in text.splitlines() if s.startswith('CONFIG_')])
        cases = results_checked(json.loads((scratch / 'results.json').read_text()),
                                (output / 'test.log').read_text(errors='replace'))
        test_log = (output / 'test.log').read_text(errors='replace')
        fixture_lines = re.findall(r'NEO_CLOCK_FIXTURE (\{[^\n]+\})', test_log)
        fixture_result = replay([loads(line) for line in fixture_lines])
        if not fixture_result['complete'] or fixture_result['calls'] != 1 or fixture_result['regressions']:
            raise ValueError('Kernel serializer fixture did not replay cleanly')
        retained = scratch / 'accepted-runs'  / uuid.uuid4().hex
        retained.mkdir(parents=True)
        (retained / 'fixture.ndjson').write_text('\n'.join(fixture_lines) + '\n')
        artifacts = {}
        for name, path in {'linux': output / 'linux', 'config': output / '.config',
                           'test.log': output / 'test.log', 'results.json': scratch / 'results.json'}.items():
            digest = sha256(path)
            shutil.copyfile(path, retained / name)
            if sha256(retained / name) != digest:
                raise ValueError('Artifact changed during retention')
            artifacts[name] = digest
        record = dict(schema_version=1, suite='neo-clock-provenance', linux=lock['linux']['tag'],
            builder=builder, inputs=input_hashes,
            source=metadata, test_source=test_metadata, candidate_patches=manifest(queue),
            test_patches=manifest(test_queue), cases=cases, fixture_replay=fixture_result,
            fixture_sha256=sha256(retained / 'fixture.ndjson'),
            artifact_dir=str(retained.relative_to(ROOT)), artifacts=artifacts,
            limits='Actual kernel conversion, scripted counter, bounded recorder, real locks/threads '
                   'and file callbacks under UML KASAN/lockdep. No real ARM counter, user-copy, '
                   'migration or hardware clock qualification; no device access.')
        if args.compile_driver:
            record['arm_builds'] = {}
            for enabled in (False, True):
                extra = ['CONFIG_NEO_CLOCK_DIAG=' + ('y' if enabled else 'n'),
                         'CONFIG_NEO_CLOCK_DIAG_KUNIT_TEST=n']
                identity = hashlib.sha256((metadata['tree_sha256'] +
                    sha256(ROOT / 'kernel/gameshellneo.config') + builder['image'] +
                    str(enabled)).encode()).hexdigest()[:16]
                arm = WORK / ('arm-' + identity)
                arm.mkdir(exist_ok=True)
                (arm / 'extra.config').write_text('\n'.join(extra) + '\n')
                objects = ['kernel/time/timekeeping.o', 'kernel/time/posix-timers.o']
                if enabled:
                    objects.append('kernel/time/neo-clock-diag.o')
                record['arm_builds']['enabled' if enabled else 'disabled'] = build_objects(
                    source, arm, lock, objects, extra, True, metadata, offline=True)
            off = set()
            on = set()
            for mode, names in (('disabled', off), ('enabled', on)):
                output_dir = ROOT / record['arm_builds'][mode]['scratch'] / 'output'
                for name in ('timekeeping.o', 'posix-timers.o'):
                    names.update(object_hooks(output_dir / 'kernel/time' / name, True))
            output_dir = ROOT / record['arm_builds']['enabled']['scratch'] / 'output'
            definitions = object_hooks(output_dir / 'kernel/time/neo-clock-diag.o', False)
            validate_symbols(off, on, definitions)
            record['arm_hook_symbols'] = dict(disabled=sorted(off), enabled=sorted(on),
                                               definitions=sorted(definitions))
        if input_hashes != {str(p.relative_to(ROOT)): sha256(p) for p in inputs}:
            raise ValueError('Diagnostic inputs changed during validation')
        if active_manifest != manifest(list(module.patches())):
            raise ValueError('Active patch queue changed during validation')
        atomic_json(retained / 'evidence.json', record)
        atomic_json(evidence, record)
        print('Evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
