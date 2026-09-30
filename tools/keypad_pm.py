"""Read-only keypad state and bounded PM tracing; never changes keypad power."""
from contextlib import contextmanager
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import select
import time

USB = Path('/sys/bus/usb/devices')
INPUT = Path('/sys/class/input')
TRACE = Path('/sys/kernel/tracing')
DEBUG = Path('/sys/kernel/debug/dynamic_debug/control')
OWNED = Path('/run/gameshellneo-keypad-trace.json')
PERSIST_OWNED = Path('/run/gameshellneo-keypad-persist.json')
QUIRKS_OWNED = Path('/run/gameshellneo-keypad-quirks.json')
QUIRK_MODES = {'baseline': 0, 'old-scheme': 1, 'fast-recovery': 2}
INSTANCE = 'gameshellneo-keypad'
TRACE_BUFFER_KB = 256  # A serialized PM cycle can place all callbacks on one CPU.
KEY_BYTES = 96  # KEY_CNT=768 in the locked Linux input-event-codes.h.
EVIOCGKEY = (2 << 30) | (KEY_BYTES << 16) | (ord('E') << 8) | 0x18
FUNCTIONS = {
    'drivers/usb/core/hub.c': {'wait_for_connected', 'check_port_resume_type',
                             'finish_port_resume', 'usb_port_resume'},
    'drivers/usb/core/hcd.c': {'hcd_bus_suspend', 'hcd_bus_resume'},
    'drivers/usb/host/ohci-hub.c': {'ohci_rh_suspend', 'ohci_rh_resume'},
    'drivers/usb/host/ohci-hcd.c': {'ohci_suspend', 'ohci_resume'},
}
EVENTS = ('regulator/regulator_disable', 'regulator/regulator_disable_complete',
          'regulator/regulator_enable', 'regulator/regulator_enable_complete',
          'power/suspend_resume', 'power/device_pm_callback_start',
          'power/device_pm_callback_end')


def optional(path):
    try:
        return Path(path).read_text().strip()
    except FileNotFoundError:
        return None


def power(path):
    return {name: optional(path / 'power' / name) for name in
            ('persist', 'wakeup', 'control', 'runtime_status', 'runtime_usage', 'runtime_enabled')}


def inspect():
    matches = [p for p in USB.iterdir() if optional(p / 'idVendor') == '4242' and
               optional(p / 'idProduct') == 'e131']
    if len(matches) != 1:
        raise ValueError('Expected exactly one 4242:e131 keypad')
    usb = matches[0]
    inputs = []
    for path in sorted(INPUT.glob('event*')):
        if usb.resolve() not in path.resolve().parents:
            continue
        node = Path('/dev/input') / path.name
        links = {str(p): str(p.resolve()) for group in ('by-id', 'by-path')
                 for p in (node.parent / group).glob('*') if p.resolve() == node}
        inputs.append(dict(event=str(node), sysfs=str(path.resolve()),
                           name=optional(path / 'device/name'), links=links))
    if len(inputs) != 1:
        raise ValueError('Expected exactly one keypad evdev interface')
    descriptors = (usb / 'descriptors').read_bytes()
    configurations = []
    offset = 0
    while offset < len(descriptors):
        length = descriptors[offset]
        if length < 2 or offset + length > len(descriptors):
            raise ValueError('Invalid USB descriptor boundaries')
        if descriptors[offset + 1] == 2 and length >= 9:
            configurations.append(dict(attributes=descriptors[offset + 7],
                                       remote_wakeup=bool(descriptors[offset + 7] & 0x20)))
        offset += length
    regulators = {}
    for path in Path('/sys/class/regulator').glob('regulator*'):
        if optional(path / 'name') == 'keypad-vbus':
            regulators[str(path)] = {n: optional(path / n) for n in
                                     ('name', 'state', 'num_users', 'microvolts')}
    hosts = {name: power(Path('/sys/bus/platform/devices') / name)
             for name in ('1c1a000.usb', '1c1a400.usb')}
    return dict(monotonic_seconds=time.monotonic(),
                boot_id=optional('/proc/sys/kernel/random/boot_id'),
                usb=dict(path=str(usb.resolve()), name=usb.name, power=power(usb),
                         attributes={n: optional(usb / n) for n in
                                     ('devnum', 'busnum', 'speed', 'version', 'bcdDevice',
                                      'manufacturer', 'product', 'serial', 'quirks')},
                         configurations=configurations, descriptors_hex=descriptors.hex()),
                inputs=inputs, hosts=hosts, regulators=regulators,
                regulator_summary=optional('/sys/kernel/debug/regulator/regulator_summary'),
                tracing_available=(TRACE / 'events/regulator/regulator_disable/enable').is_file(),
                dynamic_debug_available=DEBUG.is_file())


