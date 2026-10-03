"""USB tracing failure/ownership boundaries without a device or PM submission."""
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import usb_trace as trace

spec = importlib.util.spec_from_file_location('usb_trace_host', TOOLS/'check-usb-trace.py')
host = importlib.util.module_from_spec(spec); spec.loader.exec_module(host)
TOKEN = 'a'*32
PREFIX = 'configfs-gadget.gameshellneo gadget.0: '


def debug_text():
    entries = [(f, m) for f, messages in trace.MESSAGES.items() for m in sorted(messages)]
    return '\n'.join(f'{trace.ECM}:{i+1} [usb_f_ecm]{f} =_ "{m}"' for i, (f, m) in enumerate(entries))


def journal(*messages):
    return '\n'.join([json.dumps({'__CURSOR': 'start'})] + [json.dumps(dict(
        __MONOTONIC_TIMESTAMP='123456', MESSAGE=message)) for message in messages])


class Parsing(unittest.TestCase):
    def test_endpoint_return_format_detects_shadowed_or_missing_record_field(self):
        names = ('gadget/usb_ep_enable', 'gadget/usb_ep_disable')
        good = 'field:int ret;\nprint fmt: "endpoint --> %d", REC->ret\n'
        formats = dict.fromkeys(names, good)
        self.assertTrue(trace.endpoint_return_text_trusted(formats))
        for bad in (good.replace('REC->ret', 'ret'), good.replace('REC->ret', '1'),
                    good.replace('field:int ret;', ''), good+'print fmt: "bad", REC->ret\n', ''):
            for name in names:
                self.assertFalse(trace.endpoint_return_text_trusted(formats | {name: bad}))

    def test_only_audited_ecm_sites_are_selected(self):
        text = debug_text()
        self.assertEqual(len(trace.sites(text)), 10)
        extra = f'\n{trace.ECM}:100 [usb_f_ecm]ecm_setup =_ "packet filter %02x\\n"'
        self.assertEqual(trace.sites(text+extra), trace.sites(text))
        for bad in (text.replace('notify speed %d', 'unexpected %s'), text.split('\n', 1)[1], text+'\n'+text):
            with self.assertRaises(ValueError): trace.sites(bad)

    def test_journal_captures_only_typed_metadata(self):
        result = trace.summarize_journal(journal(
            'configfs-gadget.gameshellneo gadget.0: notify connect true',
            'configfs-gadget.gameshellneo gadget.0: notify speed 8519680',
            'configfs-gadget.gameshellneo gadget.0: notify --> -108',
            'configfs-gadget.gameshellneo gadget.0: event 2a --> -5',
            'configfs-gadget.gameshellneo gadget.0: ECM Resume',
            'configfs-gadget other: notify connect true',
            'configfs-gadget.gameshellneo gadget.0: notify connect true private-data',
            'secret-network-and-password'), 'start', PREFIX)
        self.assertEqual(len(result['events']), 5)
        self.assertNotIn('private-data', json.dumps(result))
        self.assertNotIn('secret-network', json.dumps(result))
        self.assertEqual(result['events'][3]['values'], ['2a', '-5'])

    def test_journal_missing_cursor_overflow_or_timestamp_reject(self):
        for text in ('', journal().replace('start', 'other'), journal(*(['ignored']*2001)),
                     journal('configfs-gadget.gameshellneo gadget.0: ECM Suspend').replace('123456', 'bad')):
            with self.assertRaises(ValueError): trace.summarize_journal(text, 'start', PREFIX)

    def test_short_request_capture_does_not_include_payload_or_bulk_irq_stream(self):
        self.assertEqual(trace.EVENTS['musb/musb_isr'][0], 'int_usb != 0')
        self.assertNotIn('musb/musb_log', trace.EVENTS)
        self.assertFalse(any('read' in n or 'write' in n for n in trace.EVENTS))
        for name in ('gadget/usb_ep_queue', 'gadget/usb_gadget_giveback_request'):
            self.assertEqual(trace.EVENTS[name][0], 'name == "ep0" || length == 8 || length == 16')


