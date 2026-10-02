"""Owned RTC deadline qualification while awake; never sets RTC time or enters PM."""
import argparse
import calendar
import fcntl
import json
import os
from pathlib import Path
import select
import re
import signal
import struct
import time

TIME = struct.Struct('=9i')
ALARM = struct.Struct('=BB2x9i')
RD_TIME, RD_ALARM, SET_ALARM = 0x80247009, 0x80287010, 0x4028700f
OWNED = Path('/run/gameshellneo-rtc-alarm.json')
BOOT = Path('/proc/sys/kernel/random/boot_id')
RTC = Path('/dev/rtc0')
RESULTS = Path('/var/lib/gameshellneo/rtc-tests')


def read_ioctl(fd, code, size):
    data = bytearray(size)
    fcntl.ioctl(fd, code, data, True)
    return bytes(data)


def alarm(fd):
    return list(ALARM.unpack(read_ioctl(fd, RD_ALARM, ALARM.size)))


def instant(values):
    sec, minute, hour, day, month, year, *_ = values
    # calendar.timegm normalizes some invalid dates; round-trip rejects those.
    stamp = calendar.timegm((year+1900, month+1, day, hour, minute, sec))
    if rtc_time(stamp)[:6] != list(values[:6]):
        raise ValueError('Invalid RTC calendar fields')
    return stamp


def rtc_time(stamp):
    t = time.gmtime(stamp)
    return [t.tm_sec, t.tm_min, t.tm_hour, t.tm_mday, t.tm_mon-1, t.tm_year-1900,
            (t.tm_wday+1) % 7, t.tm_yday-1, 0]


def same(a, b):
    return a[0] == b[0] and a[2:8] == b[2:8]


def identity():
    target = str(Path('/sys/class/rtc/rtc0/device').resolve())
    if not target.endswith('/soc/1f00000.rtc'):
        raise ValueError('Unexpected RTC controller')
    return target


def snapshot(fd):
    return dict(rtc_time=list(TIME.unpack(read_ioctl(fd, RD_TIME, TIME.size))),
                alarm=alarm(fd), boot_id=BOOT.read_text().strip(), identity=identity(),
                kernel=os.uname().release)


def restore_fd(fd, saved):
    if (saved.get('boot_id') != BOOT.read_text().strip() or saved.get('identity') != identity() or
            len(saved.get('original', [])) != 11 or saved['original'][0:2] != [0, 0]):
        raise ValueError('RTC restoration identity/ownership invalid; record retained')
    current = alarm(fd)
    if not (same(current, saved['original']) or current[2:8] == saved['requested'][2:8]):
        raise ValueError('RTC alarm changed by another owner; record retained')
    fcntl.ioctl(fd, SET_ALARM, ALARM.pack(*saved['original']))
    if not same(alarm(fd), saved['original']):
        raise ValueError('RTC restoration readback failed; record retained')
    OWNED.unlink()


