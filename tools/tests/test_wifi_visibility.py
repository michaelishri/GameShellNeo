"""Scan summaries must match encoded SSIDs without disclosing network names."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('visibility',
    Path(__file__).resolve().parents[1] / 'check-wifi-visibility.py')
visibility = importlib.util.module_from_spec(spec)
spec.loader.exec_module(visibility)
HEADER = 'bssid / frequency / signal level / flags / ssid\n'


class VisibilityTests(unittest.TestCase):
    def test_matches_encoded_ssid_and_omits_names_and_addresses(self):
        scan = HEADER + ('02:00:00:00:00:01\t2412\t-57\t[WPA2-PSK-CCMP][ESS]\tCaf\\xc3\\xa9\n'
                         '02:00:00:00:00:02\t2462\t-71\t[ESS]\tOther private network\n')
        result = visibility.summarize(scan, 'Café')
        self.assertEqual(result['visible_entries'], 2)
        self.assertEqual(result['target_matches'][0]['frequency_mhz'], 2412)
        for secret in ('Café', 'Other private network', '02:00:00'):
            self.assertNotIn(secret, json.dumps(result))

    def test_same_prefix_is_not_a_match(self):
        result = visibility.summarize(HEADER + '02:00:00:00:00:01\t2412\t-57\t[ESS]\tTarget-extra\n', 'Target')
        self.assertEqual(result['target_matches'], [])

    def test_failed_or_malformed_reply_is_not_empty_success(self):
        for reply in ('FAIL\n', HEADER + 'private invalid row\n'):
            with self.assertRaises(ValueError) as error:
                visibility.summarize(reply, 'secret')
            self.assertNotIn('private invalid row', str(error.exception))


if __name__ == '__main__':
    unittest.main()
