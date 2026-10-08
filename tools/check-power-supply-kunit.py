#!/usr/bin/env python3
"""Compare actual power-supply teardown orders in KASAN Linux UML kernels."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from kernel_checks import ROOT, archive_for, check_overrides, run, sha256
from kernel_sources import atomic_json, ensure_source, locked
from power_supply_kunit_results import checked_cases
from power_supply_kunit_source import FIX, manifest_for, test_patch


def retain_run(scratch):
    """Detach accepted artifacts from paths that subsequent Kbuild/KUnit runs reuse."""
    accepted = scratch / 'accepted-runs' / uuid.uuid4().hex
    accepted.mkdir(parents=True, mode=0o700)
    record = dict(scratch=str(scratch.relative_to(ROOT)),
                  artifact_dir=str(accepted.relative_to(ROOT)))
    for field, path, name in (
        ('kernel_sha256', scratch / 'output/linux', 'linux'),
        ('config_sha256', scratch / 'output/.config', 'config'),
        ('log_sha256', scratch / 'output/test.log', 'test.log'),
        ('report_sha256', scratch / 'results.json', 'results.json'),
    ):
        digest = sha256(path)
        shutil.copyfile(path, accepted / name)
        if sha256(accepted / name) != digest:
            raise RuntimeError('Accepted artifact changed during retention: ' + name)
        record[field] = digest
    return record



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', choices=('original', 'reordered', 'all'),
                        default=os.environ.get('NEO_POWER_SUPPLY_KUNIT_VARIANT', 'all'))
    args = parser.parse_args()
    if args.variant not in ('original', 'reordered', 'all'):
        parser.error('Expected original, reordered or all')
    work = ROOT / '.local/build/power-supply-kunit'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        evidence = work / ('evidence-' + args.variant + '.json')
        evidence.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        spec = importlib.util.spec_from_file_location('kernel_inputs', ROOT / 'tools/kernel-inputs.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        production_queue = list(module.patches())
        config = ROOT / 'kernel/tests/power-supply-kunit.config'
        builder = lock['builder']
        paths = [Path(__file__), config, ROOT / 'tools/kernel_sources.py',
                 ROOT / 'tools/kernel-inputs.py', ROOT / 'tools/kernel_checks.py',
                 ROOT / 'tools/power_supply_kunit_source.py',
                 ROOT / 'tools/power_supply_kunit_results.py', ROOT / 'build/sources.lock.json',
                 ROOT / 'kernel/tests/power-supply-lifetime-hooks.h',
                 ROOT / 'kernel/tests/power-supply-lifetime-kunit.c']
        inputs = {str(p.relative_to(ROOT)): sha256(p) for p in paths}
        results = {}
        variants = ('original', 'reordered') if args.variant == 'all' else (args.variant,)
        for name in variants:
            queue = [p for p in production_queue if name == 'reordered' or p[0] != FIX]
            with tempfile.TemporaryDirectory(dir=work) as temporary:
                queue.append(test_patch(ROOT, archive, lock, queue, name, module.apply_queue,
                                        Path(temporary)))
            manifest = manifest_for(queue)
            with locked(work / '.source-lock'):
                source, _, metadata = ensure_source(ROOT, work, archive, lock, manifest,
                                                    recorded_patches=queue)
            text = config.read_text() + 'CONFIG_POWER_SUPPLY_LIFETIME_ORIGINAL_ORDER=' + (
                'y' if name == 'original' else 'n') + '\n'
            identity = hashlib.sha256((metadata['tree_sha256'] + text +
                                       builder['image']).encode()).hexdigest()[:16]
            scratch = work / ('kernel-' + name + '-' + identity)
            scratch.mkdir(exist_ok=True)
            (scratch / 'kunit.config').write_text(text)
            relative = scratch.relative_to(ROOT).as_posix()
            output = scratch / 'output'
            if (output / 'test.log').exists():
                previous = scratch / 'previous-runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
                previous.mkdir(parents=True)
                for path in (output / 'test.log', scratch / 'results.json'):
                    if path.exists():
                        shutil.copyfile(path, previous / path.name)
                atomic_json(previous / 'identity.json', dict(
                    kernel_sha256=sha256(output / 'linux'),
                    config_sha256=sha256(output / '.config'), source=metadata))
            print('Linux UML KASAN power-supply variant: ' + name, flush=True)
            run(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
                 '--platform', builder['platform'], '--network', 'none',
                 '--tmpfs', '/uml-tmp:rw,exec,size=2g,mode=1777',
                 '-e', 'TMPDIR=/uml-tmp', '-e', 'KBUILD_BUILD_USER=gameshellneo',
                 '-e', 'KBUILD_BUILD_HOST=builder', '--entrypoint', 'bash',
                 '-v', f'{ROOT}:/project', '-v', f'{source}:/kernel-source:ro',
                 '-w', '/kernel-source', builder['image'], '-c',
                 'set -euo pipefail\nulimit -c 0\n'
                 'python3 -u tools/testing/kunit/kunit.py config --arch=um '
                 f'--build_dir=/project/{relative}/output '
                 f'--kunitconfig=/project/{relative}/kunit.config\n'
                 f'make ARCH=um O=/project/{relative}/output -j{builder["jobs"]} '
                 'drivers/power/supply/power_supply_core.o\n'
                 'python3 -u tools/testing/kunit/kunit.py run --arch=um '
                 f'--jobs={builder["jobs"]} --build_dir=/project/{relative}/output '
                 f'--kunitconfig=/project/{relative}/kunit.config --timeout=120 '
                 f'--json=/project/{relative}/results.json --kernel_args=uml_dir=/uml-tmp/state '
                 'power-supply-lifetime'])
            check_overrides(output / '.config', [line for line in text.splitlines()
                                                 if line.startswith('CONFIG_')])
            report = json.loads((scratch / 'results.json').read_text())
            log = (output / 'test.log').read_text(errors='replace')
            cases = checked_cases(report, log)
            record = retain_run(scratch)
            record.update(cases=cases, source=metadata)
            atomic_json(ROOT / record['artifact_dir'] / 'evidence.json', dict(
                schema_version=1, suite='power-supply-lifetime', variant=name,
                builder=builder, inputs=inputs, result=record))
            results[name] = record
            atomic_json(work / 'progress.json', results)
        atomic_json(evidence, dict(schema_version=1, suite='power-supply-lifetime',
            linux=lock['linux']['tag'], inputs=inputs, builder=builder, results=results,
            limits='Real Linux UML workqueues/kthreads/completions/device teardown with KASAN '
                   'and lock debugging on one virtual CPU. Test-only pause gates; retained device '
                   'reference keeps the original-order control safe. No ARM execution, SMP, live '
                   'AXP unbind, supplier-consumer graph or energy qualification.'))
        print('KUnit evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
