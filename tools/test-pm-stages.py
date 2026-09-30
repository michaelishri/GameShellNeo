#!/usr/bin/env python3
"""Inspect PM or exercise only the freezer/devices debug stages; never real sleep."""
import argparse
from contextlib import contextmanager, nullcontext
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

POWER = Path('/sys/power')
BOOT = Path('/proc/sys/kernel/random/boot_id')
STATE = Path('/run/gameshellneo-pm-test.json')
RESULTS = Path('/var/lib/gameshellneo/pm-tests')
STAGES = ('freezer', 'devices')
MASKS = ('sleep.target', 'suspend.target', 'hibernate.target',
         'hybrid-sleep.target', 'suspend-then-hibernate.target')
SERVICES = ('gameshellneo-usb', 'gameshellneo-battery', 'gameshellneo-ready',
            'ssh', 'systemd-networkd', 'wpa_supplicant@wlan0', 'getty@tty1')
FAULTS = ('WARNING:', 'Oops:', 'Kernel panic', 'Firmware has halted or crashed',
          'Runtime PM usage count underflow', 'timed out', 'failed to suspend',
          'failed to resume', 'error -110', 'Failed to set pm_flags',
          'Failed to probe device on resume', 'Failed to remove device on suspend',
          'error while changing bus sleep state', 'HT Avail request error',
          'HT Avail read error', 'HT Avail timeout', 'ChipClkCSR access:',
          'sunxi-musb does not have ULPI bus control register')


def read(path):
    return Path(path).read_text().strip()


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=20).strip()


def selected(text):
    values = re.findall(r'\[([a-z0-9]+)\]', text)
    if len(values) != 1:
        raise ValueError('Expected exactly one selected PM option')
    return values[0]