def restore():
    if not OWNED.exists():
        return
    fd = os.open(RTC, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        restore_fd(fd, json.loads(OWNED.read_text()))
    finally:
        os.close(fd)


def irq_event(data):
    size = struct.calcsize('@L')
    if len(data) != size:
        raise ValueError('Incomplete RTC IRQ event')
    value = struct.unpack('@L', data)[0]
    if value >> 8 < 1 or value & 0xff != 0xa0:  # RTC_IRQF | RTC_AF
        raise ValueError('Unexpected RTC interrupt flags/count')
    return dict(count=value >> 8, flags=value & 0xff)


def smoke(fd, record, seconds=10, persist=lambda: None):
    from keypad_pm import exclusive_pm
    with exclusive_pm(OWNED.parent):
        return _smoke(fd, record, seconds, persist)


def _smoke(fd, record, seconds, persist):
    if seconds != 10:
        raise ValueError('Only the fixed ten-second awake deadline is qualified')
    if OWNED.exists():
        raise ValueError('Previous RTC ownership must be restored before another test')
    before = snapshot(fd)
    record['before'] = before
    if before['alarm'][:2] != [0, 0]:
        raise ValueError('Existing active/pending RTC alarm belongs to another owner')
    instant(before['alarm'][2:])
    target = [1, 0] + rtc_time(instant(before['rtc_time']) + seconds)
    saved = dict(boot_id=before['boot_id'], identity=before['identity'],
                 original=before['alarm'], requested=target)
    # Save before any mutation, using exclusive creation and fsync.
    from keypad_pm import save_owned
    save_owned(saved, OWNED)
    started = time.monotonic()
    record['requested'] = target
    try:
        persist()
        fcntl.ioctl(fd, SET_ALARM, ALARM.pack(*target))
        record['armed'] = alarm(fd)
        if not same(record['armed'], target):
            raise ValueError('RTC logical alarm readback mismatch')
        poll = select.poll(); poll.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)
        events = poll.poll((seconds+5)*1000)
        if len(events) != 1 or events[0][1] != select.POLLIN:
            raise TimeoutError('RTC alarm interrupt not delivered within deadline')
        record['interrupt'] = irq_event(os.read(fd, struct.calcsize('@L')))
        record['elapsed_seconds'] = time.monotonic() - started
        if not seconds-2 <= record['elapsed_seconds'] <= seconds+5:
            raise ValueError('RTC interrupt arrived outside the expected window')
        record['after_delivery'] = snapshot(fd)
    except BaseException as error:
        record['operation_error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        try:
            restore_fd(fd, saved)
            record['restored'] = True
        except BaseException as error:
            record['restore_error'] = type(error).__name__ + ': ' + str(error)
            raise
    record['passed'] = True



def qualification(boot_id, kernel):
    """Require restored awake delivery in this kernel/boot, plus no active alarm."""
    if OWNED.exists():
        raise ValueError('Unrestored RTC ownership')
    for path in sorted(RESULTS.glob('*/result.json'),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        record = json.loads(path.read_text())
        if (record.get('passed') is True and record.get('restored') is True and
                record.get('mode') == 'awake-only' and
                record.get('before', {}).get('boot_id') == boot_id and
                record['before'].get('kernel') == kernel and
                record.get('interrupt', {}).get('flags') == 0xa0 and
                8 <= record.get('elapsed_seconds', -1) <= 15):
            fd = os.open(RTC, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            try:
                current = snapshot(fd)
                if current['boot_id'] != boot_id or current['kernel'] != kernel or current['alarm'][:2] != [0, 0]:
                    raise ValueError('RTC boot/kernel/alarm changed after qualification')
            finally:
                os.close(fd)
            return dict(run_id=record['run_id'], path=str(path), current=current)
    raise ValueError('Run device:rtc-smoke in this boot/kernel before platform debug')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--restore', action='store_true')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    os.umask(0o077)
    if args.restore:
        if OWNED.exists():
            from keypad_pm import exclusive_pm
            with exclusive_pm(OWNED.parent):
                restore()
        print(json.dumps(dict(restored=True)))
        return
    def interrupted(signum, _frame):
        raise SystemExit(128+signum)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, interrupted)
    directory = None
    if args.smoke:
        if not args.run_id or not re.fullmatch(r'[0-9a-f]{32}', args.run_id):
            parser.error('--smoke requires a unique --run-id')
        directory = RESULTS / args.run_id
        directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    identity()
    fd = os.open(RTC, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    record = dict(passed=False, mode='awake-only', restored=False)
    try:
        if args.inspect:
            record['inspection'] = snapshot(fd)
        else:
            from keypad_pm import save_owned
            record['run_id'] = args.run_id
            smoke(fd, record, persist=lambda: save_owned(record, directory/'started.json'))
    except BaseException as error:
        record['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        os.close(fd)
        if directory:
            from keypad_pm import save_owned
            save_owned(record, directory/'result.json')
        print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
