#!/usr/bin/env python3
"""Bounded RSB autosuspend comparison; restore the owned delay after any exit."""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from battery_sample import sample_age
from awake_clock import AwakeRun, observe, validate, windows

BUS = Path('/sys/bus/platform/devices/1f03400.rsb')
DELAY = BUS / 'power/autosuspend_delay_ms'
BOOT = Path('/proc/sys/kernel/random/boot_id')
STATE = Path('/run/gameshellneo-rsb-comparison.json')
FIRMWARE = Path('/usr/lib/firmware/brcm/brcmfmac43430a0-sdio.bin')
NVRAM = Path('/usr/lib/firmware/brcm/brcmfmac43430a0-sdio.clockwork,clockworkpi-cpi3.txt')
WIFI_CONFIG = Path('/etc/wpa_supplicant/wpa_supplicant-wlan0.conf')


def read(path):
    return Path(path).read_text().strip()


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=20).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def emit(event, **data):
    print(json.dumps(dict(event=event, **data)), flush=True)


def set_delay(value):
    DELAY.write_text(str(value) + '\n')
    if int(read(DELAY)) != value:
        raise ValueError('RSB autosuspend-delay readback failed')


def restore():
    if not STATE.exists():
        return
    saved = json.loads(read(STATE))
    original = saved['original_ms']
    if (saved['path'] != str(DELAY) or saved['boot_id'] != read(BOOT) or
            type(original) is not int or not 0 <= original <= 60000):
        raise ValueError('Invalid RSB restoration ownership; record retained')
    set_delay(original)
    STATE.unlink()


@contextmanager
def saved_delay(candidate):
    original = int(read(DELAY))
    if type(candidate) is not int or not 10 <= candidate <= 500 or original != 1000:
        raise ValueError('Expected original 1000 ms and candidate 10..500 ms')
    with STATE.open('x') as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(dict(path=str(DELAY), original_ms=original, boot_id=read(BOOT)), output)
        output.flush()
        os.fsync(output.fileno())
    try:
        yield original
    finally:
        restore()


def residency():
    clock_before = observe()
    started = time.monotonic_ns()
    values = {name: read(BUS / 'power' / name) for name in
              ('control', 'autosuspend_delay_ms', 'runtime_status',
               'runtime_active_time', 'runtime_suspended_time')}
    for name in ('autosuspend_delay_ms', 'runtime_active_time', 'runtime_suspended_time'):
        values[name] = int(values[name])
    if values['control'] != 'auto' or values['runtime_status'] not in ('active', 'suspended', 'suspending', 'resuming'):
        raise ValueError('RSB runtime PM is unavailable or not automatic')
    result = dict(started_ns=started, finished_ns=time.monotonic_ns(), **values)
    result['awake_window'] = [clock_before, observe()]
    validate(result['awake_window'])
    return result


def summarize(before, after):
    awake = windows([before, after])
    if (before['control'] != after['control'] or
            before['autosuspend_delay_ms'] != after['autosuspend_delay_ms']):
        raise ValueError('RSB policy changed during a measurement')
    seconds = (after['started_ns'] - before['started_ns']) / 1e9
    active = after['runtime_active_time'] - before['runtime_active_time']
    suspended = after['runtime_suspended_time'] - before['runtime_suspended_time']
    # Reads are sequential; allow their duration plus a small jiffy/read boundary margin.
    uncertainty_ms = ((before['finished_ns'] - before['started_ns']) +
                      (after['finished_ns'] - after['started_ns'])) / 1e6 + 100
    if seconds <= 0 or min(active, suspended) < 0 or active + suspended <= 0 or \
            abs(active + suspended - seconds * 1000) > uncertainty_ms:
        raise ValueError('RSB residency counters decreased or elapsed-time coverage failed')
    return dict(seconds=seconds, awake_validation=awake, active_ms=active, suspended_ms=suspended,
                suspended_percent=100 * suspended / (active + suspended),
                counter_coverage_percent=100 * (active + suspended) / (seconds * 1000),
                resume_count=None, limits='Runtime accounting; not physical clock or energy measurement.')


