"""Attended bounded PEK release during devices debug; no actual sleep entry."""
import json
import os
from pathlib import Path
import re
import time

import keypad_input
import keypad_pm
import power_key
import power_key_input as awake
import power_key_policy as policy
import speaker_audio


def irq_counts(text=None):
    started = time.monotonic()
    text = Path('/proc/interrupts').read_text() if text is None else text
    cpus = text.splitlines()[0].split()
    if not cpus or any(not re.fullmatch(r'CPU[0-9]+', c) for c in cpus):
        raise ValueError('Unexpected interrupt CPU columns')
    result = dict(cpus=cpus, sample_start=started, rows={})
    for edge, hwirq in (('dbf', 22), ('dbr', 23)):
        rows = [line.split() for line in text.splitlines() if line.strip().endswith('axp20x-pek-'+edge)]
        if len(rows) != 1:
            raise ValueError('Missing or ambiguous PEK IRQ identity')
        row = rows[0]
        if (len(row) != len(cpus)+5 or not re.fullmatch(r'[0-9]+:', row[0]) or
                row[-4:] != ['axp22x_irq_chip', str(hwirq), 'Edge', 'axp20x-pek-'+edge] or
                any(not n.isdecimal() for n in row[1:1+len(cpus)])):
            raise ValueError('Unexpected CPI3.1 PEK IRQ mapping')
        result[edge] = dict(irq=int(row[0][:-1]), hwirq=hwirq,
                           count=sum(int(n) for n in row[1:1+len(cpus)]))
        result['rows'][edge] = ' '.join(row)
    if result['dbf']['irq'] == result['dbr']['irq']:
        raise ValueError('PEK edges share an unexpected IRQ')
    result['sample_end'] = time.monotonic()
    return result


def require_delta(before, after, dbf, dbr):
    if before['cpus'] != after['cpus']:
        raise ValueError('Interrupt CPU topology changed')
    for edge, expected in (('dbf', dbf), ('dbr', dbr)):
        a, b = before[edge], after[edge]
        if (a['irq'] != b['irq'] or a['hwirq'] != b['hwirq'] or b['count']-a['count'] != expected):
            raise ValueError('Unexpected PEK nested IRQ dispatch delta: '+edge)


def validate_input(record):
    data, keys = record['physical_power'], awake.edges(record['power_key']['events'])
    if len(keys) != 8 or [e['value'] for e in keys] != [1, 0]*4:
        raise ValueError('Expected four logical pairs including the PM clear')
    if [s['label'] for s in data['stages']] != ['tap-1', 'tap-2', 'tap-4']:
        raise ValueError('Missing fresh awake confirmation taps')
    for index, step in zip((0, 2, 6), data['stages']):
        press, release = keys[index:index+2]
        if (not step['prompt_seconds'] <= press['seconds'] < release['seconds'] or
                release['seconds']-press['seconds'] >= 2.5 or
                step['press_seconds'] != press['seconds'] or step['release_seconds'] != release['seconds']):
            raise ValueError('Invalid awake tap after prompt')
    if not (data['hold_prompt'] <= keys[4]['seconds'] <= data['entry_seconds'] <
            keys[5]['seconds'] < data['resume_seconds'] < data['stages'][-1]['prompt_seconds']):
        raise ValueError('Held press/PM clear/fresh awake pair ordering failed')
    require_delta(data['irq_initial'], data['irq_before_hold'], 2, 2)
    require_delta(data['irq_before_hold'], data['irq_held'], 1, 0)
    require_delta(data['irq_held'], data['irq_after_pm'], 0, 1)
    require_delta(data['irq_after_pm'], data['irq_final'], 1, 1)
    return keys


def validate_trace(record):
    trace = record['keypad']
    if trace.get('trace_overrun') is not False or trace.get('trace_restored') is not True:
        raise ValueError('Incomplete or unrestored PM callback trace')
    text = trace['trace']
    if re.search(r'device_pm_callback_end: .*err=(?!0\b)-?\d+', text):
        raise ValueError('Failed PM callback')
    if re.search(r'suspend_resume: (?:machine_suspend|s2idle_enter|dpm_suspend_late|dpm_suspend_noirq)\[', text):
        raise ValueError('Unexpected deeper PM boundary')
    node = Path(record['power_key']['identity']['sysfs']).name
    starts = list(re.finditer(r'\s(\d+\.\d+): device_pm_callback_start: input '+re.escape(node)+
        r', parent: axp221-pek, type \[suspend\]', text))
    if len(starts) != 1:
        raise ValueError('Missing unique PEK input-device suspend callback')
    start = starts[0]
    end = re.search(r'\s(\d+\.\d+): device_pm_callback_end: input '+re.escape(node)+r', err=0\b', text[start.end():])
    clear = awake.edges(record['power_key']['events'])[5]['seconds']
    if end is None or not float(start[1])-0.000002 <= clear <= float(end[1])+0.000002:
        raise ValueError('Release not correlated with input-device suspend clear')
    # SYN_REPORT values are not a portable API discriminator. Callback timing
    # and the pinned source establish this narrow diagnostic attribution.
    return dict(input_node=node, clear_seconds=clear, callback_start=float(start[1]), callback_end=float(end[1]))


