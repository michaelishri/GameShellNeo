#!/usr/bin/env python3
"""USB-controlled exact-A0 firmware trial; always restore the installed binary."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import time

FIRMWARE = Path('/usr/lib/firmware/brcm/brcmfmac43430a0-sdio.bin')
NVRAM = Path('/usr/lib/firmware/brcm/brcmfmac43430a0-sdio.clockwork,clockworkpi-cpi3.txt')
STATE = Path('/run/gameshellneo-firmware-trial')
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


def trial(candidate, metadata, seconds):
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
    before = counts()
    try:
        previous_count = reload(data, mode)
        # The binary footer FWID differs from the firmware's runtime `ver` reply.
        # Require the observed exact chip/date/version/runtime FWID, not the footer.
        observed = wait_identity(metadata['runtime_identity'], previous_count)
        emit('candidate_loaded', identity=observed, sha256=digest(FIRMWARE.read_bytes()))
        after_reload = counts()
        start = time.monotonic()
        for index in range(seconds // 10 + 1):
            time.sleep(max(0, start + index * 10 - time.monotonic()))
            if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != boot:
                raise ValueError('Boot changed during firmware trial')
            fields = dict(line.split('=', 1) for line in command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'status').splitlines() if '=' in line)
            offload = command('/usr/sbin/wpa_cli', '-i', 'wlan0', 'get', 'disable_scan_offload')
            if offload != '0' or digest(NVRAM.read_bytes()) != BOARD_DATA:
                raise ValueError('Scan policy or board data changed during firmware trial')
            emit('sample', monotonic_seconds=time.monotonic(), state=fields.get('wpa_state'),
                 disable_scan_offload=0)
        after = counts()
        if any(not before[key] <= after_reload[key] <= after[key] for key in before):
            raise ValueError('Kernel event counts decreased')
        result = {key: after[key] - after_reload[key] for key in before}
        emit('candidate_complete', counts=result, duration_seconds=time.monotonic() - start,
             reload_counts={key: after_reload[key] - before[key] for key in before})
    finally:
        restored = restore()
        emit('restored', identity=restored, firmware_sha256=digest(FIRMWARE.read_bytes()))
    emit('complete', passed=True, counts=result,
         limits='Candidate observation and original restoration; not association or energy qualification.')


def interrupted(number, _frame):
    raise InterruptedError('Firmware trial interrupted by signal ' + str(number))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--metadata', type=Path)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.restore:
        restore()
        return
    if not args.candidate or not args.metadata or not 60 <= args.seconds <= 300 or args.seconds % 10:
        parser.error('Supply candidate/metadata and seconds in 60..300, a multiple of ten')
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    trial(args.candidate, json.loads(args.metadata.read_text()), args.seconds)


if __name__ == '__main__':
    main()
