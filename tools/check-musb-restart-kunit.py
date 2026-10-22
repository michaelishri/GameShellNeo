#!/usr/bin/env python3
"""Execute a selected MUSB integration suite in an isolated UML kernel."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from kernel_candidates import include_candidates
from kernel_checks import ROOT, archive_for, check_overrides, run, sha256
from kernel_sources import atomic_json, ensure_source, locked
from musb_restart_kunit import manifest_for
from managed_container import execute, result_for


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('restart', 'irq', 'work', 'pm', 'wake'), default='restart')
    parser.add_argument('--wake-control', choices=('policy-ignored',),
                        help='Disposable wake-only source mutation; require executed policy assertion failures')
    args = parser.parse_args()
    if args.wake_control and args.suite != 'wake':
        parser.error('--wake-control requires --suite wake')
    support = importlib.import_module('musb_' + args.suite + '_kunit')
    stem = 'musb-' + args.suite
    work = ROOT / '.local/build' / (stem + '-kunit' + ('-' + args.wake_control if args.wake_control else ''))
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        evidence = work / ('control-evidence.json' if args.wake_control else 'evidence.json')
        evidence.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        spec = importlib.util.spec_from_file_location('kernel_inputs', ROOT / 'tools/kernel-inputs.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        profile = 'musb-wake-startup' if args.suite == 'wake' else 'musb-retirement'
        queue = include_candidates(ROOT, profile, module.patches())
        config = ROOT / 'kernel/tests' / (stem + '-kunit.config')
        inputs = {str(p.relative_to(ROOT)): sha256(p) for p in (
            Path(__file__), config, Path(support.__file__), ROOT / 'tools/musb_restart_kunit.py',
            ROOT / 'kernel/tests' / (stem + '-kunit.c'), ROOT / 'tools/kernel_sources.py',
            ROOT / 'tools/kernel_candidates.py', ROOT / 'tools/kernel_checks.py', ROOT / 'tools/kernel-inputs.py',
            ROOT / 'build/sources.lock.json')}
        inputs.update({name: sha256(ROOT / name) for name in getattr(support, 'EXTRA_INPUTS', ())})
        if args.suite == 'wake':
            inputs.update({name: sha256(ROOT / name) for name in (
                'tools/managed_container.py', 'tools/docker-stage.py', 'Taskfile.yml',
                'tools/tests/test_musb_wake_kunit.py')})
        with tempfile.TemporaryDirectory(dir=work) as temporary:
            if args.suite == 'wake':
                patch = support.test_patch(ROOT, archive, lock, queue, module.apply_queue,
                                           Path(temporary), control=args.wake_control)
            else:
                patch = support.test_patch(ROOT, archive, lock, queue, module.apply_queue, Path(temporary))
            queue.append(patch)
        with locked(work / '.source-lock'):
            source, _, metadata = ensure_source(ROOT, work, archive, lock, manifest_for(queue),
                                                recorded_patches=queue)
        builder = lock['builder']
        text = config.read_text()
        identity = hashlib.sha256((metadata['tree_sha256'] + text + builder['image']).encode()).hexdigest()[:16]
        scratch = work / ('kernel-' + identity)
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
        arguments = ['--user', f'{os.getuid()}:{os.getgid()}',
             '--platform', builder['platform'], '--network', 'none',
             '--tmpfs', '/uml-tmp:rw,exec,size=2g,mode=1777', '-e', 'TMPDIR=/uml-tmp',
             '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
             '--entrypoint', 'bash', '-v', f'{ROOT}:/project', '-v', f'{source}:/kernel-source:ro',
             '-w', '/kernel-source', builder['image'], '-c',
             'set -euo pipefail\nulimit -c 0\n'
             'python3 -u tools/testing/kunit/kunit.py run --arch=um '
             f'--jobs={builder["jobs"]} --build_dir=/project/{relative}/output '
             f'--kunitconfig=/project/{relative}/kunit.config --timeout=120 '
             f'--json=/project/{relative}/results.json --kernel_args=uml_dir=/uml-tmp/state '
             + stem]
        managed_result = None
        if args.suite == 'wake':
            attempt = work / 'attempts' / uuid.uuid4().hex
            try:
                try:
                    managed_result = execute(stem + '-kunit', ['--pull=never', *arguments], attempt, timeout=7200)
                except RuntimeError:
                    if not args.wake_control:
                        raise
                    _, managed_result, _ = result_for(attempt / 'managed-run.json')
                    state = (managed_result or {}).get('state') or {}
                    if (not managed_result or managed_result.get('outcome') != 'exited' or
                            managed_result.get('exit_code') != 1 or managed_result.get('returncode') != 1 or
                            managed_result.get('stop_requested') or state.get('Running') is not False or
                            state.get('Status') != 'exited' or state.get('ExitCode') != 1 or
                            state.get('OOMKilled') or state.get('Error')):
                        raise RuntimeError('Wake control execution is inconclusive; retain original result')
            finally:
                atomic_json(attempt / 'inputs.json', dict(inputs=inputs, source=metadata,
                                                        candidate_profile=profile, control=args.wake_control))
            if any(sha256(ROOT / name) != digest for name, digest in inputs.items()):
                raise RuntimeError('Wake qualification inputs changed during the owned run')
        else:
            run(['docker', 'run', '--rm', *arguments])
        check_overrides(output / '.config', [line for line in text.splitlines() if line.startswith('CONFIG_')])
        validate = support.checked_control if args.wake_control else support.checked_cases
        cases = validate(json.loads((scratch / 'results.json').read_text()),
                         (output / 'test.log').read_text(errors='replace'))
        accepted = scratch / ('control-runs' if args.wake_control else 'accepted-runs') / uuid.uuid4().hex
        accepted.mkdir(parents=True)
        artifacts = {}
        for name, path in {'linux': output / 'linux', 'config': output / '.config',
                           'test.log': output / 'test.log', 'results.json': scratch / 'results.json'}.items():
            digest = sha256(path)
            shutil.copyfile(path, accepted / name)
            if sha256(accepted / name) != digest:
                raise RuntimeError('Artifact changed during retention: ' + name)
            artifacts[name] = digest
        record = dict(schema_version=1, suite=stem, linux=lock['linux']['tag'],
            builder=builder, inputs=inputs, source=metadata, cases=cases,
            artifact_dir=str(accepted.relative_to(ROOT)), artifacts=artifacts,
            limits=support.LIMITS)
        if managed_result is not None:
            record.update(candidate_profile=profile, managed_attempt=str(attempt.relative_to(ROOT)),
                          managed_result=managed_result)
        if args.wake_control:
            record.update(control=args.wake_control, expected_failures=support.CONTROL_FAILURES)
        atomic_json(accepted / 'evidence.json', record)
        atomic_json(evidence, record)
        print('KUnit evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