class Sequence(awake.Sequence):
    def tap(self, index):
        self.neutral()
        stamp = self.prompt(f'{index+1}/4: Tap POWER once.', 'Release it promptly.',
                            'Wait for tone and next prompt.')
        values = self.wait(index*2+2, 25)
        self.record['stages'].append(dict(label=f'tap-{index+1}', prompt_seconds=stamp,
            press_seconds=values[-2]['seconds'], release_seconds=values[-1]['seconds']))
        self.neutral()
        self.prompt(f'{index+1}/4 recorded.', 'Leave POWER released.')
        self.cue.play(f'tap-{index+1}')
        self.quiet(index*2+2, 1)

    def run_pm(self, pm, persist):
        self.record['irq_initial'] = irq_counts()
        self.prompt('Leave POWER released.', 'Starting in 10 seconds.',
                    'Step 3: hold for ONE second.', 'Release even if screen is dark.')
        self.quiet(0, 10)
        self.tap(0)
        self.tap(1)
        self.record['irq_before_hold'] = irq_counts()
        power_key.verify_inhibitor()
        with pm.stage_controls('devices'):
            os.sync()  # Complete disk synchronization BEFORE requesting the hold.
            self.record['hold_prompt'] = self.prompt('3/4: Press POWER.', 'Hold for ONE second, then RELEASE.',
                'Release even if screen is dark!', 'Do NOT wait for a tone or prompt.', 'Never hold longer than 2 seconds.')
            self.wait(5, 25)
            self.record['irq_held'] = irq_counts()
            require_delta(self.record['irq_before_hold'], self.record['irq_held'], 1, 0)
            self.guard.drain()
            if (len(awake.edges(self.guard.record['events'])) != 5 or
                    keypad_pm.handle_state(self.guard.fd)['held_key_codes'] != [power_key.KEY_POWER]):
                raise ValueError('Hold ended before devices entry')
            self.record['entry_seconds'] = time.monotonic()
            persist()
            pm.enter_stage('devices')
            self.record['resume_seconds'] = time.monotonic()
            self.guard.after_entry()
        # The operator must already have released, independently of kernel return.
        self.prompt('Driver test returned.', 'Leave POWER RELEASED.', 'Checking recorded events...')
        self.wait(6, 2)
        self.record['irq_after_pm'] = irq_counts()
        require_delta(self.record['irq_held'], self.record['irq_after_pm'], 0, 1)
        self.neutral()
        self.cue.play('release-during-pm')
        self.quiet(6, 1)
        self.tap(3)
        self.record['irq_final'] = irq_counts()
        self.prompt('Sequence recorded.', 'Leave POWER released.', 'Checking restoration...')


class PostResumeHandoff:
    """Fresh awake pair after the PM clear, bound to unchanged PM generation."""
    def __init__(self, guard, record):
        self.guard, self.record = guard, record
        self.events = list(guard.record['events'])
        self.state = awake.awake_state()
        self.resume = guard.consumer.resumed
        self.check()

    def check(self):
        self.guard.drain()
        validate_input(self.record)
        if (self.guard.record['events'] != self.events or self.resume is None or
                self.guard.consumer.resumed != self.resume or
                self.record['physical_power']['stages'][-1]['press_seconds'] <= self.resume or
                not self.guard.consumer.released(keypad_pm.handle_state(self.guard.fd)) or
                time.monotonic()-self.guard.consumer.last_event < 0.3 or
                awake.awake_state() != self.state):
            raise ValueError('Fresh awake post-resume handoff lost continuity')
        require_delta(self.record['physical_power']['irq_final'], irq_counts(), 0, 0)
        power_key.verify_inhibitor()


def restore(pm, token):
    # Only this run's diagnostic controls/UI. Never restore the poweroff policy.
    with keypad_pm.exclusive_pm(awake.UI_OWNED.parent):
        if not os.path.lexists(awake.UI_OWNED):
            return
        awake.ui_owner(token)
        failure = None
        for operation in (keypad_pm.restore_trace, pm.restore, speaker_audio.restore, keypad_input.restore_console):
            try:
                operation()
            except BaseException as error:
                failure = failure or error
        if failure:
            raise failure
        awake.release_ui_record(token)


