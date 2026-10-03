#!/usr/bin/env python3
"""Prove real ARM object builds share source, with isolated outputs and regeneration."""
import json

from kernel_checks import ROOT, archive_for, compile_objects, sha256
from kernel_sources import atomic_json, inventory, locked


def main():
    work = ROOT / '.local/build/kernel-source-reuse-tests'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        evidence = work / 'compile-evidence.json'
        evidence.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        obj = 'drivers/usb/musb/musb_core.o'
        board = compile_objects(archive, lock, work, [obj])
        source = ROOT / board['shared_source']['path']
        before = inventory(source)
        alternative = compile_objects(archive, lock, work, [obj],
                                      extra_config=('CONFIG_SUSPEND=n', 'CONFIG_HIBERNATION=n',
                                                    'CONFIG_PM_SLEEP=n', 'CONFIG_PM=n'),
                                      project_config=False)
        if board['scratch'] == alternative['scratch'] or board['shared_source'] != alternative['shared_source']:
            raise RuntimeError('Expected isolated outputs with the same verified source')
        if board['config_sha256'] == alternative['config_sha256'] or inventory(source) != before:
            raise RuntimeError('Configuration isolation or source integrity check failed')
        # Force an object regeneration, retaining the recorded original digest.
        (ROOT / board['scratch'] / 'output' / obj).unlink()
        repeated = compile_objects(archive, lock, work, [obj])
        if repeated != board:
            raise RuntimeError('Regenerated board object differs')
        caches = list((work / '.sources').glob('source-*'))
        atomic_json(evidence, dict(
            arm_build=board, arm_alternative_build=alternative, repeated_build=repeated,
            source_cache_count=len(caches), archive_sha256=sha256(archive),
            inputs={name: sha256(ROOT / name) for name in (
                'tools/kernel_checks.py', 'tools/kernel_sources.py', 'tools/check-kernel-source-reuse.py')},
            limits='Compiler/storage qualification only; no image or hardware change.'))
        print('Two ARM configurations and object regeneration passed; shared source:', source, flush=True)


if __name__ == '__main__':
    main()
