#!/usr/bin/env python3
"""Bounded perf instruction-pointer sampling of the existing schedutil worker."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from awake_clock import AwakeRun


def worker(processes):
    found = [row for row in processes.values() if row['comm'] == 'sugov:0']
    if len(found) != 1:
        raise ValueError('Expected exactly one sugov:0 worker')
    return found[0]


def record_command(perf, pid, seconds, data):
    if not 10 <= seconds <= 60 or pid <= 0:
        raise ValueError('Expected a positive PID and duration in 10..60 seconds')
    return [str(perf), 'record', '--no-buildid', '--no-buildid-cache',
            '-e', 'cpu-clock:k', '-F', '99', '-m', '64', '-p', str(pid),
            '-o', str(data), '--', '/usr/bin/sleep', str(seconds)]


def require_samples(report):
    if not re.search(r'^# Samples: [1-9][0-9]*', report, re.MULTILINE):
        raise ValueError('perf report contains no positive sample count; inspect raw artifacts')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=30)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 60:
        parser.error('seconds must be in 10..60')
    directory = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location('power_profile', directory / 'profile-power.py')
    profile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile)
    awake = AwakeRun()
    initial = profile.health()
    target = worker(profile.processes())
    configuration = profile.capabilities()
    configuration.pop('cpufreq_time_in_state', None)
    radio = profile.radio()
    fixed = ('boot_id', 'online_cpus', 'brightness', 'bl_power', 'governor')

    def checked():
        awake.check()
        health = profile.health()
        current = profile.capabilities()
        current.pop('cpufreq_time_in_state', None)
        identity = worker(profile.processes())
        if (any(health[key] != initial[key] for key in fixed) or current != configuration or
                profile.radio()['power_save'] != radio['power_save'] or
                any(identity[key] != target[key] for key in ('pid', 'start_ticks'))):
            raise ValueError('Device configuration or governor worker identity changed')
        return health

    perf = directory / 'perf'
    version = subprocess.check_output([str(perf), 'version'], text=True, timeout=10).strip()
    artifacts = ('perf.data', 'perf-record.txt', 'perf-report.txt', 'kallsyms.txt')
    owner = directory.stat()
    started = time.monotonic()
    profile.emit('ready', initial=initial, worker=target, configuration=configuration, radio=radio,
                 kernel=os.uname().release, machine=os.uname().machine,
                 perf_version=version, seconds=args.seconds, sample_frequency_hz=99,
                 event_name='cpu-clock:k', callchains=False)
    try:
        (directory / 'kallsyms.txt').write_text(Path('/proc/kallsyms').read_text())
        with (directory / 'perf-record.txt').open('w') as output:
            with subprocess.Popen(record_command(perf, target['pid'], args.seconds, directory / 'perf.data'),
                                  stdout=output, stderr=subprocess.STDOUT) as process:
                try:
                    while process.poll() is None:
                        if time.monotonic() - started > args.seconds + 15:
                            raise TimeoutError('perf recording exceeded its time bound')
                        checked()
                        time.sleep(2)
                    if process.returncode:
                        raise ValueError('perf recording failed; inspect perf-record.txt')
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
        final = checked()
        with (directory / 'perf-report.txt').open('w') as output:
            subprocess.run([str(perf), 'report', '--stdio', '--no-children', '-n',
                            '--sort', 'symbol', '--percent-limit', '0', '--kallsyms',
                            str(directory / 'kallsyms.txt'), '-i', str(directory / 'perf.data')],
                           stdout=output, stderr=subprocess.STDOUT, check=True, timeout=30)
        require_samples((directory / 'perf-report.txt').read_text())
        profile.emit('complete', passed=True, final=final, worker_after=worker(profile.processes()),
                     awake_proof=awake.finish())
    finally:
        # The upload directory belongs to the SSH account; make only these captures downloadable.
        for name in artifacts:
            path = directory / name
            if path.is_file():
                os.chmod(path, 0o600)
                os.chown(path, owner.st_uid, owner.st_gid)


if __name__ == '__main__':
    def interrupted(signum, _frame):
        raise InterruptedError('Governor profile interrupted by signal ' + str(signum))
    for number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(number, interrupted)
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(event='failed', passed=False, error=str(error))), flush=True)
        sys.exit(1)
