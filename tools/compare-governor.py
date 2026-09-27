#!/usr/bin/env python3
"""Compare original/slower/original schedutil update rates, then verify restoration."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


RATE_PATHS = tuple(Path('/sys/devices/system/cpu/cpufreq') / name for name in
                   ('schedutil/rate_limit_us', 'policy0/schedutil/rate_limit_us'))
STATE = Path('/run/gameshellneo-governor-comparison.json')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')


def read(path):
    return path.read_text().strip()


def set_rate(path, value):
    path.write_text(str(value) + '\n')
    if int(read(path)) != value:
        raise ValueError('Governor update-rate readback failed')


def restore_pending():
    """Also called by systemd ExecStopPost after a killed/failed measurement."""
    if not STATE.exists():
        return
    record = json.loads(read(STATE))
    path, original = Path(record['path']), record['original_us']
    if (path not in RATE_PATHS or type(original) is not int or not 0 <= original <= 1000000000 or
            record['boot_id'] != read(BOOT_ID)):
        raise ValueError('Invalid or wrong-boot restoration record; retained for inspection')
    set_rate(path, original)
    STATE.unlink()  # Retain the record if writing or verification failed.


@contextmanager
def saved_rate(candidate):
    paths = [path for path in RATE_PATHS if path.is_file()]
    if len(paths) != 1:
        raise ValueError('Expected exactly one supported schedutil rate-limit path')
    path = paths[0]
    original = int(read(path))
    if not 1000 <= candidate <= 100000 or not 0 <= original < candidate:
        raise ValueError('RATE_US must be 1000..100000 and greater than the original rate limit')
    record = dict(path=str(path), original_us=original, candidate_us=candidate, boot_id=read(BOOT_ID))
    # Exclusive creation rejects unfinished experiments. Save before any settings write.
    fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(record, output)
        output.flush()
        os.fsync(output.fileno())
    try:
        yield path, original
    finally:
        restore_pending()


def helper(filename):
    spec = importlib.util.spec_from_file_location(filename.replace('-', '_'),
                                                 Path(__file__).with_name(filename + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable_configuration(capabilities):
    return {key: value for key, value in capabilities.items()
            if key not in ('schedutil_rate_limit_us', 'cpufreq_time_in_state')}


def compare(seconds, candidate):
    profile, idle = helper('profile-power'), helper('sample-idle')
    initial = profile.health()
    if initial['governor'] != 'schedutil':
        raise ValueError('Comparison requires the existing schedutil governor')
    configuration = stable_configuration(profile.capabilities())
    radio = profile.radio()
    fixed = ('boot_id', 'online_cpus', 'brightness', 'bl_power', 'governor')
    supplies = list(Path('/sys/class/power_supply').iterdir())
    batteries = [p for p in supplies if read(p / 'type') == 'Battery']
    inputs = [p for p in supplies if read(p / 'type') != 'Battery' and (p / 'online').is_file()]
    if len(batteries) != 1 or not inputs:
        raise ValueError('Expected one battery and identifiable external-power inputs')

    def checked(expected):
        health = profile.health()
        capabilities = profile.capabilities()
        if (any(health[key] != initial[key] for key in fixed) or
                stable_configuration(capabilities) != configuration or
                int(capabilities['schedutil_rate_limit_us']) != expected or
                profile.radio()['power_save'] != radio['power_save']):
            raise ValueError('Device state or power configuration changed during comparison')
        return idle.sample(batteries[0], inputs)

    phases = []
    with saved_rate(candidate) as (path, original):
        profile.emit('ready', utc=datetime.now(timezone.utc).isoformat(), kernel=os.uname().release,
                     machine=os.uname().machine, seconds_per_phase=seconds, settle_seconds=30,
                     sample_interval_seconds=10, initial=initial, capabilities=profile.capabilities(),
                     rate_path=str(path), original_us=original, candidate_us=candidate,
                     conditions='USB unplugged; controls untouched; no concurrent diagnostics. '
                                'Only schedutil rate_limit_us changes. Guard stays active. '
                                'Software battery samples use the same cadence in each phase.')
        for label, rate in (('original_before', original), ('slower', candidate),
                            ('original_after', original)):
            if int(read(path)) != rate:
                set_rate(path, rate)
            profile.emit('phase', phase=label, rate_limit_us=rate)
            for _ in range(3):
                time.sleep(10)
                checked(rate)
            before = profile.snapshot()
            samples = []
            started = time.monotonic()
            for index in range(seconds // 10 + 1):
                target = started + index * 10
                time.sleep(max(0, target - time.monotonic()))
                sample = checked(rate)
                if samples and sample['monotonic_seconds'] - samples[-1]['monotonic_seconds'] > 20:
                    raise ValueError('Battery sampling gap exceeded twenty seconds')
                samples.append(sample)
            after = profile.snapshot()
            checked(rate)
            phases.append(dict(phase=label, rate_limit_us=rate, before=before, after=after,
                               battery_samples=samples,
                               counters=profile.summarize(before, after, os.sysconf('SC_CLK_TCK')),
                               battery=idle.summarize(samples)))
    # No success is reported until cleanup has verified the original value.
    profile.health()
    if int(read(path)) != original:
        raise ValueError('Original update rate was not retained after cleanup')
    profile.emit('raw', clock_ticks_per_second=os.sysconf('SC_CLK_TCK'), phases=phases)
    profile.emit('complete', passed=True, restored_us=original,
                 phases=[{key: phase[key] for key in ('phase', 'rate_limit_us', 'counters', 'battery')}
                         for phase in phases])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--rate-us', type=int, default=10000)
    parser.add_argument('--restore', action='store_true', help='Restore saved state only; no health prerequisite')
    args = parser.parse_args()
    if args.restore:
        restore_pending()
        return
    if not 60 <= args.seconds <= 300 or args.seconds % 30:
        parser.error('seconds per phase must be a multiple of 30 in 60..300')
    if not 1000 <= args.rate_us <= 100000:
        parser.error('rate-us must be in 1000..100000')
    compare(args.seconds, args.rate_us)


if __name__ == '__main__':
    def interrupted(signum, _frame):
        raise InterruptedError('Governor comparison interrupted by signal ' + str(signum))
    for number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(number, interrupted)
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(event='failed', passed=False, error=str(error))), flush=True)
        sys.exit(1)