def cached_health():
    guard = json.loads(read('/run/gameshellneo/battery.json'))
    age = sample_age(guard)
    usb = [read(p) for p in Path('/sys/class/udc').glob('*/state')]
    if (guard.get('monitoring') != 'valid' or not 0 <= age <= 25 or
            guard.get('status') not in ('Charging', 'Full', 'Not charging') or
            not 20 < guard.get('capacity_percent', 0) <= 100 or usb != ['configured'] or
            read('/sys/class/net/wlan0/carrier') != '1' or
            read('/proc/sys/kernel/tainted') != '0'):
        raise ValueError('USB-powered RSB comparison health check failed')
    paths = ('/sys/devices/system/cpu/online',
             '/sys/devices/system/cpu/cpufreq/policy0/scaling_governor',
             '/sys/devices/system/cpu/cpufreq/policy0/scaling_min_freq',
             '/sys/devices/system/cpu/cpufreq/policy0/scaling_max_freq',
             '/sys/class/backlight/ocp8178/brightness', '/sys/class/backlight/ocp8178/bl_power',
             '/sys/module/workqueue/parameters/power_efficient')
    rate_paths = [p for p in (Path('/sys/devices/system/cpu/cpufreq/schedutil/rate_limit_us'),
                             Path('/sys/devices/system/cpu/cpufreq/policy0/schedutil/rate_limit_us'))
                  if p.is_file()]
    if len(rate_paths) != 1:
        raise ValueError('Expected one schedutil update-rate control')
    return dict(boot_id=read(BOOT), fixed={p: read(p) for p in paths},
                schedutil_rate_us=read(rate_paths[0]), guard=guard, guard_age_seconds=age)


def fixed_health(value):
    return {key: value[key] for key in ('boot_id', 'fixed', 'schedutil_rate_us')}


def boundary_health(lock):
    image = json.loads(read('/etc/gameshellneo/image.json'))
    if (image['board'] != 'gameshellneo-cpi31' or image['version'] != lock['image_version'] or
            os.uname().release != lock['linux']['tag'][1:] + lock['linux']['localversion'] or
            (BUS / 'driver').resolve().name != 'sunxi-rsb' or
            (BUS / 'of_node/compatible').read_bytes().split(b'\0')[0] != b'allwinner,sun8i-a23-rsb' or
            digest(FIRMWARE) != lock['radio']['firmware']['sha256'] or
            digest(NVRAM) != lock['radio']['nvram']['sha256']):
        raise ValueError('Locked board/kernel/radio/RSB identity check failed')
    units = ('gameshellneo-usb', 'gameshellneo-battery', 'gameshellneo-ready', 'ssh',
             'systemd-networkd', 'wpa_supplicant@wlan0')
    for unit in units:
        fields = dict(line.split('=', 1) for line in command('systemctl', 'show', unit,
                      '-p', 'ActiveState', '-p', 'NRestarts').splitlines())
        if fields != {'ActiveState': 'active', 'NRestarts': '0'}:
            raise ValueError('Unhealthy required service: ' + unit)
    if command('systemctl', '--failed', '--no-legend', '--plain', '--no-pager'):
        raise ValueError('Failed systemd units exist')
    observers = ('idle-sample', 'power-profile', 'governor-profile', 'governor-comparison',
                 'usb-detection', 'usb-reconnects', 'usb-diagnostics', 'scan-test',
                 'firmware-trial', 'stability-test', 'backlight-test', 'pm-test')
    if command('systemctl', 'list-units', '--all', '--plain', '--no-legend',
               '--state=active,activating,deactivating',
               *['gameshellneo-' + n + '.service' for n in observers]):
        raise ValueError('Stop concurrent diagnostic observers')
    journal = command('journalctl', '-b', '-k', '--no-pager', '-o', 'cat')
    prefix = 'brcmf_c_preinit_dcmds: '
    identities = [line.split(prefix, 1)[1].strip() for line in journal.splitlines()
                  if prefix + 'Firmware: ' in line]
    faults = ('Firmware has halted or crashed', 'mmc1: card 0001 removed',
              'Runtime PM usage count underflow', 'WARNING:', 'Oops:', 'Kernel panic')
    if identities != [lock['radio']['firmware']['runtime_identity']] or any(x in journal for x in faults):
        raise ValueError('Firmware reload/crash or kernel fault marker')
    power = Path('/sys/class/power_supply/axp20x-battery')
    charging = {name: read(power / name) for name in
                ('constant_charge_current', 'constant_charge_current_max', 'voltage_max')}
    return dict(health=cached_health(), charging=charging, wifi_config_sha256=digest(WIFI_CONFIG),
                scan_offload=command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'get', 'disable_scan_offload'),
                wifi_power_save=command('/usr/sbin/iw', 'dev', 'wlan0', 'get', 'power_save'),
                journal=journal, runtime=residency())


