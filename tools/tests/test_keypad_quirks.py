"""Exercise exact-port mutation, crash recovery and rejected comparison evidence."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import keypad_pm as keypad
from test_keypad_persistence import info, PORT
import test_keypad_retention as retention_tests
spec = importlib.util.spec_from_file_location('quirks_host', TOOLS/'check-pm-stages.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class PortQuirks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.usb = self.root / PORT.lstrip('/')
        self.port = self.usb.parent / '1-0:1.0/usb1-port1'
        self.port.mkdir(parents=True)
        self.usb.mkdir()
        (self.usb/'port').symlink_to(self.port)
        (self.port/'device').symlink_to(self.usb)
        self.value = self.port/'quirks'
        self.value.write_text('00000080\n')  # Unrelated bit must survive.
        (self.usb/'quirks').write_text('00000100\n')  # Device quirks are distinct.
        self.current = info()
        self.globals = {'old_scheme_first': 'N', 'use_both_schemes': 'Y'}
        self.enterContext(patch.object(keypad, 'QUIRKS_OWNED', self.root/'owner.json'))
        self.enterContext(patch.object(keypad, 'Path', side_effect=lambda p:
            self.root / p.lstrip('/') if isinstance(p, str) and p.startswith('/sys/') else Path(p)))
        self.enterContext(patch.object(keypad, 'inspect', side_effect=lambda: deepcopy(self.current)))
        self.enterContext(patch.object(keypad, 'optional', side_effect=lambda p:
            'boot-one' if str(p).endswith('/boot_id') else self.globals[Path(p).name]))

    def test_each_candidate_restores_on_normal_return_and_exception(self):
        for mode, bits in keypad.QUIRK_MODES.items():
            for failed in (False, True):
                record = {}
                try:
                    with keypad.port_quirks(record, mode):
                        self.assertEqual(int(self.value.read_text(), 16), 0x80 | bits)
                        self.assertEqual(keypad.QUIRKS_OWNED.stat().st_mode & 0o777, 0o600)
                        if failed:
                            raise InterruptedError('termination')
                except InterruptedError:
                    pass
                self.assertEqual(int(self.value.read_text(), 16), 0x80)
                self.assertTrue(record['restored'])
                self.assertFalse(keypad.QUIRKS_OWNED.exists())
                self.assertEqual((self.usb/'quirks').read_text(), '00000100\n')
                self.assertEqual(self.globals, {'old_scheme_first': 'N', 'use_both_schemes': 'Y'})

    def test_fresh_recovery_uses_saved_record_after_interruption(self):
        with self.assertRaises(OSError), patch.object(keypad, 'restore_port_quirks', side_effect=OSError('killed')):
            with keypad.port_quirks({}, 'old-scheme'):
                pass
        self.assertEqual(int(self.value.read_text(), 16), 0x81)
        self.assertTrue(keypad.QUIRKS_OWNED.exists())
        keypad.restore_port_quirks()
        self.assertEqual(int(self.value.read_text(), 16), 0x80)
        self.assertFalse(keypad.QUIRKS_OWNED.exists())

    def test_replaced_identity_wrong_boot_and_concurrent_change_keep_record(self):
        with self.assertRaises(OSError), patch.object(keypad, 'restore_port_quirks', side_effect=OSError('killed')):
            with keypad.port_quirks({}, 'old-scheme'):
                pass
        saved = json.loads(keypad.QUIRKS_OWNED.read_text())
        for change in ({'boot_id': 'other'}, {'original': -1}, {'original': 0x81},
                       {'identity': saved['identity'] | {'descriptors_hex': 'replacement'}},
                       {'port': '/sys/unrelated'}, {'applied': 0x83}):
            keypad.QUIRKS_OWNED.write_text(json.dumps(saved | change))
            with self.assertRaises(ValueError):
                keypad.restore_port_quirks()
            self.assertTrue(keypad.QUIRKS_OWNED.exists())
            self.assertEqual(int(self.value.read_text(), 16), 0x81)
        keypad.QUIRKS_OWNED.write_text(json.dumps(saved))
        self.value.write_text('00000085\n')
        with self.assertRaises(ValueError):
            keypad.restore_port_quirks()
        self.assertEqual(int(self.value.read_text(), 16), 0x85)
        self.value.write_text('00000081\n')
        keypad.restore_port_quirks()

    def test_changed_globals_do_not_prevent_port_restoration(self):
        with self.assertRaises(ValueError), keypad.port_quirks({}, 'fast-recovery'):
            self.globals['old_scheme_first'] = 'Y'
        self.assertEqual(int(self.value.read_text(), 16), 0x80)
        self.assertEqual(self.globals['old_scheme_first'], 'Y')
        self.assertFalse(keypad.QUIRKS_OWNED.exists())

    def test_wrong_topology_backlink_existing_owner_and_policy_never_enter(self):
        self.current['usb']['path'] = '/sys/other'
        with self.assertRaises(ValueError), keypad.port_quirks({}, 'old-scheme'):
            self.fail('Wrong topology accepted')
        self.current = info()
        (self.port/'device').unlink()
        (self.port/'device').symlink_to(self.usb.parent)
        with self.assertRaises(ValueError), keypad.port_quirks({}, 'old-scheme'):
            self.fail('Wrong port accepted')
        (self.port/'device').unlink()
        (self.port/'device').symlink_to(self.usb)
        for value in ('00000081\n', 'garbage\n'):
            self.value.write_text(value)
            with self.assertRaises(ValueError), keypad.port_quirks({}, 'old-scheme'):
                self.fail('Non-baseline port accepted')
            self.assertEqual(self.value.read_text(), value)
        self.value.write_text('00000080\n')
        self.globals['old_scheme_first'] = 'Y'
        with self.assertRaises(ValueError), keypad.port_quirks({}, 'old-scheme'):
            self.fail('Global old scheme accepted')
        self.globals['old_scheme_first'] = 'N'
        keypad.QUIRKS_OWNED.write_text('foreign')
        with self.assertRaises(FileExistsError), keypad.port_quirks({}, 'old-scheme'):
            self.fail('Foreign owner accepted')
        self.assertEqual(keypad.QUIRKS_OWNED.read_text(), 'foreign')
        self.assertEqual(int(self.value.read_text(), 16), 0x80)

    def test_failed_candidate_readback_never_enters_and_restores(self):
        actual = Path.write_text
        def write(path, text, *args, **kwargs):
            return len(text) if path == self.value and text == '00000081\n' else actual(path, text, *args, **kwargs)
        with patch.object(Path, 'write_text', write):
            with self.assertRaises(ValueError), keypad.port_quirks({}, 'old-scheme'):
                self.fail('Failed write accepted')
        self.assertEqual(int(self.value.read_text(), 16), 0x80)
        self.assertFalse(keypad.QUIRKS_OWNED.exists())


class Comparison(unittest.TestCase):
    def result(self, mode):
        r = retention_tests.RetentionTests().fixture()
        before = info()
        before['usb']['attributes']['devnum'] = '2'
        r['keypad'].update(before=before, after=deepcopy(before))
        r['keypad']['trace'] = (' p [0] ... 20.000000: device_pm_callback_start: usb 1-1, parent: usb1, type [resume]\n'
            ' p [0] ... 21.100000: device_pm_callback_end: usb 1-1, err=0\n'
            ' p [0] ... 21.200000: device_pm_callback_start: usb 1-1, parent: usb1, [resume]\n'
            ' p [0] ... 21.300000: device_pm_callback_end: usb 1-1, err=0\n')
        baseline = dict(path='port', value=0, globals={'old_scheme_first':'N','use_both_schemes':'Y'})
        applied = baseline | {'value': keypad.QUIRK_MODES[mode]}
        r['port_quirks'] = dict(mode=mode, original=0, requested=applied['value'], before=baseline,
            after_restore=deepcopy(baseline), applied=applied, after_stage=deepcopy(applied),
            identity=keypad.keypad_identity(before), restored=True)
        r['before'].update(boot_id='boot', kernel='kernel', wifi_config_sha256='hash',
                           cpu_policy={}, charger={}, backlight={})
        return r

    def test_valid_result_and_rejected_continuity_policy_or_trace(self):
        r = self.result('old-scheme')
        self.assertAlmostEqual(host.validate_quirk_result(r, 'old-scheme')['usb_resume_seconds'], 1.1)
        for corrupt in ('restore','handle','power','trace','global','port','identity'):
            r = self.result('old-scheme')
            if corrupt == 'restore': r['port_quirks']['restored'] = False
            if corrupt == 'handle': r['keypad']['old_handle_after']['hung_up'] = True
            if corrupt == 'power': r['keypad']['before']['usb']['power']['persist'] = '0'
            if corrupt == 'trace': r['keypad']['trace'] = r['keypad']['trace'].replace('err=0','err=-1')
            if corrupt == 'global': r['port_quirks']['after_stage']['globals']['use_both_schemes'] = 'N'
            if corrupt == 'port': r['port_quirks']['after_stage']['path'] = 'other'
            if corrupt == 'identity': r['keypad']['after']['usb']['descriptors_hex'] = 'replacement'
            with self.subTest(corrupt=corrupt), self.assertRaises(ValueError):
                host.validate_quirk_result(r, 'old-scheme')
        r = self.result('old-scheme')
        r['keypad']['trace'] *= 2
        with self.assertRaises(ValueError): host.validate_quirk_result(r,'old-scheme')

    def test_fixed_order_and_failure_stops_without_resubmitting(self):
        for failure in (None, 'candidate', 'boot'):
            values = []
            def cycle(*args, keypad_quirk):
                values.append(keypad_quirk)
                if failure == 'candidate' and keypad_quirk == 'old-scheme':
                    raise RuntimeError('device failed')
                result = self.result(keypad_quirk)
                if failure == 'boot' and len(values) == 2:
                    result['before']['boot_id'] = 'other'
                return result
            with tempfile.TemporaryDirectory() as d, patch.object(host, 'cycle', side_effect=cycle), \
                    patch.object(host.time, 'sleep'):
                args = ({},Path(d),{'experiments':{'keypad_supply_retention':True}},'old-scheme',1)
                if failure:
                    with self.assertRaises((RuntimeError,ValueError)): host.compare_quirks(*args)
                else:
                    host.compare_quirks(*args)
                report = json.loads((Path(d)/'comparison.json').read_text())
                self.assertEqual(report['passed'], failure is None)
                self.assertEqual(values, ['baseline','old-scheme'] if failure else ['baseline','old-scheme','baseline'])

    def test_no_untraced_freezer_or_combined_persistence_mutation(self):
        for stage, trace, persist, mode in (('freezer',True,None,'old-scheme'),
                ('devices',False,None,'old-scheme'), ('devices',True,'0','old-scheme'),
                ('devices',True,None,'combined')):
            with self.assertRaises(ValueError):
                host.service_command('/tmp/gameshellneo-pm.test',stage,'a'*32,trace,persist,keypad_quirk=mode)
        command = host.service_command('/tmp/gameshellneo-pm.test','devices','a'*32,True,
                                        keypad_input=True,keypad_audio=True,keypad_quirk='old-scheme')
        self.assertEqual(command[-2:], ['--keypad-quirk','old-scheme'])


if __name__ == '__main__':
    unittest.main()
