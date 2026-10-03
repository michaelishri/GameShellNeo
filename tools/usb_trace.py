"""Owned MUSB/ECM metadata capture; never changes gadget, network or PM policy."""
from contextlib import contextmanager
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

import keypad_pm
from wifi_trace import trace_lost

TRACE = Path('/sys/kernel/tracing')
DEBUG = Path('/sys/kernel/debug/dynamic_debug/control')
BOOT = Path('/proc/sys/kernel/random/boot_id')
OWNED = Path('/run/gameshellneo-usb-trace.json')
RESULTS = Path('/var/lib/gameshellneo/usb-traces')
INSTANCE = 'gameshellneo-usb'
ECM = 'drivers/usb/gadget/function/f_ecm.c'
# Match the exact audited messages, not every callsite in these functions.
MESSAGES = {
    'ecm_do_notify': {r'notify connect %s\n', r'notify speed %d\n', r'notify --> %d\n'},
    'ecm_notify_complete': {r'event %02x --> %d\n'},
    'ecm_set_alt': {r'activate ecm\n', r'init ecm\n', r'reset ecm\n'},
    'ecm_disable': {r'ecm deactivated\n'},
    'ecm_suspend': {r'ECM Suspend\n'},
    'ecm_resume': {r'ECM Resume\n'},
}
# Short requests include ECM's 8-byte connection and 16-byte speed messages.
# Length alone does NOT identify an endpoint or prove notification delivery.
EVENTS = {
    'musb/musb_state': ('', ('char[] name;', 'u8 devctl;', 'char[] desc;')),
    'musb/musb_isr': ('int_usb != 0', ('u8 int_usb;', 'u16 int_tx;', 'u16 int_rx;')),
    'gadget/usb_gadget_set_state': ('', ('enum usb_device_state state;',)),
    'gadget/usb_gadget_connect': ('', ('unsigned connected;',)),
    'gadget/usb_gadget_disconnect': ('', ('unsigned connected;',)),
    'gadget/usb_ep_enable': ('', ('char[] name;', 'u8 address;', 'int ret;')),
    'gadget/usb_ep_disable': ('', ('char[] name;', 'u8 address;', 'int ret;')),
    'gadget/usb_ep_queue': ('name == "ep0" || length == 8 || length == 16',
                           ('char[] name;', 'unsigned length;', 'int ret;', 'struct usb_request * req;')),
    'gadget/usb_gadget_giveback_request': ('name == "ep0" || length == 8 || length == 16',
                           ('char[] name;', 'unsigned length;', 'int status;', 'struct usb_request * req;')),
    'power/suspend_resume': ('', ('const char * action;',)),
    'power/device_pm_callback_start': ('', ('char[] device;',)),
    'power/device_pm_callback_end': ('', ('char[] device;', 'int error;')),
}


def run_id(value):
    if not re.fullmatch('[0-9a-f]{32}', value):
        raise ValueError('Require an exact USB trace run ID')
    return value


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=15).strip()


def sites(text):
    found = []
    for line in text.splitlines():
        match = re.fullmatch(r'(\S+):(\d+) \[usb_f_ecm\](\S+) =([pflmstr_]+) "(.*)"', line)
        if not match or match[1] != ECM or match[3] not in MESSAGES:
            continue
        if match[5] not in MESSAGES[match[3]]:
            raise ValueError('ECM diagnostic message changed; audit before enabling')
        found.append(dict(line=int(match[2]), function=match[3], flags=match[4], message=match[5]))
    expected = {(function, message) for function, messages in MESSAGES.items() for message in messages}
    if len(found) != len(expected) or {(s['function'], s['message']) for s in found} != expected:
        raise ValueError('Missing or ambiguous ECM diagnostic sites')
    return found


def set_site(site, flags):
    if (site['function'] not in MESSAGES or site['message'] not in MESSAGES[site['function']] or
            type(site['line']) is not int or site['line'] <= 0 or flags not in ('_', 'p')):
        raise ValueError('Invalid ECM diagnostic selector')
    DEBUG.write_text(f"file {ECM} line {site['line']} ={flags}\n")


