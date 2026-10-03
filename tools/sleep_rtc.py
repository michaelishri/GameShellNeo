"""Separate, one-shot RTC s2idle diagnostic and awake rehearsal. No ordinary sleep policy."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
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

RESULTS = Path('/var/lib/gameshellneo/sleep-tests')
OWNED = Path('/run/gameshellneo-sleep-controls.json')
SECONDS, MIN_MARGIN = 30, 15
SDIO = 'consumer:platform:1c10000.mmc'
SDIO_PATCH = 'kernel/patches/0023-sunxi-mmc-sdio-reference-ownership.patch'
SDIO_SHA = '52f4e3d8b966f8f69718340697606e30d174033d998be84f98b42bc2c97e92ee'
SOURCES = ('sleep_rtc', 'test-pm-stages', 'keypad_pm', 'power_key', 'power_key_policy',
           'power_key_pm', 'power_key_input', 'keypad_input', 'speaker_audio',
           'rtc_alarm', 'pm_platform', 'wifi_trace', 'usb_trace')


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


def admission(pm, before, lock, receipt):
    pm.validate(before, lock)
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
        if digest(record) != entry['sha256']:
            raise ValueError('Device prerequisite differs from both-route host evidence')
        records.append(record)
    ids = prerequisite(records, before)
    return dict(runs=ids, rtc=pm_platform.admission(before, True, True))


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
    return dict(boot=time.clock_gettime(time.CLOCK_BOOTTIME), mono=time.monotonic())


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
    record['wakeup_count'] = wakeup_count()
    record['rtc']['margin_seconds'] = margin(fd, target)
    record['entry_intent'] = dict(mode=mode, state='freeze' if mode == 'rtc-wake' else None,
                                pm_test=pm.selected(pm.read(pm.POWER/'pm_test')), pm_async=pm.read(pm.POWER/'pm_async'))
    persist()
    guard.before_entry()
    margin(fd, target)  # Includes all durable-write/guard overhead in admission.
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
        record['rtc']['interrupt'] = delivery(fd, 0)  # Do not wait awake and misattribute later delivery.
    guard.after_entry()
    record['rtc']['after_delivery'] = rtc.snapshot(fd)
    record['rtc']['irq_after'] = rtc_irq()
    persist()


def validate_delivery(record):
    rtc_data = record['rtc']
    a, b = rtc_data['irq_before'], rtc_data['irq_after']
    if a['irq'] != b['irq'] or a['cpus'] != b['cpus'] or b['count'] != a['count']+1:
        raise ValueError('RTC interrupt delivery identity/count mismatch')
    if rtc_data['interrupt'] != dict(count=1, flags=0xa0) or rtc_data.get('restored') is not True:
        raise ValueError('RTC delivery or restoration incomplete')
    elapsed = record['returned']['boot']-rtc_data['started']['boot']
    lag = rtc.instant(rtc_data['after_delivery']['rtc_time'])-rtc.instant(rtc_data['requested'][2:])
    if not SECONDS-2 <= elapsed <= SECONDS+10 or not 0 <= lag <= 10:
        raise ValueError('RTC delivery outside the bounded deadline')
    if record['mode'] == 'rtc-wake':
        a, b = record['entry_clock'], record['returned']
        suspended = (b['boot']-a['boot'])-(b['mono']-a['mono'])
        if record['wake_irq'] != str(rtc_data['irq_before']['irq']) or not 5 <= suspended <= SECONDS+5:
            raise ValueError('No qualified RTC wake with a genuine suspended interval')
        return dict(suspended_seconds=suspended, alarm_elapsed_seconds=elapsed)
    return dict(alarm_elapsed_seconds=elapsed)


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
    return pm_platform.validate_trace(record | {'trace': sanitized}) | {'s2idle_boundary': True}


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
    before, after = record['before'], record['after']
    pm.validate(after, lock)
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
    record['delivery'] = validate_delivery(record)


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


def run(pm, token, mode, lock, receipt, rehearsal=None):
    policy.run_id(token)
    directory = RESULTS/token
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    parent = os.open(RESULTS, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    record = dict(run_id=token, mode=mode, event='started', passed=False,
                  sources=sources(), rtc={}, power_key={}, keypad={}, wifi_trace={}, usb_trace={})
    persist = lambda: pm.save(directory/'started.json', record)
    try:
        with keypad_pm.exclusive_pm(OWNED.parent):
            before = record['before'] = pm.snapshot()
            record['qualification'] = admission(pm, before, lock, receipt)
            record['policy_before'] = policy.inspect()
            record['audio_before'] = speaker_audio.idle()
            if mode == 'rtc-wake':
                prior = json.loads((RESULTS/policy.run_id(rehearsal)/'result.json').read_text())
                if (prior.get('passed') is not True or prior.get('mode') != 'rehearse' or
                        prior['sources'] != record['sources'] or prior['after']['boot_id'] != before['boot_id'] or
                        prior['after']['stats'] != before['stats']):
                    raise ValueError('Require a successful same-source/same-boot awake rehearsal')
                record['rehearsal'] = rehearsal
            persist()
            memory = os.urandom(4*1024*1024); checksum = hashlib.sha256(memory).hexdigest()
            with power_key.own(record['power_key'], persist) as guard:
                guard.before_entry()
                record['pek_before'] = power_key_pm.irq_counts()
                policy.acquire(token, before['boot_id'])
                with usb_trace.capture(record['usb_trace'], token), wifi_trace.capture(record['wifi_trace']), \
                        keypad_pm.observe(record['keypad'], tracing=True):
                    # Tag newly acquired trace ownership for this controller's
                    # recovery; untagged or foreign traces are never removed.
                    for owned in (wifi_trace.OWNED, keypad_pm.OWNED):
                        pm.save(owned, json.loads(policy.read_owned(owned)) | {'sleep_run': token})
                    with controls(pm, token):
                        os.sync()
                        record['rtc']['irq_before'] = rtc_irq()
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
                    record['after'] = pm.snapshot()
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
        pm.save(directory/'result.json', record)


def recover(pm, token):
    """Restore only this run's RTC/PM/trace controls, never poweroff policy."""
    directory = RESULTS/policy.run_id(token)
    started = json.loads((directory/'started.json').read_text())
    if started['run_id'] != token or started['before']['boot_id'] != pm.read(pm.BOOT):
        raise ValueError('Recovery belongs to another boot/run')
    with keypad_pm.exclusive_pm(OWNED.parent):
        failures = []
        operations = ((rtc.OWNED, 'run_id', rtc.restore),
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
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--lock', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--rehearsal')
    parser.add_argument('--attended', action='store_true')
    args = parser.parse_args()
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
            json.loads(args.lock.read_text()), json.loads(args.receipt.read_text()), args.rehearsal)


if __name__ == '__main__':
    main()
