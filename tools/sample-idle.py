#!/usr/bin/env python3
"""Bounded battery-powered idle sample; optional backlight-off comparison."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys
import time

from battery_sample import sample_age
from awake_clock import AwakeRun, observe, validate, windows


def read(path):
    return Path(path).read_text().strip()


def emit(event, **values):
    print(json.dumps({'event': event, **values}), flush=True)


@contextmanager
def backlight_mode(mode, directory=Path('/sys/class/backlight/ocp8178')):
    if mode == 'keep':
        yield
        return
    previous = int(read(directory / 'brightness'))
    if (mode != 'off' or not 0 < previous <= int(read(directory / 'max_brightness')) or
            int(read(directory / 'bl_power')) != 0):
        raise ValueError('Backlight-off comparison requires a lit, unblanked display')
    from speaker_audio import warn_screen
    warning = {}
    warn_screen(warning, owner=os.environ.get('NEO_WARNING_OWNER'))
    emit('screen_warning', **warning)
    try:
        (directory / 'brightness').write_text('0\n')
        if int(read(directory / 'actual_brightness')) != 0:
            raise ValueError('Backlight did not report off')
        emit('backlight_off', previous_brightness=previous)
        yield
    finally:
        (directory / 'brightness').write_text(str(previous) + '\n')
        if int(read(directory / 'actual_brightness')) != previous:
            raise ValueError('Backlight restoration readback failed')
        emit('backlight_restored', brightness=previous)


def interrupted(signum, _frame):
    # Let the context manager restore brightness before leaving the process.
    raise InterruptedError('Idle sample interrupted by signal ' + str(signum))


def wifi_signal():
    result = subprocess.run(['/usr/sbin/iw', 'dev', 'wlan0', 'link'],
                            capture_output=True, text=True, timeout=10, check=True)
    # Keep SSID and BSSID out of the result; this is context, not a radio survey.
    match = re.search(r'signal:\s*(-?\d+) dBm', result.stdout)
    return int(match[1]) if match else None


def sample(battery, inputs):
    clock_before = observe()
    guard = json.loads(read('/run/gameshellneo/battery.json'))
    now = time.monotonic()
    state = {
        'monotonic_seconds': now,
        'boot_id': read('/proc/sys/kernel/random/boot_id'),
        'capacity_percent': int(read(battery / 'capacity')),
        'status': read(battery / 'status'),
        'present': int(read(battery / 'present')),
        'voltage_uv': int(read(battery / 'voltage_now')),
        'current_ua': int(read(battery / 'current_now')),
        'external_online': {p.name: int(read(p / 'online')) for p in inputs},
        'brightness': int(read('/sys/class/backlight/ocp8178/brightness')),
        'bl_power': int(read('/sys/class/backlight/ocp8178/bl_power')),
        'wifi_carrier': int(read('/sys/class/net/wlan0/carrier')),
        'frequency_khz': int(read('/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq')),
        'governor': read('/sys/devices/system/cpu/cpufreq/policy0/scaling_governor'),
        'temperature_millic': int(read('/sys/class/thermal/thermal_zone0/temp')),
        'kernel_taint': int(read('/proc/sys/kernel/tainted')),
        'guard_monitoring': guard.get('monitoring'),
        'guard_age_seconds': sample_age(guard),
    }
    if (state['present'] != 1 or state['status'] != 'Discharging' or
            not 20 < state['capacity_percent'] <= 100 or state['voltage_uv'] <= 0 or
            state['current_ua'] > 0 or any(state['external_online'].values())):
        raise ValueError('Battery-only sampling conditions failed: ' + json.dumps(state))
    if (state['guard_monitoring'] != 'valid' or not 0 <= state['guard_age_seconds'] <= 25 or
            state['kernel_taint'] or state['temperature_millic'] >= 80000 or
            state['wifi_carrier'] != 1):
        raise ValueError('Health or Wi-Fi sampling conditions failed: ' + json.dumps(state))
    state['awake_window'] = [clock_before, observe()]
    validate(state['awake_window'])
    return state


def summarize(samples):
    if len(samples) < 2:
        raise ValueError('At least two samples are needed')
    awake = windows(samples)
    charge_uas = energy_mws = duration = 0.0
    powers = [s['voltage_uv'] * -s['current_ua'] / 1e9 for s in samples]
    for i, (left, right) in enumerate(zip(samples, samples[1:])):
        dt = right['monotonic_seconds'] - left['monotonic_seconds']
        if dt <= 0:
            raise ValueError('Sample times must increase')
        charge_uas += -(left['current_ua'] + right['current_ua']) / 2 * dt
        energy_mws += (powers[i] + powers[i + 1]) / 2 * dt
        duration += dt
    return {
        'duration_seconds': duration, 'samples': len(samples),
        'estimated_charge_mah': charge_uas / 3600000,
        'estimated_energy_mwh': energy_mws / 3600,
        'time_weighted_current_ma': charge_uas / duration / 1000,
        'time_weighted_power_mw': energy_mws / duration,
        'min_power_mw': min(powers), 'max_power_mw': max(powers),
        'median_power_mw': statistics.median(powers),
        'capacity_start_percent': samples[0]['capacity_percent'],
        'capacity_end_percent': samples[-1]['capacity_percent'],
        'frequency_samples_khz': sorted(set(s['frequency_khz'] for s in samples)),
        'peak_temperature_millic': max(s['temperature_millic'] for s in samples),
        'calibrated': False, 'awake_validation': awake,
    }


def measure(battery, inputs, seconds, mode, awake=None):
    if awake is None:
        awake = AwakeRun()
    initial = sample(battery, inputs)
    fixed = ('boot_id', 'brightness', 'bl_power', 'governor')

    def checked_sample():
        awake.check()
        value = sample(battery, inputs)
        if any(value[key] != initial[key] for key in fixed):
            raise ValueError('Boot, brightness or governor changed during sampling')
        return value

    emit('ready', seconds=seconds, backlight_mode=mode, settle_seconds=60, interval_seconds=10,
         wifi_signal_dbm=wifi_signal(), initial=initial,
         conditions='No controls or other diagnostic tasks. Quiet Wi-Fi SSH stays connected; '
                    'one JSON sample is sent every ten seconds. Battery guard remains active.')
    for remaining in range(50, -1, -10):
        time.sleep(10)
        checked_sample()
        emit('settling', remaining_seconds=remaining)
    samples = []
    started = time.monotonic()
    for index in range(seconds // 10 + 1):
        target = started + 10 * index
        time.sleep(max(0, target - time.monotonic()))
        value = checked_sample()
        value['lateness_seconds'] = max(0, value['monotonic_seconds'] - target)
        if samples and value['monotonic_seconds'] - samples[-1]['monotonic_seconds'] > 20:
            raise ValueError('Sampling gap exceeded twenty seconds')
        samples.append(value)
        emit('sample', **value)
    result = dict(wifi_signal_dbm=wifi_signal(), **summarize(samples))
    result['awake_proof'] = awake.finish()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--backlight', choices=('keep', 'off'), default='keep')
    args = parser.parse_args()
    if not 60 <= args.seconds <= 3600 or args.seconds % 10:
        parser.error('seconds must be a multiple of 10 in 60..3600')
    supplies = list(Path('/sys/class/power_supply').iterdir())
    batteries = [p for p in supplies if read(p / 'type') == 'Battery']
    inputs = [p for p in supplies if read(p / 'type') != 'Battery' and (p / 'online').is_file()]
    if len(batteries) != 1 or not inputs:
        raise ValueError('Expected one battery and identifiable external-power inputs')
    awake = AwakeRun()
    sample(batteries[0], inputs)  # Check battery/health before an optional display write.
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    with backlight_mode(args.backlight):
        result = measure(batteries[0], inputs, args.seconds, args.backlight, awake)
    # Success includes restoration, not just collection of the last sample.
    result['awake_proof'] = awake.finish()
    emit('complete', passed=True, backlight_mode=args.backlight, **result)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        emit('failed', passed=False, error=str(error))
        sys.exit(1)
