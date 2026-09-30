"""Scoped EAPOL/PM metadata and allowlisted supplicant diagnostics; no PM entry."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import time

TRACE = Path('/sys/kernel/tracing')
OWNED = Path('/run/gameshellneo-wifi-trace.json')
BOOT = Path('/proc/sys/kernel/random/boot_id')
INSTANCE = 'gameshellneo-wifi'
UNIT = 'wpa_supplicant@wlan0.service'
EXPECTED_ARGS = ['/usr/sbin/wpa_supplicant',
                 '-c/etc/wpa_supplicant/wpa_supplicant-wlan0.conf', '-iwlan0']
LEVELS = ('EXCESSIVE', 'MSGDUMP', 'DEBUG', 'INFO', 'WARNING', 'ERROR')
EVENTS = ('net/net_dev_start_xmit', 'net/netif_rx_entry', 'power/suspend_resume',
          'power/device_pm_callback_start', 'power/device_pm_callback_end')
LIMIT = 4000


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=15).strip()


def identity():
    pid = command('systemctl', 'show', UNIT, '-p', 'MainPID', '--value')
    if not re.fullmatch('[1-9][0-9]*', pid):
        raise ValueError('No running supplicant')
    process = Path('/proc') / pid
    args = process.joinpath('cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
    # This exact installed service has neither -K (key display) nor -u (D-Bus
    # debug setters). LOG_LEVEL itself cannot enable key display. Fail closed
    # for a different launch configuration instead of publishing its arguments.
    if args != EXPECTED_ARGS:
        raise ValueError('Unexpected supplicant arguments; key-logging policy unqualified')
    start_ticks = process.joinpath('stat').read_text().rsplit(')', 1)[1].split()[19]
    return dict(pid=pid, start_ticks=start_ticks)


def log_level():
    text = command('wpa_cli', '-i', 'wlan0', 'log_level')
    match = re.fullmatch(r'Current level: (\w+)\nTimestamp: ([01])', text)
    if not match or match[1] not in LEVELS:
        raise ValueError('Unexpected supplicant logging state')
    return dict(level=match[1], timestamp=match[2])


def set_level(value):
    if command('wpa_cli', '-i', 'wlan0', 'log_level', value['level'], value['timestamp']) != 'OK':
        raise ValueError('Supplicant rejected logging change')
    if log_level() != value:
        raise ValueError('Supplicant logging readback differs')


def journal_cursor():
    rows = command('journalctl', '-b', '-u', UNIT, '-n', '1', '-o', 'json', '--no-pager')
    data = json.loads(rows)
    cursor = data.get('__CURSOR')
    if not isinstance(cursor, str) or not cursor or '\n' in cursor:
        raise ValueError('Missing supplicant journal cursor')
    return cursor


def summarize_journal(text):
    """Never copy free-form messages, addresses, SSIDs, hex dumps or keys."""
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if len(rows) > LIMIT:
        raise ValueError('Supplicant journal exceeded its bounded capture')
    events = []
    for row in rows:
        message = row.get('MESSAGE', '')
        if not isinstance(message, str):
            continue
        event = None
        match = re.search(r'\bState: ([A-Z0-9_]+) -> ([A-Z0-9_]+)(?:$|\s)', message)
        if match:
            states = {'DISCONNECTED', 'INTERFACE_DISABLED', 'INACTIVE', 'SCANNING',
                      'AUTHENTICATING', 'ASSOCIATING', 'ASSOCIATED', '4WAY_HANDSHAKE',
                      'GROUP_HANDSHAKE', 'COMPLETED'}
            if match[1] in states and match[2] in states:
                event = dict(kind='state', before=match[1], after=match[2])
        elif re.search(r'RX message [1-4] of 4-Way Handshake', message):
            event = dict(kind='handshake_rx', message=int(re.search(r'RX message ([1-4])', message)[1]))
        elif re.search(r'Sending EAPOL-Key [1-4]/4', message):
            event = dict(kind='handshake_tx', message=int(re.search(r'EAPOL-Key ([1-4])', message)[1]))
        elif 'RX EAPOL from ' in message:
            event = dict(kind='eapol_rx_userspace')
        elif 'Key negotiation completed' in message:
            event = dict(kind='key_negotiation_completed')
        elif 'Authentication with ' in message and ' timed out' in message:
            event = dict(kind='authentication_timeout')
        elif 'Setting authentication timeout:' in message:
            match = re.search(r'timeout: (\d+) sec (\d+) usec', message)
            if match:
                event = dict(kind='authentication_timer', seconds=int(match[1]), microseconds=int(match[2]))
        elif 'Cancelling authentication timeout' in message:
            event = dict(kind='authentication_timer_cancelled')
        else:
            for marker, kind in (('CTRL-EVENT-ASSOC-REJECT', 'association_reject'),
                                 ('CTRL-EVENT-DISCONNECTED', 'disconnected'),
                                 ('CTRL-EVENT-CONNECTED', 'connected'),
                                 ('CTRL-EVENT-SSID-TEMP-DISABLED', 'backoff')):
                if marker in message:
                    event = dict(kind=kind)
                    for field in ('status_code', 'reason', 'auth_failures', 'duration'):
                        match = re.search(r'\b' + field + r'=(\d+)\b', message)
                        if match:
                            event[field] = int(match[1])
                    break
        if event:
            stamp = row.get('__MONOTONIC_TIMESTAMP')
            if not isinstance(stamp, str) or not stamp.isdecimal():
                raise ValueError('Missing journal monotonic timestamp')
            events.append(dict(monotonic_seconds=int(stamp) / 1e6, **event))
    return dict(journal_rows=len(rows), events=events)


def trace_lost(stats):
    if not stats:
        return True
    for value in stats.values():
        for field in ('overrun', 'commit overrun', 'dropped events'):
            match = re.search(r'^' + field + r':\s*(\d+)\s*$', value, re.M)
            if not match or int(match[1]):
                return True
    return False


def restore():
    if not OWNED.exists():
        return
    saved = json.loads(OWNED.read_text())
    original = saved.get('logging', {})
    if (saved.get('boot_id') != BOOT.read_text().strip() or
            original.get('level') not in LEVELS or original.get('timestamp') not in ('0', '1')):
        raise ValueError('Invalid Wi-Fi trace ownership; record retained')
    failure = None
    instance = TRACE / 'instances' / INSTANCE
    try:
        if instance.exists():
            (instance / 'tracing_on').write_text('0\n')
            (instance / 'events/enable').write_text('0\n')
            instance.rmdir()
    except BaseException as error:
        failure = error
    try:
        if identity() != saved.get('process'):
            raise ValueError('Supplicant changed; logging restoration ownership lost')
        if log_level() not in (original, dict(level='DEBUG', timestamp=original['timestamp'])):
            raise ValueError('Logging changed outside recorder; ownership retained')
        set_level(original)
    except BaseException as error:
        failure = failure or error
    if failure:
        raise failure
    OWNED.unlink()


@contextmanager
def capture(record):
    instance = TRACE / 'instances' / INSTANCE
    if OWNED.exists() or instance.exists():
        raise ValueError('Existing Wi-Fi recorder; restore before retrying')
    for name in EVENTS:
        if not (TRACE / 'events' / name / 'enable').is_file():
            raise ValueError('Required Wi-Fi/PM trace event unavailable')
        if name.startswith('net/'):
            text = (TRACE / 'events' / name / 'format').read_text()
            if not all(field in text for field in ('char[] name;', 'u16 protocol;', 'unsigned int len;')):
                raise ValueError('Unexpected network trace format')
    original = log_level()
    if original['level'] not in ('INFO', 'WARNING', 'ERROR'):
        raise ValueError('Existing detailed logging; refuse concurrent debugging')
    saved = dict(boot_id=BOOT.read_text().strip(), process=identity(), logging=original)
    cursor = journal_cursor()
    with OWNED.open('x') as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(saved, output)
        output.flush()
        os.fsync(output.fileno())
    record.update(logging_before=original, buffer_kb_per_cpu=256,
                  key_logging_startup_checked=True, started_monotonic=time.monotonic())
    try:
        instance.mkdir()
        (instance / 'tracing_on').write_text('0\n')
        (instance / 'current_tracer').write_text('nop\n')
        (instance / 'buffer_size_kb').write_text('256\n')
        (instance / 'trace_clock').write_text('mono\n')
        for name in EVENTS:
            event = instance / 'events' / name
            if name.startswith('net/'):
                (event / 'filter').write_text('name == "wlan0" && protocol == 34958\n')
            (event / 'enable').write_text('1\n')
        set_level(dict(level='DEBUG', timestamp=original['timestamp']))
        (instance / 'tracing_on').write_text('1\n')
        yield
    finally:
        try:
            if instance.exists():
                (instance / 'tracing_on').write_text('0\n')
                record['trace'] = (instance / 'trace').read_text()
                record['trace_stats'] = {p.parent.name: p.read_text()
                                         for p in (instance / 'per_cpu').glob('cpu*/stats')}
                record['trace_lost'] = trace_lost(record['trace_stats'])
                record['eapol_tx'] = record['trace'].count('net_dev_start_xmit:')
                record['eapol_rx'] = record['trace'].count('netif_rx_entry:')
            text = command('journalctl', '-b', '-u', UNIT, '--after-cursor=' + cursor,
                           '-n', str(LIMIT + 1), '-o', 'json', '--no-pager')
            record['supplicant'] = summarize_journal(text)
        finally:
            restore()
            record['restored'] = not OWNED.exists() and not instance.exists()
            record['finished_monotonic'] = time.monotonic()
        if record.get('trace_lost') is not False:
            raise ValueError('Incomplete Wi-Fi metadata trace')


def smoke(record):
    """One awake software reassociation; no profile change or PM entry."""
    if [p.read_text().strip() for p in Path('/sys/class/udc').glob('*/state')] != ['configured']:
        raise ValueError('Configured USB is required for the awake Wi-Fi check')
    if 'wpa_state=COMPLETED' not in command('wpa_cli', '-i', 'wlan0', 'status').splitlines():
        raise ValueError('The awake check requires connected Wi-Fi')
    with capture(record):
        if command('wpa_cli', '-i', 'wlan0', 'reassociate') != 'OK':
            raise ValueError('Awake reassociation was rejected')
        started = time.monotonic()
        # Allow the accepted reassociation request to leave its old state before
        # judging completion. This duration is not association latency.
        time.sleep(2)
        while 'wpa_state=COMPLETED' not in command('wpa_cli', '-i', 'wlan0', 'status').splitlines():
            if time.monotonic() - started >= 30:
                raise TimeoutError('Awake Wi-Fi did not reconnect within 30 seconds')
            time.sleep(1)
        time.sleep(1)
    if not record['eapol_rx'] or not record['eapol_tx']:
        raise ValueError('Awake check did not capture both directions of EAPOL')
    if not any(e['kind'] == 'key_negotiation_completed' for e in record['supplicant']['events']):
        raise ValueError('No matching supplicant security completion captured')


if __name__ == '__main__':
    import argparse
    import signal
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--restore', action='store_true')
    mode.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.restore:
        restore()
    else:
        def interrupted(signum, _frame):
            raise SystemExit(128 + signum)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, interrupted)
        result = dict(passed=False, limits='Awake reassociation only; no PM, physical AP loss or energy proof.')
        try:
            smoke(result)
            result['passed'] = True
        finally:
            print(json.dumps(result), flush=True)