def compare(lock, seconds, candidate):
    awake = AwakeRun()
    spec = importlib.util.spec_from_file_location('profile_power', Path(__file__).with_name('profile-power.py'))
    profile = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile)
    initial = boundary_health(lock)
    fixed = fixed_health(initial['health'])
    phases = []
    with saved_delay(candidate) as original:
        emit('ready', boot_id=read(BOOT), seconds_per_phase=seconds, candidate_ms=candidate,
             original_ms=original, initial=initial,
             conditions='USB attached. Cached health every 10s; no direct PMIC reads within windows. '
                        'Normal battery guard stays active. No energy or resume-count claim.')
        for label, delay in (('original_before', original), ('shorter', candidate), ('original_after', original)):
            set_delay(delay)
            emit('phase', phase=label, delay_ms=delay)
            time.sleep(15)
            awake.check()
            start_health = cached_health()
            if fixed_health(start_health) != fixed:
                raise ValueError('Initial device configuration changed')
            ticks = os.sysconf('SC_CLK_TCK')
            before_processes = profile.processes()
            before_irq = profile.interrupts(read('/proc/interrupts'))
            before_stat = profile.proc_stat(read('/proc/stat'))
            before = residency()
            started_cpu = time.process_time()
            started = time.monotonic()
            samples = []
            for index in range(seconds // 10 + 1):
                time.sleep(max(0, started + index * 10 - time.monotonic()))
                awake.check()
                health = cached_health()
                if fixed_health(health) != fixed or int(read(DELAY)) != delay or read(BUS / 'power/control') != 'auto':
                    raise ValueError('Device configuration changed during RSB measurement')
                samples.append(dict(monotonic_seconds=time.monotonic(), guard=health['guard']))
            after = residency()
            own_cpu = time.process_time() - started_cpu
            after_stat = profile.proc_stat(read('/proc/stat'))
            after_irq = profile.interrupts(read('/proc/interrupts'))
            after_processes = profile.processes()
            result = summarize(before, after)
            end = boundary_health(lock)
            if (fixed_health(end['health']) != fixed or any(end[k] != initial[k] for k in
                    ('charging', 'wifi_config_sha256', 'scan_offload', 'wifi_power_save')) or
                    not end['journal'].startswith(initial['journal'])):
                raise ValueError('Boundary health/configuration/journal continuity changed')
            new_log = end['journal'][len(initial['journal']):]
            if any('rsb' in line.lower() for line in new_log.splitlines()):
                raise ValueError('New RSB kernel messages require review')
            phases.append(dict(phase=label, delay_ms=delay, before=before, after=after,
                               residency=result, observer_cpu_seconds=own_cpu,
                               processes=profile.process_rates(before_processes, after_processes, result['seconds'], ticks),
                               interrupts=profile.interrupt_rates(before_irq, after_irq, result['seconds']),
                               cpu_accounting={'before': before_stat, 'after': after_stat},
                               guard_samples=samples, new_kernel_log=new_log))
            emit('measured', phase=label, delay_ms=delay, residency=result, observer_cpu_seconds=own_cpu)
    final = boundary_health(lock)
    if int(read(DELAY)) != original or fixed_health(final['health']) != fixed:
        raise ValueError('Final restoration/health failed')
    emit('complete', passed=True, restored_ms=original, final=final, phases=phases, awake_proof=awake.finish())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--delay-ms', type=int, default=100)
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.restore:
        restore()
        return
    if not args.lock or not 60 <= args.seconds <= 300 or args.seconds % 30 or not 10 <= args.delay_ms <= 500:
        parser.error('Lock required; seconds multiple of 30 in 60..300; delay 10..500 ms')
    def interrupted(number, _frame):
        raise InterruptedError('RSB comparison interrupted by signal ' + str(number))
    for number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(number, interrupted)
    compare(json.loads(args.lock.read_text()), args.seconds, args.delay_ms)


if __name__ == '__main__':
    main()
