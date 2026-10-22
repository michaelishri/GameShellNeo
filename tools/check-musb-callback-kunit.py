#!/usr/bin/env python3
"""Run real MUSB/UDC callbacks against concurrent unbind in an SMP ARM kernel."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from managed_container import execute as run_managed
from kernel_checks import ROOT, archive_for, check_overrides, sha256
from kernel_qemu import input_id, inputs
from kernel_sources import atomic_json, ensure_source, locked
from musb_callback_kunit import checked_cases, test_patch
from musb_restart_kunit import manifest_for


def emulator(lock):
    receipt = json.loads((ROOT / '.local/build/kernel-qemu/receipt.json').read_text())
    if receipt.get('complete') is not True or receipt.get('input_id') != input_id(inputs(lock)):
        raise ValueError('Run task setup:kernel-qemu for these pinned inputs')
    for name, digest in receipt['sources'].items():
        if sha256(ROOT / name) != digest:
            raise ValueError('Emulator setup source changed: ' + name)
    for name, digest in receipt['files'].items():
        if sha256(ROOT / receipt['evidence'] / name) != digest:
            raise ValueError('Emulator setup evidence changed: ' + name)
    image = json.loads(subprocess.check_output(
        ['docker', 'image', 'inspect', receipt['image_id']], text=True))[0]
    if image['Id'] != receipt['image_id'] or (image['Os'], image['Architecture']) != ('linux', 'amd64'):
        raise ValueError('Emulator image identity differs')
    return receipt


def execute(image, source, scratch, builder):
    relative = scratch.relative_to(ROOT).as_posix()
    attempt = scratch / 'attempts' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    arguments = [ '--pull=never', '--network=none',
        '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=256',
        '--memory=3g', '--cpus=2', '--user', f'{os.getuid()}:{os.getgid()}',
        '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
        '--entrypoint=timeout', '-v', f'{ROOT}:/project', '-v', f'{source}:/kernel-source:ro',
        '-w', '/kernel-source', image, '--signal=TERM', '--kill-after=10', '3600',
        'python3', '-u', 'tools/testing/kunit/kunit.py', 'run', '--arch=arm',
        '--cross_compile=' + builder['cross_compile'], '--jobs=' + str(builder['jobs']),
        '--build_dir=/project/' + relative + '/output',
        '--kunitconfig=/project/' + relative + '/kunit.config', '--timeout=120',
        '--json=/project/' + relative + '/results.json',
        '--qemu_args=-smp 4 -accel tcg,thread=multi -nic none', 'musb-callback-smp']
    try:
        run_managed('callback-smp', arguments, attempt, timeout=3660)
    finally:
        # Retain the available build artifacts even for a rejected run.
        # Their existence alone does not prove this attempt booted them;
        # only the complete accepted evidence makes that claim.
        available = {}
        for filename, path in {
                'results.json': scratch / 'results.json',
                'test.log': scratch / 'output/test.log',
                'zImage': scratch / 'output/arch/arm/boot/zImage',
                'config': scratch / 'output/.config'}.items():
            if path.is_file():
                shutil.copyfile(path, attempt / filename)
                available[filename] = sha256(attempt / filename)
        atomic_json(attempt / 'available-artifacts.json', available)
    return attempt


def main():
    os.umask(0o077)
    work = ROOT / '.local/build/musb-callback-kunit'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        evidence = work / 'evidence.json'
        if evidence.exists():
            evidence.rename(work / ('previous-evidence-' + uuid.uuid4().hex + '.json'))
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        qemu = emulator(lock)
        archive = archive_for(lock)
        spec = importlib.util.spec_from_file_location('kernel_inputs', ROOT / 'tools/kernel-inputs.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        queue = list(module.patches())
        config = ROOT / 'kernel/tests/musb-callback-kunit.config'
        source_paths = (Path(__file__), config, ROOT / 'tools/musb_callback_kunit.py',
            ROOT / 'kernel/tests/musb-callback-kunit.c', ROOT / 'tools/kernel_sources.py',
            ROOT / 'tools/kernel_checks.py', ROOT / 'tools/kernel-inputs.py',
            ROOT / 'tools/kernel_qemu.py', ROOT / 'tools/managed_container.py',
            ROOT / 'tools/docker-stage.py', ROOT / 'tools/build-bin/docker', ROOT / 'tools/run-logged.sh',
            ROOT / 'tools/musb_restart_kunit.py',
            ROOT / 'tools/keypad_supply.py', ROOT / 'tools/cpi_idle.py', ROOT / 'build/sources.lock.json')
        hashes = {str(p.relative_to(ROOT)): sha256(p) for p in source_paths}
        with tempfile.TemporaryDirectory(dir=work) as temporary:
            queue.append(test_patch(ROOT, archive, lock, queue, module.apply_queue, Path(temporary)))
        with locked(work / '.source-lock'):
            source, _, metadata = ensure_source(ROOT, work, archive, lock, manifest_for(queue), recorded_patches=queue)
        text = config.read_text()
        identity = hashlib.sha256((metadata['tree_sha256'] + text + qemu['image_id']).encode()).hexdigest()[:16]
        scratch = work / ('kernel-' + identity)
        scratch.mkdir(exist_ok=True)
        (scratch / 'kunit.config').write_text(text)
        # Never let an earlier TAP/JSON survive as the apparent new run output.
        for path in (scratch / 'results.json', scratch / 'output/test.log'):
            if path.exists():
                path.rename(path.with_name(path.name + '.previous-' + uuid.uuid4().hex))
        attempt = execute(qemu['image_id'], source, scratch, lock['builder'])
        output = scratch / 'output'
        check_overrides(output / '.config', [line for line in text.splitlines() if line.startswith('CONFIG_')])
        cases = checked_cases(json.loads((attempt / 'results.json').read_text()),
                              (attempt / 'test.log').read_text(errors='replace'))
        if hashes != {str(p.relative_to(ROOT)): sha256(p) for p in source_paths}:
            raise ValueError('SMP test inputs changed during execution')
        artifacts = {}
        for name, path in {'zImage': output / 'arch/arm/boot/zImage', 'config': output / '.config'}.items():
            if sha256(attempt / name) != sha256(path):
                raise ValueError('SMP artifact changed during retention')
        for path in sorted(attempt.iterdir()):
            artifacts[path.name] = sha256(path)
        record = dict(schema=1, complete=True, suite='musb-callback-smp', linux=lock['linux']['tag'],
            inputs=hashes, source=metadata, emulator=qemu, cases=cases,
            artifact_dir=str(attempt.relative_to(ROOT)), artifacts=artifacts,
            limits='Real MUSB callback paths and UDC bind/unbind on four ARM guest CPUs with KASAN/lockdep. '
                   'Hardware start/stop/pullup and register bank substituted. No electrical, DMA or GameShell qualification.')
        atomic_json(attempt / 'evidence.json', record)
        atomic_json(evidence, record)
        print('ARM SMP callback evidence:', evidence, flush=True)


if __name__ == '__main__':
    main()