def handle_state(fd):
    poll = select.poll()
    poll.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)
    flags = 0
    for _, value in poll.poll(0):
        flags |= value
    keys = bytearray(KEY_BYTES)
    error = None
    try:
        fcntl.ioctl(fd, EVIOCGKEY, keys, True)
    except OSError as exc:
        error = exc.errno
    return dict(poll_flags=flags, hung_up=bool(flags & select.POLLHUP),
                poll_error=bool(flags & select.POLLERR), ioctl_errno=error,
                disconnected=error == errno.ENODEV,
                held_key_codes=None if error else [i for i in range(KEY_BYTES * 8)
                                                  if keys[i // 8] & (1 << (i % 8))])


def sites(text):
    result = []
    for line in text.splitlines():
        match = re.match(r'(\S+):(\d+) \[[^]]+\](\S+) =(\S+) ', line)
        if not match:
            continue
        for filename, functions in FUNCTIONS.items():
            if (match[1] == filename or match[1].endswith('/' + filename)) and match[3] in functions:
                result.append(dict(file=filename, line=int(match[2]), flags=match[4]))
    if not result or not any(s['file'] == 'drivers/usb/core/hub.c' for s in result):
        raise ValueError('Missing expected USB dynamic-debug sites')
    return result


def set_site(site, flags):
    if (site['file'] not in FUNCTIONS or not isinstance(site['line'], int) or
            site['line'] <= 0 or not re.fullmatch(r'[pflmstr_]+', flags)):
        raise ValueError('Invalid saved dynamic-debug selector')
    DEBUG.write_text(f"file *{site['file']} line {site['line']} ={flags}\n")


def save_owned(record, path=None):
    with (OWNED if path is None else path).open('x') as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(record, output)
        output.flush()
        os.fsync(output.fileno())


def keypad_identity(info):
    """Pin the known internal HID and physical port, not its recycled event number."""
    usb = info['usb']
    attributes = usb['attributes']
    path = usb['path']
    if (not re.fullmatch(r'/sys/devices/platform/soc/1c1a400[.]usb/usb([0-9]+)/\1-1', path) or
            attributes['manufacturer'] != 'rancidbacon.com' or
            attributes['product'] != 'UsbKeyboard' or attributes['bcdDevice'] != '0100' or
            attributes['speed'] != '1.5' or
            info['inputs'][0]['name'] != 'rancidbacon.com UsbKeyboard'):
        raise ValueError('Refusing a keypad outside the qualified internal OHCI topology')
    # inspect() already requires exactly one 4242:e131 device and one input interface.
    return dict(path=path, descriptors_hex=usb['descriptors_hex'])


def persist_write(info, expected, value):
    if value not in ('0', '1') or keypad_identity(info) != expected:
        raise ValueError('Keypad identity or persistence value changed')
    path = Path(info['usb']['path']) / 'power/persist'
    path.write_text(value + '\n')
    if path.read_text().strip() != value:
        raise ValueError('Keypad persistence readback failed')


def port_quirks_state(info):
    """Resolve the pinned keypad's upstream port, never its device quirks file."""
    identity = keypad_identity(info)
    usb = Path(identity['path'])
    bus = usb.parent.name.removeprefix('usb')
    port = usb.parent / (bus + '-0:1.0') / ('usb' + bus + '-port1')
    if (not port.is_dir() or (usb / 'port').resolve() != port or
            (port / 'device').resolve() != usb):
        raise ValueError('Internal keypad port backlinks do not match')
    value = (port / 'quirks').read_text().strip()
    if not re.fullmatch(r'[0-9a-fA-F]{8}', value):
        raise ValueError('Invalid USB port quirks readback')
    globals_ = {name: optional('/sys/module/usbcore/parameters/' + name)
                for name in ('old_scheme_first', 'use_both_schemes')}
    return dict(path=str(port), value=int(value, 16), globals=globals_)


def port_quirks_write(info, identity, expected_port, value):
    if keypad_identity(info) != identity or type(value) is not int or not 0 <= value <= 0xffffffff:
        raise ValueError('Invalid keypad port identity or quirks value')
    state = port_quirks_state(info)
    if state['path'] != expected_port:
        raise ValueError('Keypad USB port changed')
    path = Path(state['path']) / 'quirks'
    path.write_text(f'{value:08x}\n')
    if port_quirks_state(inspect())['value'] != value:
        raise ValueError('Keypad port quirks write/readback failed')


def restore_port_quirks():
    if not QUIRKS_OWNED.exists():
        return
    saved = json.loads(QUIRKS_OWNED.read_text())
    original, applied = saved.get('original'), saved.get('applied')
    mode = saved.get('mode')
    if (saved.get('boot_id') != optional('/proc/sys/kernel/random/boot_id') or
            type(original) is not int or not 0 <= original <= 0xffffffff or original & 3 or
            mode not in QUIRK_MODES or applied != original | QUIRK_MODES[mode]):
        raise ValueError('Invalid keypad quirks ownership; record retained')
    info = inspect()
    state = port_quirks_state(info)
    if state['value'] not in (original, applied):
        raise ValueError('Concurrent keypad port change; ownership retained')
    port_quirks_write(info, saved['identity'], saved['port'], original)
    QUIRKS_OWNED.unlink()


@contextmanager
def port_quirks(record, mode):
    if mode not in QUIRK_MODES:
        raise ValueError('Explicit baseline/old-scheme/fast-recovery mode required')
    info = inspect()
    identity = keypad_identity(info)
    state = port_quirks_state(info)
    if (state['globals'] != {'old_scheme_first': 'N', 'use_both_schemes': 'Y'} or
            state['value'] & 3 or info['usb']['power']['persist'] != '1' or
            info['usb']['power']['control'] != 'on' or info['usb']['power']['wakeup'] is not None):
        raise ValueError('Expected baseline port quirks and keypad power policy')
    applied = state['value'] | QUIRK_MODES[mode]
    save_owned(dict(boot_id=info['boot_id'], original=state['value'], applied=applied,
                    mode=mode, identity=identity, port=state['path']), QUIRKS_OWNED)
    record.update(mode=mode, original=state['value'], requested=applied,
                  identity=identity, before=state, restored=False)
    try:
        port_quirks_write(info, identity, state['path'], applied)
        record['applied'] = port_quirks_state(inspect())
        yield
        record['after_stage'] = port_quirks_state(inspect())
        if record['after_stage'] != record['applied']:
            raise ValueError('Keypad port policy changed during PM')
    finally:
        restore_port_quirks()
        record['after_restore'] = port_quirks_state(inspect())
        record['restored'] = not QUIRKS_OWNED.exists() and record['after_restore'] == state
        if not record['restored']:
            raise ValueError('Keypad port policy restoration failed')


def restore_persistence():
    if not PERSIST_OWNED.exists():
        return
    saved = json.loads(PERSIST_OWNED.read_text())
    if (saved.get('boot_id') != optional('/proc/sys/kernel/random/boot_id') or
            saved.get('original') != '1' or not isinstance(saved.get('identity'), dict)):
        raise ValueError('Invalid keypad persistence ownership; record retained')
    # Re-enumeration can remove the evdev node briefly. Never restore by a stale fd
    # or write a path supplied by the ownership file without fresh identity checks.
    deadline = time.monotonic() + 10
    while True:
        try:
            info = inspect()
            break
        except (FileNotFoundError, ValueError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)
    persist_write(info, saved['identity'], saved['original'])
    PERSIST_OWNED.unlink()


@contextmanager
def persistence(record, value):
    if value not in ('0', '1'):
        raise ValueError('Explicit keypad persistence 0/1 required')
    info = inspect()
    identity = keypad_identity(info)
    if (info['usb']['power']['persist'] != '1' or
            info['usb']['power']['control'] != 'on' or
            info['usb']['power']['wakeup'] is not None):
        raise ValueError('Expected original keypad persistence/wake/runtime policy')
    save_owned(dict(boot_id=info['boot_id'], original='1', identity=identity), PERSIST_OWNED)
    record.update(original='1', requested=value, identity=identity, restored=False)
    try:
        persist_write(info, identity, value)
        record['applied'] = inspect()['usb']['power']['persist']
        if record['applied'] != value:
            raise ValueError('Keypad persistence changed before PM')
        yield
    finally:
        restore_persistence()
        record['restored'] = not PERSIST_OWNED.exists()


def wait_ready(record, started, expected):
    """Bounded fresh-handle readiness; no key injection, reads or exclusive grab."""
    deadline = time.monotonic() + 10
    attempts = 0
    while True:
        attempts += 1
        try:
            info = inspect()
            if keypad_identity(info) != expected:
                raise ValueError('Keypad identity changed while waiting for input')
            fd = os.open(info['inputs'][0]['event'], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            try:
                state = handle_state(fd)
            finally:
                os.close(fd)
            if state['ioctl_errno'] is None and not state['hung_up'] and not state['poll_error']:
                record.update(seconds=time.monotonic() - started, attempts=attempts,
                              poll_interval_seconds=0.1, input_sysfs=info['inputs'][0]['sysfs'],
                              handle=state)
                return
        except (FileNotFoundError, OSError):
            pass
        except ValueError as error:
            # Missing evdev/device can be transient. A different identified keypad
            # must fail, rather than accepting its healthy handle.
            if str(error) not in ('Expected exactly one 4242:e131 keypad',
                                  'Expected exactly one keypad evdev interface'):
                raise
        if time.monotonic() >= deadline:
            raise TimeoutError('No healthy keypad input handle within ten seconds')
        time.sleep(0.1)


def restore_trace():
    if not OWNED.exists():
        return
    saved = json.loads(OWNED.read_text())
    if saved.get('boot_id') != optional('/proc/sys/kernel/random/boot_id'):
        raise ValueError('Trace restoration belongs to a different boot')
    instance = TRACE / 'instances' / INSTANCE
    if instance.exists():
        (instance / 'tracing_on').write_text('0\n')
        for name in EVENTS:
            (instance / 'events' / name / 'enable').write_text('0\n')
    for site in saved['sites']:
        set_site(site, site['flags'])
    # A tracefs instance contains virtual files; remove only the owned directory.
    if instance.exists():
        instance.rmdir()
    OWNED.unlink()


@contextmanager
def trace(record):
    instance = TRACE / 'instances' / INSTANCE
    if not (TRACE / 'instances').is_dir() or not DEBUG.is_file():
        raise ValueError('Keypad tracing requires the new diagnostic kernel')
    if instance.exists():
        raise ValueError('Existing keypad trace instance; recover before retrying')
    if any(not (TRACE / 'events' / name / 'enable').is_file() for name in EVENTS):
        raise ValueError('Required regulator/PM trace events are unavailable')
    selected = sites(DEBUG.read_text())
    save_owned(dict(boot_id=optional('/proc/sys/kernel/random/boot_id'), sites=selected))
    try:
        instance.mkdir()
        (instance / 'tracing_on').write_text('0\n')
        (instance / 'current_tracer').write_text('nop\n')
        (instance / 'buffer_size_kb').write_text(str(TRACE_BUFFER_KB) + '\n')
        record['trace_buffer_kb_per_cpu'] = TRACE_BUFFER_KB
        (instance / 'trace_clock').write_text('mono\n')
        for name in EVENTS:
            event = instance / 'events' / name
            if name.startswith('regulator/'):
                (event / 'filter').write_text('name == "keypad-vbus"\n')
            (event / 'enable').write_text('1\n')
        for site in selected:
            set_site(site, site['flags'].replace('_', '') + ('p' if 'p' not in site['flags'] else ''))
        (instance / 'tracing_on').write_text('1\n')
        yield
    finally:
        try:
            if instance.exists():
                (instance / 'tracing_on').write_text('0\n')
                record['trace'] = (instance / 'trace').read_text()
                record['trace_stats'] = {p.parent.name: p.read_text()
                                         for p in (instance / 'per_cpu').glob('cpu*/stats')}
                record['trace_overrun'] = not record['trace_stats'] or any(
                    re.search(r'(?:^|\n)(?:overrun|commit overrun|dropped events):\s*[1-9]', s)
                    for s in record['trace_stats'].values())
        finally:
            restore_trace()
        record['trace_restored'] = not OWNED.exists() and not instance.exists()


@contextmanager
def observe(record, tracing=False):
    from contextlib import nullcontext
    record['before'] = inspect()
    node = record['before']['inputs'][0]['event']
    fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        record['handle_before'] = handle_state(fd)
        if record['handle_before']['ioctl_errno'] is not None:
            raise ValueError('Initial keypad handle is unhealthy')
        with trace(record) if tracing else nullcontext():
            yield fd
        record['old_handle_after'] = handle_state(fd)
        record['after'] = inspect()
        new_fd = os.open(record['after']['inputs'][0]['event'], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            record['new_handle_after'] = handle_state(new_fd)
        finally:
            os.close(new_fd)
        if record['new_handle_after']['ioctl_errno'] is not None or record.get('trace_overrun'):
            raise ValueError('Keypad recovery or trace completeness failed')
    finally:
        os.close(fd)


if __name__ == '__main__':
    info = inspect()
    info['port_quirks'] = port_quirks_state(info)
    print(json.dumps(info))
