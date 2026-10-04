"""Bounded, quiet ALSA cues with owned mixer restoration; no audio daemon."""
import argparse
from contextlib import contextmanager
import io
import json
import math
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import time
import wave

CARD = 'GameShellNeo'
OWNED = Path('/run/gameshellneo-speaker.json')
ASOUND = Path('/proc/asound')
ASOC = Path('/sys/kernel/debug/asoc')
BOOT = Path('/proc/sys/kernel/random/boot_id')
CONTROLS = {
    'Speaker Switch': 'on',
    'Headphone Playback Volume': '48',  # -15 dB, plus -20 dBFS waveform peak.
    'Headphone Playback Switch': 'on,on',
    'Headphone Source Playback Route': '0,0',  # Direct DAC, no analogue input mixing.
    'AIF1 DA0 Playback Volume': '160,160',  # -120 dB + 160 * 0.75 dB = unity.
    'DAC Playback Volume': '160,160',
    'AIF1 Slot 0 Digital DAC Playback Switch': 'on,on',
}
LEVELS = {1: 36, 2: 42, 3: 48}  # Analogue gain -27/-21/-15 dB; never positive digital gain.


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=10).strip()


def card():
    matches = [p for p in ASOUND.glob('card[0-9]*/id') if p.read_text().strip() == CARD]
    if len(matches) != 1:
        raise ValueError('Expected exactly one GameShellNeo sound card')
    image = json.loads(Path('/etc/gameshellneo/image.json').read_text())
    if (image['board'] != 'gameshellneo-cpi31' or
            image['sources'].get('features', {}).get('speaker_audio') is not True or
            os.uname().release != image['kernel']):
        raise ValueError('Speaker cue requires its identified audio-enabled CPI v3.1 image')
    return matches[0].parent


def control(name):
    if name not in CONTROLS:
        raise ValueError('Unowned speaker control')
    text = command('amixer', '-c', CARD, 'cget', 'name=' + name)
    match = re.search(r'^\s*: values=([a-z0-9,]+)$', text, re.M)
    if not match or not re.fullmatch(r'(?:[0-9]+|on|off)(?:,(?:[0-9]+|on|off))*', match[1]):
        raise ValueError('Unsupported ALSA control values: ' + name)
    return match[1]


def set_control(name, value):
    if name not in CONTROLS or not re.fullmatch(r'(?:[0-9]+|on|off)(?:,(?:[0-9]+|on|off))*', value):
        raise ValueError('Invalid speaker control write')
    command('amixer', '-q', '-c', CARD, 'cset', 'name=' + name, value)
    if control(name) != value:
        raise ValueError('Speaker mixer readback differs: ' + name)


def amplifiers():
    result = {}
    for name in ('Speaker Amp DRV', 'Headphone Amp'):
        paths = list(ASOC.rglob(name))
        if len(paths) != 1:
            raise ValueError('Expected one DAPM widget: ' + name)
        first = paths[0].read_text().splitlines()[0]
        match = re.match(re.escape(name) + r': (On|Off)\b', first)
        if not match:
            raise ValueError('Unexpected amplifier widget state')
        result[name] = match[1]
    return result


def idle():
    root = card()
    statuses = list(root.glob('pcm*/sub*/status'))
    if not statuses or any(p.read_text().strip() != 'closed' for p in statuses):
        raise ValueError('Close other audio streams before the speaker test')
    state = amplifiers()
    if any(value != 'Off' for value in state.values()):
        raise ValueError('Speaker/headphone amplifier did not power down')
    return state


def inspect():
    root = card()
    return dict(boot_id=BOOT.read_text().strip(), card=CARD,
        cards=(ASOUND / 'cards').read_text(), pcm=(ASOUND / 'pcm').read_text(),
        controls=command('amixer', '-c', CARD, 'contents'),
        pcm_status={str(p): p.read_text() for p in root.glob('pcm*/sub*/status')},
        amplifiers=amplifiers(), gpio=Path('/sys/kernel/debug/gpio').read_text())


def waveform(duration_ms=80):
    """Bounded stereo 880 Hz cue, -20 dBFS peak, 10 ms fades; 80 ms by default."""
    if type(duration_ms) is not int or duration_ms not in (80, 1000):
        raise ValueError('Speaker duration must be 80 or 1000 ms')
    rate, frames, fade = 48000, 48 * duration_ms, 480
    samples = bytearray()
    for index in range(frames):
        envelope = min(1.0, index / fade, (frames - 1 - index) / fade)
        value = round(3276 * envelope * math.sin(2 * math.pi * 880 * index / rate))
        samples.extend(struct.pack('<hh', value, value))
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setparams((2, 2, rate, frames, 'NONE', 'not compressed'))
        audio.writeframes(samples)
    return output.getvalue()


