#!/usr/bin/env python3
"""USB-controlled A0 trials with separate binary and runtime-network recovery."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import signal
import secrets
import stat
import subprocess
import tempfile
import time

FIRMWARE = Path('/usr/lib/firmware/brcm/brcmfmac43430a0-sdio.bin')
NVRAM = Path('/usr/lib/firmware/brcm/brcmfmac43430a0-sdio.clockwork,clockworkpi-cpi3.txt')
STATE = Path('/run/gameshellneo-firmware-trial')
INSTALLED_STATE = Path('/run/gameshellneo-wifi-recovery')
WIFI_REQUEST = Path('/run/gameshellneo-firmware-wifi.json')
WIFI_ACK = Path('/run/gameshellneo-firmware-wifi.ack')
WIFI_CONFIG = Path('/etc/wpa_supplicant/wpa_supplicant-wlan0.conf')
ORIGINAL = 'bb2bd00ede1fe04c74d3684e76ef58d9f2acd54d6759894b934bbefb159668e9'
BOARD_DATA = '5f977a2a3916ef795ceb184cf928231d587249606d1750dacecb5f16ed941ae6'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout.strip()


def write(path, data, mode=0o600):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def kernel():
    return command('journalctl', '-b', '-k', '--no-pager', '-o', 'cat')


def identities():
    return [line for line in kernel().splitlines() if 'Firmware: BCM43430/0 ' in line]


def identity():
    versions = identities()
    return versions[-1] if versions else ''


def counts():
    log = kernel()
    return {'firmware_crashes': log.count('brcmf_fw_crashed: Firmware has halted or crashed'),
            'sdio_removals': log.count('mmc1: card 0001 removed')}


def reload(data, mode):
    previous_count = len(identities())
    command('systemctl', 'stop', 'wpa_supplicant@wlan0')
    command('/usr/sbin/modprobe', '-r', 'brcmfmac_wcc', 'brcmfmac')
    write(FIRMWARE, data, mode)
    command('/usr/sbin/modprobe', 'brcmfmac')
    command('systemctl', 'start', 'wpa_supplicant@wlan0')
    return previous_count


def wait_identity(expected, previous_count):
    for _ in range(30):
        versions = identities()
        if len(versions) > previous_count and expected in versions[-1]:
            return versions[-1]
        time.sleep(1)
    raise ValueError('Expected loaded A0 firmware identity was not observed')


def restore():
    record = STATE / 'state.json'
    if not record.exists():
        return
    saved = json.loads(record.read_text())
    original = (STATE / 'original.bin').read_bytes()
    if digest(original) != ORIGINAL or digest(NVRAM.read_bytes()) != BOARD_DATA:
        raise ValueError('Original firmware backup or board data failed verification')
    previous_count = reload(original, saved['mode'])
    value = wait_identity(saved['identity'], previous_count)
    if digest(FIRMWARE.read_bytes()) != ORIGINAL:
        raise ValueError('Firmware restoration readback failed')
    record.unlink()
    (STATE / 'original.bin').unlink()
    STATE.rmdir()
    return value


def emit(event, **values):
    print(json.dumps(dict(event=event, **values)), flush=True)


def wifi_status():
    return dict(line.split('=', 1) for line in
                command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'status').splitlines() if '=' in line)


def wifi_address():
    if wifi_status().get('wpa_state') != 'COMPLETED':
        return None
    interfaces = json.loads(command('/usr/sbin/ip', '-j', '-4', 'address', 'show', 'dev', 'wlan0'))
    addresses = [entry['local'] for interface in interfaces for entry in interface['addr_info']
                 if entry.get('scope') == 'global' and entry.get('family') == 'inet']
    return str(ipaddress.IPv4Address(addresses[0])) if len(addresses) == 1 else None


def acknowledge(token):
    request = json.loads(WIFI_REQUEST.read_text())
    if token != request['token'] or len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('Stale or invalid Wi-Fi verification token')
    write(WIFI_ACK, token.encode())


def wifi_checkpoint(phase, boot, expected_identity):
    started = time.monotonic()
    deadline = started + 60
    address = None
    while time.monotonic() < deadline:
        try:
            address = wifi_address()
        except subprocess.SubprocessError:
            address = None
        if address:
            break
        time.sleep(1)
    if not address:
        raise ValueError('Wi-Fi association/address deadline expired: ' + phase)
    if (Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot or
            expected_identity not in identity()):
        raise ValueError('Boot or firmware identity changed at Wi-Fi checkpoint')
    token = secrets.token_hex(16)
    WIFI_ACK.unlink(missing_ok=True)
    write(WIFI_REQUEST, json.dumps(dict(token=token, phase=phase, boot_id=boot, address=address)).encode())
    try:
        emit('wifi_ready', token=token, phase=phase, boot_id=boot, address=address)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if WIFI_ACK.exists() and WIFI_ACK.read_text() == token:
                if (wifi_address() != address or expected_identity not in identity() or
                        Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot):
                    raise ValueError('Wi-Fi/firmware changed during independent SSH verification')
                emit('wifi_verified', phase=phase, duration_seconds=time.monotonic() - started)
                return
            time.sleep(1)
        raise ValueError('Independent Wi-Fi SSH verification deadline expired: ' + phase)
    finally:
        WIFI_REQUEST.unlink(missing_ok=True)
        WIFI_ACK.unlink(missing_ok=True)


def reconnect(cycle, boot, expected_identity, phase=None):
    if command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'disconnect') != 'OK':
        raise ValueError('Wi-Fi disconnect request was rejected')
    deadline = time.monotonic() + 10
    while wifi_status().get('wpa_state') != 'DISCONNECTED':
        if time.monotonic() >= deadline:
            raise ValueError('Wi-Fi disconnection was not observed')
        time.sleep(0.5)
    emit('wifi_disconnected', cycle=cycle)
    time.sleep(2)
    if command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'reconnect') != 'OK':
        raise ValueError('Wi-Fi reconnect request was rejected')
    wifi_checkpoint(phase or 'candidate_reconnect_' + str(cycle), boot, expected_identity)


def wpa(*args):
    value = command('/usr/sbin/wpa_cli', '-i', 'wlan0', *args)
    if value != 'OK':
        raise ValueError('Wi-Fi control request failed: ' + args[0])


def single_current_network():
    networks = command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'list_networks').splitlines()[1:]
    return (len(networks) == 1 and len(networks[0].split('\t')) == 4 and
            networks[0].split('\t')[3] == '[CURRENT]')


def installed_health(lock, saved):
    """Fail on reloads or faults even if association subsequently recovered."""
    firmware = lock['radio']['firmware']
    expected = firmware['runtime_identity']
    log = kernel()
    prefix = 'brcmf_c_preinit_dcmds: '
    loaded = [line.split(prefix, 1)[1].strip() for line in log.splitlines()
              if prefix + 'Firmware: ' in line]
    faults = {name: log.count(marker) for name, marker in {
        'firmware_crashes': 'brcmf_fw_crashed: Firmware has halted or crashed',
        'sdio_removals': 'mmc1: card 0001 removed',
        'pm_usage_underflows': 'Runtime PM usage count underflow',
    }.items()}
    if loaded != [expected] or any(faults.values()):
        raise ValueError('Installed firmware identity/reload/fault check failed')
    if (Path('/proc/sys/kernel/random/boot_id').read_text().strip() != saved['boot_id'] or
            Path('/proc/sys/kernel/tainted').read_text().strip() != '0' or
            digest(FIRMWARE.read_bytes()) != firmware['sha256'] or
            digest(NVRAM.read_bytes()) != lock['radio']['nvram']['sha256'] or
            digest(WIFI_CONFIG.read_bytes()) != saved['config_sha256'] or
            command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'get', 'disable_scan_offload') != '0'):
        raise ValueError('Installed firmware/board/configuration/boot/scan policy changed')
    udc = list(Path('/sys/class/udc').glob('*/state'))
    if len(udc) != 1 or udc[0].read_text().strip() != 'configured':
        raise ValueError('USB recovery connection must remain configured')
    return dict(identities=loaded, faults=faults)


def restore_installed():
    """Reload the unchanged persistent Wi-Fi config, without reloading firmware."""
    record = INSTALLED_STATE / 'state.json'
    if not record.exists():
        return
    saved = json.loads(record.read_text())
    if (Path('/proc/sys/kernel/random/boot_id').read_text().strip() != saved['boot_id'] or
            digest(WIFI_CONFIG.read_bytes()) != saved['config_sha256']):
        raise ValueError('Recovery boot/configuration changed; retain recovery state')
    wpa('reconfigure')
    wpa('reconnect')
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        fields = wifi_status()
        if (fields.get('wpa_state') == 'COMPLETED' and
                digest(fields.get('ssid', '').encode()) == saved['ssid_sha256'] and
                wifi_address() and single_current_network() and
                command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'get', 'disable_scan_offload') == '0'):
            record.unlink()
            INSTALLED_STATE.rmdir()
            return
        time.sleep(1)
    raise ValueError('Persistent Wi-Fi configuration reloaded, but association did not recover')


def installed_observe(lock, saved, seconds, offline=False):
    started = time.monotonic()
    scanning = 0
    for index in range(seconds // 10 + 1):
        time.sleep(max(0, started + index * 10 - time.monotonic()))
        health = installed_health(lock, saved)
        fields = wifi_status()
        state = fields.get('wpa_state')
        if offline:
            if state not in ('SCANNING', 'DISCONNECTED'):
                raise ValueError('Unavailable-network trial entered unexpected Wi-Fi state')
            scanning += state == 'SCANNING'
        elif (state != 'COMPLETED' or
              digest(fields.get('ssid', '').encode()) != saved['ssid_sha256']):
            raise ValueError('Connected observation lost the original network')
        emit('installed_sample', phase='unavailable_network' if offline else 'connected',
             monotonic_seconds=time.monotonic(), state=state, health=health)
    if offline and not scanning:
        raise ValueError('No scanning state observed for the unavailable test network')
    emit('installed_window_complete', phase='unavailable_network' if offline else 'connected',
         duration_seconds=time.monotonic() - started, scanning_samples=scanning)


def installed_trial(lock, seconds):
    image = json.loads(Path('/etc/gameshellneo/image.json').read_text())
    fields = wifi_status()
    if (image.get('board') != 'gameshellneo-cpi31' or image.get('version') != lock['image_version'] or
            os.uname().release != lock['linux']['tag'][1:] + lock['linux']['localversion'] or
            not single_current_network() or
            fields.get('wpa_state') != 'COMPLETED' or not fields.get('ssid') or
            not wifi_address() or STATE.exists()):
        raise ValueError('Installed-image/connected-single-network/recovery-state preflight failed')
    saved = dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                 config_sha256=digest(WIFI_CONFIG.read_bytes()),
                 ssid_sha256=digest(fields['ssid'].encode()))
    expected = lock['radio']['firmware']['runtime_identity']
    emit('installed_preflight', boot_id=saved['boot_id'], health=installed_health(lock, saved))
    INSTALLED_STATE.mkdir(mode=0o700)
    write(INSTALLED_STATE / 'state.json', json.dumps(saved).encode())
    try:
        wifi_checkpoint('installed_initial', saved['boot_id'], expected)
        for cycle in range(1, 5):
            reconnect(cycle, saved['boot_id'], expected, 'installed_reconnect_' + str(cycle))
            installed_health(lock, saved)
        number = command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'add_network')
        if not number.isdecimal():
            raise ValueError('Could not create a temporary network profile')
        # Random, credential-free profile exists only in supplicant memory. Never SAVE_CONFIG.
        ssid = 'Neo-test-' + secrets.token_hex(10)
        wpa('set_network', number, 'ssid', '"' + ssid + '"')
        wpa('set_network', number, 'key_mgmt', 'NONE')
        wpa('set_network', number, 'scan_ssid', '1')
        wpa('select_network', number)
        deadline = time.monotonic() + 10
        while wifi_status().get('wpa_state') not in ('DISCONNECTED', 'SCANNING'):
            if time.monotonic() >= deadline:
                raise ValueError('Unavailable-network disconnection was not observed')
            time.sleep(0.5)
        emit('unavailable_network_selected')
        installed_observe(lock, saved, seconds, offline=True)
    finally:
        restore_installed()
        emit('installed_configuration_restored')
    wifi_checkpoint('installed_restored', saved['boot_id'], expected)
    installed_observe(lock, saved, seconds)
    wifi_checkpoint('installed_final', saved['boot_id'], expected)
    emit('complete', passed=True, installed=True, connected=True,
         health=installed_health(lock, saved), configuration_restored=not INSTALLED_STATE.exists(),
         limits='Software disconnects and a synthetic unavailable network; physical AP loss, sleep and energy unqualified.')


def trial(candidate, metadata, seconds, connected=False):
    image = json.loads(Path('/etc/gameshellneo/image.json').read_text())
    value = identity()
    if (image.get('board') != 'gameshellneo-cpi31' or 'FWID 01-e2c3069b' not in value or
            FIRMWARE.is_symlink() or digest(FIRMWARE.read_bytes()) != ORIGINAL or
            digest(NVRAM.read_bytes()) != BOARD_DATA or
            command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'get', 'disable_scan_offload') != '0' or
            not Path('/sys/module/brcmfmac').is_dir()):
        raise ValueError('Original A0 firmware, board data, module or scan-policy preflight failed')
    udc = list(Path('/sys/class/udc').glob('*/state'))
    if len(udc) != 1 or udc[0].read_text().strip() != 'configured':
        raise ValueError('USB must remain configured for firmware recovery')
    data = candidate.read_bytes()
    if digest(data) != metadata['sha256'] or len(data) != metadata['size_bytes']:
        raise ValueError('Candidate firmware hash or size mismatch')
    mode = stat.S_IMODE(FIRMWARE.stat().st_mode)
    STATE.mkdir(mode=0o700)  # Refuse to overwrite any incomplete recovery state.
    write(STATE / 'original.bin', FIRMWARE.read_bytes())
    write(STATE / 'state.json', json.dumps({'identity': value, 'mode': mode}).encode())
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    config_hash = digest(WIFI_CONFIG.read_bytes())
    before = counts()
    try:
        if connected:
            wifi_checkpoint('original_before', boot, value)
            before = counts()
        previous_count = reload(data, mode)
        # The binary footer FWID differs from the firmware's runtime `ver` reply.
        # Require the observed exact chip/date/version/runtime FWID, not the footer.
        observed = wait_identity(metadata['runtime_identity'], previous_count)
        emit('candidate_loaded', identity=observed, sha256=digest(FIRMWARE.read_bytes()))
        after_reload = counts()
        if connected:
            wifi_checkpoint('candidate_initial', boot, metadata['runtime_identity'])
            for cycle in range(1, 5):
                reconnect(cycle, boot, metadata['runtime_identity'])
        start = time.monotonic()
        for index in range(seconds // 10 + 1):
            time.sleep(max(0, start + index * 10 - time.monotonic()))
            if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot:
                raise ValueError('Boot changed during firmware trial')
            fields = wifi_status()
            offload = command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'get', 'disable_scan_offload')
            if offload != '0' or digest(NVRAM.read_bytes()) != BOARD_DATA:
                raise ValueError('Scan policy or board data changed during firmware trial')
            if connected and (fields.get('wpa_state') != 'COMPLETED' or digest(WIFI_CONFIG.read_bytes()) != config_hash):
                raise ValueError('Connected trial lost association or Wi-Fi configuration changed')
            emit('sample', monotonic_seconds=time.monotonic(), state=fields.get('wpa_state'),
                 disable_scan_offload=0)
        after = counts()
        if any(not before[key] <= after_reload[key] <= after[key] for key in before):
            raise ValueError('Kernel event counts decreased')
        result = {key: after[key] - after_reload[key] for key in before}
        emit('candidate_complete', counts=result, duration_seconds=time.monotonic() - start,
             reload_counts={key: after_reload[key] - before[key] for key in before})
        if connected and any(after[key] != before[key] for key in before):
            raise ValueError('Firmware crash or SDIO removal during connected trial')
    finally:
        restored = restore()
        emit('restored', identity=restored, firmware_sha256=digest(FIRMWARE.read_bytes()))
    if connected:
        wifi_checkpoint('original_restored', boot, value)
        if digest(WIFI_CONFIG.read_bytes()) != config_hash:
            raise ValueError('Wi-Fi configuration changed during connected trial')
    emit('complete', passed=True, counts=result,
         connected=connected,
         limits=('Software reconnection and original restoration; not cold boot, AP disappearance or energy qualification.'
                 if connected else 'Candidate observation and original restoration; not association or energy qualification.'))


def interrupted(number, _frame):
    raise InterruptedError('Firmware trial interrupted by signal ' + str(number))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--metadata', type=Path)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--restore', action='store_true')
    parser.add_argument('--connected', action='store_true')
    parser.add_argument('--installed', action='store_true')
    parser.add_argument('--ack')
    args = parser.parse_args()
    os.umask(0o077)
    if args.ack:
        acknowledge(args.ack)
        return
    if args.restore:
        restore_installed() if args.installed else restore()
        WIFI_REQUEST.unlink(missing_ok=True)
        WIFI_ACK.unlink(missing_ok=True)
        return
    if ((not args.installed and not args.candidate) or not args.metadata or
            not 60 <= args.seconds <= 300 or args.seconds % 10 or (args.installed and args.connected)):
        parser.error('Supply candidate/metadata and seconds in 60..300, a multiple of ten')
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    metadata = json.loads(args.metadata.read_text())
    if args.installed:
        installed_trial(metadata, args.seconds)
    else:
        trial(args.candidate, metadata, args.seconds, args.connected)


if __name__ == '__main__':
    main()
