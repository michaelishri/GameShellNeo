#!/usr/bin/env python3
"""Execute real Linux IRQ/wakeup-source retirement in a dedicated UML kernel."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from kernel_checks import ROOT, archive_for, check_overrides, run, sha256
from kernel_run_evidence import retain_run
from kernel_sources import atomic_json, ensure_source, locked
from musb_restart_kunit import manifest_for
from musb_terminal_wake_kunit import checked_cases, LIMITS, test_patch
from musb_terminal_wake_source import PROFILE, queue_for


def main():
    work = ROOT / '.local/build/musb-terminal-wake-kunit'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        evidence = work / 'evidence.json'
        evidence.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        queue = queue_for(ROOT, PROFILE)
        config = ROOT / 'kernel/tests/musb-terminal-wake-kunit.config'
        maintained = (Path(__file__), config, ROOT / 'kernel/tests/musb-terminal-wake-kunit.c',
                      ROOT / 'tools/musb_terminal_wake_kunit.py', ROOT / 'tools/musb_terminal_wake_source.py',
                      ROOT / 'tools/musb_restart_kunit.py', ROOT / 'tools/musb_irq_checks.py',
                      ROOT / 'tools/kernel_run_evidence.py', ROOT / 'tools/kernel_sources.py',
                      ROOT / 'tools/kernel_checks.py', ROOT / 'tools/kernel_candidates.py',
                      ROOT / 'tools/kernel-inputs.py', ROOT / 'build/sources.lock.json')
        inputs = {str(path.relative_to(ROOT)): sha256(path) for path in maintained}
        with tempfile.TemporaryDirectory(dir=work) as temporary:
            queue.append(test_patch(ROOT, archive, lock, Path(temporary)))
        with locked(work / '.source-lock'):
            source, _, metadata = ensure_source(ROOT, work, archive, lock, manifest_for(queue),
                                                recorded_patches=queue)
        builder, text = lock['builder'], config.read_text()
        identity = hashlib.sha256((metadata['tree_sha256'] + text + builder['image']).encode()).hexdigest()[:16]
        scratch = work / ('kernel-' + identity)
        scratch.mkdir(exist_ok=True)
        (scratch / 'kunit.config').write_text(text)
        relative, output = scratch.relative_to(ROOT).as_posix(), scratch / 'output'
        if (output / 'test.log').exists():
            previous = scratch / 'previous-runs' / uuid.uuid4().hex
            previous.mkdir(parents=True)
            for path in (output / 'test.log', scratch / 'results.json'):
                if path.exists():
                    shutil.copyfile(path, previous / path.name)
        run(['docker', 'run', '--rm', '--network', 'none', '--pull', 'never',
             '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
             '--tmpfs', '/uml-tmp:rw,exec,size=2g,mode=1777', '-e', 'TMPDIR=/uml-tmp',
             '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
             '--entrypoint', 'bash', '-v', f'{ROOT}:/project', '-v', f'{source}:/kernel-source:ro',
             '-w', '/kernel-source', builder['image'], '-c',
             'set -euo pipefail\nulimit -c 0\n'
             'python3 -u tools/testing/kunit/kunit.py config --arch=um '
             f'--build_dir=/project/{relative}/output --kunitconfig=/project/{relative}/kunit.config\n'
             f'make ARCH=um O=/project/{relative}/output -j{builder["jobs"]} drivers/usb/musb/musb_core.o\n'
             'python3 -u tools/testing/kunit/kunit.py run --arch=um '
             f'--jobs={builder["jobs"]} --build_dir=/project/{relative}/output '
             f'--kunitconfig=/project/{relative}/kunit.config --timeout=120 '
             f'--json=/project/{relative}/results.json --kernel_args=uml_dir=/uml-tmp/state '
             'musb-terminal-wake'])
        check_overrides(output / '.config', [line for line in text.splitlines() if line.startswith('CONFIG_')])
        cases = checked_cases(json.loads((scratch / 'results.json').read_text()),
                              (output / 'test.log').read_text(errors='replace'))
        record = retain_run(ROOT, scratch)
        record.update(schema_version=1, suite=PROFILE, linux=lock['linux']['tag'],
                      builder=builder, source=metadata, inputs=inputs, cases=cases, limits=LIMITS)
        if inputs != {name: sha256(ROOT / name) for name in inputs}:
            raise ValueError('Terminal IRQ/wake kernel inputs changed during the owned run')
        atomic_json(ROOT / record['artifact_dir'] / 'evidence.json', record)
        atomic_json(evidence, record)
        print('Terminal IRQ/wake KUnit evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
