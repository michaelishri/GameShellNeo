#!/usr/bin/env python3
"""Run extcon lifetime KUnit tests in isolated Linux UML kernels; no board access."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from kernel_checks import ROOT, archive_for, check_overrides, run, sha256
from kernel_sources import atomic_json, ensure_source, locked
from extcon_kunit_results import checked_cases


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
    parser.add_argument('--variant', choices=('tree', 'tiny', 'all'),
                        default=os.environ.get('NEO_EXTCON_KUNIT_VARIANT', 'all'))
    parser.add_argument('--suite', choices=('notifier', 'provider'),
                        default=os.environ.get('NEO_EXTCON_KUNIT_SUITE', 'notifier'))
    args = parser.parse_args()
    if args.variant not in ('tree', 'tiny', 'all'):
        parser.error('Expected tree, tiny or all')
    if args.suite not in ('notifier', 'provider'):
        parser.error('Expected notifier or provider suite')
    work = ROOT / ('.local/build/extcon-kunit' if args.suite == 'notifier' else
                   '.local/build/extcon-provider-kunit')
    suite_name = 'extcon-' + args.suite + '-lifetime'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        evidence = work / ('evidence-' + args.variant + '.json')
        evidence.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        queue = work / 'patches'
        run(['python3', str(ROOT / 'tools/kernel-inputs.py'), '--export', str(queue)])
        manifest = json.loads((queue / 'manifest.json').read_text())
        with locked(work / '.source-lock'):
            source, _, metadata = ensure_source(ROOT, work, archive, lock, manifest)
        config = ROOT / ('kernel/tests/extcon-kunit.config' if args.suite == 'notifier' else
                         'kernel/tests/extcon-provider-kunit.config')
        builder = lock['builder']
        inputs = {str(p.relative_to(ROOT)): sha256(p) for p in (
            Path(__file__), config, ROOT / 'tools/kernel_sources.py',
            ROOT / 'tools/extcon_kunit_results.py',
            ROOT / 'tools/kernel_checks.py', ROOT / 'build/sources.lock.json')}
        results = {}
        for name in ('tree', 'tiny') if args.variant == 'all' else (args.variant,):
            extra = (['CONFIG_PREEMPT=y', 'CONFIG_TREE_SRCU=y'] if name == 'tree' else
                     ['CONFIG_PREEMPT_NONE=y', 'CONFIG_TINY_SRCU=y'])
            text = config.read_text() + '\n'.join(extra) + '\n'
            identity = hashlib.sha256((metadata['tree_sha256'] + text +
                                       builder['image']).encode()).hexdigest()[:16]
            scratch = work / ('kernel-' + name + '-' + identity)
            scratch.mkdir(exist_ok=True)
            fragment = scratch / 'kunit.config'
            fragment.write_text(text)
            relative = scratch.relative_to(ROOT).as_posix()
            output = scratch / 'output'
            # Keep failed/previous launches and their binary/config identities
            # before KUnit overwrites its conventional test.log/results paths.
            if (output / 'test.log').exists():
                previous = scratch / 'previous-runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
                previous.mkdir(parents=True)
                for path in (output / 'test.log', scratch / 'results.json'):
                    if path.exists():
                        shutil.copyfile(path, previous / path.name)
                atomic_json(previous / 'identity.json', dict(
                    kernel_sha256=sha256(output / 'linux'),
                    config_sha256=sha256(output / '.config'), source=metadata))
            print('Linux UML KUnit configuration: ' + name, flush=True)
            run(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
                 '--platform', builder['platform'], '--network', 'none',
                 '--tmpfs', '/uml-tmp:rw,exec,size=2g,mode=1777',
                 '-e', 'TMPDIR=/uml-tmp', '-e', 'KBUILD_BUILD_USER=gameshellneo',
                 '-e', 'KBUILD_BUILD_HOST=builder', '--entrypoint', 'bash',
                 '-v', f'{ROOT}:/project', '-v', f'{source}:/kernel-source:ro',
                 '-w', '/kernel-source', builder['image'], '-c',
                 'set -euo pipefail\nulimit -c 0\n'
                 # Catch test-source API/compiler mistakes before spending
                 # time on the rest of a new UML kernel. Reuse the same O=.
                 'python3 -u tools/testing/kunit/kunit.py config --arch=um '
                 f'--build_dir=/project/{relative}/output '
                 f'--kunitconfig=/project/{relative}/kunit.config\n'
                 f'make ARCH=um O=/project/{relative}/output -j{builder["jobs"]} '
                 f'drivers/extcon/extcon-{args.suite}-test.o\n'
                 'python3 -u tools/testing/kunit/kunit.py run --arch=um '
                 f'--jobs={builder["jobs"]} --build_dir=/project/{relative}/output '
                 f'--kunitconfig=/project/{relative}/kunit.config --timeout=120 '
                 f'--json=/project/{relative}/results.json --kernel_args=uml_dir=/uml-tmp/state '
                 + ('--kernel_args=fw_devlink=off ' if args.suite == 'provider' else '') + suite_name])
            check_overrides(output / '.config', [line for line in text.splitlines()
                                                  if line.startswith('CONFIG_')])
            report = json.loads((scratch / 'results.json').read_text())
            log = (output / 'test.log').read_text(errors='replace')
            cases = checked_cases(report, log, args.suite)
            record = retain_run(scratch)
            record['cases'] = cases
            atomic_json(ROOT / record['artifact_dir'] / 'evidence.json', dict(
                schema_version=1, suite=suite_name, variant=name, source=metadata, builder=builder,
                inputs=inputs, result=record))
            results[name] = record
            atomic_json(work / 'progress.json', results)
        atomic_json(evidence, dict(schema_version=1, suite=suite_name, linux=lock['linux']['tag'],
            source=dict(path=str(source.relative_to(ROOT)), **metadata), inputs=inputs,
            builder=builder, results=results,
            limits='Real Linux UML scheduler/SRCU on one virtual CPU, not ARM or physical IRQ/USB. '
                   'Notifier suite softirqs suppress userspace uevents. Provider suite uses synthetic '
                   'platform devices with fw_devlink=off and explicit probe-failure cleanup. '
                   'No complete Sunxi/core retirement or device power qualification.'))
        print('KUnit evidence:', evidence.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