def state():
    udcs = list(Path('/sys/class/udc').iterdir())
    gadgets = list(Path('/sys/kernel/config/usb_gadget').iterdir())
    if len(udcs) != 1 or len(gadgets) != 1:
        raise ValueError('Require the single qualified UDC/ECM gadget')
    udc, gadget = udcs[0], gadgets[0]
    functions = [p.name for p in (gadget/'functions').iterdir()]
    configs = list((gadget/'configs').iterdir())
    links = [p.resolve().name for c in configs for p in c.iterdir() if p.is_symlink()]
    if (functions != ['ecm.usb0'] or len(configs) != 1 or links != ['ecm.usb0'] or
            (gadget/'UDC').read_text().strip() != udc.name):
        raise ValueError('Unqualified gadget binding or function configuration')
    gadget_device = (udc/'gadget').resolve(strict=True)
    driver = (gadget_device/'driver').resolve(strict=True).name
    if driver != 'configfs-gadget.'+gadget.name or not re.fullmatch(r'gadget\.[0-9]+', gadget_device.name):
        raise ValueError('Unexpected gadget device/driver logging identity')
    read = lambda p: p.read_text().strip()
    return dict(boot_id=read(BOOT), udc=udc.name, state=read(udc/'state'),
                ecm_log_prefix=driver+' '+gadget_device.name+': ',
                carrier=read(Path('/sys/class/net/usb0/carrier')),
                flags=read(Path('/sys/class/net/usb0/flags')),
                pm={n: read(Path('/sys/power')/n) for n in ('pm_test', 'pm_async')},
                stats={p.name: read(p) for p in Path('/sys/power/suspend_stats').iterdir() if p.is_file()})


def summarize_journal(text, cursor, prefix):
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not rows or rows[0].get('__CURSOR') != cursor or len(rows) > 2001:
        raise ValueError('Kernel journal lost the starting cursor or exceeded bounded ECM capture')
    rows = rows[1:]
    events = []
    patterns = (
        (r'notify connect (true|false)', 'connection'),
        (r'notify speed ([0-9]+)', 'speed'),
        (r'notify --> (-?[0-9]+)', 'queue_error'),
        (r'event ([0-9a-f]{2}) --> (-?[0-9]+)', 'completion_error'),
        (r'(activate ecm|init ecm|reset ecm|ecm deactivated|ECM Suspend|ECM Resume)', 'lifecycle'),
    )
    for row in rows:
        message = row.get('MESSAGE', '')
        if not isinstance(message, str):
            continue
        for pattern, kind in patterns:
            match = re.fullmatch(re.escape(prefix) + pattern, message)
            if match:
                stamp = row.get('__MONOTONIC_TIMESTAMP', '')
                if not isinstance(stamp, str) or not stamp.isdecimal():
                    raise ValueError('Missing ECM journal monotonic timestamp')
                events.append(dict(kind=kind, values=list(match.groups()), monotonic_seconds=int(stamp)/1e6))
    return dict(journal_rows=len(rows), events=events)


def endpoint_return_text_trusted(formats):
    # Old udc_log_ep prints the generated printer's local ret, not the event's
    # saved result. Keep old images usable, but explicitly label that text.
    for name in ('gadget/usb_ep_enable', 'gadget/usb_ep_disable'):
        text = formats.get(name, '')
        lines = [line for line in text.splitlines() if line.startswith('print fmt:')]
        if ('field:int ret;' not in text or len(lines) != 1 or
                not re.search(r',\s*REC->ret\s*$', lines[0])):
            return False
    return True


def restore(token):
    run_id(token)
    if not OWNED.exists():
        return
    saved = json.loads(OWNED.read_text())
    if saved.get('run_id') != token or saved.get('boot_id') != BOOT.read_text().strip():
        raise ValueError('USB trace belongs to another boot/run; ownership retained')
    failure = None
    instance = TRACE/'instances'/INSTANCE
    try:
        if instance.exists():
            (instance/'tracing_on').write_text('0\n')
            (instance/'events/enable').write_text('0\n')
            instance.rmdir()
    except BaseException as error:
        failure = error
    try:
        current = sites(DEBUG.read_text())
        original = saved['sites']
        if (len(original) != len(current) or any(
                {k: s[k] for k in ('line', 'function', 'message')} !=
                {k: c[k] for k in ('line', 'function', 'message')} or
                s['flags'] != '_' or c['flags'] not in ('_', 'p') for s, c in zip(original, current))):
            raise ValueError('ECM sites changed outside the recorder; ownership retained')
        for site in original:
            set_site(site, '_')
        if sites(DEBUG.read_text()) != original:
            raise ValueError('ECM logging restoration readback differs')
    except BaseException as error:
        failure = failure or error
    if failure:
        raise failure
    OWNED.unlink()


