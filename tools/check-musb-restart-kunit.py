#!/usr/bin/env python3
"""Execute the real MUSB restart and giveback paths in an isolated UML kernel."""
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
from musb_restart_kunit import checked_cases, manifest_for, test_patch


def main():
    work = ROOT / '.local/build/musb-restart-kunit'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        evidence = work / 'evidence.json'
        evidence.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        spec = importlib.util.spec_from_file_location('kernel_inputs', ROOT / 'tools/kernel-inputs.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        queue = list(module.patches())
        config = ROOT / 'kernel/tests/musb-restart-kunit.config'
        inputs = {str(p.relative_to(ROOT)): sha256(p) for p in (
            Path(__file__), config, ROOT / 'tools/musb_restart_kunit.py',
            ROOT / 'kernel/tests/musb-restart-kunit.c', ROOT / 'tools/kernel_sources.py',
            ROOT / 'tools/kernel_checks.py', ROOT / 'tools/kernel-inputs.py',
            ROOT / 'build/sources.lock.json')}
        with tempfile.TemporaryDirectory(dir=work) as temporary:
            queue.append(test_patch(ROOT, archive, lock, queue, module.apply_queue, Path(temporary)))
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
        run(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
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
             'musb-restart'])
        check_overrides(output / '.config', [line for line in text.splitlines() if line.startswith('CONFIG_')])
        cases = checked_cases(json.loads((scratch / 'results.json').read_text()),
                              (output / 'test.log').read_text(errors='replace'))
        accepted = scratch / 'accepted-runs' / uuid.uuid4().hex
        accepted.mkdir(parents=True)
        artifacts = {}
        for name, path in {'linux': output / 'linux', 'config': output / '.config',
                           'test.log': output / 'test.log', 'results.json': scratch / 'results.json'}.items():
            digest = sha256(path)
            shutil.copyfile(path, accepted / name)
            if sha256(accepted / name) != digest:
                raise RuntimeError('Artifact changed during retention: ' + name)
            artifacts[name] = digest
        record = dict(schema_version=1, suite='musb-restart', linux=lock['linux']['tag'],
            builder=builder, inputs=inputs, source=metadata, cases=cases,
            artifact_dir=str(accepted.relative_to(ROOT)), artifacts=artifacts,
            limits='Actual full MUSB driver and USB giveback, real spinlocks and runtime-PM '
                   'accounting under Linux UML with KASAN/lockdep. Only the hardware restart '
                   'is intercepted. Controller runtime state is staged; a baseline PM reference '
                   'prevents real hardware power transitions. Single virtual CPU and synchronous '
                   'interleavings: no SMP, DMA, electrical USB, actual suspend or board qualification.')
        atomic_json(accepted / 'evidence.json', record)
        atomic_json(evidence, record)
        print('KUnit evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
