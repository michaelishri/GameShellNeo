#!/usr/bin/env python3
"""Identify the running clock API's binaries; no tracing or device changes."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import sysconfig
import time

MAX_BINARY = 32 * 1024 * 1024


def binaries(maps, executable):
    libraries = set()
    vdso = False
    for line in maps.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) != 6:
            continue
        path = fields[5]
        vdso |= path == '[vdso]'
        if re.fullmatch(r'/(?:usr/)?lib/arm-linux-gnueabihf/libc\.so\.6', path):
            libraries.add(path)
        elif '/libc.so' in path:
            raise ValueError('Unexpected or deleted libc mapping')
    if len(libraries) != 1 or not re.fullmatch(r'/usr/bin/python3\.13', executable):
        raise ValueError('Expected one ARM libc and the diagnostic Python executable')
    return {'python': executable, 'libc': libraries.pop()}, vdso


def binary_record(path):
    path = Path(path)
    size = path.stat().st_size
    if not 0 < size <= MAX_BINARY or not path.is_file():
        raise ValueError('Runtime binary is missing or exceeds capture bound')
    data = path.read_bytes()
    if len(data) != size or data[:4] != b'\x7fELF':
        raise ValueError('Runtime binary changed or is not ELF')
    return dict(path=str(path), size=size, sha256=hashlib.sha256(data).hexdigest())


def main():
    boot = Path('/proc/sys/kernel/random/boot_id')
    original_boot = boot.read_text().strip()
    paths, vdso = binaries(Path('/proc/self/maps').read_text(), str(Path('/proc/self/exe').resolve()))
    files = {role: binary_record(path) for role, path in paths.items()}
    packages = subprocess.run(['dpkg-query', '-W',
        '-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\t${Architecture}\t${db:Status-Status}\n',
        'python3.13-minimal', 'libc6:armhf'], check=True, capture_output=True, text=True, timeout=10).stdout
    flags = ('SIZEOF_TIME_T', 'SIZEOF_LONG', 'SIZEOF_VOID_P', 'HAVE_CLOCK_GETTIME', 'MULTIARCH',
             'CONFIG_ARGS', 'PY_CFLAGS', 'PY_CPPFLAGS')
    timer = Path('/sys/firmware/devicetree/base/timer')
    result = dict(schema=1, operation='clock-runtime-inventory', boot_id=original_boot,
        kernel=os.uname().release, python=sys.version, machine=platform.machine(),
        libc=os.confstr('CS_GNU_LIBC_VERSION'), time_module=time.__spec__.origin,
        monotonic=vars(time.get_clock_info('monotonic')), config={name: sysconfig.get_config_var(name) for name in flags},
        vdso_mapped=vdso, files=files, packages=packages,
        timer_dt=dict(node_present=timer.is_dir(),
                      registers_not_fw_configured=(timer / 'arm,cpu-registers-not-fw-configured').is_file(),
                      clock_frequency_hex=(timer / 'clock-frequency').read_bytes().hex()
                      if (timer / 'clock-frequency').is_file() else None),
        loader_environment_present={name: name in os.environ for name in ('LD_PRELOAD', 'LD_AUDIT', 'LD_LIBRARY_PATH')},
        after_boot_id=boot.read_text().strip(),
        binaries_unchanged=files == {role: binary_record(path) for role, path in paths.items()})
    result['complete'] = result['boot_id'] == result['after_boot_id'] and result['binaries_unchanged']
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
