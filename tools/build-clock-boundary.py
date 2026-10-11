#!/usr/bin/env python3
"""Build the clock-boundary reader and fixtures offline; never contact a device."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

from kernel_checks import sha256
from remote import ROOT, LOCAL, evidence_directory
from clock_boundary import decoded_ns
from clock_provenance import loads


def abi_sources(lock):
    spec = importlib.util.spec_from_file_location('boundary_abi', ROOT / 'tools/check-clock-paths.py')
    source = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source)
    receipt = source.source_receipt(lock)
    version = lock['linux']['tag'][1:]
    names = ('arch/arm/tools/syscall.tbl', 'include/vdso/time32.h', 'include/linux/clocksource_ids.h')
    files = {}
    with tarfile.open(LOCAL / 'downloads' / ('linux-' + version + '.tar.xz'), 'r|xz') as archive:
        for member in archive:
            name = member.name.removeprefix('linux-' + version + '/')
            if name in names:
                files[name] = archive.extractfile(member).read().decode()
            if len(files) == len(names):
                break
    if (not re.search(r'^263\s+common\s+clock_gettime\s+sys_clock_gettime32\s*$', files[names[0]], re.M) or
            'typedef s32 old_time32_t;' not in re.sub(r'\s+', ' ', files[names[1]]) or
            'struct old_timespec32 { old_time32_t tv_sec; s32 tv_nsec; };' not in
            re.sub(r'\s+', ' ', files[names[1]])):
        raise ValueError('Pinned ARM time32 ABI differs')
    if 'CSID_GENERIC = 0, CSID_ARM_ARCH_COUNTER,' not in re.sub(r'\s+', ' ', files[names[2]]):
        raise ValueError('Pinned architectural clocksource ID differs')
    receipt['files'].update({name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()})
    return receipt


def verify_elf(text):
    for marker in ('ELF32', 'little endian', 'ARM', 'Version5 EABI', 'hard-float ABI',
                   'DYN (Shared object file)', '__clock_gettime64@GLIBC_2.34', 'syscall@GLIBC_',
                   'neo_clock_read', 'neo_clock_layout', 'neo_clock_vdso', 'BIND_NOW', 'GNU_RELRO'):
        if marker not in text:
            raise ValueError('Boundary library ELF lacks ' + marker)


def verify_arm_fixture(text):
    records = [loads(line.removeprefix('NEO_BOUNDARY_FIXTURE ')) for line in text.splitlines()
               if line.startswith('NEO_BOUNDARY_FIXTURE ')]
    expected = [(route, clock, index) for route in ('syscall64', 'syscall32', 'libc64')
                for clock in (1, 4, 7) for index in range(3)]
    if len(records) != len(expected):
        raise ValueError('Missing or extra ARM raw-buffer fixtures')
    for c, (route, clock, index) in zip(records, expected):
        sec, nsec, value = decoded_ns(c)
        if (c['route'], c['clock'], c['size']) != (route, clock, 8 if route == 'syscall32' else 16):
            raise ValueError('ARM fixture route/order differs')
        if (c['sec'], c['nsec']) != (sec, nsec):
            raise ValueError('ARM raw bytes disagree with C fields')
        if index == 2:
            if (c['raw'], c['rc'], c['errno'], c['converted'], c['native_ns'], value) != (
                    'a5' * 16, -1, 14, 0, -1, None):
                raise ValueError('ARM failed-read evidence differs')
        else:
            wanted_nsec = 6350 if index == 0 else 5600
            if (sec, nsec, c['rc'], c['errno'], c['converted'], c['native_ns'], value) != (
                    7, wanted_nsec, 0, 0, 1, 7_000_000_000 + wanted_nsec, 7_000_000_000 + wanted_nsec):
                raise ValueError('ARM raw-buffer conversion or regression differs')
    return len(records)


def main():
    os.umask(0o077)
    destination = evidence_directory()
    print('Private clock-boundary build:', destination, flush=True)
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    abi = abi_sources(lock)
    inputs = ['tools/clock-boundary.c', 'tools/clock_boundary.py', 'tools/clock_provenance.py',
              'tools/clock_deployment.py', 'tools/capture-clock-boundary.py',
              'tools/build-clock-boundary.py', 'tools/check-clock-paths.py', 'build/sources.lock.json']
    hashes = {name: sha256(ROOT / name) for name in inputs}
    for name in inputs:
        path = destination / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    script = '''set -eu
flags="-std=c11 -O2 -Wall -Wextra -Werror"
cc $flags -fsanitize=undefined -fno-sanitize-recover=all -DNEO_CLOCK_TEST /out/tools/clock-boundary.c -ldl -o /out/test-host
/out/test-host > /out/host-fixtures.txt
arm-linux-gnueabihf-gcc $flags -DNEO_CLOCK_TEST /out/tools/clock-boundary.c -ldl -o /out/test-arm
qemu-arm -L /usr/arm-linux-gnueabihf /out/test-arm > /out/arm-fixtures.txt
arm-linux-gnueabihf-gcc $flags -fPIC -shared -Wl,-z,relro,-z,now,-z,noexecstack /out/tools/clock-boundary.c -ldl -o /out/clock-boundary.so
arm-linux-gnueabihf-readelf -h -l -d -Ws /out/clock-boundary.so > /out/reader-readelf.txt
arm-linux-gnueabihf-objdump -d /out/clock-boundary.so > /out/reader-disassembly.txt
'''
    (destination / 'build.sh').write_text(script)
    builder = lock['builder']
    with (destination / 'build-output.txt').open('wb') as output:
        subprocess.run(['docker', 'run', '--rm', '--pull=never', '--network=none', '--read-only',
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev',
            '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
            '--entrypoint', '/bin/sh', '--mount',
            'type=bind,source=' + str(destination.resolve()) + ',target=/out',
            builder['image'], '/out/build.sh'], stdout=output, stderr=subprocess.STDOUT,
            check=True, timeout=120)
    verify_elf((destination / 'reader-readelf.txt').read_text())
    fixture_count = verify_arm_fixture((destination / 'arm-fixtures.txt').read_text())
    if hashes != {name: sha256(ROOT / name) for name in inputs} or hashes != {
            name: sha256(destination / name) for name in inputs}:
        raise ValueError('Clock-boundary inputs changed during build')
    outputs = ('clock-boundary.so', 'test-host', 'test-arm', 'reader-readelf.txt',
               'reader-disassembly.txt', 'build.sh', 'build-output.txt', 'host-fixtures.txt', 'arm-fixtures.txt')
    receipt = dict(schema=1, operation='clock-boundary-build', complete=True, builder=builder,
                   abi=abi, arm_raw_buffer_fixtures=fixture_count, inputs=hashes,
                   outputs={name: sha256(destination / name) for name in outputs},
                   tests=['host-ubsan-fixtures', 'arm-qemu-fixtures', 'arm-production-layout-assertions'])
    (destination / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Native/ARM fixtures and library validation passed. BUILD=' + destination.name)


if __name__ == '__main__':
    main()
