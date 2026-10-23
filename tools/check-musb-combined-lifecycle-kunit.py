#!/usr/bin/env python3
"""Joined lifecycle tests on one exact readonly46 view, with retained originals."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from kernel_sources import atomic_json, digest, inventory, locked, real_directory, real_file
from managed_container import execute, ManagedCommandFailure
from musb_combined_lifecycle_source import LIMITS, TREE_SHA256, sha256
from musb_combined_lifecycle_kunit import (
    CONFIG, SUITES, TARGETS, checked_cases, diagnostic_contract, generated_view,
    guest, mounted_admission, resources, terminal_result,
)

ROOT = Path(__file__).resolve().parents[1]
MAINTAINED = (
    'tools/check-musb-combined-lifecycle-kunit.py', 'tools/musb_combined_lifecycle_kunit.py',
    'tools/musb_combined_lifecycle_source.py', 'kernel/tests/musb-combined-lifecycle-kunit.c',
    'kernel/tests/musb-combined-lifecycle-kunit.h', 'kernel/tests/musb-combined-sunxi-kunit.c',
    'kernel/tests/musb-combined-phy-kunit.c', 'kernel/tests/musb-combined-lifecycle-kunit.config',
    'tools/tests/test_musb_combined_lifecycle_kunit.py', 'tools/kernel_sources.py',
    'tools/kernel_checks.py', 'tools/kernel_candidates.py', 'tools/kernel-inputs.py',
    'tools/musb_terminal_wake_source.py', 'tools/managed_container.py', 'tools/docker-stage.py',
    'build/sources.lock.json', 'Taskfile.yml',
)
PARSER = ('tools/testing/kunit/kunit.py', 'tools/testing/kunit/kunit_kernel.py',
          'tools/testing/kunit/kunit_parser.py', 'tools/testing/kunit/kunit_json.py',
          'lib/kunit/test.c', 'lib/kunit/attributes.c', 'kernel/power/main.c',
          'drivers/base/power/main.c', 'drivers/base/core.c', 'drivers/base/dd.c',
          'drivers/base/platform.c', 'include/linux/platform_device.h', 'include/linux/suspend.h')


def pins(root):
    return {name: sha256(root / name) for name in MAINTAINED}


def prepare(source, work):
    """Only five small files/inventories: never extract or mutate a kernel tree."""
    work.mkdir(parents=True)
    generated, patch, metadata = generated_view(ROOT, source)
    before = inventory(source)
    if digest(before) != TREE_SHA256:
        raise ValueError('Original45 inventory changed during preparation')
    expected = copy.deepcopy(before)
    for name, data in generated.items():
        if before[name][0] != 'file' or before[name][1] != 0:
            raise ValueError('Read-only replacement requires an existing non-executable target')
        expected[name][2] = hashlib.sha256(data).hexdigest()
        target = work / 'files' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if set(generated) != set(TARGETS):
        raise ValueError('Joined view has an undeclared replacement')
    metadata.update(tree_sha256=digest(expected), inputs=pins(ROOT),
        parser_inputs={name: sha256(source / name) for name in PARSER},
        config_sha256=sha256(ROOT / 'kernel/tests/musb-combined-lifecycle-kunit.config'),
        diagnostic_streams={mode: diagnostic_contract(mode) for mode in SUITES})
    (work / metadata['test_append']['name']).write_bytes(patch)
    atomic_json(work / 'base-inventory.json', before)
    atomic_json(work / 'view-inventory.json', expected)
    atomic_json(work / 'view.json', metadata)
    # Independently replay the actual append on only its four existing targets.
    # This is not a full source tree and cannot be passed to a kernel build.
    replay = work / 'append-replay'
    for name in generated:
        if name == '.gameshellneo-patches.json':
            continue
        path = replay / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((source / name).read_bytes())
    result = subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1'],
        cwd=replay, input=patch, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (work / 'append-replay.stdout').write_bytes(result.stdout)
    (work / 'append-replay.stderr').write_bytes(result.stderr)
    if result.returncode or result.stderr or b'fuzz' in result.stdout or b'offset' in result.stdout:
        raise ValueError('Generated append failed exact no-fuzz replay')
    if any((replay / name).read_bytes() != generated[name] for name in generated if name != TARGETS[-1]):
        raise ValueError('Generated append replay differs from complete replacements')
    atomic_json(work / 'append-replay.json', dict(returncode=result.returncode,
        stdout_sha256=sha256(work / 'append-replay.stdout'), stderr_sha256=sha256(work / 'append-replay.stderr'),
        files={name: sha256(replay / name) for name in generated if name != TARGETS[-1]}))
    return metadata


def admitted_preparation(path, source):
    real_directory(path)
    view = json.loads((path / 'view.json').read_text())
    if view['inputs'] != pins(ROOT):
        raise ValueError('Prepared joined input pins changed; retain and create a new preparation')
    if view['diagnostic_streams'] != {mode: diagnostic_contract(mode) for mode in SUITES}:
        raise ValueError('Prepared entire-stream contract changed')
    # Bind generated bytes back to CURRENT maintained source, not self-declared
    # hashes/stamps in a stale or altered preparation.
    generated, patch_bytes, regenerated = generated_view(ROOT, source)
    if any(view.get(key) != value for key, value in regenerated.items()):
        raise ValueError('Prepared view does not reproduce the current source generator')
    base = json.loads((path / 'base-inventory.json').read_text())
    if digest(base) != TREE_SHA256:
        raise ValueError('Prepared original inventory changed')
    expected = copy.deepcopy(base)
    for name in TARGETS:
        expected[name][2] = hashlib.sha256(generated[name]).hexdigest()
    if (json.loads((path / 'view-inventory.json').read_text()) != expected or
            digest(expected) != view['tree_sha256']):
        raise ValueError('Prepared view inventory does not derive from current five replacements')
    for name in TARGETS:
        target = path / 'files' / name
        real_file(target)
        if target.read_bytes() != generated[name] or sha256(target) != view['replacements'][name]:
            raise ValueError('Prepared replacement changed: ' + name)
    patch = path / view['test_append']['name']
    if patch.read_bytes() != patch_bytes or sha256(patch) != view['test_append']['sha256']:
        raise ValueError('Prepared test append changed')
    return view


def container_args(source, view, destination, lock, command):
    arguments = ['--pull=never', '--network', 'none', '--cpus=1', '--memory=2560m',
        '--user', f'{os.getuid()}:{os.getgid()}', '--platform', lock['builder']['platform'],
        '--tmpfs', '/uml-tmp:rw,exec,size=768m,mode=1777',
        '-e', 'TMPDIR=/uml-tmp', '-e', 'PYTHONDONTWRITEBYTECODE=1',
        '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
        '--entrypoint', 'bash', '-v', f'{ROOT}:/project:ro',
        '-v', f'{source.parent}:/kernel-entry:ro', '-v', f'{source}:/kernel-source:ro',
        '-v', f'{destination}:/qualification', '-v', f'{view}:/view:ro']
    for name in TARGETS:
        arguments += ['-v', f'{view / "files" / name}:/kernel-source/{name}:ro']
    return arguments + ['-w', '/kernel-source', lock['builder']['image'], '-c', command]


def mounted_script():
    return ('python3 -c \'from pathlib import Path;import sys;sys.path.insert(0,"/project/tools");'
        'from musb_combined_lifecycle_kunit import mounted_admission;'
        'from kernel_sources import atomic_json;'
        'atomic_json(Path("/qualification/mounted-source.json"),'
        'mounted_admission(Path("/kernel-entry"),Path("/kernel-source"),Path("/view")))\'\n')


def execute_kernel(source, view_path, work, view):
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    resources(ROOT, ROOT, starting=True)
    build = work / 'build'
    build.mkdir()
    command = ('set -euo pipefail\nulimit -c 0\n' + mounted_script() +
        'python3 -u tools/testing/kunit/kunit.py build --arch=um --jobs=1 '
        '--build_dir=/qualification/output '
        '--kunitconfig=/project/kernel/tests/musb-combined-lifecycle-kunit.config\n'
        'gcc --version > /qualification/compiler.txt\n'
        'readelf -h /qualification/output/linux > /qualification/elf-info.txt\n')
    result = execute('musb-combined-lifecycle-build',
        container_args(source, view_path, build, lock, command), build / 'managed', timeout=None)
    output = build / 'output'
    from kernel_checks import check_overrides
    config = ROOT / 'kernel/tests/musb-combined-lifecycle-kunit.config'
    check_overrides(output / '.config', config.read_text().splitlines())
    # SUNXI_SRAM is selected by the real Sunxi driver, not just requested by us.
    check_overrides(output / '.config', ['CONFIG_SUNXI_SRAM=y', 'CONFIG_REGMAP_MMIO=y'])
    frozen = work / 'frozen-kernel'
    frozen.mkdir()
    shutil.copyfile(output / 'linux', frozen / 'linux')
    (frozen / 'linux').chmod(0o555)
    shutil.copyfile(output / '.config', frozen / 'config')
    identities = dict(kernel_sha256=sha256(frozen / 'linux'), config_sha256=sha256(frozen / 'config'))
    atomic_json(build / 'evidence.json', dict(managed_result=result, **identities,
        mounted_source=json.loads((build / 'mounted-source.json').read_text()),
        source=view, compiler_sha256=sha256(build / 'compiler.txt'), elf_info_sha256=sha256(build / 'elf-info.txt')))
    outcomes = {}
    # Controls are observed before the positive suite, using the SAME kernel.
    for mode in ('terminal-control', 'work-control', 'positive'):
        resources(ROOT, ROOT)
        destination = work / mode
        destination.mkdir()
        # Only own new output: no previous run/kernel/log/result is reused.
        args = container_args(source, view_path, destination, lock,
            'set -euo pipefail\nulimit -c 0\n' + mounted_script() +
            'python3 /project/tools/check-musb-combined-lifecycle-kunit.py '
            '--inside-guest ' + mode + '\n')
        args[args.index(lock['builder']['image']):args.index(lock['builder']['image'])] = [
            '-v', f'{frozen}:/frozen:ro']
        try:
            result = execute('musb-combined-lifecycle-' + mode, args,
                             destination / 'managed', timeout=None)
        except ManagedCommandFailure as error:
            if mode == 'positive':
                raise
            result = error.result
        terminal_result(result, mode=mode)
        raw = destination / 'test.log'
        report = destination / 'results.json'
        cases = checked_cases(json.loads(report.read_text()), raw.read_text(errors='strict'), mode=mode)
        guest_result = json.loads((destination / 'guest-result.json').read_text())
        parser_result = json.loads((destination / 'parser-result.json').read_text())
        if (guest_result['returncode'] != 0 or guest_result['kernel_sha256'] != identities['kernel_sha256'] or
                guest_result['kernel_after_sha256'] != identities['kernel_sha256'] or
                guest_result['raw_log_sha256'] != sha256(raw) or
                parser_result['raw_log_sha256'] != sha256(raw) or
                parser_result['report_sha256'] != sha256(report) or
                parser_result['returncode'] != (0 if mode == 'positive' else 1)):
            raise ValueError('Current guest/parser original execution identity differs')
        record = dict(mode=mode, managed_result=result, source=view, kernel=identities,
            mounted_source=json.loads((destination / 'mounted-source.json').read_text()),
            cases=cases, guest_result=guest_result, parser_result=parser_result,
            artifacts={name: sha256(destination / name) for name in (
                'guest-command.json', 'guest-result.json', 'parser-result.json', 'test.log', 'results.json')},
            resources=resources(ROOT, ROOT))
        atomic_json(destination / 'evidence.json', record)
        outcomes[mode] = record
    if pins(ROOT) != view['inputs'] or sha256(frozen / 'linux') != identities['kernel_sha256']:
        raise ValueError('Joined maintained payload/kernel changed during the original operation')
    return dict(build=str(build), kernel=identities, modes=outcomes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verified-source', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--prepared-view', type=Path)
    parser.add_argument('--inside-guest', choices=tuple(SUITES), help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.inside_guest:
        if options.verified_source or options.prepare_only or options.prepared_view:
            parser.error('Internal guest execution cannot prepare or substitute a source')
        raise SystemExit(guest(Path('/kernel-source'), Path('/frozen/linux'),
                               Path('/qualification'), mode=options.inside_guest))
    if options.verified_source is None or options.verified_source.resolve() != options.verified_source:
        parser.error('--verified-source requires the exact absolute immutable45 path')
    base = ROOT / '.local/build/musb-combined-lifecycle-kunit'
    base.mkdir(parents=True, exist_ok=True)
    with locked(base / 'qualification.lock'):
        resources(ROOT, ROOT, starting=not options.prepare_only)
        attempt = base / ('attempt-' + uuid.uuid4().hex)
        attempt.mkdir()
        atomic_json(attempt / 'admission.json', dict(inputs=pins(ROOT), arguments=vars(options) | {
            'verified_source': str(options.verified_source),
            'prepared_view': str(options.prepared_view) if options.prepared_view else None},
            scope=LIMITS, resources=resources(ROOT, ROOT)))
        try:
            if options.prepared_view:
                if options.prepare_only:
                    parser.error('Existing preparation cannot be overwritten by --prepare-only')
                view_path = options.prepared_view
                if (not view_path.is_absolute() or view_path.resolve() != view_path or
                        not view_path.is_relative_to(base)):
                    parser.error('Prepared view must be an exact owned absolute path')
                view = admitted_preparation(view_path, options.verified_source)
            else:
                view_path = attempt / 'view'
                view = prepare(options.verified_source, view_path)
            if options.prepare_only:
                print('Prepared read-only joined46 view:', view_path, flush=True)
                print('View identity:', view['tree_sha256'], flush=True)
                return
            result = execute_kernel(options.verified_source, view_path, attempt, view)
            atomic_json(attempt / 'evidence.json', dict(schema=1, inputs=pins(ROOT), source=view,
                limits=LIMITS, result=result, resources=resources(ROOT, ROOT)))
            print('Joined lifecycle Linux evidence:', attempt / 'evidence.json', flush=True)
        except BaseException as error:
            atomic_json(attempt / 'failure.json', dict(type=type(error).__name__, error=str(error),
                inputs_after=pins(ROOT), free_bytes=shutil.disk_usage(ROOT).free))
            raise


if __name__ == '__main__':
    main()
