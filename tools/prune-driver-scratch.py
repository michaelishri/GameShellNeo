#!/usr/bin/env python3
"""Remove superseded driver compiler trees, retaining current build evidence."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil

from kernel_sources import checked_file, sha256

ROOT = Path(__file__).resolve().parents[1]
SUITES = ('brcmfmac-pm-tests', 'brcmfmac-lifecycle-tests', 'brcmfmac-irq-tests',
          'brcmfmac-irq-worker-tests', 'brcmfmac-lifecycle-worker-tests', 'usb-policy-tests')


def build_records(value):
    if isinstance(value, dict):
        if 'scratch' in value:
            yield value
        for child in value.values():
            yield from build_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from build_records(child)


def real_directory(path):
    if path.is_symlink() or not path.is_dir():
        raise ValueError('Expected a real scratch directory: ' + str(path))


def plan(root, suite):
    if suite not in SUITES:
        raise ValueError('Unsupported suite')
    work = root / '.local/build' / suite
    for path in (root / '.local', root / '.local/build', work):
        real_directory(path)
    evidence_path = work / 'compile-evidence.json'
    if evidence_path.is_symlink():
        raise ValueError('Build evidence must not be a symlink')
    evidence = json.loads(evidence_path.read_text())
    retained = set()
    if suite == 'usb-policy-tests':
        # This checker records one ARM build rather than a normal/debug pair. Protect all
        # additional saved references too, and verify the surviving outputs.
        records = [evidence['arm_build']]
        for saved in sorted(work.glob('*evidence.json')):
            if saved.is_symlink() or not saved.is_file():
                raise ValueError('Expected regular evidence file')
            records.extend(build_records(json.loads(saved.read_text())))
    else:
        records = [evidence[key] for key in ('arm_build', 'arm_debug_build')]
    for record in records:
        relative = record['scratch']
        if not isinstance(relative, str) or not re.fullmatch(
                re.escape('.local/build/' + suite + '/') + r'kernel-[0-9a-f]{16}', relative):
            raise ValueError('Unexpected retained scratch path')
        path = root / relative
        real_directory(path)
        if suite == 'usb-policy-tests':
            if not isinstance(record.get('objects'), dict) or not record['objects']:
                raise ValueError('Missing retained object evidence')
            files = {'.config': record['config_sha256'], **record['objects']}
            for name, expected in files.items():
                if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
                    raise ValueError('Invalid retained output digest')
                if sha256(checked_file(path / 'output', name)) != expected:
                    raise ValueError('Retained output differs from evidence')
        retained.add(path)
    candidates = []
    for path in sorted(work.glob('kernel-*')):
        if not re.fullmatch(r'kernel-[0-9a-f]{16}', path.name):
            raise ValueError('Unexpected compiler tree name: ' + path.name)
        real_directory(path)
        if path in retained:
            continue
        # This task only knows the kernel_checks.py source/output layout.
        if {p.name for p in path.iterdir()} - {
                'source', 'output', 'extra.config', 'compiler.txt', 'elf-info.txt'}:
            raise ValueError('Unexpected files in compiler tree: ' + path.name)
        real_directory(path / 'output')
        source = path / 'source'
        if source.is_symlink():
            # A superseded output may point at a shared source. Remove only
            # this link with the scratch tree; never remove the source cache.
            target = os.readlink(source)
            if not re.fullmatch(r'[.][.]/[.]sources/source-[0-9a-f]{64}/source', target):
                raise ValueError('Unexpected shared source link')
            entry = work / '.sources' / Path(target).parts[2]
            for parent in (work / '.sources', entry, entry / 'source'):
                real_directory(parent)
        else:
            real_directory(source)
        if not (path / 'source/Makefile').is_file() or not (path / 'output/.config').is_file():
            raise ValueError('Incomplete compiler tree: ' + path.name)
        candidates.append(path)
    return work, sorted(retained), candidates


def prune(root, suite, apply=False):
    if suite not in SUITES:
        raise ValueError('Unsupported suite')
    # Reuse the exact lock held by check-brcmfmac-pm.py throughout compilation.
    work = root / '.local/build' / suite
    for path in (root / '.local', root / '.local/build', work):
        real_directory(path)
    lock_path = work / '.lock'
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ValueError('Expected the existing suite lock')
    with lock_path.open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        work, retained, candidates = plan(root, suite)
        result = dict(suite=suite, apply=apply,
                      retained=[str(p.relative_to(root)) for p in retained],
                      candidates=[str(p.relative_to(root)) for p in candidates], removed=[])
        print(json.dumps(result, indent=2), flush=True)
        if apply:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
            # Keep an incremental record even if a deletion is interrupted.
            report = work / ('prune-' + stamp + '.json')
            result['free_bytes_before'] = shutil.disk_usage(work).free
            report.write_text(json.dumps(result, indent=2) + '\n')
            try:
                for path in candidates:
                    shutil.rmtree(path)
                    result['removed'].append(str(path.relative_to(root)))
                    report.write_text(json.dumps(result, indent=2) + '\n')
            finally:
                result['free_bytes_after'] = shutil.disk_usage(work).free
                report.write_text(json.dumps(result, indent=2) + '\n')
            print('Cleanup evidence:', report.relative_to(root), flush=True)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=SUITES, default=os.environ.get('NEO_SCRATCH_SUITE'))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--target', type=Path, default=os.environ.get('NEO_SCRATCH_TARGET') or ROOT)
    args = parser.parse_args()
    if not args.suite:
        parser.error('Supply SUITE naming the driver test directory')
    apply = os.environ.get('NEO_SCRATCH_APPLY', '0')
    if apply not in ('0', '1'):
        parser.error('APPLY must be 0 or 1')
    os.umask(0o077)
    root = Path(args.target).resolve()
    real_directory(root)
    prune(root, args.suite, args.apply or apply == '1')


if __name__ == '__main__':
    main()
