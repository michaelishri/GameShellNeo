"""macOS redaction must not turn an unknown SSID into a network mismatch."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('mac_wifi',
    Path(__file__).resolve().parents[1] / 'check-mac-wifi.py')
mac_wifi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mac_wifi)


class MacWifiTests(unittest.TestCase):
    def test_redacted_name_stays_unknown_while_band_is_retained(self):
        data = {'SPAirPortDataType': [{'spairport_airport_interfaces': [{
            'spairport_current_network_information': {'_name': '<redacted>',
                'spairport_network_channel': '48 (5GHz, 80MHz)'}}]}]}
        result = mac_wifi.summarize(data, 'private target')
        self.assertIsNone(result['interfaces'][0]['current_ssid_matches'])
        self.assertEqual(result['interfaces'][0]['current']['spairport_network_channel'], '48 (5GHz, 80MHz)')

    def test_exact_matches_omit_names_and_mac_addresses(self):
        network = {'_name': 'private target', 'spairport_network_channel': '6 (2GHz, 20MHz)',
                   'spairport_network_bssid': '00:00:00:00:00:01'}
        data = {'SPAirPortDataType': [{'spairport_airport_interfaces': [{
            'spairport_current_network_information': network,
            'spairport_airport_other_local_wireless_networks': [network]}]}]}
        result = mac_wifi.summarize(data, 'private target')
        self.assertTrue(result['interfaces'][0]['current_ssid_matches'])
        self.assertEqual(len(result['interfaces'][0]['target_cached_matches']), 1)
        self.assertNotIn('private target', json.dumps(result))
        self.assertNotIn('00:00:00:00:00:01', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
