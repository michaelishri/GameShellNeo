#!/usr/bin/env python3
"""One owning-task clock capture in a qualified image; launched by the host task."""
import ctypes
import gzip
import io
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import sys
import threading
import time

# -I -S excludes environment/site customization. The host verifies these
# staged files before launch, and the runner checks their contract hashes again.
DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY))
from clock_boundary import KernelControl, NativeReader
from clock_deployment import (SERVICES, bounded, build_id, configuration, digest,
                              execute, save, validate_files)


def read(path):
    return bounded(path).decode().strip()


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=10).stdout.strip()


def runtime_files(maps):
    libraries = set()
    for line in maps.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) != 6:
            continue
        path = fields[5]
        if re.fullmatch(r'/(?:usr/)?lib/arm-linux-gnueabihf/libc\.so\.6', path):
            libraries.add(path)
        elif '/libc.so' in path:
            raise ValueError('Unexpected/deleted libc mapping')
    if len(libraries) != 1:
        raise ValueError('Expected one mapped ARM libc')
    paths = dict(python=str(Path('/proc/self/exe').resolve()), libc=libraries.pop())
    result = {}
    for name, path in paths.items():
        data = bounded(path, 32 * 1024 * 1024)
        if not data.startswith(b'\x7fELF'):
            raise ValueError('Runtime file is not ELF')
        result[name] = dict(path=path, size=len(data), sha256=digest(data))
    return result


def snapshot(reader, contract):
    validate_files(DIRECTORY, contract)
    compressed = bounded('/proc/config.gz', 1024 * 1024)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        config = stream.read(2 * 1024 * 1024 + 1)
    if len(config) > 2 * 1024 * 1024:
        raise ValueError('Oversized running kernel configuration')
    values = configuration(config)
    status = dict(line.split(':', 1) for line in read('/proc/self/status').splitlines())
    namespace = Path('/proc/self/ns/time')
    time_namespace = namespace.stat().st_ino if values.get('CONFIG_TIME_NS') == 'y' else 0
    preload = Path('/etc/ld.so.preload')
    active_pm = command('systemctl', 'list-units', '--all', '--plain', '--no-legend',
                        '--state=active,activating,deactivating',
                        'gameshellneo-pm-test.service', 'gameshellneo-sleep-test.service')
    services = {name: dict(line.split('=', 1) for line in command('systemctl', 'show', name,
                '-p', 'ActiveState', '-p', 'NRestarts').splitlines()) for name in SERVICES}
    return dict(boot_id=read('/proc/sys/kernel/random/boot_id'), kernel=os.uname().release,
        build_id=build_id(bounded('/sys/kernel/notes', 65536)),
        image_sha256=digest(bounded('/etc/gameshellneo/image.json')), config_sha256=digest(config),
        runtime=runtime_files(read('/proc/self/maps')), files=contract['files'],
        platform=dict(machine=platform.machine(), byteorder=sys.byteorder,
            pointer_bytes=ctypes.sizeof(ctypes.c_void_p), long_bytes=ctypes.sizeof(ctypes.c_long),
            isolated=sys.flags.isolated, no_site=sys.flags.no_site, uid=os.geteuid()),
        loader_environment=[key for key in ('LD_PRELOAD', 'LD_AUDIT', 'LD_LIBRARY_PATH') if key in os.environ],
        preload_configured=preload.exists() and bool(preload.read_text().strip()),
        tracing=bool(sys.gettrace() or sys.getprofile()), taint=read('/proc/sys/kernel/tainted'),
        tid=threading.get_native_id(), tgid=os.getpid(),
        nspid=[int(x) for x in status.get('NSpid', '').split()],
        nstgid=[int(x) for x in status.get('NStgid', '').split()],
        namespace_id=time_namespace, affinity=sorted(os.sched_getaffinity(0)),
        task_ids=sorted(int(p.name) for p in Path('/proc/self/task').iterdir()),
        clocksource=read('/sys/devices/system/clocksource/clocksource0/current_clocksource'),
        vdso=reader.vdso(), pm_test=read('/sys/power/pm_test'), pm_units=active_pm,
        pm_stats={p.name: read(p) for p in Path('/sys/power/suspend_stats').iterdir() if p.is_file()},
        usb=[read(p) for p in sorted(Path('/sys/class/udc').glob('*/state'))],
        usb_power={key: read('/sys/class/power_supply/axp20x-usb/' + key) for key in ('present', 'online')},
        services=services)


def open_control():
    fd = os.open('/sys/kernel/debug/neo_clock_capture', os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != 0:
            raise ValueError('Unexpected kernel recorder ownership/mode')
        return KernelControl(fd)
    except BaseException:
        os.close(fd)
        raise


def interrupted(signum, frame):
    raise InterruptedError('Clock diagnostic terminated by signal ' + str(signum))


def main():
    os.umask(0o077)
    # Allow graceful partial export on a host-requested stop. SIGKILL/process
    # loss remain incomplete; the host retains the private stage and unit state.
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        contract = json.loads(bounded(DIRECTORY / 'contract.json'))
        validate_files(DIRECTORY, contract)
        reader = NativeReader(DIRECTORY / 'clock-boundary.so')
        public = {1: time.monotonic_ns, 4: lambda: time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW),
                  7: lambda: time.clock_gettime_ns(time.CLOCK_BOOTTIME)}
        result = execute(DIRECTORY, contract, lambda: snapshot(reader, contract), reader, public, open_control)
    except BaseException as error:
        save(DIRECTORY, 'runner-error.json', dict(type=type(error).__name__, message=str(error)))
        return 1
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
