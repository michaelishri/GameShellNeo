#!/usr/bin/env python3
"""Replace verified duplicate compiler sources; preserve all outputs and evidence."""
import argparse
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from kernel_sources import (atomic_json, checked_file, digest, ensure_source, inventory,
                            locked, real_directory, real_file, sha256, source_link,
                            sync_directory, verify_link)

ROOT = Path(__file__).resolve().parents[1]
SUITES = ('musb-sleep-tests', 'cpuidle-s2idle-tests', 'brcmfmac-pm-tests',
          'brcmfmac-lifecycle-tests', 'brcmfmac-irq-tests',
          'brcmfmac-irq-worker-tests', 'brcmfmac-lifecycle-worker-tests')
CONTENTS = {'source', 'output', 'extra.config', 'compiler.txt', 'elf-info.txt',
            '.source-retired', '.source-migration.json'}


def evidence_builds(value):
    if isinstance(value, dict):
        if 'scratch' in value:
            yield value
        for child in value.values():
            yield from evidence_builds(child)
    elif isinstance(value, list):
        for child in value:
            yield from evidence_builds(child)


def evidence_plan(root, work):
    builds, evidence_hashes, output_hashes = set(), {}, {}
    for name in ('matrix-evidence.json', 'compile-evidence.json', 'evidence.json'):
        path = work / name
        if not path.exists() and not path.is_symlink():
            continue
        real_file(path)
        evidence_hashes[name] = sha256(path)
        for record in evidence_builds(json.loads(path.read_text())):
            relative = record['scratch']
            if not isinstance(relative, str) or not re.fullmatch(
                    re.escape(str(work.relative_to(root))) + r'/kernel-[0-9a-f]{16}', relative):
                raise ValueError('Unexpected evidence scratch path')
            scratch = root / relative
            real_directory(scratch)
            if {p.name for p in scratch.iterdir()} - CONTENTS:
                raise ValueError('Unexpected compiler scratch contents: ' + str(scratch))
            objects = record['objects']
            if not isinstance(objects, dict) or not objects:
                raise ValueError('Missing object evidence')
            checks = {'.config': record['config_sha256']}
            for obj, expected in objects.items():
                if not re.fullmatch(r'(?:drivers/|kernel/|arch/arm/)[A-Za-z0-9_./-]+[.]o', obj):
                    raise ValueError('Unexpected object path')
                checks[obj] = expected
            for file, expected in checks.items():
                actual = checked_file(scratch / 'output', file)
                if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
                    raise ValueError('Invalid object/configuration digest')
                if sha256(actual) != expected:
                    raise ValueError('Object/configuration evidence mismatch: ' + str(actual))
                output_hashes[str(actual.relative_to(root))] = expected
            builds.add(scratch)
    if not builds:
        raise ValueError('No completed compiler evidence')
    return sorted(builds), evidence_hashes, output_hashes


def migration_plan(scratch, source, entries, marker):
    current = scratch / 'source'
    retired = scratch / '.source-retired'
    journal = scratch / '.source-migration.json'
    has_journal = journal.exists() or journal.is_symlink()
    has_retired = retired.exists() or retired.is_symlink()
    if has_journal:
        real_file(journal)
        if json.loads(journal.read_text()) != marker:
            raise ValueError('Unexpected source migration record')
    elif has_retired:
        raise ValueError('Retired source has no migration record')
    if current.is_symlink():
        verify_link(current, source)
        if has_retired:
            # rmtree may have been interrupted. Only verified original entries
            # may remain; a replaced source symlink is never followed here.
            remaining = inventory(retired)
            if any(entries.get(name) != value for name, value in remaining.items()):
                raise ValueError('Retired source changed during interrupted cleanup')
        return 'resume' if has_journal else 'shared'
    if current.exists():
        if has_retired or inventory(current) != entries:
            raise ValueError('Legacy source differs from freshly verified source')
        return 'resume' if has_journal else 'replace'
    if not has_journal or not has_retired or inventory(retired) != entries:
        raise ValueError('Missing or incomplete compiler source')
    return 'resume'


def migrate(scratch, source, marker):
    current = scratch / 'source'
    retired = scratch / '.source-retired'
    journal = scratch / '.source-migration.json'
    if not journal.exists():
        atomic_json(journal, marker)
    if not current.is_symlink():
        if current.exists():
            current.rename(retired)
            sync_directory(scratch)
        current.symlink_to(source_link(scratch, source), target_is_directory=True)
        sync_directory(scratch)
    if retired.exists():
        shutil.rmtree(retired)
        sync_directory(scratch)
    journal.unlink()
    sync_directory(scratch)


