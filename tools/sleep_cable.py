"""Owned observer prompts for one cable transition; no PM or network writes."""
from contextlib import contextmanager
import base64
import json
from pathlib import Path
import time

import keypad_input
import keypad_pm
import power_key_policy as policy
import sleep_connection

OWNED = Path('/run/gameshellneo-sleep-console.json')


def restore(token):
    if not OWNED.exists():
        return
    saved = json.loads(policy.read_owned(OWNED))
    if (saved.get('run_id') != policy.run_id(token) or
            saved.get('boot_id') != keypad_pm.optional('/proc/sys/kernel/random/boot_id')):
        raise ValueError('Sleep console belongs to another run/boot; ownership retained')
    screen = base64.b64decode(saved['screen'], validate=True)
    current = keypad_input.SCREEN.read_bytes()
    if (len(screen) < 4 or len(screen) != 4 + 2 * screen[0] * screen[1] or
            len(screen) > 65536 or screen[:2] != current[:2]):
        raise ValueError('Sleep console geometry changed; ownership retained')
    keypad_input.SCREEN.write_bytes(screen)
    OWNED.unlink()


def prompt(record, phase, *lines):
    record['cable_console']['prompts'].append(dict(phase=phase, monotonic_seconds=time.monotonic(), lines=lines))
    keypad_input.TTY.write_text('\x1b[H\x1b[2JGameShellNeo USB sleep test\r\n\r\n' +
                               '\r\n'.join(lines) + '\r\n')


@contextmanager
def console(record, token):
    if not sleep_connection.transition(record.get('connection', 'usb')) or record['mode'] != 'rtc-wake':
        yield
        return
    if (OWNED.exists() or keypad_input.CONSOLE_OWNED.exists() or
            keypad_pm.optional('/sys/class/tty/tty0/active') != 'tty1'):
        raise ValueError('Sleep cable test requires unowned visible tty1')
    screen = keypad_input.SCREEN.read_bytes()
    if len(screen) < 4 or len(screen) != 4 + 2 * screen[0] * screen[1] or len(screen) > 65536:
        raise ValueError('Unexpected sleep console geometry')
    keypad_pm.save_owned(dict(run_id=policy.run_id(token), boot_id=record['before']['boot_id'],
                             screen=base64.b64encode(screen).decode()), OWNED)
    record['cable_console'] = dict(prompts=[], restored=False)
    try:
        remove = record['connection'] == 'usb-remove'
        prompt(record, 'instructions',
               'When the screen goes dark:', 'Wait 10 seconds, then ONCE:',
               'UNPLUG USB at the GameShell.' if remove else 'CONNECT USB to the Mac.',
               'Leave USB unplugged.' if remove else 'Leave USB connected.',
               '', 'If the screen returns early,', 'DO NOT change the cable.',
               'Do not press any buttons.', '', 'Starting in 10 seconds...')
        time.sleep(10)  # Before arming RTC; does not reduce the wake deadline.
        yield
    finally:
        restore(token)
        record['cable_console']['restored'] = True


def returned(record):
    if 'cable_console' in record:
        prompt(record, 'returned', 'Sleep has returned.', 'Do not touch USB or buttons.',
               'Collecting the original result...')


def wake_observation(record):
    """Observe only: no inference that cable IRQ dispatch timestamps an edge."""
    event = record['rtc'].get('interrupt')
    if event is None:
        kind = 'no-rtc-event-at-return'
    elif record.get('wake_irq') != str(record['rtc']['irq_before']['irq']):
        kind = 'rtc-event-with-other-wake-irq'
    else:
        kind = 'rtc-event-and-wake-irq'
    return dict(kind=kind, wake_irq=record.get('wake_irq'), cable_wake_proven=False,
                physical_timing_qualified=False)
