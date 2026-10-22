#!/usr/bin/env python3
"""Run the separate wake/startup profile through actual Linux device PM."""
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
from kernel_checks import ROOT, archive_for, check_overrides, sha256
from kernel_sources import atomic_json, ensure_source, locked
from managed_container import execute, result_for
from musb_restart_kunit import manifest_for
import musb_wake_dpm_kunit as support


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', choices=('callbacks-unregistered',),
                        help='Require executed missing-callback assertions in an independent disposable kernel')
    args = parser.parse_args()
    stem = 'musb-wake-dpm'
    work = ROOT / '.local/build' / (stem + '-kunit' + ('-' + args.control if args.control else ''))
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        evidence = work / ('control-evidence.json' if args.control else 'evidence.json')
        evidence.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        spec = importlib.util.spec_from_file_location('kernel_inputs', ROOT / 'tools/kernel-inputs.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        queue = include_candidates(ROOT, 'musb-wake-startup', module.patches())
        config = ROOT / 'kernel/tests/musb-wake-dpm-kunit.config'
        inputs = {str(path.relative_to(ROOT)): sha256(path) for path in (
            Path(__file__), config, Path(support.__file__),
            ROOT / 'kernel/tests/musb-wake-dpm-kunit.c', ROOT / 'tools/musb_restart_kunit.py',
            ROOT / 'tools/musb_irq_checks.py', ROOT / 'tools/kernel_sources.py',
            ROOT / 'tools/kernel_candidates.py', ROOT / 'tools/kernel_checks.py', ROOT / 'tools/kernel-inputs.py',
            ROOT / 'tools/managed_container.py', ROOT / 'tools/docker-stage.py', ROOT / 'Taskfile.yml',
            ROOT / 'tools/tests/test_musb_wake_dpm_kunit.py', ROOT / 'build/sources.lock.json')}
        with tempfile.TemporaryDirectory(dir=work) as temporary:
            patch = support.test_patch(ROOT, archive, lock, queue, module.apply_queue,
                                       Path(temporary), control=args.control)
        queue.append(patch)
        with locked(work / '.source-lock'):
            source, _, metadata = ensure_source(ROOT, work, archive, lock, manifest_for(queue), recorded_patches=queue)
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
        arguments = ['--pull=never', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--network', 'none',
            '--tmpfs', '/uml-tmp:rw,exec,size=2g,mode=1777', '-e', 'TMPDIR=/uml-tmp',
            '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
            '--entrypoint', 'bash', '-v', f'{ROOT}:/project', '-v', f'{source}:/kernel-source:ro',
            '-w', '/kernel-source', builder['image'], '-c',
            'set -euo pipefail\nulimit -c 0\n'
            'python3 -u tools/testing/kunit/kunit.py run --arch=um '
            f'--jobs={builder["jobs"]} --build_dir=/project/{relative}/output '
            f'--kunitconfig=/project/{relative}/kunit.config --timeout=120 '
            f'--json=/project/{relative}/results.json --kernel_args=uml_dir=/uml-tmp/state ' + stem]
        attempt = work / 'attempts' / uuid.uuid4().hex
        try:
            try:
                result = execute(stem + '-kunit', arguments, attempt, timeout=7200)
            except RuntimeError:
                if not args.control:
                    raise
                _, result, _ = result_for(attempt / 'managed-run.json')
                state = (result or {}).get('state') or {}
                if (not result or result.get('outcome') != 'exited' or result.get('exit_code') != 1 or
                        result.get('returncode') != 1 or result.get('stop_requested') or
                        state.get('Running') is not False or state.get('Status') != 'exited' or
                        state.get('ExitCode') != 1 or state.get('OOMKilled') or state.get('Error')):
                    raise RuntimeError('DPM control execution is inconclusive; retain original result')
        finally:
            atomic_json(attempt / 'inputs.json', dict(inputs=inputs, source=metadata,
                candidate_profile='musb-wake-startup', control=args.control))
        if any(sha256(ROOT / name) != digest for name, digest in inputs.items()):
            raise RuntimeError('DPM qualification inputs changed during the owned run')
        check_overrides(output / '.config', [line for line in text.splitlines() if line.startswith('CONFIG_')])
        validate = support.checked_control if args.control else support.checked_cases
        cases = validate(json.loads((scratch / 'results.json').read_text()),
                         (output / 'test.log').read_text(errors='replace'))
        accepted = scratch / ('control-runs' if args.control else 'accepted-runs') / uuid.uuid4().hex
        accepted.mkdir(parents=True)
        artifacts = {}
        for name, path in {'linux': output / 'linux', 'config': output / '.config',
                           'test.log': output / 'test.log', 'results.json': scratch / 'results.json'}.items():
            artifacts[name] = sha256(path)
            shutil.copyfile(path, accepted / name)
            if sha256(accepted / name) != artifacts[name]:
                raise RuntimeError('Artifact changed during retention: ' + name)
        record = dict(schema_version=1, suite=stem, linux=lock['linux']['tag'], builder=builder,
            candidate_profile='musb-wake-startup', inputs=inputs, source=metadata, cases=cases,
            artifact_dir=str(accepted.relative_to(ROOT)), artifacts=artifacts,
            managed_attempt=str(attempt.relative_to(ROOT)), managed_result=result, limits=support.LIMITS)
        if args.control:
            record.update(control=args.control, expected_failures=[support.CONTROL_CASE],
                          expected_assertions=list(support.CONTROL_ASSERTIONS))
        atomic_json(accepted / 'evidence.json', record)
        atomic_json(evidence, record)
        print('DPM KUnit evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
