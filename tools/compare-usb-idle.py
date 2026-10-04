#!/usr/bin/env python3
"""Run the saved experimental/stock/experimental battery comparison over Wi-Fi."""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import paramiko
from private_config import load_env
from remote import LOCAL, ROOT, device, evidence_directory, run, python_command


def state(config):
    # Reuse the checked-in battery/health/radio readers without running a profile.
    code = ('import json, hashlib\n'
            'from pathlib import Path\n'
            'scope = {"__name__": "power_state"}\n'
            'exec(' + repr((ROOT / 'tools/profile-power.py').read_text()) + ', scope)\n'
            'log = scope["subprocess"].run(["journalctl", "-b", "-k", "--no-pager", "-o", "cat"], '
            'check=True, capture_output=True, text=True, timeout=30).stdout\n'
            'print(json.dumps(dict(health=scope["health"](), radio=scope["radio"](), '
            'capabilities=scope["capabilities"](), kernel=scope["os"].uname().release, '
            'radio_events=dict(firmware_crashes=log.count("brcmf_fw_crashed: Firmware has halted or crashed"), '
            'sdio_removals=log.count("mmc1: card 0001 removed")), '
            'firmware_sha256=hashlib.sha256(Path("/usr/lib/firmware/brcm/brcmfmac43430a0-sdio.bin").read_bytes()).hexdigest(), '
            'wifi_config_sha256=hashlib.sha256(Path("/etc/wpa_supplicant/wpa_supplicant-wlan0.conf").read_bytes()).hexdigest())))\n')
    with device(config, 'wifi') as client:
        return json.loads(run(client, **python_command(code), display=False))


def fixed(value):
    health = value['health']
    capabilities = dict(value['capabilities'])
    capabilities.pop('cpufreq_time_in_state', None)
    return dict(settings={key: health[key] for key in ('online_cpus', 'brightness', 'bl_power', 'governor')},
                capabilities=capabilities, power_save=value['radio']['power_save'], kernel=value['kernel'],
                firmware_sha256=value['firmware_sha256'], wifi_config_sha256=value['wifi_config_sha256'])


def require_state(value, baseline, boot=None, radio_events=None):
    if fixed(value) != baseline or (boot is not None and value['health']['boot_id'] != boot):
        raise ValueError('Comparison settings or phase boot identity changed')
    if radio_events is not None and value['radio_events'] != radio_events:
        raise ValueError('Radio crash/reprobe events changed during measurement')


def task(capture, name, arguments, tolerate_disconnect=False):
    path = capture / (name + '.log')
    attempt = 1
    while path.exists():
        attempt += 1
        path = capture / (name + '-attempt-' + str(attempt) + '.log')
    print('Running:', ' '.join(arguments), flush=True)
    # Task 3 normally gives inherited environment values precedence over its
    # env mapping. The outer task exports default NEO_* values, which would
    # silently override nested SECONDS=300 and MODE=stock arguments.
    environment = {key: value for key, value in os.environ.items() if not key.startswith('NEO_')}
    with path.open('wb') as output:
        result = subprocess.run(['task', *arguments], cwd=ROOT, env=environment,
                                stdout=output, stderr=subprocess.STDOUT)
    if result.returncode and not tolerate_disconnect:
        raise RuntimeError('Task failed; inspect private log ' + str(path))
    return path.read_text()


def policy(capture, name, mode, next_mode=None):
    if next_mode:
        task(capture, name + '-write', ['device:usb-policy', 'ROUTE=wifi', 'MODE=' + next_mode])
    # Selection prints both a write receipt and a status record. Verify with
    # a separate read-only status command instead of interpreting the receipt.
    output = task(capture, name, ['device:usb-policy', 'ROUTE=wifi', 'MODE=status'])
    value, _ = json.JSONDecoder().raw_decode(output)
    if (not value['running_policy_verified'] or not value['boot_source_matches'] or
            value['running_requested'] != ('Y' if mode == 'experimental' else 'N') or
            value['next_boot'] != (next_mode or mode)):
        raise ValueError('Running/next-boot USB policy verification failed')
    return value


