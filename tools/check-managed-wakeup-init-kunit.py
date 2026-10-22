#!/usr/bin/env python3
"""Execute the five managed-wakeup cases in one disposable owned UML kernel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from kernel_checks import ROOT, archive_for, check_overrides, sha256
from kernel_sources import atomic_json, locked
from managed_container import ManagedCommandFailure, execute, owns_active, result_for
from managed_wakeup_init_source import CONTROL_FAILURES, PATCH
import managed_wakeup_init_kunit as support


def completed_control(failure, attempt):
    """Admit only the exact completed command after authoritative owner release."""
    identity, result, _ = result_for(attempt / 'managed-run.json')
    state = (result or {}).get('state') or {}
    if (identity != failure.identity or result != failure.result or owns_active(identity) or
            not result or result.get('outcome') != 'exited' or result.get('exit_code') != 1 or
            result.get('returncode') != 1 or result.get('stop_requested') or
            state.get('Running') is not False or state.get('Status') != 'exited' or
            state.get('ExitCode') != 1 or state.get('OOMKilled') or state.get('Error')):
        raise RuntimeError('Managed-wakeup control execution is inconclusive; retain original result')
    return result


def retain_previous(scratch, paths):
    existing = [path for path in paths if path.exists()]
    if existing:
        previous = scratch / 'previous-runs' / uuid.uuid4().hex
        previous.mkdir(parents=True)
        for path in existing:
            retained = previous / path.name
            shutil.copyfile(path, retained)
            if sha256(path) != sha256(retained):
                raise RuntimeError('Previous managed-wakeup result changed during retention')
        for path in existing:
            path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', choices=('return-ignored',))
    args = parser.parse_args()
    base = ROOT / '.local/build/managed-wakeup-init-kernel'
    base.mkdir(parents=True, exist_ok=True)
    with locked(base / '.qualification-lock'):
        evidence = base / ('control-evidence.json' if args.control else 'evidence.json')
        evidence.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        config = ROOT / 'kernel/tests/managed-wakeup-init-kunit.config'
        paths = (Path(__file__), config, Path(support.__file__), ROOT / PATCH,
            ROOT / 'kernel/tests/managed-wakeup-init-kunit.c',
            ROOT / 'kernel/tests/managed-wakeup-init-kunit.h',
            ROOT / 'tools/managed_wakeup_init_source.py', ROOT / 'tools/musb_restart_kunit.py',
            ROOT / 'tools/musb_irq_checks.py', ROOT / 'tools/kernel_checks.py',
            ROOT / 'tools/kernel_sources.py', ROOT / 'tools/kernel-inputs.py',
            ROOT / 'tools/kernel_candidates.py', ROOT / 'tools/managed_container.py',
            ROOT / 'tools/docker-stage.py', ROOT / 'tools/tests/test_managed_wakeup_init_kunit.py',
            ROOT / 'build/sources.lock.json', ROOT / 'Taskfile.yml')
        inputs = {str(path.relative_to(ROOT)): sha256(path) for path in paths}
        inputs.update(support.production_pins(ROOT))
        base, source, metadata = support.kernel_source(ROOT, lock, archive)
        builder = lock['builder']
        text = config.read_text()
        key = hashlib.sha256((metadata['tree_sha256'] + text + builder['image']).encode()).hexdigest()[:16]
        # Both variants reuse one output; immutable accepted kernels/configs/logs
        # retain the exact executed result before the next configuration changes.
        scratch = base / ('uml-' + key)
        scratch.mkdir(exist_ok=True)
        text += 'CONFIG_NEO_MANAGED_WAKEUP_RETURN_IGNORED=' + ('y' if args.control else 'n') + '\n'
        (scratch / 'kunit.config').write_text(text)
        output = scratch / 'output'
        result_paths = (output / 'test.log', scratch / 'results.json')
        retain_previous(scratch, result_paths)
        relative = scratch.relative_to(ROOT).as_posix()
        resources_before = support.resources(ROOT, base)
        arguments = ['--pull=never', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--network', 'none',
            '--tmpfs', '/uml-tmp:rw,exec,size=2g,mode=1777', '-e', 'TMPDIR=/uml-tmp',
            '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
            '--entrypoint', 'bash', '-v', f'{ROOT}:/project', '-v', f'{source}:/kernel-source:ro',
            '-w', '/kernel-source', builder['image'], '-c',
            'set -euo pipefail\nulimit -c 0\n'
            'python3 -u tools/testing/kunit/kunit.py run --arch=um --jobs=1 '
            f'--build_dir=/project/{relative}/output --kunitconfig=/project/{relative}/kunit.config '
            f'--timeout=120 --json=/project/{relative}/results.json '
            '--kernel_args=uml_dir=/uml-tmp/state ' + support.STEM]
        attempt = base / 'attempts' / uuid.uuid4().hex
        try:
            try:
                # No observer timeout: an uncertain build must remain the
                # original owned job, not be stopped/replaced by a retry.
                result = execute(support.STEM + '-kunit', arguments, attempt, timeout=None)
                if args.control:
                    raise RuntimeError('Managed-wakeup control returned normally; expected original raw exit 1')
            except ManagedCommandFailure as failure:
                if not args.control:
                    raise
                result = completed_control(failure, attempt)
        finally:
            atomic_json(attempt / 'inputs.json', dict(inputs=inputs, source=metadata, control=args.control))
        if any(sha256(ROOT / name) != digest for name, digest in inputs.items()):
            raise RuntimeError('Managed-wakeup qualification inputs changed during original run')
        if any(not path.is_file() for path in result_paths):
            raise RuntimeError('Missing current-execution managed-wakeup log or JSON; retain original result')
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
                raise RuntimeError('Managed-wakeup artifact changed during retention')
        record = dict(schema_version=1, suite=support.STEM, linux=lock['linux']['tag'], builder=builder,
            inputs=inputs, source=metadata, cases=cases, control=args.control,
            artifact_dir=str(accepted.relative_to(ROOT)), artifacts=artifacts,
            managed_attempt=str(attempt.relative_to(ROOT)), managed_result=result,
            resources_before=resources_before, resources_after=support.resources(ROOT, base), limits=support.LIMITS)
        if args.control:
            record['expected_assertions'] = CONTROL_FAILURES
        atomic_json(accepted / 'evidence.json', record)
        atomic_json(evidence, record)
        print('Managed-wakeup Linux evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
