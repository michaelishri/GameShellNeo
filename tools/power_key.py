"""Exclusive diagnostic PEK ownership; no normal power policy or sleep entry."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import select
import stat
import struct
import subprocess
import time

from keypad_pm import handle_state, save_owned

EVENT = struct.Struct('@llHHi')
KEY_POWER = 116
OWNED = Path('/run/gameshellneo-power-key.json')
BOOT = Path('/proc/sys/kernel/random/boot_id')
WHO = 'GameShellNeo PM diagnostic'


def ancestors():
    result, pid = set(), os.getpid()
    while pid > 1 and pid not in result:
        result.add(pid)
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        pid = int(fields[1])
    return result


def verify_inhibitor():
    value = json.loads(subprocess.check_output([
        'busctl', '--system', '--json=short', 'call', 'org.freedesktop.login1',
        '/org/freedesktop/login1', 'org.freedesktop.login1.Manager', 'ListInhibitors'],
        text=True, stderr=subprocess.PIPE, timeout=5))
    return validate_inhibitors(value, ancestors())


def validate_inhibitors(value, owners):
    if value.get('type') != 'a(ssssuu)' or len(value.get('data', [])) != 1:
        raise ValueError('Unexpected login1 inhibitor response')
    matches = [row for row in value['data'][0] if len(row) == 6 and
               row[1] == WHO and row[3] == 'block' and row[4] == 0 and
               row[5] in owners and
               {'handle-power-key', 'sleep', 'idle'} <= set(row[0].split(':'))]
    if len(matches) != 1:
        raise ValueError('Diagnostic ancestor does not own the required login1 inhibitor')
    return dict(what=matches[0][0], who=matches[0][1], mode='block', pid=matches[0][5])


def identity():
    matches = [p for p in Path('/sys/class/input').glob('event*')
               if (p/'device/name').read_text().strip() == 'axp20x-pek']
    if len(matches) != 1:
        raise ValueError('Expected one AXP power-key event device')
    p = matches[0]
    target = str((p/'device').resolve())
    if '/1f03400.rsb/sunxi-rsb-3a3/axp221-pek/input/' not in target:
        raise ValueError('Unexpected power-key controller')
    return dict(node='/dev/input/' + p.name, sysfs=target,
                dev=(p/'dev').read_text().strip())


class Consumer:
    def __init__(self, record):
        self.record = record
        self.down = False
        self.resumed = None
        self.last_event = time.monotonic()
        self.failed = False
        record.update(events=[], handed_back=False)

    def feed(self, data):
        if not data or len(data) % EVENT.size:
            self.failed = True
            raise ValueError('Power-key evdev data incomplete/disconnected')
        for seconds, micros, kind, code, value in EVENT.iter_unpack(data):
            if len(self.record['events']) >= 4096 or (kind == 0 and code == 3):
                self.failed = True
                raise ValueError('Power-key event loss/limit; continuity unknown')
            stamp = seconds + micros / 1e6
            self.record['events'].append(dict(seconds=stamp, type=kind, code=code, value=value))
            self.last_event = time.monotonic()
            if kind == 1:
                if code != KEY_POWER or value not in (0, 1, 2):
                    self.failed = True
                    raise ValueError('Unexpected power-key event')
                if value == 2:
                    if not self.down:
                        self.failed = True
                        raise ValueError('Power-key repeat without press')
                else:
                    self.down = bool(value)
                    if value == 0 and self.resumed is not None and stamp < self.resumed:
                        self.record['pre_resume_release_seen'] = True
                        # May be input-core clearing; this is NOT proof of physical release.

    def released(self, state):
        return (not self.failed and not self.down and state['ioctl_errno'] is None and
                not state['hung_up'] and not state['poll_error'] and not state['held_key_codes'])


class Guard:
    def __init__(self, fd, record, persist):
        self.fd, self.record, self.persist = fd, record, persist
        self.consumer = Consumer(record)
        self.poll = select.poll()
        self.poll.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)

    def drain(self, wait_ms=0):
        for _, flags in self.poll.poll(wait_ms):
            if flags & (select.POLLERR | select.POLLHUP):
                self.consumer.failed = True
                raise ValueError('Power-key handle disconnected')
            try:
                self.consumer.feed(os.read(self.fd, EVENT.size * 64))
            except BlockingIOError:
                pass

    def before_entry(self):
        self.record['inhibitor'] = verify_inhibitor()
        self.drain()
        if self.record['events'] or not self.consumer.released(handle_state(self.fd)):
            raise ValueError('Power key was touched or held before PM entry')
        self.record['entry_seconds'] = time.monotonic()
        self.persist()

    def after_entry(self):
        self.consumer.resumed = time.monotonic()
        self.record['resume_seconds'] = self.consumer.resumed
        self.persist()

    def finish(self):
        deadline = time.monotonic() + 8
        # Drain while inhibition and grab are still held. No key actions are emitted.
        while time.monotonic() < deadline:
            self.drain(50)
            if self.consumer.released(handle_state(self.fd)) and time.monotonic() - self.consumer.last_event >= 0.3:
                self.record['inhibitor_at_handoff'] = verify_inhibitor()
                self.record['logical_release_verified'] = True
                self.persist()
                return
        raise TimeoutError('Power-key release unqualified; recovery marker retained, cold restart required')


@contextmanager
def own(record, persist):
    if OWNED.exists():
        raise ValueError('Unresolved power-key ownership record; cold restart required')
    record['inhibitor'] = verify_inhibitor()
    record['identity'] = identity()
    fd = os.open(record['identity']['node'], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    grabbed = saved = False
    guard = None
    try:
        device = os.fstat(fd)
        if not stat.S_ISCHR(device.st_mode) or f'{os.major(device.st_rdev)}:{os.minor(device.st_rdev)}' != record['identity']['dev']:
            raise ValueError('Power-key opened device identity changed')
        fcntl.ioctl(fd, 0x400445a0, struct.pack('i', time.CLOCK_MONOTONIC))
        fcntl.ioctl(fd, 0x40044590, 1)  # EVIOCGRAB
        grabbed = True
        save_owned(dict(boot_id=BOOT.read_text().strip(), pid=os.getpid(), identity=record['identity']), OWNED)
        saved = True
        guard = Guard(fd, record, persist)
        if not guard.consumer.released(handle_state(fd)):
            raise ValueError('Power key is held at ownership acquisition')
        persist()
        yield guard
    finally:
        try:
            if guard is not None:
                guard.finish()
            if grabbed:
                fcntl.ioctl(fd, 0x40044590, 0)
                grabbed = False
            if saved:
                OWNED.unlink()
            record['handed_back'] = True
        except BaseException as error:
            record['cleanup_error'] = type(error).__name__ + ': ' + str(error)
            raise
        finally:
            os.close(fd)
            # Closing a descriptor releases its grab, even if cleanup failed.
            # A retained marker blocks another diagnostic, NOT future logind actions.
            record['descriptor_closed'] = True
            persist()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.inspect:
        print(json.dumps(dict(identity=identity(), stale_owner=OWNED.exists())))
        return
    # This command never accesses /sys/power; it validates ownership while awake.
    record = dict(passed=False, mode='awake-ownership-only')
    def persist():
        print(json.dumps(record), flush=True)
    try:
        from keypad_pm import exclusive_pm
        with exclusive_pm(OWNED.parent), own(record, persist) as guard:
            guard.before_entry()
            time.sleep(1)
            guard.after_entry()
        if record['events']:
            raise ValueError('Power key touched during the awake smoke check')
        record['passed'] = True
    finally:
        persist()


if __name__ == '__main__':
    main()