def restore_radio(config, value, baseline):
    if value['radio']['power_save'] == 'on' and baseline['power_save'] == 'off':
        candidate = fixed(value)
        candidate['power_save'] = 'off'
        if candidate != baseline:
            raise ValueError('Reboot changed settings beyond the Wi-Fi power-save default')
        print('Restoring baseline Wi-Fi power saving: off after reboot', flush=True)
        with device(config, 'wifi') as client:
            run(client, 'sudo -n /usr/sbin/iw dev wlan0 set power_save off', display=False)
        value = state(config)
        value['restored_wifi_power_save_from'] = 'on'
    require_state(value, baseline)
    return value


def wait_new_boot(config, previous, baseline, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = state(config)
            if value['health']['boot_id'] != previous:
                return restore_radio(config, value, baseline)
        except (OSError, RuntimeError, paramiko.SSHException):
            pass  # A reboot temporarily removes Wi-Fi; no USB fallback can count as recovery.
        time.sleep(3)
    raise TimeoutError('No verified new battery-powered Wi-Fi boot before deadline')


def cool(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        left = max(0, deadline - time.monotonic())
        print('Cooling/settling:', round(left), 'seconds remaining', flush=True)
        time.sleep(min(60, left))


def initial_cooling(value):
    if not value:
        return 300
    started = datetime.fromisoformat(value)
    if started.tzinfo is None:
        raise ValueError('COOLING_STARTED needs a timezone')
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    if not 0 <= elapsed <= 1800:
        raise ValueError('COOLING_STARTED must be within the last 30 minutes')
    return max(0, 300 - elapsed)


def measurement(capture, name, arguments, filename, seconds):
    output = task(capture, name, arguments)
    match = re.search(r'^Private capture: (.+)$', output, flags=re.M)
    if not match:
        raise ValueError('Measurement did not report its private capture')
    directory = Path(match[1]).resolve()
    return checked_capture(directory, filename, seconds)


def checked_capture(directory, filename, seconds):
    directory.relative_to((LOCAL / 'diagnostics').resolve())
    records = [json.loads(line) for line in (directory / filename).read_text().splitlines()]
    if not records or records[-1].get('event') != 'complete' or not records[-1].get('passed'):
        raise ValueError('Incomplete measurement; preserve it but do not compare')
    ready = [row for row in records if row.get('event') == 'ready']
    duration = records[-1]['duration_seconds']
    if len(ready) != 1 or ready[0].get('seconds') != seconds or not seconds - 1 <= duration <= seconds + 10:
        raise ValueError('Measurement duration does not match the comparison protocol')
    return dict(capture=str(directory), summary=records[-1])


def resume_report(capture, retry_incomplete=False):
    report = json.loads((capture / 'comparison.json').read_text())
    original = json.dumps(report, indent=2) + '\n'
    phases = report['phases']
    if retry_incomplete:
        if (report['passed'] or not 2 <= len(phases) <= 3 or phases[-1]['passed'] or
                any(not phase['passed'] for phase in phases[:-1])):
            raise ValueError('Retry requires exactly one incomplete final phase after completed phases')
        discarded = phases.pop()
        report.setdefault('discarded_phases', []).append(dict(
            reason='Explicit retry: exclude incomplete phase and restart it after settling',
            phase=discarded, discarded_at=datetime.now(timezone.utc).isoformat()))
    if (report['passed'] or not 1 <= len(phases) <= 2 or
            [phase['mode'] for phase in phases] != ['experimental', 'stock'][:len(phases)] or
            any(not phase['passed'] for phase in phases)):
        raise ValueError('Resume requires only completed phases at an interrupted phase boundary')
    baseline = fixed(report['baseline'])
    for phase in phases:
        require_state(phase['before'], baseline, phase['boot_id'])
        require_state(phase['after'], baseline, phase['boot_id'], phase['before']['radio_events'])
        for kind, filename, seconds in (('idle', 'idle-sample.jsonl', 300), ('profile', 'power-profile.jsonl', 120)):
            saved = phase[kind]
            if checked_capture(Path(saved['capture']).resolve(), filename, seconds) != saved:
                raise ValueError('Completed capture changed since phase acceptance')
    rows = [json.loads(line) for line in (Path(phases[-1]['profile']['capture']) / 'power-profile.jsonl').read_text().splitlines()]
    started = datetime.fromisoformat(next(row['utc'] for row in rows if row.get('event') == 'ready'))
    if not 0 <= (datetime.now(timezone.utc) - started).total_seconds() <= 1800:
        raise ValueError('Resume is limited to thirty minutes after the last profile started')
    # Preserve the exact pre-resume record; logs also get distinct attempt names.
    name = datetime.now(timezone.utc).strftime('comparison-before-resume-%Y%m%dT%H%M%S.%fZ.json')
    (capture / name).write_text(original)
    report.setdefault('resumes', []).append(datetime.now(timezone.utc).isoformat())
    return report


def main():
    os.umask(0o077)
    config = load_env()
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    with (LOCAL / 'usb-idle-comparison.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        resume = os.environ.get('NEO_COMPARISON_RESUME', '')
        capture = Path(resume).resolve() if resume else evidence_directory()
        capture.relative_to((LOCAL / 'diagnostics').resolve())
        retry = os.environ.get('NEO_COMPARISON_RETRY_INCOMPLETE', '0')
        if retry not in ('0', '1') or (retry == '1' and not resume):
            raise ValueError('RETRY_INCOMPLETE=1 requires RESUME; otherwise leave it at 0')
        report = resume_report(capture, retry == '1') if resume else dict(
            passed=False, phases=[], protocol='experimental-stock-experimental; idle300/profile120; settle300')
        print('Private comparison:', capture, flush=True)
        try:
            first = state(config)
            baseline = fixed(report['baseline']) if resume else fixed(first)
            completed = len(report['phases'])
            if resume:
                previous_boot = report['phases'][-1]['boot_id']
                if first['health']['boot_id'] != previous_boot:
                    first = restore_radio(config, first, baseline)
                require_state(first, baseline)
            if (first['firmware_sha256'] != lock['radio']['firmware']['sha256'] or
                    first['kernel'] != lock['linux']['tag'][1:] + lock['linux']['localversion'] or
                    baseline['settings'] != dict(online_cpus='0-3', brightness=1, bl_power=0, governor='schedutil') or
                    baseline['power_save'] != 'off' or
                    baseline['capabilities']['schedutil_rate_limit_us'] != '366' or
                    baseline['capabilities']['cpufreq']['scaling_min_freq'] != '120000' or
                    baseline['capabilities']['cpufreq']['scaling_max_freq'] != '1008000'):
                raise ValueError('Expected diagnostic firmware/kernel/power settings are not active')
            if not resume:
                report['baseline'] = first
            boot = first['health']['boot_id']
            previous_mode = report['phases'][-1]['mode'] if completed else None
            for index in range(completed, 3):
                mode = ('experimental', 'stock', 'experimental')[index]
                name = str(index + 1) + '-' + mode
                fresh = None
                already_rebooted = bool(resume and index == completed and boot != previous_boot)
                if index and not already_rebooted:
                    policy(capture, name + '-select', previous_mode, mode)
                    task(capture, name + '-reboot', ['device:reboot', 'ROUTE=wifi'])
                    fresh = wait_new_boot(config, boot, baseline)
                    boot = fresh['health']['boot_id']
                phase = dict(mode=mode, boot_id=boot, passed=False)
                if fresh is not None or already_rebooted:
                    phase['boot_setup'] = fresh if fresh is not None else first
                report['phases'].append(phase)
                phase['policy'] = policy(capture, name + '-policy', mode)
                cool(initial_cooling(os.environ.get('NEO_COOLING_STARTED', '')) if index == 0 else 300)
                phase['before'] = state(config)
                require_state(phase['before'], baseline, boot)
                events = phase['before']['radio_events']
                (capture / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
                phase['idle'] = measurement(capture, name + '-idle',
                    ['device:idle-sample', 'ROUTE=wifi', 'SECONDS=300', 'BACKLIGHT=keep'], 'idle-sample.jsonl', 300)
                require_state(state(config), baseline, boot, events)
                phase['profile'] = measurement(capture, name + '-profile',
                    ['device:power-profile', 'ROUTE=wifi', 'SECONDS=120'], 'power-profile.jsonl', 120)
                phase['after'] = state(config)
                require_state(phase['after'], baseline, boot, events)
                phase['passed'] = True
                previous_mode = mode
                (capture / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
                print('Phase complete:', name, flush=True)
            report['passed'] = True
        finally:
            (capture / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
        print('Comparison complete; experimental policy is active. Telemetry is not calibrated.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, paramiko.SSHException) as error:
        print('Comparison stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
