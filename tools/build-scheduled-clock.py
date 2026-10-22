#!/usr/bin/env python3
"""Build and qualify the separate scheduled-clock pause library offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tarfile
import uuid

from development_clock import ROOT, require, sha
from clock_provenance import loads
from managed_container import execute

ABI_FILES = ('arch/arm/tools/syscall.tbl', 'include/uapi/linux/time_types.h',
             'include/uapi/asm-generic/posix_types.h', 'include/uapi/linux/time.h',
             'kernel/time/posix-timers.c')
INPUTS = ('tools/clock-pause.c', 'tools/clock-pause.h', 'tools/tests/clock_pause_probe.c',
          'tools/build-scheduled-clock.py', 'build/sources.lock.json',
          'tools/development_clock.py', 'tools/clock_provenance.py',
          'tools/managed_container.py', 'tools/docker-stage.py', 'tools/kernel_sources.py')
OUTPUTS = ('test-native', 'test-arm', 'probe-arm', 'clock-pause.so', 'pause-readelf.txt',
           'pause-disassembly.txt', 'native-fixtures.txt', 'arm-fixtures.txt',
           'arm-production.txt', 'build.sh')
REQUEST = struct.pack('<qq', 0, 100_000_000).hex()


def abi_sources(archive, lock):
    require(sha(archive) == lock['linux']['tarball_sha256'], 'Pinned Linux pause ABI archive differs')
    version, files = lock['linux']['tag'].removeprefix('v'), {}
    with tarfile.open(archive, 'r|xz') as source:
        for member in source:
            name = member.name.removeprefix('linux-' + version + '/')
            if name in ABI_FILES:
                require(member.isfile(), 'Pause ABI source is not regular')
                files[name] = source.extractfile(member).read().decode()
            if len(files) == len(ABI_FILES):
                break
    verify_abi(files)
    return dict(linux=lock['linux'], files={name: hashlib.sha256(raw.encode()).hexdigest()
        for name, raw in files.items()}, syscall=407, clock=1, flags=0, timespec_bytes=16,
        relative_pause_ns=100_000_000)


def verify_abi(files):
    require(set(files) == set(ABI_FILES), 'Incomplete locked pause ABI source')
    clean = {name: re.sub(r'/\*.*?\*/', '', raw, flags=re.S) for name, raw in files.items()}
    require(re.search(r'^407\s+common\s+clock_nanosleep_time64\s+sys_clock_nanosleep\s*$',
                      clean[ABI_FILES[0]], re.M), 'ARM time64 pause syscall differs')
    compact = lambda name: re.sub(r'\s+', ' ', clean[name])
    require('struct __kernel_timespec { __kernel_time64_t tv_sec; long long tv_nsec; };' in compact(ABI_FILES[1])
        and 'typedef long long __kernel_time64_t;' in compact(ABI_FILES[2])
        and re.search(r'^#define\s+CLOCK_MONOTONIC\s+1\s*$', clean[ABI_FILES[3]], re.M)
        and 'SYSCALL_DEFINE4(clock_nanosleep, const clockid_t, which_clock, int, flags,' in compact(ABI_FILES[4]),
        'Pinned pause timespec/clock/syscall implementation differs')


def buffer_record(value):
    require(all(type(value[key]) is int for key in ('clock', 'syscall', 'flags', 'calls', 'rc', 'errno')),
            'Pause fixture metadata is not integer evidence')
    require((value['clock'], value['syscall'], value['flags'], value['calls']) == (1, 407, 0, 1),
            'Pause fixture syscall/clock/flags/count differs')
    for key in ('request_before', 'request_after', 'remaining'):
        require(isinstance(value[key], str) and re.fullmatch('[0-9a-f]{32}', value[key]),
                'Malformed pause fixture buffer')
    require(value['request_before'] == REQUEST, 'Pause fixture original request differs')


def verify_fixtures(text):
    records = [loads(line.removeprefix('NEO_PAUSE_FIXTURE ')) for line in text.splitlines()
               if line.startswith('NEO_PAUSE_FIXTURE ')]
    require(len(records) == 4 and 'pause fixtures passed:' in text, 'Incomplete pause fixtures')
    for scenario, value in enumerate(records):
        buffer_record(value)
        require(type(value['scenario']) is int and value['scenario'] == scenario and
                (value['rc'], value['errno']) == ((0, 0), (-1, 4), (-1, 14), (0, 0))[scenario],
                'Pause fixture error/status/order differs')
        require(value['request_after'] == (struct.pack('<qq', 0, 1).hex() if scenario == 3 else REQUEST),
                'Pause fixture changed-request evidence differs')
        require(value['remaining'] == (struct.pack('<qq', 0, 30_000_000).hex() if scenario == 1 else 'a5' * 16),
                'Pause fixture original remaining buffer differs')
    return len(records)


def verify_production(text):
    records = [loads(line.removeprefix('NEO_PAUSE_REAL ')) for line in text.splitlines()
               if line.startswith('NEO_PAUSE_REAL ')]
    require(len(records) == 2 and 'ARM production pause library passed:' in text,
            'Incomplete actual ARM pause evidence')
    for value, mode, status in zip(records, ('success', 'interrupted'), ((0, 0), (-1, 4))):
        buffer_record(value)
        require(value['mode'] == mode and (value['rc'], value['errno']) == status and
                value['request_after'] == REQUEST, 'Actual ARM pause status/request differs')
        if mode == 'interrupted':
            sec, ns = struct.unpack('<qq', bytes.fromhex(value['remaining']))
            require(sec == 0 and 0 < ns <= 100_000_000, 'Actual ARM interrupted remainder differs')
    return len(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--linux-archive', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    archive = args.linux_archive.resolve(strict=True)
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    abi = abi_sources(archive, lock)
    output = ROOT / '.local/build/scheduled-clock-pause' / uuid.uuid4().hex
    output.mkdir(parents=True)
    inputs = {name: sha(ROOT / name) for name in INPUTS}
    for name in inputs:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    script = '''set -eu
flags="-std=c11 -O2 -Wall -Wextra -Werror"
cc $flags -fsanitize=undefined -fno-sanitize-recover=all -DNEO_PAUSE_TEST /out/tools/clock-pause.c -o /out/test-native
/out/test-native > /out/native-fixtures.txt
arm-linux-gnueabihf-gcc $flags -DNEO_PAUSE_TEST /out/tools/clock-pause.c -o /out/test-arm
qemu-arm -L /usr/arm-linux-gnueabihf /out/test-arm > /out/arm-fixtures.txt
arm-linux-gnueabihf-gcc $flags -fPIC -shared -Wl,-z,relro,-z,now,-z,noexecstack /out/tools/clock-pause.c -o /out/clock-pause.so
arm-linux-gnueabihf-gcc $flags /out/tools/tests/clock_pause_probe.c -L/out -Wl,-rpath,'$ORIGIN' -l:clock-pause.so -o /out/probe-arm
qemu-arm -L /usr/arm-linux-gnueabihf /out/probe-arm > /out/arm-production.txt
arm-linux-gnueabihf-readelf -h -l -d -Ws /out/clock-pause.so > /out/pause-readelf.txt
arm-linux-gnueabihf-objdump -d /out/clock-pause.so > /out/pause-disassembly.txt
'''
    (output / 'build.sh').write_text(script)
    builder = lock['builder']
    print('Private managed scheduled pause build:', output, flush=True)
    managed = execute('scheduled-clock-pause', ['--pull=never', '--network=none', '--read-only',
        '--cap-drop=ALL', '--security-opt=no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev',
        '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
        '--entrypoint', '/bin/sh', '--mount', f'type=bind,source={output},target=/out',
        builder['image'], '/out/build.sh'], output / 'managed', timeout=180)
    for name in ('native-fixtures.txt', 'arm-fixtures.txt'):
        verify_fixtures((output / name).read_text())
    verify_production((output / 'arm-production.txt').read_text())
    elf = (output / 'pause-readelf.txt').read_text()
    for marker in ('ELF32', 'little endian', 'ARM', 'Version5 EABI', 'hard-float ABI',
                   'DYN (Shared object file)', 'syscall@GLIBC_', 'neo_clock_pause',
                   'neo_clock_pause_layout', 'BIND_NOW', 'GNU_RELRO'):
        require(marker in elf, 'Pause library ELF lacks ' + marker)
    require(inputs == {name: sha(ROOT / name) for name in INPUTS} ==
            {name: sha(output / name) for name in INPUTS} and sha(archive) == lock['linux']['tarball_sha256'],
            'Pause build source/archive changed')
    receipt = dict(schema=1, operation='clock-pause-build', complete=True, builder=builder, abi=abi,
        inputs=inputs, outputs={name: sha(output / name) for name in OUTPUTS},
        tests=['native-ubsan-error-buffers', 'arm-qemu-error-buffers',
               'arm-production-relative-pause', 'arm-production-signal-eintr-no-retry'],
        managed_run=managed['job']['run'], native_fixture_count=4, arm_fixture_count=4, production_calls=2,
        source_archive_sha256=sha(archive), no_hardware_contact=True)
    (output / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Native/ARM pause qualification passed:', output / 'build-receipt.json')


if __name__ == '__main__':
    main()