def validate_result(record):
    validate_input(record)
    validate_trace(record)
    if (record.get('policy_restored') is not True or record.get('policy_before') != record.get('policy_after') or
            record.get('audio_before') != record.get('audio_after') or
            record.get('console_restored') is not True or
            record.get('policy_owner_retained') is not False or record.get('dropin_retained') is not False):
        raise ValueError('PM input policy/audio/console restoration incomplete')
    if not all(record['power_key'].get(k) is True for k in
            ('handed_back', 'logical_release_verified', 'descriptor_closed')):
        raise ValueError('Power-key input handle not restored')
    keypad = record['keypad']
    old = keypad['old_handle_after']
    if (old['ioctl_errno'] is not None or old['hung_up'] or old['poll_error'] or
            keypad['before']['usb']['path'] != keypad['after']['usb']['path'] or
            keypad['before']['usb']['attributes']['devnum'] != keypad['after']['usb']['attributes']['devnum'] or
            keypad['before']['inputs'] != keypad['after']['inputs']):
        raise ValueError('Original internal keypad connection was not retained')
    cues = record['speaker_audio']
    if (cues.get('restored') is not True or [c['label'] for c in cues['cues']] !=
            ['tap-1', 'tap-2', 'release-during-pm', 'tap-4'] or
            any(c['amplifiers_after'] != {'Speaker Amp DRV':'Off', 'Headphone Amp':'Off'} for c in cues['cues'])):
        raise ValueError('Speaker cues or idle restoration incomplete')


def test(pm, lock, token):
    directory = pm.result_dir(token)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = dict(run_id=policy.run_id(token), stage='devices', mode='bounded-power-release',
        event='started', passed=False, physical_power={}, power_key={}, keypad={}, speaker_audio={})
    persist = lambda: pm.save(directory/'started.json', record)
    try:
        record['before'] = pm.snapshot()
        pm.validate(record['before'], lock)
        if lock.get('features', {}).get('speaker_audio') is not True:
            raise ValueError('Speaker diagnostic image required')
        record['policy_before'] = policy.inspect()
        record['audio_before'] = speaker_audio.inspect()
        pek = Path(power_key.identity()['sysfs']).parent.parent
        record['shutdown_ms'] = int((pek/'shutdown').read_text())
        if record['shutdown_ms'] < 6000:
            raise ValueError('Configured off delay below qualified short-hold preflight')
        persist()
        with keypad_pm.exclusive_pm(policy.OWNED.parent), power_key.own(record['power_key'], persist) as guard:
            guard.before_entry()
            with policy.worker(token, record['before']['boot_id'], directory) as child:
                awake.claim_ui(token)
                with keypad_input.console():
                    seq = Sequence(guard, record['physical_power'], None)
                    try:
                        with speaker_audio.session(record['speaker_audio']) as cue:
                            seq.cue = cue
                            with keypad_pm.observe(record['keypad'], tracing=True):
                                memory = os.urandom(4*1024*1024)
                                import hashlib
                                digest = hashlib.sha256(memory).hexdigest()
                                seq.run_pm(pm, persist)
                                record['stage_seconds'] = (record['physical_power']['resume_seconds']-
                                                           record['physical_power']['entry_seconds'])
                                record['process_memory_ok'] = hashlib.sha256(memory).hexdigest() == digest
                        validate_input(record)
                        record['input_clear_trace'] = validate_trace(record)
                    except BaseException:
                        seq.prompt('TEST STOPPED.', 'Release POWER immediately.',
                            'Do not press it again.', 'Evidence retained for inspection.')
                        time.sleep(2)
                        raise
                record['console_restored'] = not keypad_input.CONSOLE_OWNED.exists()
                awake.release_ui_record(token)
                time.sleep(max(0, 30-(time.monotonic()-record['physical_power']['resume_seconds'])))
                record['after'] = pm.snapshot()
                pm.validate(record['after'], lock)
                record['journal_delta'] = pm.check_result(record['before'], record['after'], 'devices', record['process_memory_ok'])
                # The counters above only support the PM observation. This fresh
                # awake pair is required independently before policy restoration.
                proof = PostResumeHandoff(guard, record)
                record['worker_returncode'] = policy.kill_worker(child)
                policy._restore_checked(token, proof.check)
                record['policy_restored'] = True
                proof.check()
        record['policy_after'] = policy.inspect()
        record['audio_after'] = speaker_audio.inspect()
        record['policy_owner_retained'] = os.path.lexists(policy.OWNED)
        record['dropin_retained'] = os.path.lexists(policy.DROPIN)
        validate_result(record)
        record.update(passed=True, event='complete')
    except BaseException as error:
        record.update(event='failed', error=type(error).__name__+': '+str(error))
        raise
    finally:
        record['policy_owner_retained'] = os.path.lexists(policy.OWNED)
        record['dropin_retained'] = os.path.lexists(policy.DROPIN)
        pm.save(directory/'result.json', record)
