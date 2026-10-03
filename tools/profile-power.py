#!/usr/bin/env python3
"""Bounded awake-power counter profile without changing device power settings."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from battery_sample import sample_age


def read(path):
    return Path(path).read_text().strip()


def optional(path):
    try:
        return read(path)
    except OSError:
        return None


def emit(event, **values):
    print(json.dumps(dict(event=event, **values)), flush=True)


def proc_stat(text):
    result = {'cpus': {}, 'counters': {}}
    for line in text.splitlines():
        key, *values = line.split()
        if re.fullmatch(r'cpu\d*', key):
            # Guest time is already included in user/nice; never add it twice.
            if len(values) < 8:
                raise ValueError('Incomplete CPU accounting')
            result['cpus'][key] = [int(x) for x in values[:8]]
        elif key in ('ctxt', 'intr', 'processes', 'softirq'):
            result['counters'][key] = int(values[0])
    return result


def interrupts(text):
    lines = text.splitlines()
    cpus = lines[0].split()
    if not cpus or not all(re.fullmatch(r'CPU\d+', name) for name in cpus):
        raise ValueError('Unrecognized interrupt CPU header')
    result = {}
    for line in lines[1:]:
        key, sep, rest = line.partition(':')
        values = rest.split()
        if not sep or len(values) < len(cpus) or not all(x.isdigit() for x in values[:len(cpus)]):
            continue  # E.g. the non-per-CPU Err counter.
        result[key.strip()] = dict(counts=[int(x) for x in values[:len(cpus)]],
                                   description=' '.join(values[len(cpus):]))
    return {'cpus': cpus, 'rows': result}


def process_stat(text):
    # comm may itself contain spaces or closing parentheses.
    start, end = text.index('('), text.rindex(')')
    fields = text[end + 1:].split()  # Starts at stat field 3 (state).
    return dict(pid=int(text[:start].strip()), comm=text[start + 1:end],
                start_ticks=int(fields[19]), cpu_ticks=int(fields[11]) + int(fields[12]))


def processes():
    result = {}
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            value = process_stat(read(path))
            value['wchan'] = optional(path.with_name('wchan'))
            result[str(value['pid'])] = value
        except (FileNotFoundError, ProcessLookupError):
            continue  # An ordinary exit during enumeration.
    return result


def health():
    guard = json.loads(read('/run/gameshellneo/battery.json'))
    age = sample_age(guard)
    inputs = {p.parent.name: int(read(p)) for p in Path('/sys/class/power_supply').glob('*/online')
              if read(p.parent / 'type') != 'Battery'}
    state = dict(boot_id=read('/proc/sys/kernel/random/boot_id'),
                 online_cpus=read('/sys/devices/system/cpu/online'),
                 brightness=int(read('/sys/class/backlight/ocp8178/brightness')),
                 bl_power=int(read('/sys/class/backlight/ocp8178/bl_power')),
                 governor=read('/sys/devices/system/cpu/cpufreq/policy0/scaling_governor'),
                 wifi_carrier=int(read('/sys/class/net/wlan0/carrier')),
                 temperature_millic=int(read('/sys/class/thermal/thermal_zone0/temp')),
                 kernel_taint=int(read('/proc/sys/kernel/tainted')),
                 guard_age_seconds=age, guard=guard, external_online=inputs)
    if (not inputs or any(inputs.values()) or guard.get('monitoring') != 'valid' or
            guard.get('status') != 'Discharging' or not 20 < guard.get('capacity_percent', 0) <= 100 or
            not 0 <= age <= 25 or state['kernel_taint'] or state['temperature_millic'] >= 80000 or
            state['wifi_carrier'] != 1):
        raise ValueError('Battery-only profile conditions failed: ' + json.dumps(state))
    return state


def radio():
    def iw(*args):
        return subprocess.run(['/usr/sbin/iw', 'dev', 'wlan0', *args], check=True,
                              capture_output=True, text=True, timeout=10).stdout.strip()
    power = iw('get', 'power_save')
    if power not in ('Power save: on', 'Power save: off'):
        raise ValueError('Unrecognized Wi-Fi power-save response')
    link = iw('link')
    match = re.search(r'signal:\s*(-?\d+) dBm', link)
    # Never retain SSID/BSSID, credentials or process command lines.
    return dict(power_save=power.rsplit(' ', 1)[1],
                signal_dbm=int(match[1]) if match else None)


def capabilities():
    base = Path('/sys/devices/system/cpu')
    names = ('scaling_driver', 'scaling_governor', 'scaling_min_freq', 'scaling_max_freq',
             'cpuinfo_transition_latency')
    return dict(cpuidle_driver=optional(base / 'cpuidle/current_driver'),
                cpuidle_governor=optional(base / 'cpuidle/current_governor_ro'),
                cpufreq={name: optional(base / 'cpufreq/policy0' / name) for name in names},
                cpufreq_time_in_state=optional(base / 'cpufreq/policy0/stats/time_in_state'),
                schedutil_rate_limit_us=(optional(base / 'cpufreq/policy0/schedutil/rate_limit_us') or
                                        optional(base / 'cpufreq/schedutil/rate_limit_us')),
                trace_events_available=Path('/sys/kernel/tracing/available_events').is_file(),
                workqueue_power_efficient=optional('/sys/module/workqueue/parameters/power_efficient'))


def peripheral_state():
    result = {}
    for bus in ('platform', 'sdio', 'usb'):
        for path in Path('/sys/bus', bus, 'devices').glob('*/power/runtime_status'):
            result[bus + '/' + path.parents[1].name] = {
                name: optional(path.with_name(name)) for name in
                ('runtime_status', 'control', 'runtime_active_time', 'runtime_suspended_time')}
    return result


def snapshot():
    started = time.monotonic()
    result = dict(health=health(), radio=radio(), capabilities=capabilities(),
                  peripherals=peripheral_state(),
                  processes=processes(),
                  network={p.name: int(read(p)) for p in Path('/sys/class/net/wlan0/statistics').iterdir()
                           if p.name in ('rx_bytes', 'tx_bytes', 'rx_packets', 'tx_packets',
                                         'rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped')},
                  cpuidle={str(p.relative_to('/sys/devices/system/cpu')): read(p)
                           for p in Path('/sys/devices/system/cpu').glob('cpu[0-9]*/cpuidle/state*/*')
                           if p.name in ('name', 'usage', 'time', 'disable')})
    # Keep the main counter reads adjacent; these files are not an atomic snapshot.
    result['monotonic_seconds'] = time.monotonic()
    result['stat'] = proc_stat(read('/proc/stat'))
    result['interrupts'] = interrupts(read('/proc/interrupts'))
    result['softirqs'] = interrupts(read('/proc/softirqs'))
    result['capture_seconds'] = time.monotonic() - started
    return result


def delta(left, right):
    value = right - left
    if value < 0:
        raise ValueError('Counter decreased; cannot interpret the interval')
    return value


def interrupt_rates(left, right, seconds):
    if left['cpus'] != right['cpus']:
        raise ValueError('Interrupt CPU columns changed')
    rows = []
    for key in left['rows'].keys() & right['rows'].keys():
        a, b = left['rows'][key], right['rows'][key]
        if a['description'] != b['description']:
            raise ValueError('Interrupt identity changed')
        counts = [delta(x, y) for x, y in zip(a['counts'], b['counts'])]
        rows.append(dict(id=key, description=a['description'], counts=counts,
                         count=sum(counts), per_second=sum(counts) / seconds))
    return sorted(rows, key=lambda row: row['count'], reverse=True)


def process_rates(left, right, seconds, ticks):
    rows = []
    for pid in left.keys() & right.keys():
        a, b = left[pid], right[pid]
        if a['start_ticks'] != b['start_ticks']:
            continue  # Reused PID is not a continuous process.
        cpu = delta(a['cpu_ticks'], b['cpu_ticks']) / ticks
        rows.append(dict(pid=int(pid), comm=b['comm'], cpu_seconds=cpu,
                         percent_one_cpu=100 * cpu / seconds, wchan=b.get('wchan')))
    return sorted(rows, key=lambda row: row['cpu_seconds'], reverse=True)


def stack_samples(ranked, identities):
    # Best-effort stacks after the quiet counter interval, not a statistical profiler.
    targets = [row for row in ranked if row['cpu_seconds'] > 0][:3]
    samples = []
    for _ in range(20):
        for row in targets:
            pid = str(row['pid'])
            value = optional(Path('/proc', pid, 'stat'))
            if value is None or process_stat(value)['start_ticks'] != identities[pid]['start_ticks']:
                continue
            samples.append(dict(pid=int(pid), comm=row['comm'], monotonic_seconds=time.monotonic(),
                                stack=optional(Path('/proc', pid, 'stack'))))
        time.sleep(0.1)
    return samples


def summarize(before, after, ticks):
    seconds = after['monotonic_seconds'] - before['monotonic_seconds']
    if seconds <= 0 or before['stat']['cpus'].keys() != after['stat']['cpus'].keys():
        raise ValueError('Invalid duration or changed CPU set')
    cpus = {}
    for key, a in before['stat']['cpus'].items():
        values = [delta(x, y) for x, y in zip(a, after['stat']['cpus'][key])]
        total = sum(values)
        if not total:
            raise ValueError('No CPU accounting progress')
        busy = sum(values[i] for i in (0, 1, 2, 5, 6))
        cpu_count = len(before['stat']['cpus']) - 1 if key == 'cpu' else 1
        cpus[key] = dict(busy_percent=100 * busy / total, idle_percent=100 * values[3] / total,
                         iowait_percent=100 * values[4] / total,
                         steal_percent=100 * values[7] / total,
                         accounted_cpu_seconds=total / ticks,
                         accounting_coverage_percent=100 * total / ticks / seconds / cpu_count
                         if cpu_count else None)
    return dict(duration_seconds=seconds, cpu=cpus,
                counters={key: dict(count=delta(a, after['stat']['counters'][key]),
                                    per_second=delta(a, after['stat']['counters'][key]) / seconds)
                          for key, a in before['stat']['counters'].items()},
                interrupts=interrupt_rates(before['interrupts'], after['interrupts'], seconds),
                softirqs=interrupt_rates(before['softirqs'], after['softirqs'], seconds),
                processes=process_rates(before['processes'], after['processes'], seconds, ticks),
                network={key: delta(a, after['network'][key]) for key, a in before['network'].items()},
                radio_before=before['radio'], radio_after=after['radio'],
                processes_only_before=len(before['processes'].keys() - after['processes'].keys()),
                processes_only_after=len(after['processes'].keys() - before['processes'].keys()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 300 or args.seconds % 30:
        parser.error('seconds must be a multiple of 30 in 30..300')
    initial = health()
    fixed = ('boot_id', 'online_cpus', 'brightness', 'bl_power', 'governor')

    def checked():
        value = health()
        if any(value[key] != initial[key] for key in fixed):
            raise ValueError('Boot, CPU set, brightness or governor changed')
        return value

    emit('ready', utc=datetime.now(timezone.utc).isoformat(), kernel=os.uname().release,
         machine=os.uname().machine, seconds=args.seconds,
         settle_seconds=30, initial=initial, capabilities=capabilities(),
         conditions='Keep USB unplugged and controls untouched. No concurrent diagnostics. '
                    'Power settings unchanged. Health read every 30 seconds; raw counters '
                    'held in memory until the end to reduce SSH traffic.')
    time.sleep(30)
    checked()
    before = snapshot()
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        time.sleep(min(30, max(0, deadline - time.monotonic())))
        checked()
    after = snapshot()
    checked()
    # Residency counters naturally change; compare the remaining configuration.
    a, b = dict(before['capabilities']), dict(after['capabilities'])
    a.pop('cpufreq_time_in_state', None)
    b.pop('cpufreq_time_in_state', None)
    if a != b or before['radio']['power_save'] != after['radio']['power_save']:
        raise ValueError('Power configuration changed during profile')
    ticks = os.sysconf('SC_CLK_TCK')
    summary = summarize(before, after, ticks)
    stacks = stack_samples(summary['processes'], after['processes'])
    summary['stack_reads'] = len(stacks)
    summary['stack_reads_with_frames'] = sum(bool(row['stack']) for row in stacks)
    emit('raw', clock_ticks_per_second=ticks, before=before, after=after,
         post_interval_stacks=stacks,
         debug={name: optional(path) for name, path in {
             'clocks': '/sys/kernel/debug/clk/clk_summary',
             'regulators': '/sys/kernel/debug/regulator/regulator_summary',
             'timers': '/proc/timer_list'}.items()})
    emit('complete', passed=True, **summary)


if __name__ == '__main__':
    def interrupted(signum, _frame):
        raise InterruptedError('Profile interrupted by signal ' + str(signum))
    for signal_number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_number, interrupted)
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        emit('failed', passed=False, error=str(error))
        sys.exit(1)
