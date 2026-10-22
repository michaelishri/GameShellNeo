#!/usr/bin/env python3
"""Replay unchanged reader binaries in an owned offline native/ARM container."""
import argparse
import json
import os
from pathlib import Path
import uuid

from development_clock import ROOT, READER_OUTPUTS, reader_fixtures, require, sha
from managed_container import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reader-build', type=Path, required=True)
    args = parser.parse_args()
    reader = args.reader_build.resolve(strict=True)
    receipt = json.loads((reader / 'build-receipt.json').read_text())
    require(receipt['operation'] == 'clock-boundary-build' and receipt['complete'] is True and
            set(receipt['outputs']) == set(READER_OUTPUTS), 'Expected original completed reader build')
    for name, expected in receipt['outputs'].items():
        require(sha(reader / name) == expected, 'Original reader output changed: ' + name)
    builder = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']
    require(receipt['builder'] == builder, 'Pinned reader builder differs')
    output = ROOT / '.local/build/development-clock-reader' / uuid.uuid4().hex
    output.mkdir(parents=True)
    paths = [ROOT / name for name in ('tools/qualify-development-clock.py', 'tools/development_clock.py',
             'tools/managed_container.py', 'tools/docker-stage.py', 'build/sources.lock.json')]
    paths += [reader / name for name in ('build-receipt.json', *READER_OUTPUTS)]
    inputs = {str(path): sha(path) for path in paths}
    (output / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    script = '''set -eu
/reader/test-host > /out/host-fixtures.txt
qemu-arm -L /usr/arm-linux-gnueabihf /reader/test-arm > /out/arm-fixtures.txt
arm-linux-gnueabihf-readelf -h -l -d -Ws /reader/clock-boundary.so > /out/reader-readelf.txt
'''
    (output / 'run.sh').write_text(script)
    print('Private managed reader replay:', output, flush=True)
    result = execute('development-clock-reader', ['--pull=never', '--network=none', '--read-only',
        '--cap-drop=ALL', '--security-opt=no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev',
        '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
        '--entrypoint', '/bin/sh', '--mount', f'type=bind,source={reader},target=/reader,readonly',
        '--mount', f'type=bind,source={output},target=/out', builder['image'], '/out/run.sh'],
        output / 'managed', timeout=180)
    require('clock-boundary fixtures passed' in (output / 'host-fixtures.txt').read_text(),
            'Native fixture did not finish')
    count = reader_fixtures((output / 'arm-fixtures.txt').read_text())
    require((output / 'reader-readelf.txt').read_bytes() == (reader / 'reader-readelf.txt').read_bytes(),
            'Reader ELF metadata changed')
    require(inputs == {str(path): sha(path) for path in paths}, 'Reader qualification inputs changed')
    record = dict(schema=1, operation='development-clock-reader-qualification', complete=True,
        original_receipt_sha256=sha(reader / 'build-receipt.json'), original_reader=str(reader),
        reader_sha256=sha(reader / 'clock-boundary.so'), arm_raw_buffer_fixtures=count,
        managed_run=result['job']['run'], producer_sha256=sha(Path(__file__)),
        inputs=inputs,
        outputs={name: sha(output / name) for name in
                 ('run.sh', 'host-fixtures.txt', 'arm-fixtures.txt', 'reader-readelf.txt')})
    (output / 'qualification.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Managed native/ARM reader qualification passed:', output / 'qualification.json')


if __name__ == '__main__':
    main()
