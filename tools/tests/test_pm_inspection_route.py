"""Keep route selection read-only and preserve failures without fallback or PM."""
from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('pm_inspection_route', TOOLS / 'check-pm-stages.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class InspectionRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.capture = Path(self.temporary.name)
        self.enterContext(patch.dict(os.environ, {'NEO_ROUTE': 'wifi'}, clear=True))
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(redirect_stderr(io.StringIO()))
        self.config = self.enterContext(patch.object(host, 'load_env', return_value={'private': 'placeholder'}))
        self.directory = self.enterContext(patch.object(host, 'evidence_directory', return_value=self.capture))
        self.device = self.enterContext(patch.object(host, 'device'))
        self.client = self.device.return_value.__enter__.return_value
        self.snapshot = dict(kernel='kernel', boot_id='boot', pm={}, pm_test_delay='5', rsb={})
        self.inline = self.enterContext(patch.object(host, 'inline', return_value=json.dumps(self.snapshot).encode()))
        self.operations = [self.enterContext(patch.object(host, name)) for name in
                           ('run', 'upload', 'collect', 'cycle', 'wifi_smoke', 'compare_keypad', 'compare_quirks')]

    def invoke(self, *arguments):
        with patch.object(sys, 'argv', ['check-pm-stages.py', *arguments]):
            host.main()

    def test_inspection_uses_usb_by_default_despite_general_wifi_default(self):
        self.invoke('--inspect')
        self.device.assert_called_once_with(self.config.return_value, 'usb')
        self.inline.assert_called_once_with(self.client, '--inspect')
        self.assertEqual(json.loads((self.capture / 'inspection.json').read_text()), self.snapshot)
        self.assertEqual(json.loads((self.capture / 'route.json').read_text()),
                         dict(operation='pm.inspect', route='usb'))
        for operation in self.operations:
            operation.assert_not_called()

    def test_explicit_and_task_environment_wifi_route_are_used(self):
        for cli in (False, True):
            with self.subTest(cli=cli):
                self.device.reset_mock()
                self.inline.reset_mock()
                with patch.dict(os.environ, {'NEO_PM_INSPECT_ROUTE': 'usb' if cli else 'wifi'}):
                    self.invoke('--inspect', *(['--inspect-route', 'wifi'] if cli else []))
                self.device.assert_called_once_with(self.config.return_value, 'wifi')
                self.inline.assert_called_once_with(self.client, '--inspect')
                self.assertEqual(json.loads((self.capture / 'route.json').read_text())['route'], 'wifi')
        for operation in self.operations:
            operation.assert_not_called()

    def test_invalid_routes_and_noninspection_modes_reject_before_work(self):
        for mode in ('--test', '--collect', '--restore', '--keypad-compare', '--keypad-retention',
                     '--keypad-input', '--keypad-quirks', '--wifi-smoke', '--platform'):
            for route in ('usb', 'wifi'):
                with self.subTest(mode=mode, route=route), self.assertRaises(SystemExit):
                    self.invoke(mode, '--inspect-route', route)
        for route in ('', 'ethernet', 'wifi;false'):
            with self.subTest(route=route), patch.dict(os.environ, {'NEO_PM_INSPECT_ROUTE': route}), \
                    self.assertRaises(SystemExit):
                self.invoke('--inspect')
        self.config.assert_not_called()
        self.directory.assert_not_called()
        self.device.assert_not_called()

    def test_transport_failure_is_not_retried_or_changed_to_usb(self):
        failure = RuntimeError('SSH greeting unavailable')
        self.device.side_effect = failure
        with self.assertRaises(RuntimeError) as caught:
            self.invoke('--inspect', '--inspect-route', 'wifi')
        self.assertIs(caught.exception, failure)
        self.device.assert_called_once_with(self.config.return_value, 'wifi')
        self.assertFalse((self.capture / 'inspection.json').exists())
        self.assertEqual(json.loads((self.capture / 'route.json').read_text())['route'], 'wifi')
        self.inline.assert_not_called()
        for operation in self.operations:
            operation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
