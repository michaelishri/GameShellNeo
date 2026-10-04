#!/usr/bin/env python3
"""Inspect or run bounded speaker cues on the audio-enabled diagnostic image."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import time
import uuid

import paramiko
from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run, upload, python_command
from speaker_audio import WARNING_DURATION_MS, WARNING_LEVEL


def inline(client, option):
    return run(client, **python_command((ROOT / 'tools/speaker_audio.py').read_text(), option),
               display=False, timeout=45)


def collect(config, run_id, route='usb'):
    if not re.fullmatch('[a-f0-9]{32}', run_id):
        raise ValueError('Supply the 32-character audio RUN ID')
    with device(config, route) as client:
        return json.loads(run(client, shlex.join(['sudo', '-n', 'cat',
            '/var/lib/gameshellneo/audio-tests/' + run_id + '/result.json']), display=False))


def validate(result, before, run_id, path_test=False, path_level=5):
    if (result.get('passed') is not True or result.get('restored') is not True or
            result.get('run_id') != run_id or
            result['before']['boot_id'] != before['boot_id'] or
            result['after']['boot_id'] != before['boot_id'] or
            result['before']['controls'] != before['controls'] or
            result['after']['controls'] != before['controls']):
        raise ValueError('Speaker cue or restoration checks failed; evidence retained')
    if path_test:
        if (result.get('kind') != 'audio-path' or
                [(c.get('level'), c.get('duration_ms')) for c in result.get('cues', [])] != [(path_level, 1000)] or
                [p.get('duration_ms') for p in result.get('paths', [])] != [1000] or
                any('error' in p or not p.get('samples') for p in result['paths'])):
            raise ValueError('Incomplete active audio path comparison; evidence retained')
    elif [(c.get('level'), c.get('duration_ms')) for c in result.get('cues', [])] != [(WARNING_LEVEL, WARNING_DURATION_MS)] * 3:
        raise ValueError('Expected three cues at the qualified warning level and duration')


def request_reboot(config, route, capture, run_id, before, result):
    """Queue once, only after the original cue and mixer restoration passed."""
    if (result.get('passed') is not True or result.get('restored') is not True or
            result.get('run_id') != run_id or
            [(c.get('level'), c.get('duration_ms')) for c in result.get('cues', [])] != [(WARNING_LEVEL, WARNING_DURATION_MS)] * 3 or
            result['before']['boot_id'] != before['boot_id'] or
            result['after']['boot_id'] != before['boot_id'] or
            result['before']['controls'] != before['controls'] or
            result['after']['controls'] != before['controls']):
        raise ValueError('A completed same-boot speaker warning is required before reboot')
    record = dict(run_id=run_id, boot_id=before['boot_id'], route=route,
                  unit='gameshellneo-audible-reboot-' + run_id,
                  submission_attempted=False, accepted=False)
    path = capture / 'reboot.json'
    with device(config, route) as client:
        boot = run(client, 'cat /proc/sys/kernel/random/boot_id', display=False).decode().strip()
        if boot != before['boot_id']:
            raise ValueError('Boot changed after the speaker warning; refusing another reboot')
        record['submission_attempted'] = True
        path.write_text(json.dumps(record, indent=2) + '\n')
        # Defer briefly so acceptance can return before SSH disconnects. Never
        # retry an uncertain submission: this timer has a unique recorded name.
        command = ['sudo', '-n', 'systemd-run', '--quiet', '--collect',
                   '--unit=' + record['unit'], '--on-active=2s',
                   '--timer-property=AccuracySec=1s', '/usr/bin/systemctl', 'reboot']
        try:
            run(client, shlex.join(command), display=False, timeout=20)
        except (OSError, RuntimeError, paramiko.SSHException) as error:
            record['error'] = type(error).__name__ + ': ' + str(error)
            path.write_text(json.dumps(record, indent=2) + '\n')
            raise RuntimeError('Reboot submission uncertain; inspect its recorded unit and boot, do not retry') from error
        record['accepted'] = True
        path.write_text(json.dumps(record, indent=2) + '\n')
    print('Speaker warning and restoration passed; one reboot queued. Verify the new boot separately.')


def restore(client):
    # A completed --collect unit may have disappeared while its ownership
    # record remains. A missing unit must not prevent mixer recovery.
    try:
        state = run(client, 'systemctl show gameshellneo-audio-test -p LoadState --value',
                    display=False).decode().strip()
        if state != 'not-found':
            run(client, 'sudo -n systemctl stop gameshellneo-audio-test', display=False, timeout=30)
    finally:
        inline(client, '--restore')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--test', action='store_true')
    mode.add_argument('--path-test', action='store_true', help='Play one long tone with active path observations')
    mode.add_argument('--reboot', action='store_true', help='Play the three speaker cues, then queue one reboot')
    mode.add_argument('--collect', action='store_true')
    mode.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    path_level = os.environ.get('NEO_AUDIO_LEVEL', '5')
    if args.path_test and path_level not in ('3', '4', '5'):
        raise ValueError('Use LEVEL=3/4/5 for the active audio comparison')
    os.umask(0o077)
    config, capture = load_env(), evidence_directory()
    route = os.environ.get('NEO_AUDIO_ROUTE', 'usb')
    if route not in ('usb', 'wifi'):
        raise ValueError('Use ROUTE=usb/wifi')
    print('Private audio evidence:', capture, flush=True)
    if args.collect:
        value = collect(config, os.environ.get('NEO_AUDIO_RUN', ''), route)
        (capture / 'result.json').write_text(json.dumps(value, indent=2) + '\n')
        print('Collected audio result; passed:', value.get('passed'))
        return
    with (LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with device(config, route) as client:
            if args.inspect:
                (capture / 'audio.json').write_bytes(inline(client, '--inspect'))
                print('Read-only speaker/card/mixer state saved.')
                return
            if args.restore:
                restore(client)
                print('Stopped speaker test and restored its owned mixer controls.')
                return
            for unit in ('gameshellneo-audio-test', 'gameshellneo-pm-test'):
                if run(client, 'systemctl show ' + unit + ' -p LoadState --value', display=False).decode().strip() != 'not-found':
                    raise ValueError('Collect/restore the existing diagnostic unit first: ' + unit)
            before = json.loads(inline(client, '--inspect'))
            (capture / 'before.json').write_text(json.dumps(before, indent=2) + '\n')
            directory = run(client, 'umask 077; mktemp -d /tmp/gameshellneo-audio.XXXXXXXX',
                            display=False).decode().strip()
            if not re.fullmatch(r'/tmp/gameshellneo-audio\.[a-zA-Z0-9]+', directory):
                raise ValueError('Unexpected audio helper directory')
            script, run_id = directory + '/speaker_audio.py', uuid.uuid4().hex
            with client.open_sftp() as sftp:
                upload(sftp, ROOT / 'tools/speaker_audio.py', script)
                if args.path_test:
                    upload(sftp, ROOT / 'tools/audio_path_probe.py', directory + '/audio_path_probe.py')
            sources = ['speaker_audio.py'] + (['audio_path_probe.py'] if args.path_test else [])
            (capture / 'run.json').write_text(json.dumps(dict(run_id=run_id, helper=directory,
                sources={name: hashlib.sha256((ROOT / 'tools' / name).read_bytes()).hexdigest()
                         for name in sources})) + '\n')
            print('Audio run:', run_id, flush=True)
            command = ['sudo', '-n', 'systemd-run', '--quiet', '--collect',
                '--unit=gameshellneo-audio-test', '--property=RuntimeMaxSec=90',
                '--property=TimeoutStopSec=15', '--property=UMask=0077',
                '--property=ExecStopPost=/usr/bin/python3 -B ' + script + ' --restore',
                '/usr/bin/python3', '-B'] + (
                    [directory + '/audio_path_probe.py', run_id, '--level', path_level]
                    if args.path_test else [script, '--test', run_id])
            try:
                run(client, shlex.join(command), display=False, timeout=20)
            except (OSError, RuntimeError, paramiko.SSHException) as error:
                (capture / 'submission-error.txt').write_text(type(error).__name__ + '\n')
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            time.sleep(5)
            try:
                result = collect(config, run_id, route)
            except (OSError, RuntimeError, paramiko.SSHException) as error:
                with (capture / 'collection-errors.txt').open('a') as output:
                    output.write(type(error).__name__ + '\n')
                continue
            (capture / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
            validate(result, before, run_id, args.path_test, int(path_level) if args.path_test else 3)
            print(('Active audio path check' if args.path_test else 'Three bounded cues') +
                  ' completed; mixer and amplifier idle state restored. Audibility needs owner confirmation.')
            if args.reboot:
                request_reboot(config, route, capture, run_id, before, result)
            return
        raise TimeoutError('Collect/recover audio RUN=' + run_id + '; do not resubmit blindly')


if __name__ == '__main__':
    main()
