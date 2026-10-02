"""Attended awake PEK edges and bounded held-release handoff; never enters PM."""
import argparse
import json
import os
from pathlib import Path
import signal
import time

import keypad_input
from keypad_pm import exclusive_pm, handle_state, save_owned
import power_key
import power_key_policy as policy
import speaker_audio

POWER = Path('/sys/power')
LABELS = ('tap-1', 'tap-2', 'hold', 'tap-4')
UI_OWNED = Path('/run/gameshellneo-power-input-ui.json')


def awake_state():
    return dict(boot_id=policy.BOOT.read_text().strip(),
        controls={n: (POWER/n).read_text().strip() for n in ('pm_test', 'pm_async', 'mem_sleep')},
        stats={p.name: p.read_text().strip() for p in (POWER/'suspend_stats').iterdir() if p.is_file()})


def edges(events):
    down, result, previous = False, [], -1
    for event in events:
        if event['seconds'] < previous or (event['type'] == 0 and event['code'] == 3):
            raise ValueError('Power-key timestamp order or continuity lost')
        previous = event['seconds']
        if event['type'] != 1:
            continue
        code, value = event['code'], event['value']
        if code != power_key.KEY_POWER or value not in (0, 1, 2):
            raise ValueError('Unexpected power-key event')
        if value == 2:
            if not down:
                raise ValueError('Repeat without held power key')
            continue
        if bool(value) == down:
            raise ValueError('Unpaired or duplicate power-key edge')
        down = bool(value)
        result.append(event)
    return result


def validate_sequence(events, stages):
    values = edges(events)
    if ([s['label'] for s in stages] != list(LABELS) or
            [e['value'] for e in values] != [1, 0] * 4):
        raise ValueError('Expected exactly four awake power-key press/release pairs')
    for i, stage in enumerate(stages):
        press, release = values[i*2:i*2+2]
        if (stage['press_seconds'] != press['seconds'] or stage['release_seconds'] != release['seconds'] or
                press['seconds'] < stage['prompt_seconds'] or
                not 0 < release['seconds']-press['seconds'] < 2.5):
            raise ValueError('Power-key prompt/timing mismatch')
        if stage['label'] == 'hold' and not (press['seconds'] <= stage['worker_killed_seconds'] <
                stage['release_prompt_seconds'] <= release['seconds']):
            raise ValueError('Held-key release did not follow worker death and release prompt')
    return values


