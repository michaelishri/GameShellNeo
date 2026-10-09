#!/usr/bin/env python3
"""Build/test the fixed ARM clock comparator in the pinned offline container."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

from remote import ROOT, LOCAL, evidence_directory
from kernel_checks import sha256


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def vdso_sources(lock):
    version = lock['linux']['tag'][1:]
    archive = LOCAL / 'downloads' / ('linux-' + version + '.tar.xz')
    if sha256(archive) != lock['linux']['tarball_sha256']:
        raise ValueError('Kernel archive hash differs')
    names = ('arch/arm/vdso/vgettimeofday.c', 'arch/arm/vdso/vdso.lds.S', 'arch/arm/kernel/vdso.c')
    files = {}
    with tarfile.open(archive, 'r|xz') as tar:
        for member in tar:
            name = member.name.removeprefix('linux-' + version + '/')
            if name in names:
                files[name] = tar.extractfile(member).read()
            if len(files) == len(names):
                break
    code = re.sub(r'\s+', ' ', files[names[0]].decode())
    version_script = files[names[1]].decode()
    if ('int __vdso_clock_gettime64(clockid_t clock, struct __kernel_timespec *ts)' not in code or
            not re.search(r'LINUX_2\.6\s*\{[^}]*__vdso_clock_gettime64;', version_script, re.S)):
        raise ValueError('Pinned ARM vDSO export or layout differs')
    return {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}


def symbols(text):
    return set(re.findall(r'\b([A-Za-z_][A-Za-z_0-9]*)@@?(GLIBC_[0-9.]+)\b', text))


def verify_elf(text):
    for required in ('ELF32', 'little endian', 'ARM', 'Version5 EABI', 'hard-float ABI',
                     '/lib/ld-linux-armhf.so.3', '__clock_gettime64@GLIBC_2.34'):
        if required not in text:
            raise ValueError('Native comparator ELF lacks ' + required)
    if not symbols(text):
        raise ValueError('Missing versioned libc imports')


def main():
    os.umask(0o077)
    destination = evidence_directory()
    print('Private native clock build:', destination, flush=True)
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    abi = load('native_clock_abi', 'check-clock-paths.py').source_receipt(lock)
    vdso = vdso_sources(lock)
    builder = lock['builder']
    source = ROOT / 'tools/compare-clocks-native.c'
    # Compile the retained copy, so the manifest describes the exact input.
    (destination / source.name).write_bytes(source.read_bytes())
    script = '''set -eu
flags="-std=c11 -O2 -Wall -Wextra -Werror"
cc $flags -DNEO_CLOCK_TEST /out/compare-clocks-native.c -o /out/test-host
/out/test-host
arm-linux-gnueabihf-gcc $flags -DNEO_CLOCK_TEST /out/compare-clocks-native.c -o /out/test-arm
qemu-arm -L /usr/arm-linux-gnueabihf /out/test-arm
arm-linux-gnueabihf-gcc $flags /out/compare-clocks-native.c -ldl -o /out/compare-clocks-native
arm-linux-gnueabihf-readelf -h -l -Ws /out/compare-clocks-native > /out/native-readelf.txt
arm-linux-gnueabihf-objdump -d /out/compare-clocks-native > /out/native-disassembly.txt
'''
    (destination / 'build.sh').write_text(script)
    with (destination / 'build-output.txt').open('wb') as output:
        subprocess.run(['docker', 'run', '--rm', '--pull=never', '--network=none', '--read-only',
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev',
            '--user', f'{os.getuid()}:{os.getgid()}', '--platform', builder['platform'],
            '--entrypoint', '/bin/sh', '--mount',
            'type=bind,source=' + str(destination.resolve()) + ',target=/out',
            builder['image'], '/out/build.sh'], stdout=output, stderr=subprocess.STDOUT,
            check=True, timeout=120)
    verify_elf((destination / 'native-readelf.txt').read_text())
    receipt = dict(schema=1, complete=True, builder=builder, abi=abi, vdso_sources=vdso,
        source_sha256=sha256(source), producer_sha256=sha256(Path(__file__)),
        tests=['host-fixtures', 'arm-qemu-fixtures', 'arm-production-abi-assertions'],
        files={name: sha256(destination / name) for name in (
            source.name, 'compare-clocks-native', 'native-readelf.txt', 'native-disassembly.txt',
            'build-output.txt', 'build.sh')})
    if receipt['files'][source.name] != receipt['source_sha256']:
        raise ValueError('Source changed during build')
    (destination / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Native and ARM fixtures passed; ARM production binary ready. BUILD=' + destination.name)


if __name__ == '__main__':
    main()