def recorded_queue(work):
    directory = work / 'patches'
    real_directory(directory)
    real_file(directory / 'manifest.json')
    manifest = json.loads((directory / 'manifest.json').read_text())
    if not isinstance(manifest, list) or not manifest:
        raise ValueError('Missing recorded patch manifest')
    queue, names = [], []
    for entry in manifest:
        if (not isinstance(entry, dict) or set(entry) != {'name', 'sha256'} or
                not isinstance(entry['name'], str) or
                not re.fullmatch(r'[0-9]{4}-[A-Za-z0-9_.-]+[.]patch', entry['name']) or
                not isinstance(entry['sha256'], str) or
                not re.fullmatch('[0-9a-f]{64}', entry['sha256'])):
            raise ValueError('Invalid recorded patch entry')
        path = directory / entry['name']
        real_file(path)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Recorded patch hash mismatch: ' + entry['name'])
        names.append(entry['name'])
        queue.append((entry['name'], data))
    if names != sorted(set(names)) or {p.name for p in directory.iterdir()} != set(names) | {'manifest.json'}:
        raise ValueError('Unexpected recorded patch order or export contents')
    return manifest, queue


def compact(root, suite, *, apply=False, recorded=False):
    if suite not in SUITES:
        raise ValueError('Unsupported suite')
    root = Path(root)
    real_directory(root)
    work = root / '.local/build' / suite
    for path in (root / '.local', root / '.local/build', work):
        real_directory(path)
    with locked(work / '.lock', existing=True), locked(work / '.source-lock'):
        free_before = shutil.disk_usage(work).free
        builds, evidence_hashes, output_hashes = evidence_plan(root, work)
        lock = json.loads(checked_file(root, 'build/sources.lock.json').read_text())
        archive = root / ('.local/downloads/linux-' + lock['linux']['tag'].removeprefix('v') + '.tar.xz')
        # Existing downloads may be intentional shared links; verify their bytes.
        if sha256(archive) != lock['linux']['tarball_sha256']:
            raise ValueError('Locked archive hash mismatch')
        queue = None
        if recorded:
            manifest, queue = recorded_queue(work)
        else:
            with tempfile.TemporaryDirectory(prefix='.queue-', dir=work) as temporary:
                subprocess.run(['python3', str(root / 'tools/kernel-inputs.py'), '--export', temporary],
                               check=True, stdout=subprocess.DEVNULL)
                manifest = json.loads((Path(temporary) / 'manifest.json').read_text())
        source, entries, metadata = ensure_source(root, work, archive, lock, manifest,
                                                 recorded_patches=queue)
        marker = dict(schema=1, source=str(source.relative_to(work)), tree_sha256=digest(entries))
        # Validate every selected tree before removing any copy.
        selection = []
        for scratch in builds:
            print('Verifying source:', scratch.name, flush=True)
            selection.append((scratch, migration_plan(scratch, source, entries, marker)))
        result = dict(schema=1, suite=suite, apply=apply,
                      patch_source='recorded-export' if recorded else 'current-checkout',
                      shared_source=str(source.relative_to(root)), tree_sha256=metadata['tree_sha256'],
                      evidence_sha256=evidence_hashes, output_sha256=output_hashes,
                      selection={p.name: action for p, action in selection}, completed=[],
                      free_bytes_before=free_before,
                      free_bytes_after_preparation=shutil.disk_usage(work).free)
        print(json.dumps({key: value for key, value in result.items() if key != 'output_sha256'}, indent=2), flush=True)
        if apply:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
            report = work / ('compact-' + stamp + '.json')
            atomic_json(report, result)
            try:
                for scratch, action in selection:
                    if action != 'shared':
                        migrate(scratch, source, marker)
                    result['completed'].append(scratch.name)
                    atomic_json(report, result)
                # Recheck preserved evidence and outputs after all replacements.
                _, final_evidence, final_outputs = evidence_plan(root, work)
                if (final_evidence, final_outputs) != (evidence_hashes, output_hashes):
                    raise ValueError('Evidence changed during compaction')
                result['verified'] = True
            finally:
                result['free_bytes_after'] = shutil.disk_usage(work).free
                atomic_json(report, result)
            print('Compaction evidence:', report, flush=True)
        return result


def target_root(value):
    target = Path(value).absolute()
    real_directory(target)
    def common(path):
        return subprocess.check_output(['git', '-C', str(path), 'rev-parse',
                                        '--path-format=absolute', '--git-common-dir'], text=True).strip()
    if common(target) != common(ROOT):
        raise ValueError('TARGET must be this repository or one of its worktrees')
    # Reject symlink aliases; callers should pass the actual worktree path.
    if target != target.resolve():
        raise ValueError('TARGET must be a canonical worktree path')
    top = subprocess.check_output(['git', '-C', str(target), 'rev-parse', '--show-toplevel'], text=True).strip()
    if top != str(target):
        raise ValueError('TARGET must name the worktree root')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=SUITES, default=os.environ.get('NEO_SCRATCH_SUITE'))
    parser.add_argument('--target', default=os.environ.get('NEO_SCRATCH_TARGET') or str(ROOT))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--recorded-patches', action='store_true')
    args = parser.parse_args()
    apply = os.environ.get('NEO_SCRATCH_APPLY', '0')
    recorded = os.environ.get('NEO_SCRATCH_RECORDED_PATCHES', '0')
    if not args.suite or apply not in ('0', '1') or recorded not in ('0', '1'):
        parser.error('Supply SUITE; APPLY and RECORDED_PATCHES must be 0 or 1')
    os.umask(0o077)
    compact(target_root(args.target), args.suite, apply=args.apply or apply == '1',
            recorded=args.recorded_patches or recorded == '1')


if __name__ == '__main__':
    main()
