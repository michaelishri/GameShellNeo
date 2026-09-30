"""Bounded physical-key qualification on the original retained-keypad evdev fd."""
from contextlib import contextmanager
import base64
import fcntl
import json
import os
from pathlib import Path
import select
import struct
import threading
import time

from keypad_pm import handle_state, optional, save_owned

CONSOLE_OWNED = Path('/run/gameshellneo-keypad-input-console.json')
SCREEN = Path('/dev/vcsa1')
TTY = Path('/dev/tty1')
EVENT = struct.Struct('@llHHi')  # Linux input_event: native long, including ARM32.
EVIOCGRAB = 0x40044590
EVIOCSCLOCKID = 0x400445a0
BUTTONS = (('A', 36), ('B', 37), ('X', 22), ('Y', 23))  # J/K/U/I, board-qualified.
MAX_EVENTS = 4096


def restore_console():
    if not CONSOLE_OWNED.exists():
        return
    saved = json.loads(CONSOLE_OWNED.read_text())
    if saved.get('boot_id') != optional('/proc/sys/kernel/random/boot_id'):
        raise ValueError('Console restoration belongs to a different boot')
    screen = base64.b64decode(saved['screen'], validate=True)
    current = SCREEN.read_bytes()
    if (len(screen) < 4 or len(screen) != 4 + 2 * screen[0] * screen[1] or
            screen[:2] != current[:2] or len(screen) > 65536):
        raise ValueError('Console geometry changed; restoration record retained')
    SCREEN.write_bytes(screen)
    CONSOLE_OWNED.unlink()


@contextmanager
def console():
    if optional('/sys/class/tty/tty0/active') != 'tty1':
        raise ValueError('Physical keypad test requires the visible tty1 console')
    screen = SCREEN.read_bytes()
    if len(screen) < 4 or len(screen) != 4 + 2 * screen[0] * screen[1] or len(screen) > 65536:
        raise ValueError('Unexpected tty1 screen geometry')
    save_owned(dict(boot_id=optional('/proc/sys/kernel/random/boot_id'),
                    screen=base64.b64encode(screen).decode()), CONSOLE_OWNED)
    try:
        yield
    finally:
        restore_console()


class EventLog:
    """Loss or inconsistent edges invalidate evidence instead of resynchronizing it."""
    def __init__(self, record):
        self.record = record
        record.update(events=[], prompts=[], checkpoints=[], passed=False,
                      input_event_bytes=EVENT.size, timestamp_clock='CLOCK_MONOTONIC')
        self.down = set()
        self.phase = 'initial'
        self.error = None
        self.lock = threading.Lock()

    def feed(self, data):
        if not data or len(data) % EVENT.size:
            raise ValueError('Incomplete or empty evdev read')
        with self.lock:
            for seconds, micros, kind, code, value in EVENT.iter_unpack(data):
                if len(self.record['events']) >= MAX_EVENTS:
                    raise ValueError('Physical input event limit exceeded')
                self.record['events'].append(dict(seconds=seconds + micros / 1e6,
                    type=kind, code=code, value=value, phase=self.phase))
                if kind == 0 and code == 3:  # SYN_DROPPED
                    raise ValueError('Evdev queue overflow; input continuity unqualified')
                if kind != 1:
                    continue
                if value == 1 and code not in self.down:
                    self.down.add(code)
                elif value == 0 and code in self.down:
                    self.down.remove(code)
                elif value != 2 or code not in self.down:
                    raise ValueError('Inconsistent physical key edge/repeat')

    def state(self):
        with self.lock:
            if self.error:
                raise ValueError(self.error)
            return set(self.down), len(self.record['events'])

    def key_events(self, start):
        with self.lock:
            if self.error:
                raise ValueError(self.error)
            return [e.copy() for e in self.record['events'][start:] if e['type'] == 1]

    def mark(self, phase):
        with self.lock:
            self.phase = phase


