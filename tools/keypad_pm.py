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
INSTANCE = 'gameshellneo-keypad'
KEY_BYTES = 96  # KEY_CNT=768 in the locked Linux input-event-codes.h.
EVIOCGKEY = (2 << 30) | (KEY_BYTES << 16) | (ord('E') << 8) | 0x18
FUNCTIONS = {
    'drivers/usb/core/hub.c': {'check_port_resume_type', 'finish_port_resume', 'usb_port_resume'},
    'drivers/usb/core/hcd.c': {'hcd_bus_suspend', 'hcd_bus_resume'},
    'drivers/usb/host/ohci-hub.c': {'ohci_rh_suspend', 'ohci_rh_resume'},
    'drivers/usb/host/ohci-hcd.c': {'ohci_suspend', 'ohci_resume'},
}
EVENTS = ('regulator/regulator_disable', 'regulator/regulator_disable_complete',
          'regulator/regulator_enable', 'regulator/regulator_enable_complete',
          'power/suspend_resume')


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


def save_owned(record):
    with OWNED.open('x') as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(record, output)
        output.flush()
        os.fsync(output.fileno())


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
        (instance / 'buffer_size_kb').write_text('128\n')
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
                record['trace_overrun'] = any(re.search(r'(?:^|\n)(?:overrun|dropped events):\s*[1-9]', s)
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
            yield
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
    print(json.dumps(inspect()))
