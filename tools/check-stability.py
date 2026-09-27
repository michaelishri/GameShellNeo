#!/usr/bin/env python3
"""Bounded on-device CPU/memory load and temporary-file storage verification."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

MIB = 1024 * 1024
POLICY = Path('/sys/devices/system/cpu/cpufreq/policy0')
TEMP = Path('/sys/class/thermal/thermal_zone0/temp')


def emit(event, **fields):
    print(json.dumps({'time': datetime.now(timezone.utc).isoformat(),
                      'event': event, **fields}), flush=True)


def number(path):
    return int(path.read_text().strip())


def sample(phase):
    values = {'phase': phase, 'temperature_mc': number(TEMP),
              'frequency_khz': number(POLICY / 'scaling_cur_freq'),
              'kernel_taint': number(Path('/proc/sys/kernel/tainted'))}
    emit('sample', **values)
    if values['temperature_mc'] >= 80000:
        raise RuntimeError('Stopped at the test temperature limit of 80 C')
    if values['kernel_taint']:
        raise RuntimeError('Kernel taint detected')
    states = [path.read_text().strip() for path in Path('/sys/class/udc').glob('*/state')]
    if states != ['configured']:
        raise RuntimeError('Keep USB connected throughout the stability test')


def stop_process(process):
    if process is not None and process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def interrupted(signum, _frame):
    raise RuntimeError('Test interrupted by signal {}'.format(signum))


def check_storage(directory):
    target = directory / 'storage.bin'
    expected = hashlib.sha256()
    emit('storage_start', bytes=128 * MIB, path=str(target))
    with target.open('xb') as output:
        for index in range(128):
            block = os.urandom(MIB)
            output.write(block)
            expected.update(block)
            if (index + 1) % 32 == 0:
                sample('storage_write_{}MiB'.format(index + 1))
        output.flush()
        os.fsync(output.fileno())
    actual = hashlib.sha256()
    read_bytes = 0
    process = None
    try:
        with (directory / 'dd.log').open('wb') as error_log:
            process = subprocess.Popen(['dd', 'if=' + str(target), 'bs=1M',
                                        'iflag=direct', 'status=none'],
                                       stdout=subprocess.PIPE, stderr=error_log,
                                       start_new_session=True)
            with process.stdout:
                while block := process.stdout.read(MIB):
                    actual.update(block)
                    read_bytes += len(block)
            code = process.wait(timeout=10)
        if code or read_bytes != 128 * MIB or actual.digest() != expected.digest():
            raise RuntimeError('Direct-read storage verification failed: ' +
                               (directory / 'dd.log').read_text())
        emit('storage_passed', bytes=read_bytes, sha256=actual.hexdigest(), direct_read=True)
    finally:
        stop_process(process)
        target.unlink(missing_ok=True)


def check_load(directory):
    command = ['stress-ng', '--cpu', '4', '--cpu-method', 'all', '--vm', '1',
               '--vm-bytes', '256M', '--vm-keep', '--verify', '--abort',
               '--timeout', '300s', '--metrics-brief']
    emit('load_start', command=command)
    process = None
    try:
        with (directory / 'stress.log').open('wb') as output:
            process = subprocess.Popen(command, cwd=directory, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 330
            while process.poll() is None:
                sample('cpu_memory_load')
                if time.monotonic() >= deadline:
                    raise RuntimeError('Load exceeded its time limit')
                time.sleep(5)
        emit('stress_result', exit_code=process.returncode,
             log=(directory / 'stress.log').read_text())
        if process.returncode:
            raise RuntimeError('stress-ng reported a failure')
    finally:
        stop_process(process)


def main():
    os.umask(0o077)
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, interrupted)
    try:
        if not shutil.which('stress-ng') or not shutil.which('dd'):
            raise RuntimeError('The diagnostic stress-ng and coreutils tools are required')
        available_kb = next(int(line.split()[1]) for line in
                            Path('/proc/meminfo').read_text().splitlines()
                            if line.startswith('MemAvailable:'))
        if available_kb < 512 * 1024 or shutil.disk_usage('/var/tmp').free < 512 * MIB:
            raise RuntimeError('Need at least 512 MiB of available memory and free disk space')
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        emit('start', boot_id=boot_id, memory_available_kb=available_kb,
             governor=(POLICY / 'scaling_governor').read_text().strip(),
             min_frequency_khz=number(POLICY / 'scaling_min_freq'),
             max_frequency_khz=number(POLICY / 'scaling_max_freq'))
        sample('baseline')
        with tempfile.TemporaryDirectory(prefix='gameshellneo-stability-', dir='/var/tmp') as path:
            directory = Path(path)
            check_storage(directory)
            check_load(directory)
        for _ in range(3):
            time.sleep(5)
            sample('recovery')
        if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot_id:
            raise RuntimeError('Boot identity changed')
        emit('passed', boot_id=boot_id, temporary_files_removed=True)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        emit('failed', error=str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