def save(path, data):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(data, output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def result_dir(run_id):
    if not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise ValueError('RUN must be the 32-character lowercase hex capture ID')
    return RESULTS / run_id


def restore():
    if not STATE.exists():
        return
    saved = json.loads(read(STATE))
    if (saved.get('boot_id') != read(BOOT) or saved.get('pm_test') != 'none' or
            saved.get('pm_async') not in ('0', '1')):
        raise ValueError('Invalid PM restoration ownership; record retained')
    (POWER / 'pm_test').write_text('none\n')
    (POWER / 'pm_async').write_text(saved['pm_async'] + '\n')
    if selected(read(POWER / 'pm_test')) != 'none' or read(POWER / 'pm_async') != saved['pm_async']:
        raise ValueError('PM restoration readback failed; record retained')
    STATE.unlink()


@contextmanager
def stage_controls(stage):
    if stage not in STAGES:
        raise ValueError('Only freezer and devices are permitted')
    original = dict(boot_id=read(BOOT), pm_test=selected(read(POWER / 'pm_test')),
                    pm_async=read(POWER / 'pm_async'))
    if original['pm_test'] != 'none' or original['pm_async'] not in ('0', '1'):
        raise ValueError('Unexpected initial PM debug policy')
    with STATE.open('x') as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(original, output)
        output.flush()
        os.fsync(output.fileno())
    try:
        (POWER / 'pm_async').write_text('0\n')
        (POWER / 'pm_test').write_text(stage + '\n')
        yield
    finally:
        restore()


def enter_stage(stage):
    if (stage not in STAGES or selected(read(POWER / 'pm_test')) != stage or
            read(POWER / 'pm_async') != '0' or
            read('/sys/module/suspend/parameters/pm_test_delay') != '5'):
        raise ValueError('Refusing entry: debug stage/readback/delay guard failed')
    # pm_test stops before actual s2idle. Never accept "none" or write "mem".
    (POWER / 'state').write_text('freeze\n')


def snapshot():
    def optional(path):
        return read(path) if Path(path).exists() else None

    rsb = Path('/sys/bus/platform/devices/1f03400.rsb/power')
    links = {}
    for link in sorted([*rsb.parent.glob('supplier:*'), *rsb.parent.glob('consumer:*')]):
        links[link.name] = {name: optional(link / name) for name in ('status', 'runtime_pm', 'sync_state_only')}
        for role in ('supplier', 'consumer'):
            target = (link / role).resolve()
            links[link.name][role] = dict(path=str(target), power={
                name: optional(target / 'power' / name)
                for name in ('control', 'runtime_status', 'runtime_usage', 'runtime_enabled')})
    image = json.loads(read('/etc/gameshellneo/image.json'))
    services = {unit: dict(line.split('=', 1) for line in command(
        'systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'NRestarts').splitlines())
        for unit in SERVICES}
    battery = json.loads(read('/run/gameshellneo/battery.json'))
    journal = command('journalctl', '-b', '-k', '--no-pager', '-o', 'short-monotonic')
    config = gzip.decompress(Path('/proc/config.gz').read_bytes()).decode()
    return dict(boot_id=read(BOOT), image=image, kernel=os.uname().release,
                monotonic_seconds=time.monotonic(), taint=read('/proc/sys/kernel/tainted'),
                pm={name: optional(POWER / name) for name in ('state', 'mem_sleep', 'pm_test', 'pm_async')},
                pm_test_delay=optional('/sys/module/suspend/parameters/pm_test_delay'),
                usb_experiments={name: optional('/sys/module/axp20x_usb_power/parameters/' + name)
                                 for name in ('gameshellneo_slow_poll', 'gameshellneo_diagnostics')},
                sdio_retains_power=Path('/sys/firmware/devicetree/base/soc/mmc@1c10000/keep-power-in-suspend').is_file(),
                keypad_retains_supply=Path('/sys/firmware/devicetree/base/regulator-keypad/regulator-always-on').is_file(),
                stats={p.name: read(p) for p in (POWER / 'suspend_stats').glob('*') if p.is_file()},
                rsb={p.name: read(p) for p in rsb.glob('*') if p.is_file()},
                rsb_links=links,
                wakeup_sources=optional('/sys/kernel/debug/wakeup_sources'),
                kernel_config=config, cmdline=read('/proc/cmdline'),
                masks={name: os.path.realpath('/etc/systemd/system/' + name) for name in MASKS},
                sleep_config=read('/etc/systemd/sleep.conf.d/50-gameshellneo.conf'),
                services=services, battery=battery,
                battery_age_seconds=time.monotonic() - battery['monotonic_seconds'],
                external_power={name: {field: read('/sys/class/power_supply/' + name + '/' + field)
                                       for field in ('type', 'present', 'online')}
                                for name in ('axp20x-usb', 'axp22x-ac')},
                failed_units=command('systemctl', '--failed', '--no-legend', '--plain', '--no-pager'),
                usb=[read(p) for p in Path('/sys/class/udc').glob('*/state')],
                wifi=command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'status'),
                wifi_config_sha256=hashlib.sha256(Path('/etc/wpa_supplicant/wpa_supplicant-wlan0.conf').read_bytes()).hexdigest(),
                wifi_power_save=command('/usr/sbin/iw', 'dev', 'wlan0', 'get', 'power_save'),
                charger={n: read('/sys/class/power_supply/axp20x-battery/' + n)
                         for n in ('constant_charge_current', 'constant_charge_current_max', 'voltage_max')},
                cpu_policy={n: read('/sys/devices/system/cpu/cpufreq/policy0/' + n)
                            for n in ('scaling_governor', 'scaling_min_freq', 'scaling_max_freq')},
                inputs=sorted(read(p) for p in Path('/sys/class/input').glob('event*/device/name')),
                backlight={n: read('/sys/class/backlight/ocp8178/' + n) for n in ('brightness', 'bl_power')},
                firmware_sha256=hashlib.sha256(Path('/usr/lib/firmware/brcm/brcmfmac43430a0-sdio.bin').read_bytes()).hexdigest(),
                nvram_sha256=hashlib.sha256(Path('/usr/lib/firmware/brcm/brcmfmac43430a0-sdio.clockwork,clockworkpi-cpi3.txt').read_bytes()).hexdigest(),
                journal=journal)


def validate(snapshot, lock):
    experiments = lock.get('experiments', {})
    retention = experiments.get('keypad_supply_retention', False)
    if (experiments not in ({'suspend_diagnostics': True},
                           {'suspend_diagnostics': True, 'keypad_supply_retention': True}) or
            any(type(value) is not bool for value in experiments.values())):
        raise ValueError('A dedicated suspend diagnostic source lock is required')
    s = snapshot
    if s['keypad_retains_supply'] is not retention:
        raise ValueError('Live keypad supply policy differs from the image experiment')
    if (s['image']['board'] != 'gameshellneo-cpi31' or s['image']['version'] != lock['image_version'] or
            s['image']['sources'].get('experiments') != experiments or
            s['kernel'] != lock['linux']['tag'][1:] + lock['linux']['localversion'] or
            s['firmware_sha256'] != lock['radio']['firmware']['sha256'] or
            s['nvram_sha256'] != lock['radio']['nvram']['sha256']):
        raise ValueError('Board/image/kernel/radio mismatch')
    for option in ('SUSPEND', 'PM_SLEEP_DEBUG', 'PM_ADVANCED_DEBUG'):
        if f'CONFIG_{option}=y\n' not in s['kernel_config']:
            raise ValueError('Missing kernel PM debug support')
    for option in ('HIBERNATION', 'PM_AUTOSLEEP', 'PM_WAKELOCKS', 'ARM_PSCI_CPUIDLE', 'PM_TEST_SUSPEND'):
        if f'CONFIG_{option}=y\n' in s['kernel_config']:
            raise ValueError('Unexpected deep/automatic/test-boot power support')
    identities = re.findall(r'brcmf_c_preinit_dcmds: (Firmware: .+)', s['journal'])
    if (not identities or any(v != lock['radio']['firmware']['runtime_identity'] for v in identities) or
            any(x in s['journal'] for x in FAULTS)):
        raise ValueError('Unexpected firmware identity or kernel fault evidence')
    if (selected(s['pm']['pm_test'] or '') != 'none' or selected(s['pm']['mem_sleep'] or '') != 's2idle' or
            'freeze' not in (s['pm']['state'] or '').split() or s['pm_test_delay'] != '5' or
            any(s['masks'][n] != '/dev/null' for n in MASKS) or 'AllowSuspend=no' not in s['sleep_config'] or
            any(value != 'N' for value in s['usb_experiments'].values()) or len(s['usb_experiments']) != 2 or
            s['sdio_retains_power'] is not True or
            'gameshellneo_slow_poll=' in s['cmdline'] or 'gameshellneo_diagnostics=' in s['cmdline']):
        raise ValueError('PM stage isolation or ordinary sleep policy failed')
    b = s['battery']
    # Battery status describes current flow, not whether the PMIC has USB input.
    # Require a fresh USB supply observation as well as the configured UDC below.
    usb_supply = s.get('external_power', {}).get('axp20x-usb', {})
    health = dict(
        kernel_taint=s['taint'] == '0', failed_units=not s['failed_units'],
        usb_configured=s['usb'] == ['configured'],
        wifi_connected='wpa_state=COMPLETED' in s['wifi'].splitlines(),
        battery_monitoring=b.get('monitoring') == 'valid',
        battery_freshness=0 <= s['battery_age_seconds'] <= 25,
        usb_external_power=usb_supply == {'type': 'USB', 'present': '1', 'online': '1'},
        battery_status=b.get('status') in ('Charging', 'Discharging', 'Full', 'Not charging'),
        battery_capacity=b.get('capacity_percent', 0) > 20,
        services=all(v == {'ActiveState': 'active', 'NRestarts': '0'} for v in s['services'].values()))
    failed = [name for name, passed in health.items() if not passed]
    if failed:
        raise ValueError('Device must be healthy, USB-powered and connected to Wi-Fi; failed: ' + ', '.join(failed))


def check_result(before, after, stage, memory_ok):
    if stage not in STAGES or before['boot_id'] != after['boot_id'] or not memory_ok:
        raise ValueError('Stage, boot identity or process memory changed')
    if not after['journal'].startswith(before['journal']):
        raise ValueError('Kernel evidence lost or rotated during stage')
    delta = after['journal'][len(before['journal']):]
    if delta.count('suspend debug: Waiting for 5 second(s).') != 1 or any(x in delta for x in FAULTS):
        raise ValueError('Expected bounded debug wait missing or new kernel fault')
    if int(after['stats']['success']) - int(before['stats']['success']) != 1:
        raise ValueError('Expected exactly one completed PM debug cycle')
    for name in before['stats']:
        if name == 'fail' or name.startswith('failed_'):
            if before['stats'][name] != after['stats'].get(name):
                raise ValueError('Suspend failure statistics changed: ' + name)
    if before['backlight'] != after['backlight'] or before['inputs'] != after['inputs']:
        raise ValueError('Display/input state did not return')
    if before['pm']['pm_async'] != after['pm']['pm_async']:
        raise ValueError('Asynchronous PM setting did not return')
    for name in ('wifi_config_sha256', 'wifi_power_save', 'charger', 'cpu_policy'):
        if before[name] != after[name]:
            raise ValueError('Configuration changed across PM stage: ' + name)
    def network(snapshot):
        fields = dict(line.split('=', 1) for line in snapshot['wifi'].splitlines() if '=' in line)
        return fields.get('ssid'), fields.get('id')
    if network(before) != network(after):
        raise ValueError('Wi-Fi returned to a different network profile')
    return delta


def test_stage(lock, stage, run_id, keypad_trace=False, keypad_persist=None, keypad_input=False, keypad_audio=False,
               keypad_quirk=None):
    if stage not in STAGES:
        raise ValueError('Only freezer and devices are permitted')
    if keypad_trace and stage != 'devices':
        raise ValueError('Keypad tracing is restricted to the devices debug stage')
    if keypad_persist is not None and (keypad_persist not in ('0', '1') or
                                      stage != 'devices' or not keypad_trace):
        raise ValueError('Persistence comparison requires a traced devices debug stage')
    if keypad_input and (stage != 'devices' or not keypad_trace or keypad_persist is not None or
                         lock.get('experiments', {}).get('keypad_supply_retention') is not True):
        raise ValueError('Physical input requires traced devices with retained supply and unchanged persistence')
    if keypad_audio and (not keypad_input or lock.get('features', {}).get('speaker_audio') is not True):
        raise ValueError('Speaker cues require physical input on the identified audio image')
    if keypad_quirk is not None and (keypad_quirk not in ('baseline', 'old-scheme', 'fast-recovery') or
            stage != 'devices' or not keypad_trace or keypad_persist is not None or
            lock.get('experiments', {}).get('keypad_supply_retention') is not True):
        raise ValueError('Port quirks require traced devices with retained supply and unchanged persistence')
    directory = result_dir(run_id)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = dict(run_id=run_id, stage=stage, passed=False, event='started',
                  limits='PM debug stage only; no actual sleep, energy, wake or DRAM-retention proof.')
    try:
        before = snapshot()
        record['before'] = before
        validate(before, lock)
        observers = ('rsb-comparison', 'idle-sample', 'power-profile', 'governor-profile',
                     'governor-comparison', 'usb-detection', 'usb-reconnects', 'usb-diagnostics',
                     'scan-test', 'firmware-trial', 'stability-test', 'backlight-test', 'keypad-capture', 'audio-test')
        if command('systemctl', 'list-units', '--all', '--plain', '--no-legend',
                   '--state=active,activating,deactivating',
                   *['gameshellneo-' + n + '.service' for n in observers]):
            raise ValueError('Stop concurrent diagnostic observers')
        save(directory / 'started.json', record)
        memory = bytearray(os.urandom(4 * 1024 * 1024))
        digest = hashlib.sha256(memory).hexdigest()
        from keypad_pm import observe, persistence, wait_ready, keypad_identity, port_quirks
        record['keypad'] = {}
        record['persistence'] = {}
        record['port_quirks'] = {}
        with (persistence(record['persistence'], keypad_persist)
              if keypad_persist is not None else nullcontext()), \
             (port_quirks(record['port_quirks'], keypad_quirk)
              if keypad_quirk is not None else nullcontext()):
            with observe(record['keypad'], tracing=keypad_trace) as original_fd:
                from keypad_input import capture
                from speaker_audio import session as speaker_session, idle as speaker_idle
                record['physical_input'] = {}
                record['speaker_audio'] = {}
                if keypad_input:
                    keypad_identity(record['keypad']['before'])
                with (speaker_session(record['speaker_audio']) if keypad_audio else nullcontext()) as cue, \
                     (capture(record['physical_input'], original_fd, cue) if keypad_input else nullcontext()) as inputs:
                    if inputs:
                        inputs.before_stage()
                        record['entry_preflight'] = snapshot()
                        validate(record['entry_preflight'], lock)
                        if record['entry_preflight']['boot_id'] != before['boot_id']:
                            raise ValueError('Boot changed while waiting for physical input')
                        save(directory / 'started.json', record)
                    started = time.monotonic()
                    with stage_controls(stage):
                        os.sync()
                        if inputs:
                            inputs.verify_hold('immediately-before-entry')
                        if cue:
                            record['speaker_audio']['idle_before_pm'] = speaker_idle()
                        enter_stage(stage)
                    resumed = time.monotonic()
                    record['stage_seconds'] = resumed - started
                    record['process_memory_ok'] = hashlib.sha256(memory).hexdigest() == digest
                    if keypad_trace:
                        record['keypad_ready_after_stage'] = {}
                        wait_ready(record['keypad_ready_after_stage'], resumed,
                                   keypad_identity(record['keypad']['before']))
                    if inputs:
                        inputs.after_stage()
                    # Physical input runs include human interaction and are not latency comparisons.
                    time.sleep(max(0, 30 - (time.monotonic() - resumed)))
        after = snapshot()
        record['after'] = after
        validate(after, lock)
        record['journal_delta'] = check_result(before, after, stage, record['process_memory_ok'])
        record.update(passed=True, event='complete')
    except BaseException as error:
        record.update(event='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        save(directory / 'result.json', record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--restore', action='store_true')
    mode.add_argument('--collect', metavar='RUN')
    mode.add_argument('--stage', choices=STAGES)
    parser.add_argument('--run-id')
    parser.add_argument('--lock', type=Path)
    parser.add_argument('--keypad-trace', action='store_true')
    parser.add_argument('--keypad-persist', choices=('0', '1'))
    parser.add_argument('--keypad-input', action='store_true')
    parser.add_argument('--keypad-audio', action='store_true')
    parser.add_argument('--keypad-quirk', choices=('baseline', 'old-scheme', 'fast-recovery'))
    args = parser.parse_args()
    os.umask(0o077)
    if args.restore:
        from keypad_pm import restore_trace, restore_persistence, restore_port_quirks
        from keypad_input import restore_console
        from speaker_audio import restore as restore_audio
        failure = None
        for operation in (restore_trace, restore_persistence, restore_port_quirks, restore_audio, restore_console, restore):
            try:
                operation()
            except BaseException as error:
                failure = failure or error
        if failure:
            raise failure
    elif args.inspect:
        print(json.dumps(snapshot()))
    elif args.collect:
        directory = result_dir(args.collect)
        result = directory / 'result.json'
        if not result.exists():
            result = directory / 'started.json'
        print(read(result) if result.exists() else json.dumps(dict(event='pending', run_id=args.collect)))
    else:
        if not args.run_id or not args.lock:
            parser.error('--stage requires --run-id and --lock')
        def interrupted(signum, _frame):
            raise SystemExit(128 + signum)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, interrupted)
        test_stage(json.loads(read(args.lock)), args.stage, args.run_id,
                   args.keypad_trace, args.keypad_persist, args.keypad_input, args.keypad_audio, args.keypad_quirk)


if __name__ == '__main__':
    main()