class Sequence:
    def __init__(self, guard, record, cue):
        self.guard, self.record, self.cue = guard, record, cue
        record.update(stages=[], prompts=[])

    def prompt(self, *lines):
        stamp = time.monotonic()
        self.record['prompts'].append(dict(seconds=stamp, lines=lines))
        keypad_input.TTY.write_text('\x1b[H\x1b[2JGameShellNeo power-key test\r\n\r\n' +
            '\r\n'.join(lines) + '\r\n\r\nKeep USB connected.\r\n')
        return stamp

    def read_edges(self):
        self.guard.drain(20)
        return edges(self.guard.record['events'])

    def neutral(self):
        self.guard.drain()
        if not self.guard.consumer.released(handle_state(self.guard.fd)):
            raise ValueError('Power key is held or its state is unknown')

    def wait(self, count, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            values = self.read_edges()
            if len(values) > count:
                raise ValueError('Extra power-key press; sequence stopped')
            if len(values) == count:
                return values
        raise TimeoutError('Requested power-key edge was not received')

    def quiet(self, count, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if len(self.read_edges()) != count:
                raise ValueError('Unexpected power key during confirmation')
        self.neutral()

    def run(self, child):
        self.prompt('Leave POWER released.', 'Starting in 10 seconds.',
                    'Tones play AFTER release.')
        self.quiet(0, 10)
        for i, label in enumerate(LABELS):
            self.neutral()
            if label == 'hold':
                stamp = self.prompt('3/4: HOLD POWER briefly.', 'Release when RELEASE appears.',
                    'If no prompt: release after', '2 seconds. Do NOT hold longer.')
            else:
                stamp = self.prompt(f'{i+1}/4: Tap POWER once.', 'Release it promptly.',
                    'Wait for tone and next prompt.')
            stage = dict(label=label, prompt_seconds=stamp)
            values = self.wait(i*2+1, 25) if label == 'hold' else self.wait(i*2+2, 25)
            if label == 'hold':
                stage['press_seconds'] = values[-1]['seconds']
                try:
                    self.record['worker_returncode'] = policy.kill_worker(child, timeout=0.2)
                    stage['worker_killed_seconds'] = time.monotonic()
                    # No D-Bus/config/audio operation can delay this release prompt.
                    deadline = stage['press_seconds'] + 0.8
                    while time.monotonic() < deadline:
                        if len(self.read_edges()) != i*2+1:
                            raise ValueError('Power key released before the release prompt')
                finally:
                    stage['release_prompt_seconds'] = self.prompt('RELEASE POWER NOW.',
                        'Then leave it released.', 'Wait for the confirmation tone.')
                values = self.wait(i*2+2, 2)
            stage.update(press_seconds=values[-2]['seconds'], release_seconds=values[-1]['seconds'])
            self.record['stages'].append(stage)
            self.neutral()
            self.prompt(f'{i+1}/4 recorded.', 'Press and release received.',
                        'Do not press it again.', 'Wait for the next prompt.')
            self.cue.play(label)
            self.quiet(i*2+2, 1)
        validate_sequence(self.guard.record['events'], self.record['stages'])
        self.prompt('All four pairs recorded.', 'Leave POWER released.', 'Checking restoration...')


class AwakeHandoff:
    """A validated awake transcript bound to this still-open event stream."""
    def __init__(self, guard, stages, before):
        self.guard, self.stages, self.before = guard, stages, before
        self.count = len(guard.record['events'])
        self.check()

    def check(self):
        self.guard.drain()
        validate_sequence(self.guard.record['events'], self.stages)
        if (len(self.guard.record['events']) != self.count or self.guard.consumer.resumed is not None or
                not self.guard.consumer.released(handle_state(self.guard.fd)) or
                time.monotonic()-self.guard.consumer.last_event < 0.3 or awake_state() != self.before):
            raise ValueError('Awake released-key handoff lost continuity or crossed PM')
        power_key.verify_inhibitor()


def claim_ui(token):
    if any(os.path.lexists(p) for p in (UI_OWNED, speaker_audio.OWNED, keypad_input.CONSOLE_OWNED)):
        raise ValueError('Existing UI/audio ownership must be recovered first')
    save_owned(dict(run_id=policy.run_id(token), boot_id=policy.BOOT.read_text().strip()), UI_OWNED)


def ui_owner(token):
    expected = dict(run_id=policy.run_id(token), boot_id=policy.BOOT.read_text().strip())
    if json.loads(policy.read_owned(UI_OWNED)) != expected:
        raise ValueError('UI recovery belongs to another run or boot')


def release_ui_record(token):
    ui_owner(token)
    if any(os.path.lexists(p) for p in (speaker_audio.OWNED, keypad_input.CONSOLE_OWNED)):
        raise ValueError('UI/audio restoration incomplete; owner retained')
    UI_OWNED.unlink()


def restore_ui(token):
    # Restoring the UI does not restore power-key policy after an unknown handoff.
    with exclusive_pm(UI_OWNED.parent):
        if not os.path.lexists(UI_OWNED):
            return
        ui_owner(token)
        try:
            speaker_audio.restore()
        finally:
            keypad_input.restore_console()
        release_ui_record(token)


def test_input(token, directory):
    record = dict(run_id=policy.run_id(token), passed=False, mode='awake-power-key-input',
                  restored=False, power_key={}, input={}, speaker_audio={})
    try:
        record['before'] = policy.inspect()
        record['awake_before'] = awake_state()
        if '[none]' not in record['awake_before']['controls']['pm_test']:
            raise ValueError('PM debug control must be idle for awake key qualification')
        pek = Path(power_key.identity()['sysfs']).parent.parent
        record['shutdown_ms'] = int((pek/'shutdown').read_text())
        if record['shutdown_ms'] < 6000:
            raise ValueError('Short hold requires at least the observed six-second configured off delay')
        record['audio_before'] = speaker_audio.inspect()
        save_owned(record, directory/'started.json')
        with exclusive_pm(policy.OWNED.parent), power_key.own(record['power_key'], lambda: None) as guard:
            guard.before_entry()
            with policy.worker(token, record['before']['boot_id'], directory) as child:
                claim_ui(token)
                with keypad_input.console():
                    seq = Sequence(guard, record['input'], None)
                    try:
                        with speaker_audio.session(record['speaker_audio']) as cue:
                            seq.cue = cue
                            seq.run(child)
                        record['worker_returncode'] = record['input']['worker_returncode']
                        record['survived_worker_death'] = policy.inspect()
                        proof = AwakeHandoff(guard, record['input']['stages'], record['awake_before'])
                        policy._restore_checked(token, proof.check)
                        record['restored'] = True
                        proof.check()
                    except BaseException:
                        seq.prompt('TEST STOPPED.', 'Release POWER immediately.',
                            'Do not press it again.', 'Evidence saved for review.')
                        time.sleep(2)
                        raise
                record['console_restored'] = not keypad_input.CONSOLE_OWNED.exists()
                release_ui_record(token)
        record['after'] = policy.inspect()
        record['awake_after'] = awake_state()
        record['audio_after'] = speaker_audio.inspect()
        validate_result(record)
        record['passed'] = True
    except BaseException as error:
        record['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        record['policy_owner_retained'] = os.path.lexists(policy.OWNED)
        record['dropin_retained'] = os.path.lexists(policy.DROPIN)
        save_owned(record, directory/'result.json')
    return record


def validate_result(record):
    validate_sequence(record['power_key']['events'], record['input']['stages'])
    if (record.get('worker_returncode') != -signal.SIGKILL or not record.get('restored') or
            record.get('before') != record.get('after') or
            record.get('awake_before') != record.get('awake_after') or
            record.get('audio_before') != record.get('audio_after') or
            record.get('console_restored') is not True):
        raise ValueError('Awake input/policy/audio/console restoration failed')
    held = record['survived_worker_death']
    if held['policy'] != record['before']['policy'] | policy.IGNORE or not held['owned'] or not held['dropin']:
        raise ValueError('Ignore policy missing after held-key worker death')
    if not all(record['power_key'].get(k) is True for k in
            ('handed_back', 'logical_release_verified', 'descriptor_closed')):
        raise ValueError('Power-key handle not handed back')
    audio = record['speaker_audio']
    if (audio.get('restored') is not True or [c['label'] for c in audio['cues']] != list(LABELS) or
            any(c['amplifiers_after'] != {'Speaker Amp DRV':'Off', 'Headphone Amp':'Off'} for c in audio['cues'])):
        raise ValueError('Four speaker confirmations and idle restoration required')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore-ui', action='store_true', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    restore_ui(args.run_id)