def restore(owner=None):
    if not OWNED.exists():
        return
    saved = json.loads(OWNED.read_text())
    if owner is not None and (not re.fullmatch('[a-f0-9]{32}', owner) or saved.get('notice_owner') != owner):
        raise ValueError('Speaker warning belongs to another owner; record retained')
    card()
    original = saved.get('controls', {})
    if saved.get('boot_id') != BOOT.read_text().strip() or set(original) != set(CONTROLS):
        raise ValueError('Invalid speaker mixer ownership; record retained')
    # Disable the speaker path before restoring gains/routes. Restore its original
    # switch last, when no PCM is open; failed restoration keeps the owner file.
    set_control('Speaker Switch', 'off')
    for name, value in original.items():
        if name != 'Speaker Switch':
            set_control(name, value)
    set_control('Speaker Switch', original['Speaker Switch'])
    idle()
    OWNED.unlink()


class Cue:
    def __init__(self, record):
        self.record = record

    def play(self, label, level=3, *, duration_ms=80):
        if type(level) is not int or level not in LEVELS:
            raise ValueError('Speaker level must be 1, 2 or 3')
        payload = waveform(duration_ms)
        idle()
        set_control('Headphone Playback Volume', str(LEVELS[level]))
        started = time.monotonic()
        # A child stuck in playback cannot survive normal timeout cleanup. The
        # owning systemd unit additionally kills its whole cgroup on interruption.
        process = subprocess.Popen(['aplay', '-q', '-D', 'hw:CARD=' + CARD + ',DEV=0', '-t', 'wav'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            _, error = process.communicate(payload, timeout=5)
            if process.returncode:
                raise RuntimeError('Speaker playback failed: ' + error.decode(errors='replace')[:400])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
        deadline = time.monotonic() + 6
        while True:
            try:
                state = idle()
                break
            except ValueError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        self.record.setdefault('cues', []).append(dict(label=label, level=level, duration_ms=duration_ms,
            started_seconds=started, completed_seconds=time.monotonic(), amplifiers_after=state))


@contextmanager
def session(record, owner=None):
    if owner is not None and not re.fullmatch('[a-f0-9]{32}', owner):
        raise ValueError('Invalid speaker warning owner')
    idle()
    original = {name: control(name) for name in CONTROLS}
    with OWNED.open('x') as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(dict(boot_id=BOOT.read_text().strip(), controls=original,
                       notice_owner=owner), output)
        output.flush()
        os.fsync(output.fileno())
    record.update(original_controls=original, restored=False, cues=[])
    try:
        set_control('Speaker Switch', 'off')
        for name, value in CONTROLS.items():
            if name != 'Speaker Switch':
                set_control(name, value)
        set_control('Speaker Switch', 'on')
        yield Cue(record)
    finally:
        restore()
        record['restored'] = not OWNED.exists()


def warn_screen(record, owner=None):
    """Finish a quiet cue and restore idle audio before allowing darkness."""
    record['passed'] = False
    with session(record, owner=owner) as cue:
        cue.play('screen-blank')
    time.sleep(1)  # Observer lead-in; outside PM/energy measurement windows.
    record['passed'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--restore', action='store_true')
    mode.add_argument('--test', metavar='RUN')
    mode.add_argument('--warn-screen', action='store_true')
    parser.add_argument('--owner', help='Limit warning ownership/recovery to this 32-character run ID')
    args = parser.parse_args()
    os.umask(0o077)
    if args.restore:
        restore(args.owner)
    elif args.inspect:
        print(json.dumps(inspect()))
    elif args.warn_screen:
        def interrupted(signum, _frame):
            raise SystemExit(128 + signum)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, interrupted)
        record = {}
        warn_screen(record, owner=args.owner)
        print(json.dumps(record))
    else:
        if not re.fullmatch('[a-f0-9]{32}', args.test):
            raise ValueError('Expected a private 32-character run ID')
        directory = Path('/var/lib/gameshellneo/audio-tests') / args.test
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        record = dict(run_id=args.test, passed=False)
        def interrupted(signum, _frame):
            raise SystemExit(128 + signum)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, interrupted)
        try:
            record['before'] = inspect()
            with session(record) as cue:
                print('Three quiet speaker cues start in ten seconds.', flush=True)
                time.sleep(10)
                for level in (1, 2, 3):
                    cue.play('speaker-check-' + str(level), level)
                    time.sleep(2)
            record['after'] = inspect()
            record['passed'] = True
        except BaseException as error:
            record['error'] = type(error).__name__ + ': ' + str(error)
            raise
        finally:
            with (directory / 'result.json').open('w') as output:
                json.dump(record, output, indent=2)
                output.flush()
                os.fsync(output.fileno())


if __name__ == '__main__':
    main()
