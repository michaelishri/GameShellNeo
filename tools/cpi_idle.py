"""CPI v3.1 WFI inventory and s2idle evidence; no control writes or energy claims."""
from pathlib import Path
import re


def enabled(lock):
    experiments = lock.get('experiments', {})
    value = experiments.get('cpi_wfi_s2idle', False)
    if type(value) is not bool or ('cpi_wfi_s2idle' in experiments and value is not True):
        raise ValueError('CPI WFI experiment must be explicitly enabled or absent')
    if value and (experiments.get('suspend_diagnostics') is not True or
                  lock.get('features', {}).get('battery_sample_clock') != 'CLOCK_BOOTTIME'):
        raise ValueError('CPI WFI requires suspend diagnostics and BOOTTIME battery samples')
    return value


def timer_dt(root):
    def strings(path):
        return path.read_bytes().rstrip(b'\0').decode('ascii').split('\0') if path.exists() else None
    def cells(path):
        if not path.exists():
            return None
        raw = path.read_bytes()
        return [int.from_bytes(raw[i:i+4], 'big') for i in range(0, len(raw), 4)] if len(raw) % 4 == 0 else None
    timer = root/'timer'
    return dict(board=strings(root/'compatible'), compatible=strings(timer/'compatible'),
                frequency=cells(timer/'clock-frequency'), interrupts=cells(timer/'interrupts'),
                registers_not_fw_configured=(timer/'arm,cpu-registers-not-fw-configured').exists(),
                no_tick_in_suspend=(timer/'arm,no-tick-in-suspend').exists(),
                always_on=(timer/'always-on').exists())


def snapshot(root=Path('/sys/devices/system'), dt=Path('/sys/firmware/devicetree/base')):
    def read(path):
        return path.read_text().strip() if path.exists() else None
    cpu = root/'cpu'
    fields = ('name', 'desc', 'latency', 'residency', 'disable', 'usage', 'time')
    states = {}
    for path in sorted(cpu.glob('cpu[0-9]*/cpuidle/state*')):
        state = {name: read(path/name) for name in fields}
        # These are grouped sysfs attributes, not state0/s2idle_usage files.
        state.update({name: read(path/'s2idle'/name.removeprefix('s2idle_'))
                      for name in ('s2idle_usage', 's2idle_time')})
        states[str(path.relative_to(cpu))] = state
    return dict(schema=1, online=read(cpu/'online'), possible=read(cpu/'possible'),
                driver=read(cpu/'cpuidle/current_driver'),
                governor=read(cpu/'cpuidle/current_governor_ro'),
                clocksource=read(root/'clocksource/clocksource0/current_clocksource'),
                clockevents={p.parent.name: read(p) for p in sorted(
                    (root/'clockevents').glob('clockevent[0-9]*/current_device'))},
                broadcast=read(root/'clockevents/broadcast/current_device'), states=states,
                timer_dt=timer_dt(dt))


def counter(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+', value):
        raise ValueError('Missing or malformed CPU-idle counter')
    return int(value)


def validate(value):
    names = {f'cpu{i}/cpuidle/state0' for i in range(4)}
    if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1 or
            value.get('online') != '0-3' or value.get('possible') != '0-3' or
            value.get('driver') != 'cpi_wfi' or value.get('governor') != 'menu' or
            value.get('clocksource') != 'arch_sys_counter' or set(value.get('states', {})) != names):
        raise ValueError('Expected CPI WFI driver and exactly one state on each of four CPUs')
    events = value.get('clockevents', {})
    if (len(events) != 4 or any(not re.fullmatch(r'clockevent\d+', key) for key in events) or
            any(name != 'arch_sys_timer' for name in events.values()) or value.get('broadcast') != 'sun4i_tick'):
        raise ValueError('Expected four active architecture clock-event devices and a broadcast timer')
    dt = value.get('timer_dt', {})
    if (not {'clockwork,clockworkpi-cpi3', 'allwinner,sun8i-a33'}.issubset(dt.get('board') or []) or
            dt.get('compatible') != ['arm,armv7-timer'] or dt.get('frequency') != [24000000] or
            dt.get('interrupts') != [cell for irq in (13, 14, 11, 10) for cell in (1, irq, 0xf08)] or
            dt.get('registers_not_fw_configured') is not True or
            dt.get('no_tick_in_suspend') is not False or dt.get('always_on') is not False):
        raise ValueError('Live architecture-timer DT differs from the audited CPI v3.1 contract')
    for state in value['states'].values():
        if any(state.get(key) != expected for key, expected in
               dict(name='WFI', desc='ARM WFI', latency='1', residency='1', disable='0').items()):
            raise ValueError('CPI WFI state is disabled or differs from its driver contract')
        for name in ('usage', 'time', 's2idle_usage', 's2idle_time'):
            counter(state.get(name))


def assess(before, after, mode, delivery):
    validate(before)
    validate(after)
    for key in ('online', 'possible', 'driver', 'governor', 'clocksource', 'clockevents', 'broadcast', 'timer_dt'):
        if before[key] != after[key]:
            raise ValueError('CPU-idle/timer identity changed across the diagnostic')
    deltas = {}
    for path in before['states']:
        a, b = before['states'][path], after['states'][path]
        change = {key: counter(b[key])-counter(a[key]) for key in
                  ('usage', 'time', 's2idle_usage', 's2idle_time')}
        if any(number < 0 for number in change.values()):
            raise ValueError('CPU-idle counters reset across the diagnostic')
        deltas[path] = change['s2idle_usage']
    if mode == 'rtc-wake':
        if (any(number < 1 for number in deltas.values()) or
                delivery.get('timekeeping', {}).get('observation') != 'observed'):
            raise ValueError('Require all-CPU s2idle callbacks and observed timekeeping freeze')
    elif mode != 'rehearse' or any(deltas.values()):
        raise ValueError('Unexpected s2idle callback during awake rehearsal')
    return dict(all_cpu_s2idle_callbacks=mode == 'rtc-wake', s2idle_usage_delta=deltas,
                timekeeping_freeze_observed=mode == 'rtc-wake', energy_qualified=False,
                limits='Callback counts and frozen timekeeping; not CPU/DRAM power-off, residency or energy.')