@contextmanager
def capture(record, token):
    run_id(token)
    instance = TRACE/'instances'/INSTANCE
    if OWNED.exists() or instance.exists():
        raise ValueError('Existing USB trace; preserve before another capture')
    before = state()
    original = sites(DEBUG.read_text())
    if any(s['flags'] != '_' for s in original):
        raise ValueError('ECM diagnostics already enabled; refuse concurrent ownership')
    formats = {}
    for name, (_, fields) in EVENTS.items():
        formats[name] = (TRACE/'events'/name/'format').read_text()
        if not all(field in formats[name] for field in fields):
            raise ValueError('Unexpected USB/PM trace format: '+name)
    cursor = json.loads(command('journalctl', '-k', '-b', '-n', '1', '-o', 'json', '--no-pager'))['__CURSOR']
    keypad_pm.save_owned(dict(run_id=token, boot_id=before['boot_id'], sites=original), OWNED)
    record.update(before=before, formats=formats, sites_before=original, buffer_kb_per_cpu=256,
                  endpoint_return_text_trusted=endpoint_return_text_trusted(formats),
                  started_monotonic=time.monotonic(), filters={})
    completed = False
    try:
        instance.mkdir()
        (instance/'tracing_on').write_text('0\n')
        (instance/'current_tracer').write_text('nop\n')
        (instance/'buffer_size_kb').write_text('256\n')
        (instance/'trace_clock').write_text('mono\n')
        if '[mono]' not in (instance/'trace_clock').read_text():
            raise ValueError('USB trace clock readback differs')
        for name, (expression, _) in EVENTS.items():
            event = instance/'events'/name
            if expression:
                (event/'filter').write_text(expression+'\n')
                actual = (event/'filter').read_text().strip()
                if re.sub(r'\s', '', actual) != re.sub(r'\s', '', expression):
                    raise ValueError('USB trace filter readback differs')
                record['filters'][name] = actual
            (event/'enable').write_text('1\n')
            if (event/'enable').read_text().strip() != '1':
                raise ValueError('USB trace event enable failed')
        for site in original:
            set_site(site, 'p')
        if sites(DEBUG.read_text()) != [s | {'flags': 'p'} for s in original]:
            raise ValueError('ECM logging enable readback differs')
        (instance/'tracing_on').write_text('1\n')
        (instance/'trace_marker').write_text('usb-trace-start '+token+'\n')
        yield
        (instance/'trace_marker').write_text('usb-trace-end '+token+'\n')
        completed = True
    finally:
        try:
            if instance.exists():
                (instance/'tracing_on').write_text('0\n')
                with (instance/'trace').open() as source:
                    record['trace'] = source.read(8*1024*1024+1)
                if len(record['trace']) > 8*1024*1024:
                    raise ValueError('USB trace text exceeded bound')
                record['trace_stats'] = {p.parent.name: p.read_text() for p in (instance/'per_cpu').glob('cpu*/stats')}
                record['trace_lost'] = trace_lost(record['trace_stats'])
            record['ecm'] = summarize_journal(command('journalctl', '-k', '-b', '--cursor='+cursor,
                                                      '-n', '2002', '-o', 'json', '--no-pager'), cursor,
                                              before['ecm_log_prefix'])
            record['after'] = state()
        finally:
            restore(token)
            record['restored'] = not OWNED.exists() and not instance.exists()
            record['finished_monotonic'] = time.monotonic()
        if record.get('trace_lost') is not False:
            raise ValueError('Incomplete USB metadata trace')
        if completed and any(record['trace'].count(marker+token) != 1
                             for marker in ('usb-trace-start ', 'usb-trace-end ')):
            raise ValueError('Missing or duplicate USB trace boundary')


def sample(token):
    directory = RESULTS/run_id(token)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = dict(run_id=token, passed=False, limits='Passive awake capture; no notification, resume or energy qualification.',
                  sources={n: hashlib.sha256(Path(__file__).with_name(n+'.py').read_bytes()).hexdigest()
                           for n in ('usb_trace', 'wifi_trace', 'keypad_pm')})
    try:
        with keypad_pm.exclusive_pm(OWNED.parent):
            with capture(record, token):
                if record['before']['state'] != 'configured' or record['before']['carrier'] != '1':
                    raise ValueError('Awake USB sample requires a configured working link')
                time.sleep(10)
            if record['before'] != record['after']:
                raise ValueError('USB or PM state changed during passive sample')
            record['passed'] = True
    except BaseException as error:
        record['error'] = type(error).__name__+': '+str(error)
        raise
    finally:
        with (directory/'result.json').open('x') as output:
            json.dump(record, output)
            output.flush()
            os.fsync(output.fileno())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--sample', action='store_true')
    mode.add_argument('--restore', action='store_true')
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if args.restore:
        with keypad_pm.exclusive_pm(OWNED.parent):
            restore(args.run_id)
    else:
        def interrupted(signum, _frame):
            raise SystemExit(128+signum)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, interrupted)
        sample(args.run_id)
