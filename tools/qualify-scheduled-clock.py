#!/usr/bin/env python3
"""Run new native/ARM Python fixtures and the actual ARM workload offline."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import uuid

from development_clock import ROOT, offline_inputs, require, sha
from managed_container import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('image-checkout', 'reader-build', 'runtime-capture', 'release-manifest', 'pause-build'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('boot-id', 'card-cid', 'store-uuid'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    base = offline_inputs(args.image_checkout, args.reader_build, args.runtime_capture, args.release_manifest,
                          boot_id=args.boot_id, cid=args.card_cid, store_uuid=args.store_uuid)
    spec = importlib.util.spec_from_file_location('scheduled_qualification_host', ROOT / 'tools/check-scheduled-clock.py')
    host = importlib.util.module_from_spec(spec); spec.loader.exec_module(host)
    pause_raw, _ = host.pause_inputs(args.pause_build, args.image_checkout, args.runtime_capture)
    artifacts = args.image_checkout.resolve(strict=True) / '.local/artifacts'
    verification = json.loads((artifacts / 'verification.json').read_text())
    image = artifacts / verification['image']
    require(stat.S_ISREG(image.stat().st_mode) and not image.is_symlink() and
            sha(image) == base['development']['source_image_sha256'], 'Expected verified immutable source image file')
    output = ROOT / '.local/build/scheduled-clock-workload' / uuid.uuid4().hex
    output.mkdir(parents=True)
    paths = [p for p in (ROOT / 'tools').rglob('*') if p.is_file() and p.suffix in ('.py', '.c', '.h', '.sh')]
    paths.append(ROOT / 'build/sources.lock.json')
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}
    for name in inputs:
        target = output / 'source' / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    (output / 'source-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    expected_runtime = []
    for item in base['runtime'].values():
        relative = item['path'].lstrip('/')
        if relative.startswith('lib/'): relative = 'usr/' + relative
        expected_runtime.append(item['sha256'] + '  ' + relative)
    (output / 'runtime-expected.sha256').write_text('\n'.join(expected_runtime) + '\n')
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    layout = lock['layout']['root']
    require(layout['start_sector'] % 2048 == layout['sectors'] % 2048 == 0,
            'Offline extraction requires exact MiB partition boundaries')
    start, count = layout['start_sector'] // 2048, layout['sectors'] // 2048
    script = f'''set -eu
test ! -e /out/rootfs.ext4
dd if=/image of=/out/rootfs.ext4 bs=1048576 skip={start} count={count} conv=sparse,excl status=none
test -f /out/rootfs.ext4
test ! -L /out/rootfs.ext4
mkdir -p /out/runtime/usr/bin /out/runtime/usr/lib
debugfs -R 'rdump /usr/lib/python3.13 /out/runtime/usr/lib' /out/rootfs.ext4 > /out/runtime-extract.log 2>&1
debugfs -R 'rdump /usr/lib/arm-linux-gnueabihf /out/runtime/usr/lib' /out/rootfs.ext4 >> /out/runtime-extract.log 2>&1
debugfs -R 'dump /usr/bin/python3.13 /out/runtime/usr/bin/python3.13' /out/rootfs.ext4 >> /out/runtime-extract.log 2>&1
ln -s usr/lib /out/runtime/lib
ln -s arm-linux-gnueabihf/ld-linux-armhf.so.3 /out/runtime/usr/lib/ld-linux-armhf.so.3
chmod 700 /out/runtime/usr/bin/python3.13
(cd /out/runtime && sha256sum -c /out/runtime-expected.sha256) > /out/runtime-hashes.txt
python3 -B -m unittest discover -s /out/source/tools/tests -p test_clock_scheduled.py -v > /out/native-python-tests.log 2>&1
qemu-arm -L /out/runtime /out/runtime/usr/bin/python3.13 -I -S -B -m unittest discover -s /out/source/tools/tests -p test_clock_scheduled.py -v > /out/arm-python-tests.log 2>&1
qemu-arm -L /out/runtime /out/runtime/usr/bin/python3.13 -I -S -B /out/source/tools/tests/scheduled_clock_arm_probe.py /reader/clock-boundary.so /pause/clock-pause.so /out > /out/arm-workload.log 2>&1
'''
    (output / 'run.sh').write_text(script)
    builder = lock['builder']
    print('Private managed native/ARM Python qualification:', output, flush=True)
    managed = execute('scheduled-clock-workload', ['--pull=never', '--network=none', '--read-only',
        '--cap-drop=ALL', '--security-opt=no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev',
        '--cpus=1', '--memory=512m', '--memory-swap=512m',
        '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
        '--entrypoint', '/bin/sh', '--mount', f'type=bind,source={image},target=/image,readonly',
        '--mount', f'type=bind,source={args.reader_build.resolve()},target=/reader,readonly',
        '--mount', f'type=bind,source={args.pause_build.resolve()},target=/pause,readonly',
        '--mount', f'type=bind,source={output},target=/out', builder['image'], '/out/run.sh'],
        output / 'managed', timeout=300)
    require(inputs == {name: sha(ROOT / name) for name in inputs} ==
            {name: sha(output / 'source' / name) for name in inputs}, 'Python qualification source changed')
    require(sha(image) == base['development']['source_image_sha256'], 'Immutable source image changed')
    runtime = json.loads((args.runtime_capture / 'inventory.json').read_text())
    extracted = {}
    for name, item in runtime['files'].items():
        relative = item['path'].lstrip('/')
        if relative.startswith('lib/'): relative = 'usr/' + relative
        path = output / 'runtime' / relative
        require(path.stat().st_size == item['size'] and sha(path) == item['sha256'], 'Extracted actual runtime differs: ' + name)
        extracted[name] = dict(path=relative, size=path.stat().st_size, sha256=sha(path))
    summary = json.loads((output / 'arm-workload-summary.json').read_text())
    require(summary['complete'] is True and summary['no_kernel_records'] is True and
            summary['no_hardware_contact'] is True and (summary['clocks'], summary['relative_pauses']) == (256, 31),
            'Actual ARM workload did not finish the finite plan')
    test_counts = {}
    for name in ('native-python-tests.log', 'arm-python-tests.log'):
        text = (output / name).read_text()
        counts = re.findall(r'^Ran (\d+) tests', text, re.M)
        require('\nOK\n' in text and len(counts) == 1 and int(counts[0]) > 0,
                'Offline Python fixtures did not pass: ' + name)
        test_counts[name] = int(counts[0])
    names = ('run.sh', 'source-inputs.json', 'runtime-extract.log', 'native-python-tests.log',
             'arm-python-tests.log', 'runtime-expected.sha256', 'runtime-hashes.txt', 'arm-workload.log', 'arm-workload-users.json',
             'arm-workload-no-kernel.txt', 'arm-workload-summary.json')
    record = dict(schema=1, operation='scheduled-clock-offline-workload-qualification', complete=True,
        managed_run=managed['job']['run'], source_image_sha256=sha(image),
        pause_receipt_sha256=hashlib.sha256(pause_raw).hexdigest(),
        original_reader_sha256=sha(args.reader_build / 'clock-boundary.so'),
        pause_library_sha256=sha(args.pause_build / 'clock-pause.so'), extracted_runtime=extracted,
        pure_clock_pause_replay_test_counts=test_counts,
        inputs=inputs, outputs={name: sha(output / name) for name in names}, actual_arm_summary=summary,
        partition_copy=dict(path=str(output / 'rootfs.ext4'), regular_file=True, start_sector=layout['start_sector'],
            sectors=layout['sectors'], readonly_original=True), no_kernel_records=True, no_hardware_contact=True,
        pm_admission=False, clock_reliability_qualified=False)
    (output / 'qualification.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Native/ARM Python and actual256/31 ABI/workload passed:', output / 'qualification.json')


if __name__ == '__main__':
    main()
