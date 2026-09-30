"""Exercise scoped persistence mutation, re-enumeration and independent recovery."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import keypad_pm as keypad

HOST_SPEC = importlib.util.spec_from_file_location('keypad_host',
    Path(__file__).resolve().parents[1] / 'check-pm-stages.py')
host = importlib.util.module_from_spec(HOST_SPEC)
HOST_SPEC.loader.exec_module(host)

PORT = '/sys/devices/platform/soc/1c1a400.usb/usb1/1-1'


def info():
    return dict(boot_id='boot-one', usb=dict(path=PORT, descriptors_hex='fixture',
        attributes=dict(manufacturer='rancidbacon.com', product='UsbKeyboard',
                        bcdDevice='0100', speed='1.5'),
        power=dict(persist='1', control='on', wakeup=None)),
        inputs=[dict(name='rancidbacon.com UsbKeyboard', event='/dev/input/event1', sysfs='input1')])


class Persistence(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.value = self.root / 'power/persist'
        self.value.parent.mkdir()
        self.value.write_text('1\n')
        self.current = info()
        self.enterContext(patch.object(keypad, 'PERSIST_OWNED', self.root/'owner.json'))
        self.enterContext(patch.object(keypad, 'optional', return_value='boot-one'))
        self.enterContext(patch.object(keypad, 'Path', side_effect=lambda p:
            self.root if p == PORT else Path(p)))
        self.enterContext(patch.object(keypad, 'inspect', side_effect=self.inspect))

    def inspect(self):
        result = deepcopy(self.current)
        result['usb']['power']['persist'] = self.value.read_text().strip()
        return result

    def test_off_restores_after_reenumeration_or_exception(self):
        for failed in (False, True):
            record = {}
            try:
                with keypad.persistence(record, '0'):
                    self.assertEqual(self.value.read_text().strip(), '0')
                    self.current['inputs'][0].update(event='/dev/input/event4', sysfs='input9')
                    # Newly enumerated USB devices regain the kernel default.
                    self.value.write_text('1\n')
                    if failed:
                        raise InterruptedError('signal')
            except InterruptedError:
                pass
            self.assertEqual(self.value.read_text().strip(), '1')
            self.assertEqual(record['applied'], '0')
            self.assertTrue(record['restored'])
            self.assertFalse(keypad.PERSIST_OWNED.exists())

    def test_independent_restore_uses_saved_identity_and_fresh_input(self):
        identity = keypad.keypad_identity(self.inspect())
        keypad.save_owned(dict(boot_id='boot-one', original='1', identity=identity), keypad.PERSIST_OWNED)
        self.value.write_text('0\n')
        self.current['inputs'][0].update(event='/dev/input/event6', sysfs='input42')
        keypad.restore_persistence()
        self.assertEqual(self.value.read_text().strip(), '1')
        self.assertFalse(keypad.PERSIST_OWNED.exists())

    def test_unqualified_port_product_and_runtime_policy_never_write(self):
        for group, key, value in (('usb', 'path', '/sys/devices/other/usb1/1-1'),
                                 ('attributes', 'product', 'Storage'),
                                 ('attributes', 'bcdDevice', '0200'),
                                 ('power', 'control', 'auto'), ('power', 'wakeup', 'enabled')):
            self.current = info()
            target = self.current['usb'] if group == 'usb' else self.current['usb'][group]
            target[key] = value
            with self.assertRaises(ValueError), keypad.persistence({}, '0'):
                self.fail('Unqualified target accepted')
            self.assertEqual(self.value.read_text().strip(), '1')
            self.assertFalse(keypad.PERSIST_OWNED.exists())

    def test_ambiguous_device_or_existing_owner_is_preserved(self):
        with patch.object(keypad, 'inspect', side_effect=ValueError('Expected exactly one 4242:e131 keypad')):
            with self.assertRaises(ValueError), keypad.persistence({}, '0'):
                self.fail('Ambiguous target accepted')
        keypad.PERSIST_OWNED.write_text('foreign')
        with self.assertRaises(FileExistsError), keypad.persistence({}, '0'):
            self.fail('Foreign owner accepted')
        self.assertEqual(keypad.PERSIST_OWNED.read_text(), 'foreign')
        self.assertEqual(self.value.read_text().strip(), '1')

    def test_failed_restore_retains_owner_then_retry_succeeds(self):
        with self.assertRaises(OSError):
            with keypad.persistence({}, '0'):
                with patch.object(keypad, 'persist_write', side_effect=OSError('sysfs unavailable')):
                    keypad.restore_persistence()
        # The context's independent finally recovered after the injected failure.
        self.assertFalse(keypad.PERSIST_OWNED.exists())
        self.assertEqual(self.value.read_text().strip(), '1')
        keypad.save_owned(dict(boot_id='boot-one', original='1',
            identity=keypad.keypad_identity(self.inspect())), keypad.PERSIST_OWNED)
        with patch.object(keypad, 'persist_write', side_effect=OSError('sysfs unavailable')):
            with self.assertRaises(OSError):
                keypad.restore_persistence()
        self.assertTrue(keypad.PERSIST_OWNED.exists())
        keypad.restore_persistence()

    def test_wrong_boot_and_replaced_descriptor_cannot_restore(self):
        original = dict(boot_id='boot-one', original='1', identity=keypad.keypad_identity(self.inspect()))
        for change in ({'boot_id': 'another-boot'}, {'original': '0'},
                       {'identity': original['identity'] | {'descriptors_hex': 'other'}}):
            keypad.PERSIST_OWNED.write_text(json.dumps(original | change))
            self.value.write_text('0\n')
            with self.assertRaises(ValueError):
                keypad.restore_persistence()
            self.assertTrue(keypad.PERSIST_OWNED.exists())
            self.assertEqual(self.value.read_text().strip(), '0')

    def test_write_readback_failure_refuses_stage_and_restores(self):
        real_write = Path.write_text
        def write(path, text, *args, **kwargs):
            return len(text) if path == self.value and text == '0\n' else real_write(path, text, *args, **kwargs)
        with patch.object(Path, 'write_text', write):
            with self.assertRaises(ValueError), keypad.persistence({}, '0'):
                self.fail('Failed readback accepted')
        self.assertFalse(keypad.PERSIST_OWNED.exists())
        self.assertEqual(self.value.read_text().strip(), '1')

    def test_missing_device_during_recovery_is_bounded_and_keeps_owner(self):
        keypad.save_owned(dict(boot_id='boot-one', original='1',
            identity=keypad.keypad_identity(self.inspect())), keypad.PERSIST_OWNED)
        self.value.write_text('0\n')
        with patch.object(keypad, 'inspect', side_effect=FileNotFoundError('not enumerated')), \
                patch.object(keypad.time, 'monotonic', side_effect=[0, 11]):
            with self.assertRaises(FileNotFoundError):
                keypad.restore_persistence()
        self.assertTrue(keypad.PERSIST_OWNED.exists())
        keypad.restore_persistence()
        self.assertEqual(self.value.read_text().strip(), '1')

    def test_ready_wait_rejects_dead_reused_handle_then_accepts_fresh(self):
        expected = keypad.keypad_identity(self.inspect())
        bad = dict(ioctl_errno=19, hung_up=True, poll_error=True)
        good = dict(ioctl_errno=None, hung_up=False, poll_error=False)
        with patch.object(keypad.os, 'open', side_effect=[4, 5]), \
                patch.object(keypad.os, 'close') as close, \
                patch.object(keypad, 'handle_state', side_effect=[bad, good]), \
                patch.object(keypad.time, 'sleep'), \
                patch.object(keypad.time, 'monotonic', return_value=1):
            record = {}
            keypad.wait_ready(record, 0, expected)
        self.assertEqual(record['attempts'], 2)
        self.assertEqual(close.call_count, 2)
        self.assertEqual(record['handle'], good)

    def test_ready_wait_cannot_wait_forever_or_accept_a_replacement(self):
        expected = keypad.keypad_identity(self.inspect())
        with patch.object(keypad, 'inspect', side_effect=FileNotFoundError('gone')), \
                patch.object(keypad.time, 'monotonic', side_effect=[0, 11]):
            with self.assertRaises(TimeoutError):
                keypad.wait_ready({}, 0, expected)
        self.current['usb']['descriptors_hex'] = 'replacement'
        with self.assertRaises(ValueError):
            keypad.wait_ready({}, 0, expected)


class Comparison(unittest.TestCase):
    def result(self, value):
        return dict(run_id='a'*32, before=dict(boot_id='boot', kernel='kernel', wifi_config_sha256='hash',
            cpu_policy={}, charger={}, backlight={}), stage_seconds=9 if value == '1' else 6,
            keypad_ready_after_stage=dict(seconds=1),
            keypad=dict(old_handle_after=dict(disconnected=True)),
            persistence=dict(identity={'path':PORT}, restored=True))

    def test_fixed_on_off_on_order_and_no_retry_after_failure(self):
        for failure in (False, True):
            values = []
            def cycle(_config, _capture, _lock, stage, tracing, value):
                values.append(value)
                self.assertEqual((stage,tracing), ('devices',True))
                if failure and value == '0':
                    raise RuntimeError('incomplete recovery')
                return self.result(value)
            with tempfile.TemporaryDirectory() as d, patch.object(host, 'cycle', side_effect=cycle), \
                    patch.object(host.time, 'sleep'):
                capture = Path(d)
                if failure:
                    with self.assertRaises(RuntimeError): host.compare_keypad({},capture,{})
                else:
                    host.compare_keypad({},capture,{})
                report = json.loads((capture/'comparison.json').read_text())
                self.assertEqual(report['passed'], not failure)
                self.assertEqual(values, ['1','0'] if failure else ['1','0','1'])

    def test_service_requires_traced_devices_for_persistence(self):
        for stage, trace, value in (('freezer',True,'0'), ('devices',False,'0'),
                                    ('devices',True,'2'), ('devices',True,0)):
            with self.assertRaises(ValueError):
                host.service_command('/tmp/gameshellneo-pm.test',stage,'a'*32,trace,value)
        command = host.service_command('/tmp/gameshellneo-pm.test','devices','a'*32,True,'0')
        self.assertEqual(command[-2:], ['--keypad-persist','0'])

    def test_cross_phase_boot_change_rejects_comparison(self):
        results = [self.result('1'), self.result('0')]
        results[1]['before']['boot_id'] = 'changed'
        with tempfile.TemporaryDirectory() as d, patch.object(host, 'cycle', side_effect=results) as cycle, \
                patch.object(host.time, 'sleep'):
            with self.assertRaises(ValueError):
                host.compare_keypad({},Path(d),{})
            self.assertEqual(cycle.call_count, 2)
            self.assertFalse(json.loads((Path(d)/'comparison.json').read_text())['passed'])


if __name__ == '__main__':
    unittest.main()