class Session:
    def __init__(self, fd, record, cue=None):
        self.fd, self.record = fd, record
        self.cue = cue
        self.log = EventLog(record)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.read_events, daemon=True)
        self.hold_start = None

    def read_events(self):
        try:
            poll = select.poll()
            poll.register(self.fd, select.POLLIN | select.POLLERR | select.POLLHUP)
            while not self.stop.is_set():
                for _, flags in poll.poll(50):
                    if flags & (select.POLLERR | select.POLLHUP):
                        raise ValueError('Original evdev handle disconnected')
                    try:
                        data = os.read(self.fd, EVENT.size * 64)
                    except BlockingIOError:
                        continue
                    self.log.feed(data)
        except Exception as error:
            with self.log.lock:
                self.log.error = type(error).__name__ + ': ' + str(error)
                self.record['reader_error'] = self.log.error

    def prompt(self, phase, *lines):
        self.log.mark(phase)
        self.record['prompts'].append(dict(phase=phase, seconds=time.monotonic(), lines=lines))
        # Fixed strings only; no network/credential text goes to the physical console.
        TTY.write_text('\x1b[H\x1b[2JGameShellNeo keypad test\r\n\r\n' +
                       '\r\n'.join(lines) + '\r\n\r\nKeep USB connected.\r\n')

    def checkpoint(self, name, expected):
        state = handle_state(self.fd)
        self.record['checkpoints'].append(dict(name=name, seconds=time.monotonic(), handle=state))
        if (state['ioctl_errno'] is not None or state['hung_up'] or state['poll_error'] or
                state['held_key_codes'] != sorted(expected)):
            raise ValueError('Original handle/key bitmap mismatch: ' + name)
        down, _ = self.log.state()
        if down != set(expected):
            raise ValueError('Recorded key state mismatch: ' + name)

    def wait_edges(self, start, code, values, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            edges = [(e['code'], e['value']) for e in self.log.key_events(start) if e['value'] != 2]
            expected = [(code, v) for v in values]
            if edges != expected[:len(edges)]:
                raise ValueError('Unexpected button or edge order; sequence stopped')
            if edges == expected:
                return
            time.sleep(0.02)
        raise TimeoutError('Timed out waiting for the requested physical button')

    def taps(self, phase):
        for index, (label, code) in enumerate(BUTTONS, 1):
            self.checkpoint(phase + '-neutral-' + label, [])
            _, start = self.log.state()
            self.prompt(phase + '-' + label, phase.upper() + ' TEST: ' + str(index) + '/4',
                        'Tap and release ' + label + ' once.', 'Wait for the next instruction.')
            self.wait_edges(start, code, [1, 0])
            self.checkpoint(phase + '-released-' + label, [])
            self.prompt(phase + '-' + label + '-confirmed', label + ' recorded (' + str(index) + '/4).',
                        'Press and release received.', 'Do not press it again.',
                        'Wait for the next button prompt.')
            if self.cue:
                self.cue.play(phase + '-' + label)
            time.sleep(2)
            self.wait_edges(start, code, [1, 0])  # Extra taps during confirmation still reject the run.
        self.prompt(phase + '-done', 'Four taps recorded.', 'Leave all buttons released.')
        time.sleep(1)
        self.checkpoint(phase + '-complete', [])

    def before_stage(self):
        self.prompt('countdown', 'Leave all buttons released.', 'Starting in 10 seconds...')
        time.sleep(10)
        self.checkpoint('initial', [])
        if self.log.key_events(0):
            raise ValueError('Buttons pressed before the sequence started')
        self.taps('before')
        _, self.hold_start = self.log.state()
        self.prompt('hold', 'Press and HOLD A.', 'Keep holding through the dark screen.',
                    'Release only when told RELEASE A.')
        self.wait_edges(self.hold_start, 36, [1])
        time.sleep(1)
        self.verify_hold('before-stage')
        if self.cue:
            self.cue.play('hold-A')
        self.prompt('suspend', 'KEEP HOLDING A.', 'Driver test starting...',
                    'Screen may go dark briefly.')

    def verify_hold(self, name):
        edges = [(e['code'], e['value']) for e in self.log.key_events(self.hold_start) if e['value'] != 2]
        if edges != [(36, 1)]:
            raise ValueError('A hold interrupted before the release instruction')
        self.checkpoint(name, [36])

    def after_stage(self):
        time.sleep(0.1)  # Allow the reader to drain queued PM/repeat events.
        edges = [(e['code'], e['value']) for e in self.log.key_events(self.hold_start) if e['value'] != 2]
        modes = {((36, 1),): 'continuous', ((36, 1), (36, 0)): 'cleared',
                 ((36, 1), (36, 0), (36, 1)): 'reasserted'}
        mode = modes.get(tuple(edges))
        if mode is None:
            raise ValueError('Unexpected held-key edge sequence across PM')
        self.record.update(hold_resume_mode=mode, continuous_hold=mode == 'continuous')
        expected = [] if mode == 'cleared' else [36]
        self.checkpoint('after-stage', expected)
        _, start = self.log.state()
        if mode == 'cleared':
            self.prompt('release', 'RELEASE A now.', 'Linux cleared its held-key state.',
                        'Next button prompt in 4 seconds.')
            time.sleep(4)
            if self.log.key_events(start):
                raise ValueError('Unexpected key activity during release of cleared A')
            self.record['physical_release_event_observed'] = False
        else:
            self.prompt('release', 'RELEASE A now.', 'Then leave all buttons released.')
            self.wait_edges(start, 36, [0])
            self.record['physical_release_event_observed'] = True
        self.checkpoint('released-after-stage', [])
        time.sleep(1)
        self.taps('after')
        self.record['passed'] = True
        self.prompt('finished', 'Button sequence recorded.', 'Leave controls untouched.',
                    'Checking network recovery...')


@contextmanager
def capture(record, fd, cue=None):
    # Exclusive grab affects only this internal keypad, never the separate power key.
    # Closing the fd releases the grab even if the worker is killed.
    grabbed = False
    session = Session(fd, record, cue)
    try:
        state = handle_state(fd)
        if (state['ioctl_errno'] is not None or state['hung_up'] or state['poll_error'] or
                state['held_key_codes']):
            raise ValueError('Release all keys before starting the physical test')
        fcntl.ioctl(fd, EVIOCGRAB, 1)
        grabbed = True
        fcntl.ioctl(fd, EVIOCSCLOCKID, struct.pack('@i', time.CLOCK_MONOTONIC))
        with console():
            session.thread.start()
            try:
                yield session
                session.checkpoint('final', [])
                session.log.state()
            except BaseException:
                record['passed'] = False
                session.prompt('failed', 'Test stopped.', 'Release ALL buttons now.',
                               'Evidence saved for inspection.')
                time.sleep(3)
                raise
            finally:
                session.stop.set()
                session.thread.join(timeout=1)
                if session.thread.is_alive():
                    record['passed'] = False
                    raise RuntimeError('Input reader failed to stop')
        record['console_restored'] = not CONSOLE_OWNED.exists()
    finally:
        record['console_restored'] = not CONSOLE_OWNED.exists()
        if grabbed:
            fcntl.ioctl(fd, EVIOCGRAB, 0)
            record['grab_released'] = True