class Capture(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for key, name in (('TRACE', 'trace'), ('DEBUG', 'debug'), ('BOOT', 'boot'), ('OWNED', 'owner')):
            self.enterContext(patch.object(trace, key, root/name))
        trace.BOOT.write_text('boot'); trace.DEBUG.write_text(debug_text())
        (trace.TRACE/'instances').mkdir(parents=True)
        for name, (_, fields) in trace.EVENTS.items():
            event = trace.TRACE/'events'/name; event.mkdir(parents=True)
            (event/'format').write_text('\n'.join(fields))
        self.enterContext(patch.object(trace, 'state', return_value=dict(boot_id='boot', state='configured', carrier='1', ecm_log_prefix=PREFIX)))
        self.enterContext(patch.object(trace, 'command', side_effect=lambda *a: journal()))
        self.instance = trace.TRACE/'instances'/trace.INSTANCE
        self.mkdir, self.rmdir, self.write = Path.mkdir, Path.rmdir, Path.write_text
        self.enterContext(patch.object(Path, 'mkdir', lambda path, *a, **kw: self.mkdir_trace(path, *a, **kw)))
        self.enterContext(patch.object(Path, 'rmdir', lambda path, *a, **kw: self.rmdir_trace(path, *a, **kw)))
        self.enterContext(patch.object(Path, 'write_text', lambda path, *a, **kw: self.write_trace(path, *a, **kw)))

    def mkdir_trace(self, path, *args, **kwargs):
        self.mkdir(path, *args, **kwargs)
        if path == self.instance:
            for name in trace.EVENTS:
                self.mkdir(path/'events'/name, parents=True)
                self.write(path/'events'/name/'filter', 'none')
            self.mkdir(path/'per_cpu/cpu0', parents=True)
            self.write(path/'per_cpu/cpu0/stats', 'overrun: 0\ncommit overrun: 0\ndropped events: 0\n')
            self.write(path/'trace', '')

    def rmdir_trace(self, path, *args, **kwargs):
        if path == self.instance:
            for child in path.iterdir():
                if child.is_dir(): shutil.rmtree(child)
                else: child.unlink()
        return self.rmdir(path, *args, **kwargs)

    def write_trace(self, path, text, *args, **kwargs):
        if path == trace.DEBUG:
            # Simulate kernel dynamic-debug control, preserving the site catalogue.
            fields = text.split(); line, flags = int(fields[3]), fields[4][1:]
            entries = trace.DEBUG.read_text().splitlines()
            entries[line-1] = entries[line-1].replace(' =_ ', ' ='+flags+' ').replace(' =p ', ' ='+flags+' ')
            text = '\n'.join(entries)
        elif path == self.instance/'trace_clock':
            text = '['+text.strip()+']'
        elif path == self.instance/'trace_marker':
            self.write(self.instance/'trace', (self.instance/'trace').read_text()+text)
        return self.write(path, text, *args, **kwargs)

    def assert_clean(self, record):
        self.assertFalse(trace.OWNED.exists()); self.assertFalse(self.instance.exists())
        self.assertEqual(trace.DEBUG.read_text(), debug_text())
        self.assertTrue(record['restored'])

    def test_capture_restores_global_logging_and_owned_instance(self):
        record = {}
        with trace.capture(record, TOKEN):
            self.assertTrue(all(s['flags'] == 'p' for s in trace.sites(trace.DEBUG.read_text())))
        self.assert_clean(record); self.assertFalse(record['trace_lost'])
        self.assertEqual(record['trace'].count(TOKEN), 2)

    def test_body_exception_and_signal_still_restore(self):
        for error in (RuntimeError('operation failed'), SystemExit(143)):
            record = {}
            with self.assertRaises(type(error)):
                with trace.capture(record, TOKEN): raise error
            self.assert_clean(record)

    def test_loss_and_missing_journal_cursor_fail_after_restoration(self):
        record = {}
        with self.assertRaisesRegex(ValueError, 'Incomplete USB'):
            with trace.capture(record, TOKEN):
                (self.instance/'per_cpu/cpu0/stats').write_text('overrun: 1\n')
        self.assert_clean(record)
        with self.assertRaisesRegex(ValueError, 'cursor'):
            with trace.capture(record, TOKEN):
                self.enterContext(patch.object(trace, 'command', return_value=''))
        self.assert_clean(record)

    def test_partial_setup_error_restores_already_enabled_sites(self):
        setter = trace.set_site
        def failing(site, flags):
            if site['line'] == 3 and flags == 'p': raise OSError('injected site write error')
            return setter(site, flags)
        record = {}
        with patch.object(trace, 'set_site', side_effect=failing), self.assertRaises(OSError):
            with trace.capture(record, TOKEN): self.fail('Partial setup accepted')
        self.assert_clean(record)

    def test_lost_boundary_fails_even_if_ring_buffer_reports_no_overrun(self):
        record = {}
        with self.assertRaisesRegex(ValueError, 'boundary'):
            with trace.capture(record, TOKEN):
                (self.instance/'trace').write_text('')
        self.assert_clean(record)

    def test_instance_removal_failure_still_restores_logging_and_retains_owner(self):
        record = {}
        with patch.object(Path, 'rmdir', side_effect=OSError('busy')), self.assertRaises(OSError):
            with trace.capture(record, TOKEN): pass
        self.assertEqual(trace.DEBUG.read_text(), debug_text()); self.assertTrue(trace.OWNED.exists())
        trace.restore(TOKEN); self.assertFalse(trace.OWNED.exists())

    def test_foreign_run_and_boot_never_restore(self):
        with trace.capture({}, TOKEN):
            for token in ('b'*32, '../bad'):
                with self.assertRaises(ValueError): trace.restore(token)
            trace.BOOT.write_text('other')
            with self.assertRaises(ValueError): trace.restore(TOKEN)
            trace.BOOT.write_text('boot')
            with self.assertRaises(ValueError):
                with trace.capture({}, 'b'*32): self.fail('Concurrent recorder admitted')

    def test_unexpected_logging_stops_owned_trace_but_preserves_foreign_flags(self):
        with self.assertRaisesRegex(ValueError, 'outside the recorder'):
            with trace.capture({}, TOKEN):
                self.write(trace.DEBUG, trace.DEBUG.read_text().replace(' =p ', ' =pf ', 1))
        self.assertFalse(self.instance.exists()); self.assertTrue(trace.OWNED.exists())
        self.assertIn(' =pf ', trace.DEBUG.read_text())

    def test_format_and_existing_logging_fail_before_mutation(self):
        with patch.object(trace, 'state'), self.assertRaises(ValueError):
            (trace.TRACE/'events/musb/musb_isr/format').write_text('unknown')
            with trace.capture({}, TOKEN): self.fail('Bad format admitted')
        self.assertFalse(trace.OWNED.exists()); self.assertFalse(self.instance.exists())
        self.write(trace.DEBUG, debug_text().replace(' =_ ', ' =p ', 1))
        with self.assertRaisesRegex(ValueError, 'already enabled'):
            with trace.capture({}, TOKEN): self.fail('Existing logging admitted')


class Host(unittest.TestCase):
    def test_service_is_device_owned_with_exact_run_cleanup_and_no_pm(self):
        command = host.service('/tmp/gameshellneo-usb-trace.test', TOKEN)
        self.assertIn('--wait', command); self.assertNotIn('--pipe', command)
        self.assertIn('--sample', command)
        self.assertIn('--property=ExecStopPost=/usr/bin/python3 -B /tmp/gameshellneo-usb-trace.test/usb_trace.py --restore --run-id '+TOKEN, command)
        for bad in ('/tmp/other', '/tmp/gameshellneo-usb-trace.a;true'):
            with self.assertRaises(ValueError): host.service(bad, TOKEN)

    def test_collection_retains_failed_result_and_does_not_restore(self):
        result = dict(run_id=TOKEN, passed=False, error='trace failed')
        with patch.object(host, 'device', return_value=nullcontext('client')) as device, \
                patch.object(host, 'run', return_value=json.dumps(result).encode()) as run:
            self.assertEqual(host.collect({}, TOKEN, 'wifi'), result)
            device.assert_called_once_with({}, 'wifi')
            self.assertTrue(run.call_args.args[1].startswith('sudo -n cat '))
        with patch.object(host, 'device', return_value=nullcontext('client')), \
                patch.object(host, 'run', return_value=json.dumps(result | {'run_id': 'b'*32}).encode()):
            with self.assertRaises(ValueError): host.collect({}, TOKEN, 'usb')


if __name__ == '__main__':
    unittest.main()
