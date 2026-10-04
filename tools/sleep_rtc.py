"""RTC s2idle diagnostic with verified sequential attempts and awake rehearsal. No ordinary sleep policy."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import struct
import subprocess
import sys
import time

import keypad_pm
import power_key
import power_key_pm
import power_key_policy as policy
import rtc_alarm as rtc
import pm_platform
import wifi_trace
import usb_trace
import speaker_audio
import sleep_connection
import sleep_cable

RESULTS = Path('/var/lib/gameshellneo/sleep-tests')
OWNED = Path('/run/gameshellneo-sleep-controls.json')
SECONDS, MIN_MARGIN = 30, 15
MAX_CLOCK_SAMPLE_SECONDS = 0.05
MAX_SLEEP_CHAIN = 16
SDIO = 'consumer:platform:1c10000.mmc'
SDIO_PATCH = 'kernel/patches/0023-sunxi-mmc-sdio-reference-ownership.patch'
SDIO_SHA = '52f4e3d8b966f8f69718340697606e30d174033d998be84f98b42bc2c97e92ee'
SOURCES = ('sleep_rtc', 'test-pm-stages', 'keypad_pm', 'power_key', 'power_key_policy',
           'power_key_pm', 'power_key_input', 'keypad_input', 'speaker_audio',
           'rtc_alarm', 'pm_platform', 'wifi_trace', 'usb_trace', 'sleep_connection', 'sleep_cable')


def pm_module():
    spec = importlib.util.spec_from_file_location('sleep_pm', Path(__file__).with_name('test-pm-stages.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sources():
    return {name: hashlib.sha256(Path(__file__).with_name(name+'.py').read_bytes()).hexdigest()
            for name in SOURCES}


def digest(record):
    # The host adds these two proofs after collecting the unchanged device result.
    value = {k: v for k, v in record.items() if k not in ('usb_ssh_verified', 'wifi_ssh_verified')}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prerequisite(records, current):
    """Exact same-boot completed baseline, with stable counts and no intervening PM."""
    ordered = sorted(records, key=lambda r: r['before']['monotonic_seconds'])
    stages = [r.get('stage') for r in ordered]
    if (len(records) != 7 or stages != ['freezer', 'devices']+['platform']*5 or
            len({r.get('run_id') for r in records}) != 7):
        raise ValueError('Require the qualified freezer/driver/five-platform sequence')
    reference = current['rsb_links'][SDIO]['consumer']['power']
    previous = None
    for r in ordered:
        policy.run_id(r['run_id'])
        if r.get('passed') is not True or r.get('event') != 'complete':
            raise ValueError('Unaccepted prerequisite')
        for side in ('before', 'after'):
            s = r[side]
            if (s['boot_id'] != current['boot_id'] or s['image'] != current['image'] or
                    s['kernel'] != current['kernel'] or s['rsb_links'][SDIO]['consumer']['power'] != reference):
                raise ValueError('Prerequisite boot/image/reference mismatch')
        a, b = r['before'], r['after']
        if a['monotonic_seconds'] >= b['monotonic_seconds'] or (previous is not None and
                (previous['monotonic_seconds'] >= a['monotonic_seconds'] or previous['stats'] != a['stats'])):
            raise ValueError('Overlapping prerequisite or unrecorded intervening PM')
        if int(b['stats']['success']) != int(a['stats']['success'])+1:
            raise ValueError('Prerequisite did not complete exactly one PM cycle')
        if any(b['stats'][k] != '0' for k in b['stats'] if k == 'fail' or k.startswith('failed_')):
            raise ValueError('Prior PM failure')
        if r['stage'] in ('devices', 'platform'):
            if (not r.get('process_memory_ok') or r['keypad']['old_handle_after']['disconnected'] or
                    r['power_key'].get('handed_back') is not True or
                    r['wifi_trace'].get('restored') is not True or r['wifi_trace'].get('trace_lost') is not False):
                raise ValueError('Prerequisite restoration or input failure')
        if r['stage'] == 'platform':
            pm_platform.validate_trace(r['keypad'])
        previous = b
    if previous['stats'] != current['stats'] or previous['monotonic_seconds'] >= current['monotonic_seconds']:
        raise ValueError('PM occurred after the supplied qualification')
    if reference != dict(control='on', runtime_status='active', runtime_usage='2', runtime_enabled='forbidden'):
        raise ValueError('Qualified SDIO baseline changed')
    return [r['run_id'] for r in ordered]


def completed_result(pm, record, lock, mode):
    """Revalidate original evidence; a stored 'passed' flag is not sufficient."""
    policy.run_id(record['run_id'])
    if (record.get('event') != 'complete' or record.get('passed') is not True or
            record.get('mode') != mode or record.get('sources') != sources() or
            record.get('policy_restored') is not True or
            any(record.get(k) is not False for k in
                ('policy_owner_retained', 'dropin_retained', 'controls_retained', 'rtc_owner_retained'))):
        raise ValueError('Incomplete, unrestored or different-source sleep evidence')
    if (record['policy_before'] != record['policy_after'] or record['power_key'].get('events') or
            not all(record['power_key'].get(k) is True for k in
                    ('handed_back', 'logical_release_verified', 'descriptor_closed'))):
        raise ValueError('Power-key policy or handback differs')
    connection = sleep_connection.profile(record.get('connection', 'usb'))
    pm.validate(record['before'], lock, sleep_connection.endpoint(connection, mode))
    evaluated = deepcopy(record)
    health(pm, evaluated, lock)
    for field in ('delivery', 'sleep_trace') if mode == 'rtc-wake' else ('delivery',):
        if evaluated[field] != record.get(field):
            raise ValueError('Recorded wake assessment differs from original evidence')
    if sleep_connection.transition(connection) and mode == 'rtc-wake':
        if (record.get('cable_console', {}).get('restored') is not True or
                record.get('console_owner_retained') is not False or
                record.get('wake_observation') != sleep_cable.wake_observation(record)):
            raise ValueError('Cable console restoration or wake observation differs')
    for side in ('before', 'after'):
        usb = record['usb_trace'][side]
        expected = ('configured', '1') if sleep_connection.endpoint(connection, mode, side) == 'usb' else ('not attached', '0')
        if (usb['state'], usb['carrier']) != expected:
            raise ValueError('USB configuration/carrier differs from connection profile')


def history(pm, records, sleeps, current, lock, connection='usb'):
    """An unchanged debug anchor followed by contiguous, fully checked sleeps."""
    if not isinstance(sleeps, list) or len(sleeps) > MAX_SLEEP_CHAIN:
        raise ValueError('Sleep history exceeds the bounded qualification chain')
    sleep_connection.profile(connection)
    if sleep_connection.transition(connection) and sleeps:
        raise ValueError('Cable transitions require a fresh one-shot baseline, not a repeat chain')
    now = current['monotonic_seconds']
    if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
        raise ValueError('Invalid current snapshot time')
    anchor = sleeps[0]['before'] if sleeps else current
    ids = prerequisite(records, anchor)
    tokens, previous, alarm, rehearsal = [], None, None, None
    for record in sleeps:
        if record.get('connection', 'usb') != connection:
            raise ValueError('Sleep chain changed connection profile')
        token = policy.run_id(record['run_id'])
        if token in ids + tokens:
            raise ValueError('Duplicate or replayed sleep record')
        completed_result(pm, record, lock, 'rtc-wake')
        qualification = record['qualification']
        if (qualification['runs'] != ids or qualification.get('sleep_runs') != tokens or
                qualification.get('connection', 'usb') != connection):
            raise ValueError('Sleep ancestry differs from the supplied history')
        parent = tokens[-1] if tokens else ids[-1]
        if record.get('parent_claim') != dict(parent=parent, run_id=token, boot_id=current['boot_id']):
            raise ValueError('Missing or mismatched single-successor claim')
        if rehearsal is not None and record['rehearsal'] != rehearsal:
            raise ValueError('Sleep chain changed its awake rehearsal')
        rehearsal = policy.run_id(record['rehearsal'])
        for side in ('before', 'after'):
            snapshot = record[side]
            if any(snapshot[k] != current[k] for k in ('boot_id', 'kernel', 'image')):
                raise ValueError('Sleep history boot/image differs')
            if snapshot['rsb_links'][SDIO]['consumer']['power'] != current['rsb_links'][SDIO]['consumer']['power']:
                raise ValueError('Sleep history SDIO ownership differs')
        before, after = record['before'], record['after']
        times = (before['monotonic_seconds'], after['monotonic_seconds'])
        if (any(type(t) not in (int, float) or not math.isfinite(t) for t in times) or
                not 0 <= times[0] < times[1]):
            raise ValueError('Invalid sleep history time ordering')
        if previous is not None and (previous['stats'] != before['stats'] or
                previous['monotonic_seconds'] >= times[0] or record['rtc']['irq_before'] != alarm):
            raise ValueError('Unrecorded PM/RTC activity or overlapping sleeps')
        previous, alarm = after, record['rtc']['irq_after']
        tokens.append(token)
    if previous is not None and (previous['stats'] != current['stats'] or
            previous['monotonic_seconds'] >= current['monotonic_seconds']):
        raise ValueError('PM occurred after the supplied sleep history')
    return dict(runs=ids, sleep_runs=tokens, connection=connection)


def successor_path(pm, qualification):
    repeats = qualification['sleep_runs']
    parent = repeats[-1] if repeats else qualification['runs'][-1]
    return (RESULTS if repeats else pm.RESULTS)/policy.run_id(parent)/'sleep-successor.json'


def claim_successor(pm, qualification, token, boot_id):
    """Consume one parent before any alarm/PM mutation; never overwrite a claim."""
    path = successor_path(pm, qualification)
    claim = dict(parent=path.parent.name, run_id=policy.run_id(token), boot_id=boot_id)
    keypad_pm.save_owned(claim, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return claim


def admission(pm, before, lock, receipt, connection='usb'):
    sleep_connection.profile(connection)
    if receipt.get('connection', 'usb') != connection:
        raise ValueError('Qualification receipt has another connection profile')
    pm.validate(before, lock, sleep_connection.endpoint(connection))
    if before['image']['project_inputs_sha256'].get(SDIO_PATCH) != SDIO_SHA:
        raise ValueError('Require the hardware-qualified SDIO reference fix')
    if OWNED.exists() or pm.STATE.exists():
        raise ValueError('Interrupted PM controls; preserve and recover the original run')
    units = pm.command('systemctl', 'list-units', '--all', '--plain', '--no-legend',
                       '--state=active,activating,deactivating', 'gameshellneo-*.service')
    allowed = {'gameshellneo-usb.service', 'gameshellneo-ready.service',
               'gameshellneo-battery.service', 'gameshellneo-sleep-test.service'}
    if any(line.split()[0] not in allowed for line in units.splitlines() if line.split()):
        raise ValueError('Another diagnostic is running; stop before the sleep experiment')
    records = []
    if receipt.get('boot_id') != before['boot_id'] or len(receipt.get('runs', [])) != 7:
        raise ValueError('Qualification receipt does not match this boot')
    for entry in receipt['runs']:
        token = policy.run_id(entry['run_id'])
        record = json.loads((pm.RESULTS/token/'result.json').read_text())
        if record.get('run_id') != token or digest(record) != entry['sha256']:
            raise ValueError('Device prerequisite differs from both-route host evidence')
        records.append(record)
    entries = receipt.get('sleeps', [])
    if not isinstance(entries, list) or len(entries) >= MAX_SLEEP_CHAIN:
        raise ValueError('Sleep history is invalid or at its admission limit')
    sleeps = []
    for entry in entries:
        token = policy.run_id(entry['run_id'])
        record = json.loads((RESULTS/token/'result.json').read_text())
        if record.get('run_id') != token or digest(record) != entry['sha256']:
            raise ValueError('Device sleep differs from both-route host evidence')
        claim = json.loads(successor_path(pm, record['qualification']).read_text())
        if claim != record.get('parent_claim'):
            raise ValueError('Device successor ledger differs from the sleep evidence')
        sleeps.append(record)
    qualified = history(pm, records, sleeps, before, lock, connection)
    if sleeps and rtc_irq() != sleeps[-1]['rtc']['irq_after']:
        raise ValueError('RTC activity occurred after the supplied sleep history')
    if successor_path(pm, qualified).exists():
        raise ValueError('Qualification already claimed; collect its original successor')
    return qualified | dict(rtc=pm_platform.admission(before, True, True))


def rtc_irq(text=None):
    text = Path('/proc/interrupts').read_text() if text is None else text
    cpus = text.splitlines()[0].split()
    rows = [line.split() for line in text.splitlines() if line.strip().endswith('1f00000.rtc')]
    if len(rows) != 1 or not cpus or any(not re.fullmatch('CPU[0-9]+', c) for c in cpus):
        raise ValueError('Ambiguous RTC interrupt topology')
    row = rows[0]
    if (len(row) != len(cpus)+5 or row[-4:] != ['sun6i-r-intc', '40', 'Level', '1f00000.rtc'] or
            not re.fullmatch('[0-9]+:', row[0]) or any(not n.isdecimal() for n in row[1:1+len(cpus)])):
        raise ValueError('Unexpected RTC interrupt identity')
    return dict(irq=int(row[0][:-1]), count=sum(int(n) for n in row[1:1+len(cpus)]), cpus=cpus)


def clock_pair():
    # Bracket BOOTTIME rather than interpreting sequential-read skew as sleep.
    left = time.monotonic()
    boot = time.clock_gettime(time.CLOCK_BOOTTIME)
    right = time.monotonic()
    return dict(boot=boot, mono=(left+right)/2, mono_before=left, mono_after=right)


def clock_interval(before, after):
    errors = []
    for sample in (before, after):
        if any(type(sample.get(k)) not in (int, float) or not math.isfinite(sample[k]) or sample[k] < 0
               for k in ('boot', 'mono')):
            raise ValueError('Invalid sleep clock sample')
        if 'mono_before' not in sample and 'mono_after' not in sample:
            errors.append(None)  # Historical records have no measured sampling bound.
            continue
        a, b = sample.get('mono_before'), sample.get('mono_after')
        if (any(type(x) not in (int, float) or not math.isfinite(x) for x in (a, b)) or
                not 0 <= a <= sample['mono'] <= b or b-a > MAX_CLOCK_SAMPLE_SECONDS):
            raise ValueError('Invalid or excessively delayed bracketed clock sample')
        errors.append(max(sample['mono']-a, b-sample['mono']))
    wall = after['boot']-before['boot']
    mono = after['mono']-before['mono']
    if wall < 0 or mono < 0:
        raise ValueError('Sleep clocks moved backwards')
    uncertainty = None if None in errors else sum(errors)
    gap = wall-mono
    if uncertainty is not None and gap < -uncertainty-1e-6:
        raise ValueError('MONOTONIC advanced beyond BOOTTIME sampling uncertainty')
    return dict(boottime_seconds=wall, monotonic_seconds=mono, clock_gap_seconds=gap,
                sampling_uncertainty_seconds=uncertainty)


def idle_snapshot():
    """CPU-idle/timer inventory, not evidence of entering a hardware idle state."""
    cpu = Path('/sys/devices/system/cpu')
    return dict(online=keypad_pm.optional(cpu/'online'),
                driver=keypad_pm.optional(cpu/'cpuidle/current_driver'),
                governor=keypad_pm.optional(cpu/'cpuidle/current_governor_ro'),
                clocksource=keypad_pm.optional('/sys/devices/system/clocksource/clocksource0/current_clocksource'),
                states={str(p.relative_to(cpu)): {name: keypad_pm.optional(p/name) for name in
                        ('name', 'desc', 'latency', 'residency', 'disable', 'usage', 'time', 's2idle_usage', 's2idle_time')}
                        for p in sorted(cpu.glob('cpu[0-9]*/cpuidle/state*'))})


def inspect_clocks():
    def state():
        return dict(boot_id=keypad_pm.optional('/proc/sys/kernel/random/boot_id'),
                    pm={name: keypad_pm.optional('/sys/power/'+name) for name in ('pm_test', 'pm_async')},
                    stats={p.name: p.read_text().strip() for p in Path('/sys/power/suspend_stats').iterdir() if p.is_file()})
    before = state()
    idle = idle_snapshot()
    samples = [clock_pair() for _ in range(8)]
    intervals = [clock_interval(a, b) for a, b in zip(samples, samples[1:])]
    after = state()
    if before != after:
        raise ValueError('PM/boot changed during clock inspection')
    return dict(before=before, after=after, cpu_idle=idle, samples=samples, intervals=intervals,
                sources=sources(), limits='Awake read-only clock sampling; no RTC programming or PM entry.')


def wakeup_count():
    # sysfs show calls pm_get_wakeup_count(..., true); O_NONBLOCK does not bound it.
    value = subprocess.check_output(['cat', '/sys/power/wakeup_count'], timeout=3,
                                    text=True, stderr=subprocess.PIPE).strip()
    if not re.fullmatch('[0-9]+', value) or int(value) > 0xffffffff:
        raise ValueError('Invalid wakeup counter')
    return value


def single_write(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC)
    try:
        data = value.encode()
        if os.write(fd, data) != len(data):
            raise OSError('Incomplete sysfs write; no retry permitted')
    finally:
        os.close(fd)


def restore_controls(pm, token):
    if not OWNED.exists():
        return
    saved = json.loads(policy.read_owned(OWNED))
    if (saved.get('run_id') != policy.run_id(token) or saved.get('boot_id') != pm.read(pm.BOOT) or
            saved.get('async') not in ('0', '1') or pm.selected(pm.read(pm.POWER/'pm_test')) != 'none' or
            pm.read(pm.POWER/'pm_async') not in ('0', saved['async'])):
        raise ValueError('Sleep controls changed ownership; record retained')
    single_write(pm.POWER/'pm_async', saved['async']+'\n')
    if pm.read(pm.POWER/'pm_async') != saved['async']:
        raise ValueError('PM controls did not restore')
    OWNED.unlink()


@contextmanager
def controls(pm, token):
    if pm.selected(pm.read(pm.POWER/'pm_test')) != 'none':
        raise ValueError('Real sleep requires pm_test=none, never changes it implicitly')
    original = pm.read(pm.POWER/'pm_async')
    if original not in ('0', '1'):
        raise ValueError('Unexpected asynchronous PM policy')
    keypad_pm.save_owned(dict(run_id=token, boot_id=pm.read(pm.BOOT), **{'async': original}), OWNED)
    try:
        single_write(pm.POWER/'pm_async', '0\n')
        yield
    finally:
        restore_controls(pm, token)


@contextmanager
def deadline(record, persist, token):
    policy.run_id(token)
    if rtc.OWNED.exists():
        raise ValueError('Existing RTC owner')
    fd = os.open(rtc.RTC, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    saved = None
    claimed = False
    try:
        before = rtc.snapshot(fd)
        if before['alarm'][:2] != [0, 0]:
            raise ValueError('Existing active/pending RTC alarm')
        rtc.instant(before['alarm'][2:])
        target = [1, 0]+rtc.rtc_time(rtc.instant(before['rtc_time'])+SECONDS)
        saved = dict(run_id=token, boot_id=before['boot_id'], identity=before['identity'],
                     original=before['alarm'], requested=target)
        keypad_pm.save_owned(saved, rtc.OWNED)
        claimed = True
        record.update(before=before, requested=target, started=clock_pair())
        persist()  # Durable intent before programming.
        fcntl.ioctl(fd, rtc.SET_ALARM, rtc.ALARM.pack(*target))
        record['armed'] = rtc.alarm(fd)
        if not rtc.same(record['armed'], target):
            raise ValueError('RTC alarm readback mismatch')
        yield fd, target
    finally:
        try:
            if claimed:
                if json.loads(policy.read_owned(rtc.OWNED)) != saved:
                    raise ValueError('RTC ownership changed')
                rtc.restore_fd(fd, saved)
                record['restored'] = True
        finally:
            os.close(fd)


def margin(fd, target):
    current = rtc.snapshot(fd)
    left = rtc.instant(target[2:])-rtc.instant(current['rtc_time'])
    if not rtc.same(current['alarm'], target) or current['alarm'][1] or not MIN_MARGIN <= left <= SECONDS:
        raise ValueError('RTC alarm changed or insufficient entry margin')
    return left


def delivery(fd, wait_ms):
    poll = select.poll(); poll.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)
    events = poll.poll(wait_ms)
    if events != [(fd, select.POLLIN)]:
        raise ValueError('RTC alarm was not delivered at return; early/unrelated wake or missed deadline')
    event = rtc.irq_event(os.read(fd, struct.calcsize('@L')))
    if event['count'] != 1:
        raise ValueError('Unexpected multiple RTC notifications')
    return event


def enter(pm, record, guard, fd, target, persist, mode):
    if mode not in ('rehearse', 'rtc-wake'):
        raise ValueError('Explicit rehearsal or RTC wake mode required')
    guard.before_entry()
    connection = record.get('connection', 'usb')
    if connection != 'usb':
        record['cable']['entry'] = sleep_connection.observe()
        sleep_connection.unchanged(record['cable']['before'], record['cable']['entry'],
                                   sleep_connection.endpoint(connection, mode))
    record['wakeup_count'] = wakeup_count()
    record['rtc']['margin_seconds'] = margin(fd, target)
    record['entry_intent'] = dict(mode=mode, state='freeze' if mode == 'rtc-wake' else None,
                                pm_test=pm.selected(pm.read(pm.POWER/'pm_test')), pm_async=pm.read(pm.POWER/'pm_async'))
    persist()
    guard.before_entry()
    record['rtc']['entry_margin_seconds'] = margin(fd, target)  # Includes durable-write/guard overhead.
    if (record['entry_intent']['pm_test'] != 'none' or record['entry_intent']['pm_async'] != '0' or
            pm.selected(pm.read(pm.POWER/'pm_test')) != 'none' or pm.read(pm.POWER/'pm_async') != '0'):
        raise ValueError('Sleep controls failed readback')
    if mode == 'rehearse':
        # Never writes wakeup_count or state in the awake rehearsal.
        record['rtc']['interrupt'] = delivery(fd, (SECONDS+5)*1000)
        record['returned'] = clock_pair()
    else:
        single_write(pm.POWER/'wakeup_count', record['wakeup_count']+'\n')
        record['entry_clock'] = clock_pair()
        single_write(pm.POWER/'state', 'freeze\n')  # Exactly one submission; no retry.
        record['returned'] = clock_pair()
        record['wake_irq'] = pm.read(pm.POWER/'pm_wakeup_irq')
        if sleep_connection.transition(connection):
            # Preserve an early wake and collect recovery state. The unchanged
            # RTC acceptance below still rejects it; never wait awake for an alarm.
            poll = select.poll(); poll.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)
            events = poll.poll(0)
            if events not in ([], [(fd, select.POLLIN)]):
                raise ValueError('RTC descriptor error at cable-test return')
            record['rtc']['interrupt'] = rtc.irq_event(os.read(fd, struct.calcsize('@L'))) if events else None
            record['wake_observation'] = sleep_cable.wake_observation(record)
            sleep_cable.returned(record)
        else:
            record['rtc']['interrupt'] = delivery(fd, 0)  # No awake wait for later delivery.
    guard.after_entry()
    record['rtc']['after_delivery'] = rtc.snapshot(fd)
    record['rtc']['irq_after'] = rtc_irq()
    persist()


def validate_delivery(record):
    if record.get('mode') not in ('rehearse', 'rtc-wake'):
        raise ValueError('Unknown sleep evidence mode')
    rtc_data = record['rtc']
    if rtc_data.get('interrupt') is None:
        raise ValueError('No RTC event at return: early/unattributed wake, not an RTC-wake pass')
    a, b = rtc_data['irq_before'], rtc_data['irq_after']
    if a['irq'] != b['irq'] or a['cpus'] != b['cpus'] or b['count'] != a['count']+1:
        raise ValueError('RTC interrupt delivery identity/count mismatch')
    if rtc_data['interrupt'] != dict(count=1, flags=0xa0) or rtc_data.get('restored') is not True:
        raise ValueError('RTC delivery or restoration incomplete')
    elapsed = clock_interval(rtc_data['started'], record['returned'])['boottime_seconds']
    lag = rtc.instant(rtc_data['after_delivery']['rtc_time'])-rtc.instant(rtc_data['requested'][2:])
    if not SECONDS-2 <= elapsed <= SECONDS+10 or not 0 <= lag <= 10:
        raise ValueError('RTC delivery outside the bounded deadline')
    if record['mode'] == 'rtc-wake':
        if record.get('entry_intent') != dict(mode='rtc-wake', state='freeze', pm_test='none', pm_async='0'):
            raise ValueError('No explicit actual-sleep intent with debug mode disabled')
        clock_interval(rtc_data['started'], record['entry_clock'])
        interval = clock_interval(record['entry_clock'], record['returned'])
        margin_seconds = rtc_data.get('entry_margin_seconds', rtc_data.get('margin_seconds'))
        if (type(margin_seconds) is not int or not MIN_MARGIN <= margin_seconds <= SECONDS or
                record['wake_irq'] != str(rtc_data['irq_before']['irq']) or
                not margin_seconds-2 <= interval['boottime_seconds'] <= SECONDS+5):
            raise ValueError('Wrong wake IRQ or RTC-wait interval outside the admitted deadline')
        trace = validate_trace(record['keypad'])
        # Mono trace timestamps exclude timekeeping suspension. Never require a
        # minimum duration in this clock, or call the clock gap CPU residency.
        if (trace['s2idle_start_mono'] < record['entry_clock']['mono']-MAX_CLOCK_SAMPLE_SECONDS or
                trace['s2idle_end_mono'] > record['returned']['mono']+MAX_CLOCK_SAMPLE_SECONDS):
            raise ValueError('Actual-sleep trace lies outside the submitted interval')
        pairs = trace['timekeeping_freeze_pairs']
        uncertainty = interval['sampling_uncertainty_seconds']
        gap = interval['clock_gap_seconds']
        if uncertainty is not None and pairs == 0 and gap > uncertainty+1e-6:
            raise ValueError('Clock discontinuity without a matching timekeeping-freeze trace')
        observed = pairs > 0 and uncertainty is not None and gap > uncertainty+1e-6
        # Exclude entry/resume delays from the required RTC wait. A clock gap
        # contributes only when bounded sampling and paired in-loop freeze
        # events support it. Historical unbracketed samples add no duration.
        supported = trace['s2idle_monotonic_seconds']
        if observed:
            supported += max(0, gap-uncertainty)
        entry_overhead = max(0, trace['s2idle_start_mono']-record['entry_clock']['mono'])
        if supported < max(5, margin_seconds-entry_overhead-2):
            raise ValueError('Trace does not establish the admitted RTC wait inside s2idle')
        return dict(functional_rtc_wake=True, alarm_elapsed_seconds=elapsed, interval=interval,
                    s2idle_trace=trace,
                    s2idle_supported_seconds=supported,
                    timekeeping=dict(freeze_pairs=pairs, observation='observed' if observed else
                                     'inconclusive' if pairs else 'not_observed'),
                    cpu_retention_qualified=False, energy_qualified=False)
    if re.search(r'suspend_resume: (?:suspend_enter|machine_suspend|timekeeping_freeze)\[', record['keypad']['trace']):
        raise ValueError('Unexpected sleep/timekeeping transition during awake rehearsal')
    return dict(alarm_elapsed_seconds=elapsed, functional_rtc_wake=False,
                cpu_retention_qualified=False, energy_qualified=False)


def validate_trace(record):
    text = record['trace']
    markers = list(re.finditer(r'suspend_resume: machine_suspend\[1\] (begin|end)', text))
    if [m[1] for m in markers] != ['begin', 'end']:
        raise ValueError('Missing or repeated actual-s2idle boundary')
    left = re.search(r'suspend_resume: dpm_suspend_noirq\[\d+\] end', text)
    right = re.search(r'suspend_resume: dpm_resume_noirq\[\d+\] begin', text)
    if (left is None or right is None or not left.end() < markers[0].start() < markers[1].end() < right.start() or
            re.search(r'machine_suspend\[(?!1\])|s2idle_enter\[', text)):
        raise ValueError('Unexpected sleep state or callback ordering')
    # Reuse the established exact late/noirq + RSB checker after checking the
    # real-sleep boundary separately; never broaden the debug checker's contract.
    sanitized = re.sub(r'^.*suspend_resume: machine_suspend\[1\].*\n?', '', text, flags=re.M)
    result = pm_platform.validate_trace(record | {'trace': sanitized})
    def stamp(marker):
        prefix = text[text.rfind('\n', 0, marker.start())+1:marker.start()]
        value = re.search(r'\s([0-9]+\.[0-9]+): $', prefix)
        if not value:
            raise ValueError('Missing monotonic timestamp on sleep trace boundary')
        return float(value[1])
    start, end = [stamp(m) for m in markers]
    if end < start:
        raise ValueError('Sleep trace timestamps moved backwards')
    freezes = list(re.finditer(r'suspend_resume: timekeeping_freeze\[\d+\] (begin|end)', text))
    if text.count('suspend_resume: timekeeping_freeze') != len(freezes) or len(freezes) % 2:
        raise ValueError('Incomplete timekeeping-freeze trace')
    last = start
    for index, marker in enumerate(freezes):
        timestamp = stamp(marker)
        if (marker[1] != ('begin' if index % 2 == 0 else 'end') or
                not markers[0].end() < marker.start() < markers[1].start() or
                not last <= timestamp <= end):
            raise ValueError('Timekeeping-freeze trace outside the sleep boundary or out of order')
        last = timestamp
    return result | dict(s2idle_boundary=True, s2idle_start_mono=start, s2idle_end_mono=end,
                         s2idle_monotonic_seconds=end-start, timekeeping_freeze_pairs=len(freezes)//2,
                         limits='Actual s2idle path; trace duration is MONOTONIC, not CPU residency or energy.')


class UntouchedHandoff:
    """RTC-only handoff: no PEK dispatch or input event across the whole attempt."""
    def __init__(self, guard, initial, stats):
        self.guard, self.initial, self.stats = guard, initial, stats

    def check(self):
        self.guard.drain()
        power_key.verify_inhibitor()
        power_key_pm.require_delta(self.initial, power_key_pm.irq_counts(), 0, 0)
        current = {p.name: p.read_text().strip() for p in Path('/sys/power/suspend_stats').iterdir() if p.is_file()}
        if (self.guard.record['events'] or not self.guard.consumer.released(keypad_pm.handle_state(self.guard.fd)) or
                current != self.stats):
            raise ValueError('Untouched RTC-wake handoff lost key/PM continuity; ignore policy retained')


def health(pm, record, lock):
    # Preserve the wake/clock result even if a later device recovery check fails.
    record['delivery'] = validate_delivery(record)
    before, after = record['before'], record['after']
    pm.validate(after, lock, sleep_connection.endpoint(record.get('connection', 'usb'), record['mode'], 'after'))
    sleep_connection.validate(record)
    keys = ('boot_id', 'kernel', 'image', 'pm', 'pm_test_delay', 'masks', 'inputs', 'backlight',
            'wifi_config_sha256', 'wifi_power_save', 'charger', 'cpu_policy')
    if any(before[k] != after[k] for k in keys) or not after['journal'].startswith(before['journal']):
        raise ValueError('State restoration or journal continuity failed')
    delta = after['journal'][len(before['journal']):]
    if any(x in delta for x in pm.FAULTS) or 'suspend debug: Waiting' in delta:
        raise ValueError('Kernel fault or unexpected debug return')
    successes = int(after['stats']['success'])-int(before['stats']['success'])
    if successes != (1 if record['mode'] == 'rtc-wake' else 0) or any(
            before['stats'][k] != after['stats'][k] for k in before['stats'] if k != 'success'):
        raise ValueError('Unexpected PM generation or failure')
    if before['rsb_links'][SDIO]['consumer']['power'] != after['rsb_links'][SDIO]['consumer']['power']:
        raise ValueError('SDIO reference or policy changed')
    if record['mode'] == 'rtc-wake':
        record['sleep_trace'] = validate_trace(record['keypad'])
    elif re.search(r'suspend_resume: (?:suspend_enter|machine_suspend)\[', record['keypad']['trace']):
        raise ValueError('Unexpected PM during awake rehearsal')
    k = record['keypad']
    if (k.get('trace_overrun') is not False or k.get('trace_restored') is not True or
            k['old_handle_after']['disconnected'] or k['old_handle_after']['ioctl_errno'] is not None or
            k['before']['usb']['attributes'] != k['after']['usb']['attributes'] or
            k['before']['inputs'] != k['after']['inputs'] or
            record['wifi_trace'].get('restored') is not True or record['wifi_trace'].get('trace_lost') is not False or
            record['usb_trace'].get('restored') is not True or record['usb_trace'].get('trace_lost') is not False):
        raise ValueError('Input retention or trace restoration failed')
    if record.get('process_memory_ok') is not True:
        raise ValueError('Process memory changed')
    if record['audio_before'] != record['audio_after']:
        raise ValueError('Idle audio state changed')


def retain_failed_handoff(record, token):
    """The ancestor inhibitor still lives if final evdev cleanup fails.

    Re-establish boot-local suppression before that ancestor exits. This is
    never an instruction to remove an unknown/foreign policy marker.
    """
    if record.get('policy_restored'):
        try:
            policy.acquire(token, record['before']['boot_id'])
            record['policy_restored'] = False
            record['policy_rearmed_after_failure'] = True
        except BaseException as error:
            record['policy_rearm_error'] = type(error).__name__+': '+str(error)


def rehearsal_for_chain(pm, before, lock, qualification, rehearsal):
    preceding = qualification['sleep_runs']
    connection = sleep_connection.profile(qualification.get('connection', 'usb'))
    prior = json.loads((RESULTS/policy.run_id(rehearsal)/'result.json').read_text())
    if prior.get('connection', 'usb') != connection:
        raise ValueError('Awake rehearsal has another connection profile')
    completed_result(pm, prior, lock, 'rehearse')
    first = json.loads((RESULTS/preceding[0]/'result.json').read_text()) if preceding else None
    anchor = first['before'] if first else before
    if (prior['run_id'] != rehearsal or prior['after']['boot_id'] != before['boot_id'] or
            prior['after']['image'] != before['image'] or
            prior['after']['rsb_links'][SDIO]['consumer']['power'] != anchor['rsb_links'][SDIO]['consumer']['power'] or
            prior['after']['stats'] != anchor['stats'] or
            prior['after']['monotonic_seconds'] >= anchor['monotonic_seconds'] or
            prior['qualification']['runs'] != qualification['runs'] or
            prior['qualification'].get('connection', 'usb') != connection or
            prior['qualification'].get('sleep_runs') != [] or
            (first and (first['rehearsal'] != rehearsal or
                        first['rtc']['irq_before'] != prior['rtc']['irq_after']))):
        raise ValueError('Require a successful same-source/same-boot awake rehearsal')
    last = json.loads((RESULTS/preceding[-1]/'result.json').read_text()) if preceding else prior
    return last['rtc']['irq_after']


def run(pm, token, mode, lock, receipt, rehearsal=None, connection='usb', cable_absent=False, cable_action=False):
    sleep_connection.profile(connection)
    if connection == 'battery' and cable_absent is not True:
        raise ValueError('Battery test requires fresh physical cable-absence confirmation')
    if sleep_connection.transition(connection) and cable_action is not True:
        raise ValueError('Cable transition requires explicit observer/action readiness')
    if sleep_connection.endpoint(connection) == 'battery' and cable_absent is not True:
        raise ValueError('Battery-start cable test requires physical USB absence')
    policy.run_id(token)
    directory = RESULTS/token
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    parent = os.open(RESULTS, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    record = dict(run_id=token, mode=mode, connection=connection,
                  cable_absent_confirmed=cable_absent, cable_action_confirmed=cable_action, event='started', passed=False,
                  qualification_scope='functional-wake-and-device-recovery' if mode == 'rtc-wake' else 'awake-rehearsal',
                  sources=sources(), rtc={}, power_key={}, keypad={}, wifi_trace={}, usb_trace={})
    persist = lambda: pm.save(directory/'started.json', record)
    try:
        with keypad_pm.exclusive_pm(OWNED.parent):
            before = record['before'] = pm.snapshot()
            record['cpu_idle_before'] = idle_snapshot()
            record['qualification'] = admission(pm, before, lock, receipt, connection)
            if connection != 'usb':
                record['cable'] = {'before': sleep_connection.observe()}
                sleep_connection.state(record['cable']['before'], sleep_connection.endpoint(connection))
            record['policy_before'] = policy.inspect()
            record['audio_before'] = speaker_audio.idle()
            preceding = record['qualification']['sleep_runs']
            if mode == 'rehearse' and preceding:
                raise ValueError('A repeat chain retains its original awake rehearsal')
            if mode == 'rtc-wake':
                expected_rtc = rehearsal_for_chain(pm, before, lock, record['qualification'], rehearsal)
                record['rehearsal'] = rehearsal
            persist()
            if mode == 'rtc-wake':
                record['parent_claim'] = claim_successor(pm, record['qualification'], token, before['boot_id'])
                persist()
            memory = os.urandom(4*1024*1024); checksum = hashlib.sha256(memory).hexdigest()
            with power_key.own(record['power_key'], persist) as guard:
                guard.before_entry()
                record['pek_before'] = power_key_pm.irq_counts()
                policy.acquire(token, before['boot_id'])
                with sleep_cable.console(record, token):
                    with usb_trace.capture(record['usb_trace'], token), wifi_trace.capture(record['wifi_trace']), \
                            keypad_pm.observe(record['keypad'], tracing=True):
                        # Tag newly acquired trace ownership for this controller's
                        # recovery; untagged or foreign traces are never removed.
                        for owned in (wifi_trace.OWNED, keypad_pm.OWNED):
                            pm.save(owned, json.loads(policy.read_owned(owned)) | {'sleep_run': token})
                        with controls(pm, token):
                            os.sync()
                            record['rtc']['irq_before'] = rtc_irq()
                            if mode == 'rtc-wake' and record['rtc']['irq_before'] != expected_rtc:
                                raise ValueError('RTC activity changed before sleep admission')
                            with deadline(record['rtc'], persist, token) as (fd, target):
                                policy.verify(token)
                                power_key_pm.require_delta(record['pek_before'], power_key_pm.irq_counts(), 0, 0)
                                enter(pm, record, guard, fd, target, persist, mode)
                        record['process_memory_ok'] = hashlib.sha256(memory).hexdigest() == checksum
                        if mode == 'rtc-wake':
                            record['keypad_ready'] = {}
                            keypad_pm.wait_ready(record['keypad_ready'], time.monotonic(),
                                                 keypad_pm.keypad_identity(record['keypad']['before']))
                            time.sleep(30)  # Recovery observation only; never an asleep watchdog.
                        if connection != 'usb':
                            record['cable']['after'] = sleep_connection.observe()
                        record['after'] = pm.snapshot()
                        record['cpu_idle_after'] = idle_snapshot()
                        record['audio_after'] = speaker_audio.idle()
                    health(pm, record, lock)
                    handoff = UntouchedHandoff(guard, record['pek_before'], record['after']['stats'])
                    policy._restore_checked(token, handoff.check)
                    record['policy_restored'] = True
            if record['power_key']['events'] or record['power_key'].get('handed_back') is not True:
                raise ValueError('Power-key activity/cleanup failure during final handoff')
            record['policy_after'] = policy.inspect()
            if record['policy_after'] != record['policy_before']:
                raise ValueError('Power policy did not match the original state')
            record.update(passed=True, event='complete')
    except BaseException as error:
        record.update(event='failed', error=type(error).__name__+': '+str(error))
        retain_failed_handoff(record, token)
        raise
    finally:
        record['policy_owner_retained'] = os.path.lexists(policy.OWNED)
        record['dropin_retained'] = os.path.lexists(policy.DROPIN)
        record['controls_retained'] = os.path.lexists(OWNED)
        record['rtc_owner_retained'] = os.path.lexists(rtc.OWNED)
        record['console_owner_retained'] = os.path.lexists(sleep_cable.OWNED)
        pm.save(directory/'result.json', record)


def recover(pm, token):
    """Restore only this run's RTC/PM/trace controls, never poweroff policy."""
    directory = RESULTS/policy.run_id(token)
    started = json.loads((directory/'started.json').read_text())
    if started['run_id'] != token or started['before']['boot_id'] != pm.read(pm.BOOT):
        raise ValueError('Recovery belongs to another boot/run')
    with keypad_pm.exclusive_pm(OWNED.parent):
        failures = []
        operations = ((sleep_cable.OWNED, 'run_id', lambda: sleep_cable.restore(token)),
                      (rtc.OWNED, 'run_id', rtc.restore),
                      (OWNED, 'run_id', lambda: restore_controls(pm, token)),
                      (usb_trace.OWNED, 'run_id', lambda: usb_trace.restore(token)),
                      (wifi_trace.OWNED, 'sleep_run', wifi_trace.restore),
                      (keypad_pm.OWNED, 'sleep_run', keypad_pm.restore_trace))
        for path, field, operation in operations:
            try:
                if os.path.lexists(path):
                    if json.loads(policy.read_owned(path)).get(field) != token:
                        raise ValueError('Recovery encountered foreign ownership: '+str(path))
                    operation()
            except BaseException as error:
                failures.append(type(error).__name__+': '+str(error))
        pm.save(directory/'recovery.json', dict(run_id=token, controls_restored=not failures, errors=failures,
                policy_owner_retained=os.path.lexists(policy.OWNED), dropin_retained=os.path.lexists(policy.DROPIN)))
        if failures:
            raise ValueError('Incomplete recovery; preserve remaining owners: '+'; '.join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--rehearse', action='store_true')
    modes.add_argument('--rtc-wake', action='store_true')
    modes.add_argument('--recover', action='store_true')
    modes.add_argument('--clock-inspect', action='store_true')
    modes.add_argument('--connection-inspect', action='store_true')
    parser.add_argument('--run-id')
    parser.add_argument('--lock', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--rehearsal')
    parser.add_argument('--attended', action='store_true')
    parser.add_argument('--connection', choices=('usb', 'battery', 'usb-remove', 'usb-attach'), default='usb')
    parser.add_argument('--cable-absent-confirmed', action='store_true')
    parser.add_argument('--cable-action-confirmed', action='store_true')
    args = parser.parse_args()
    if sleep_connection.transition(args.connection) and not args.cable_action_confirmed:
        parser.error('Cable transition requires explicit observer/action readiness')
    if sleep_connection.endpoint(args.connection) == 'battery' and not args.cable_absent_confirmed:
        parser.error('Battery test requires fresh physical cable-absence confirmation')
    if args.connection_inspect:
        print(json.dumps(dict(sources=sources(), connection=sleep_connection.observe())))
        return
    if args.clock_inspect:
        print(json.dumps(inspect_clocks()))
        return
    if not args.run_id:
        parser.error('Require --run-id for a rehearsal, sleep submission or recovery')
    if args.rtc_wake and not args.attended:
        parser.error('Actual sleep requires the separately confirmed attended run')
    os.umask(0o077)
    def interrupted(signum, _frame):
        raise SystemExit(128+signum)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, interrupted)
    pm = pm_module()
    if args.recover:
        recover(pm, args.run_id)
    else:
        run(pm, args.run_id, 'rtc-wake' if args.rtc_wake else 'rehearse',
            json.loads(args.lock.read_text()), json.loads(args.receipt.read_text()), args.rehearsal, args.connection, args.cable_absent_confirmed, args.cable_action_confirmed)


if __name__ == '__main__':
    main()
