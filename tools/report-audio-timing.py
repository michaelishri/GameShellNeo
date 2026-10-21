#!/usr/bin/env python3
"""Summarize saved cue software timings offline; never infer acoustic onset."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import stat
import sys

MAX_CAPTURE = 32 * 1024 * 1024
MAX_CUES = 128
POINTS = ('call_seconds', 'waveform_ready_seconds', 'idle_before_seconds',
          'playback_requested_seconds', 'process_created_seconds',
          'process_finished_seconds', 'idle_after_seconds')
PHASES = ('waveform', 'pre_playback_idle_check', 'mixer', 'process_creation',
          'playback_process', 'post_playback_idle_check')
LIMITS = ('Software operation durations only; no acoustic-onset, keypress-to-sound, '
          'driver-only latency, power or PM acceptance claim. Caller/session setup '
          'and prompt pauses are outside Cue.play. Historical cues without phase '
          'timestamps retain only their original playback-request-to-idle interval.')


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Invalid audio timing value')
    return value


def milliseconds(start, end):
    elapsed = number(end) - number(start)
    if elapsed < 0 or not math.isfinite(elapsed * 1000):
        raise ValueError('Invalid audio timing order or duration')
    return round(elapsed * 1000, 3)


def cue_summary(cue):
    if not isinstance(cue, dict):
        raise ValueError('Invalid cue record')
    duration = cue.get('duration_ms')
    if duration is not None and (type(duration) is not int or duration not in (80, 1000)):
        raise ValueError('Unsupported saved waveform duration')
    result = dict(playback_request_to_idle_ms=milliseconds(
        cue['started_seconds'], cue['completed_seconds']), phase_ms=None,
        call_to_idle_ms=None, waveform_duration_ms=duration)
    if 'timing' not in cue:
        return result
    timing = cue['timing']
    if (not isinstance(timing, dict) or set(timing) != set(POINTS) | {'schema', 'clock'} or
            type(timing['schema']) is not int or timing['schema'] != 1 or
            timing['clock'] != 'monotonic'):
        raise ValueError('Unsupported audio timing schema')
    points = [number(timing[name]) for name in POINTS]
    if (points[3] != cue['started_seconds'] or points[-1] != cue['completed_seconds']):
        raise ValueError('Audio timing endpoints differ from original cue')
    result['phase_ms'] = {name: milliseconds(a, b)
                          for name, a, b in zip(PHASES, points, points[1:])}
    result['call_to_idle_ms'] = milliseconds(points[0], points[-1])
    return result


def summarize(record):
    if not isinstance(record, dict):
        raise ValueError('Expected one saved audio, PM or sleep result')
    # Explicit containers avoid scanning embedded prerequisite results or
    # accidentally treating earlier tests as observations from this test.
    containers = [('audio', record)]
    for name in ('speaker_audio', 'screen_warning'):
        if record.get(name) is not None:
            if not isinstance(record[name], dict):
                raise ValueError('Invalid audio result container')
            containers.append((name, record[name]))
    result = []
    for scope, container in containers:
        cues = container.get('cues', [])
        if not isinstance(cues, list) or len(cues) + len(result) > MAX_CUES:
            raise ValueError('Invalid or oversized cue list')
        for index, cue in enumerate(cues, 1):
            result.append(dict(scope=scope, cue=index, **cue_summary(cue)))
    if not result:
        raise ValueError('No completed cue timings in this result')
    passed = record.get('passed')
    if passed is not None and type(passed) is not bool:
        raise ValueError('Invalid original result status')
    return dict(original_result_passed=passed, cues=result, limits=LIMITS)


def report(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError('Expected a regular saved result')
        raw = source.read(MAX_CAPTURE + 1)
    if len(raw) > MAX_CAPTURE:
        raise ValueError('Audio timing capture exceeds 32 MiB')
    try:
        result = summarize(json.loads(raw))
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
        raise ValueError('Invalid audio timing evidence; contents withheld') from None
    return dict(sha256=hashlib.sha256(raw).hexdigest(), capture_bytes=len(raw), **result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    args = parser.parse_args(sys.argv[1:] or shlex.split(os.environ.get('NEO_COMMAND', '')))
    print(json.dumps(report(args.capture), indent=2))


if __name__ == '__main__':
    main()
