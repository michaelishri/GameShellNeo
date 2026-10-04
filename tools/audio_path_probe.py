"""Audio-only short/long comparison with bounded observations during playback."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import signal
import threading
import time

import speaker_audio as audio

RESULTS = Path('/var/lib/gameshellneo/audio-tests')
GPIO = Path('/sys/kernel/debug/gpio')
MAX_SAMPLES = 400
WINDOW_SECONDS = 8
INTERVAL_SECONDS = 0.02


def reader():
    """Resolve once; all subsequent observation is read-only and sequential."""
    root = audio.card()
    pcm = root / 'pcm0p/sub0'
    widgets = {}
    for name in ('Speaker Amp DRV', 'Headphone Amp'):
        matches = list(audio.ASOC.rglob(name))
        if len(matches) != 1:
            raise ValueError('Expected one DAPM widget: ' + name)
        widgets[name] = matches[0]

    def sample():
        started = time.monotonic()
        status = (pcm / 'status').read_text()
        params = (pcm / 'hw_params').read_text()
        states = {}
        for name, path in widgets.items():
            match = re.match(re.escape(name) + r': (On|Off)\b', path.read_text())
            if not match:
                raise ValueError('Unexpected amplifier widget state: ' + name)
            states[name] = match[1]
        # Keep the full GPIO text privately: gpiochip numbering is not stable.
        gpio = GPIO.read_text()
        return dict(started_seconds=started, completed_seconds=time.monotonic(),
                    pcm_status=status, hw_params=params, amplifiers=states,
                    gpio=gpio)
    return sample


def observe(sample, record, stop):
    deadline = time.monotonic() + WINDOW_SECONDS
    try:
        while not stop.is_set():
            if len(record['samples']) >= MAX_SAMPLES or time.monotonic() >= deadline:
                raise TimeoutError('Active audio observation limit reached')
            record['samples'].append(sample())
            stop.wait(INTERVAL_SECONDS)
    except BaseException as error:
        record['error'] = type(error).__name__ + ': ' + str(error)


def summarize(samples):
    # These are software observations, never proof of physical sound. Reads
    # within a sample are sequential; their timestamps bound that uncertainty.
    return dict(
        pcm_running_observed=any(re.search(r'^state:\s+RUNNING\s*$', s['pcm_status'], re.M)
                                 is not None for s in samples),
        both_amplifiers_on_observed=any(all(v == 'On' for v in s['amplifiers'].values())
                                       for s in samples),
        sample_count=len(samples))


@contextmanager
def capture_path(record):
    sample = reader()
    record['samples'] = [sample()]
    stop = threading.Event()
    worker = threading.Thread(target=observe, args=(sample, record, stop), daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=2)
        if worker.is_alive():
            record['error'] = 'Audio observer did not stop; service timeout remains in force'
            raise TimeoutError(record['error'])
        record['summary'] = summarize(record['samples'])
        if 'error' in record:
            raise RuntimeError(record['error'])


def test(run_id, level=3):
    if not re.fullmatch('[a-f0-9]{32}', run_id):
        raise ValueError('Expected a private 32-character run ID')
    if type(level) is not int or level not in (3, 4, 5):
        raise ValueError('Active path comparison supports only levels 3, 4 and 5')
    directory = RESULTS / run_id
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = dict(run_id=run_id, kind='audio-path', passed=False,
                  audibility='requires-owner-observation', paths=[])
    try:
        record['before'] = audio.inspect()
        with audio.session(record, owner=run_id) as cue:
            audio.set_control('Headphone Playback Volume', str(audio.LEVELS[level]))
            record['active_controls'] = {name: audio.control(name) for name in audio.CONTROLS}
            print('Same-volume 80 ms and 1000 ms tones start in ten seconds.', flush=True)
            time.sleep(10)
            for duration in (80, 1000):
                path = dict(duration_ms=duration, level=level)
                record['paths'].append(path)
                with capture_path(path):
                    cue.play('audio-path-' + str(duration), level, duration_ms=duration)
                time.sleep(2)
        record['after'] = audio.inspect()
        if (record['before']['boot_id'] != record['after']['boot_id'] or
                record['before']['controls'] != record['after']['controls']):
            raise ValueError('Audio comparison changed boot or did not restore mixer state')
        record['passed'] = True
    except BaseException as error:
        record['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        with (directory / 'result.json').open('w') as output:
            json.dump(record, output, indent=2)
            output.flush()
            os.fsync(output.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id')
    parser.add_argument('--level', type=int, choices=(3, 4, 5), default=3)
    args = parser.parse_args()
    os.umask(0o077)
    def interrupted(signum, _frame):
        raise SystemExit(128 + signum)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    test(args.run_id, args.level)


if __name__ == '__main__':
    main()
