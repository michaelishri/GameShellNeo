"""Reject firmware reloads and faults even when services and SSH recover."""
import importlib.util
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('check_boot_cycles', TOOLS / 'check-boot-cycles.py')
boot_cycles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot_cycles)

IDENTITY = ('Firmware: BCM43430/0 wl0: May 29 2017 00:03:43 '
            'version 7.13.53.9 (r664949) FWID 01-130000')
LOADED = '[    9.191221] gameshellneo kernel: brcmfmac: brcmf_c_preinit_dcmds: ' + IDENTITY


def healthy_snapshot(journal=LOADED):
    return {
        'image': {'version': 'test'}, 'kernel': '6.18.54-test', 'cpus': 4,
        'memory_kib': 1024 * 1024, 'taint': 0,
        'services': {'ssh': {'ActiveState': 'active', 'NRestarts': '0'}},
        'failed_units': '', 'ready': {'local_userspace_ready': True},
        'battery': {'monitoring': 'valid'}, 'usb_states': ['configured'],
        'backlight': {'brightness': 1, 'bl_power': 0},
        'inputs': ['axp20x-pek', 'rancidbacon.com UsbKeyboard'], 'kernel_journal': journal,
    }


def source_lock():
    return {'image_version': 'test', 'linux': {'tag': 'v6.18.54', 'localversion': '-test'},
            'radio': {'firmware': {'runtime_identity': IDENTITY}}}


class BootFirmwareTests(unittest.TestCase):
    def test_single_pinned_load_passes_and_preserves_evidence(self):
        snapshot = healthy_snapshot()
        self.assertEqual(boot_cycles.validate(snapshot, source_lock()), [])
        evidence = snapshot['firmware_check']
        self.assertTrue(evidence['required'])
        self.assertTrue(evidence['passed'])
        self.assertEqual(evidence['expected'], IDENTITY)
        self.assertEqual(evidence['identities'], [IDENTITY])
        self.assertEqual(sum(evidence['faults'].values()), 0)

    def test_missing_wrong_truncated_and_reloaded_identities_fail(self):
        wrong = LOADED.replace('7.13.53.9', '7.10.34.0')
        for journal in ('', wrong, LOADED[:-1], LOADED + '\n' + LOADED,
                        wrong + '\n' + LOADED):
            with self.subTest(journal=journal):
                snapshot = healthy_snapshot(journal)
                self.assertEqual(boot_cycles.validate(snapshot, source_lock()), ['firmware'])
                self.assertFalse(snapshot['firmware_check']['passed'])

    def test_radio_faults_fail_even_with_one_correct_load_and_healthy_services(self):
        for name, marker in (
            ('firmware_crashes', 'brcmfmac: brcmf_fw_crashed: Firmware has halted or crashed'),
            ('sdio_removals', 'mmc1: card 0001 removed'),
            ('pm_usage_underflows', 'sunxi-mmc 1c10000.mmc: Runtime PM usage count underflow!'),
        ):
            with self.subTest(name=name):
                snapshot = healthy_snapshot(LOADED + '\n' + marker + '\n' + marker)
                self.assertEqual(boot_cycles.validate(snapshot, source_lock()), ['firmware'])
                self.assertEqual(snapshot['firmware_check']['faults'][name], 2)

    def test_optional_file_fallbacks_do_not_fail_a_successful_load(self):
        snapshot = healthy_snapshot(
            'brcmfmac mmc1:0001:1: Direct firmware load for '
            'brcm/brcmfmac43430a0-sdio.clockworkpi,cpi3.bin failed with error -2\n' + LOADED +
            '\nbrcmfmac: brcmf_c_process_clm_blob: no clm_blob available (err=-2), '
            'device may have limited channels available')
        self.assertEqual(boot_cycles.validate(snapshot, source_lock()), [])

    def test_malformed_expectations_are_not_treated_as_legacy(self):
        for expected in (None, '', False, 7, [], {}, 'not a firmware identity'):
            with self.subTest(expected=expected):
                lock = source_lock()
                lock['radio']['firmware']['runtime_identity'] = expected
                snapshot = healthy_snapshot()
                self.assertEqual(boot_cycles.validate(snapshot, lock), ['firmware'])
                self.assertTrue(snapshot['firmware_check']['required'])

    def test_legacy_locks_skip_identity_qualification_explicitly(self):
        for radio in ({}, {'firmware': {}}, {'firmware': {'filename': 'old.bin'}}):
            with self.subTest(radio=radio):
                lock = source_lock()
                lock['radio'] = radio
                snapshot = healthy_snapshot('')
                self.assertEqual(boot_cycles.validate(snapshot, lock), [])
                self.assertFalse(snapshot['firmware_check']['required'])
                self.assertIsNone(snapshot['firmware_check']['passed'])

    def test_existing_boot_health_failures_are_still_rejected(self):
        for field, value, expected in (('taint', 1, 'kernel_taint'),
                                       ('usb_states', ['not attached'], 'usb'),
                                       ('failed_units', 'ssh.service failed', 'failed_units')):
            with self.subTest(field=field):
                snapshot = healthy_snapshot()
                snapshot[field] = value
                self.assertEqual(boot_cycles.validate(snapshot, source_lock()), [expected])


if __name__ == '__main__':
    unittest.main()
