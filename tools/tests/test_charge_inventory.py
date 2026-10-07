"""Reject unsafe regmap layouts and misleading charge claims without hardware."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import charge_inventory as charge


def metadata():
    volatile = {0, 1, 0x78, 0x79, 0xb9}
    rows = [f'{n:02x}: y n {"y" if n in volatile else "n"} n' for n in range(0xe7)]
    return dict(name='axp20x-rsb', range='0-e6', access='\n'.join(rows),
                cache_only='N', cache_bypass='N')


def register_data(**changes):
    values = {f'{n:02x}': 0 for n in charge.REGISTERS}
    values.update({'33': 0xc6, 'b8': 0xc0, 'b9': 0xe4, 'e0': 0x83, 'e1': 0x38, 'e6': 0xa0})
    values.update(changes)
    return {k: dict(value=v) for k, v in values.items()}


def checkpoint(now=100, offset=50):
    return dict(boot_id='fixture', pm={'success': '11', 'fail': '0'},
                clock=dict(monotonic_before_ns=now, monotonic_after_ns=now+10,
                           boottime_ns=now+offset+5, offset_low_ns=offset-5,
                           offset_high_ns=offset+5))


class RegisterReads(unittest.TestCase):
    def test_only_documented_addresses_read_without_buffered_read_ahead(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory/'registers').write_bytes(b''.join(f'{n:02x}: 42\n'.encode() for n in range(0xe7)))
            with patch.object(charge, 'REGMAP', directory), \
                    patch.object(charge.os, 'open', wraps=os.open) as opened, \
                    patch.object(charge.os, 'pread', wraps=os.pread) as reads:
                result = charge.read_registers(metadata())
            opened.assert_called_once_with(directory/'registers', os.O_RDONLY | os.O_CLOEXEC)
            self.assertEqual([(c.args[1], c.args[2]) for c in reads.call_args_list],
                [(7, a*7) for a in (0, 1, 0x33, 0x34, 0x78, 0x79, 0xb8, 0xb9, 0xe0, 0xe1, 0xe6)])
            self.assertEqual(result['b8']['source'], 'regmap-cache-possible')
            self.assertEqual(result['34']['source'], 'regmap-cache-possible')
            self.assertEqual(result['78']['source'], 'volatile-regmap-read')
            self.assertEqual(result['79']['source'], 'volatile-regmap-read')
            self.assertEqual(result['b9']['source'], 'volatile-regmap-read')
            self.assertTrue(all(r['value'] == 0x42 for r in result.values()))

    def test_bad_metadata_rejected_before_register_open(self):
        good = metadata()
        changes = [dict(name='other'), dict(range='0-ff'), dict(range='0-47\n50-e6'),
                   dict(cache_only='Y'), dict(cache_bypass='Y'),
                   dict(access=good['access'].replace('b8: y n n n', 'b8: y n y n')),
                   dict(access=good['access'].replace('34: y n n n', '34: y n y n')),
                   dict(access=good['access'].replace('78: y n y n', '78: y n n n')),
                   dict(access=good['access'].replace('79: y n y n', '79: y n n n')),
                   dict(access=good['access'].replace('e2: y n n n', 'e2: y n n y')),
                   dict(access=good['access'].replace('e2: y n n n', 'e1: y n n n')),
                   dict(access=good['access'].replace('00: y n y n\n', ''))]
        for change in changes:
            with self.subTest(change=change), patch.object(charge.os, 'open') as opened:
                with self.assertRaises(ValueError):
                    charge.read_registers(good | change)
                opened.assert_not_called()

    def test_error_short_and_wrong_address_reads_fail_and_close(self):
        for line in (b'00: XX\n', b'00: f\n', b'01: ff\n', b'', b'00: ff\n01: ff\n'):
            with self.subTest(line=line), patch.object(charge.os, 'open', return_value=42), \
                    patch.object(charge.os, 'pread', return_value=line) as read, \
                    patch.object(charge.os, 'close') as close:
                with self.assertRaises(ValueError):
                    charge.read_registers(metadata())
                read.assert_called_once_with(42, 7, 0)
                close.assert_called_once_with(42)


class Meaning(unittest.TestCase):
    def test_disputed_control_polarity_remains_raw_and_possibly_cached(self):
        for raw in (0, 4, 0xfb, 0xff):
            result = charge.decode(register_data(**{'34': raw}))['charger_control2']
            self.assertEqual(result['raw'], raw)
            self.assertEqual(result['bit2'], (raw >> 2) & 1)
            self.assertEqual(result['source'], 'regmap-cache-possible')
            self.assertIn('unresolved', result['bit2_interpretation'])
            self.assertNotIn('enabled', result)

    def test_voltage_byte_formulas_preserve_unused_bits_without_coherence_claim(self):
        for high, low, masked, linux in ((0xf1, 0x0d, 4255900, 4255900),
                                        (0xf0, 0x1d, 4238300, 4255900),
                                        (0xff, 0xff, 4504500, 4504500)):
            result = charge.decode(register_data(**{'78': high, '79': low}))['battery_voltage_bytes']
            self.assertEqual(result['high'], high)
            self.assertEqual(result['low'], low)
            self.assertEqual(result['unused_low_bits'], low & 0xf0)
            self.assertEqual(result['masked_12bit_formula_uv'], masked)
            self.assertEqual(result['linux_helper_formula_uv'], linux)
            self.assertEqual(result['unused_bits_change_formula'], masked != linux)
            self.assertFalse(result['coherent_sample_established'])
            self.assertFalse(result['physical_accuracy_qualified'])

    def test_cache_is_not_live_charge_calibration_or_remaining_capacity(self):
        report = charge.decode(register_data())
        self.assertEqual(report['cached_configuration']['configured_capacity_uah'], 824*1456)
        self.assertTrue(report['cached_configuration']['charger_enabled'])
        self.assertEqual(report['gauge_result'], {'valid': True, 'percent': 100})
        self.assertFalse(report['accumulated_charge_available'])
        self.assertEqual(report['charging_during_sleep'], 'not-measured')
        for missing in ('charge_now', 'charge_counter', 'charge_gained_uah', 'passed'):
            self.assertNotIn(missing, report)

    def test_unconfigured_and_invalid_values_do_not_become_valid_measurements(self):
        report = charge.decode(register_data(e0=0x03, b9=0x7f, b8=0x30))
        self.assertIsNone(report['cached_configuration']['configured_capacity_uah'])
        self.assertFalse(report['cached_configuration']['capacity_configured'])
        self.assertFalse(report['gauge_result']['valid'])
        self.assertTrue(report['cached_configuration']['calibration_in_progress_bit'])
        self.assertFalse(charge.decode(register_data(b9=0xff))['gauge_result']['valid'])

    def test_awake_clock_uncertainty_allowed_but_sleep_and_boot_changes_rejected(self):
        before = checkpoint()
        charge.validate_continuity(before, checkpoint(now=200, offset=53))
        bad = [checkpoint(now=200, offset=1_000_000), checkpoint(now=50),
               checkpoint(now=200) | {'boot_id': 'other'},
               checkpoint(now=200) | {'pm': {'success': '12', 'fail': '0'}}]
        for after in bad:
            with self.subTest(after=after), self.assertRaises(ValueError):
                charge.validate_continuity(before, after)


class Collection(unittest.TestCase):
    def test_kernel_image_and_board_identity_required_before_register_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory/'image'; board = directory/'board'; pmic = directory/'pmic'
            (pmic/'of_node').mkdir(parents=True)
            (pmic/'of_node/compatible').write_bytes(b'x-powers,axp223\0')
            image.write_text(json.dumps({'version': 'test', 'board': 'gameshellneo-cpi31'}))
            board.write_bytes(b'clockwork,clockworkpi-cpi3\0allwinner,sun8i-a33\0')
            with patch.object(charge, 'IMAGE', image), patch.object(charge, 'BOARD', board), \
                    patch.object(charge, 'PMIC', pmic), \
                    patch.object(charge.os, 'uname', return_value=SimpleNamespace(release='6.18.54-gameshellneo19')), \
                    patch.object(charge, 'metadata', return_value=metadata()), \
                    patch.object(charge, 'read_registers', return_value=register_data()) as reads, \
                    patch.object(charge, 'checkpoint', return_value=checkpoint()), \
                    patch.object(charge, 'validate_continuity'), \
                    patch.object(charge, 'supply_inventory', return_value={}):
                self.assertTrue(charge.inspect('6.18.54-gameshellneo19', 'test')['completed'])
                reads.reset_mock()
                for kernel, version in [('6.19.0-gameshellneo19', 'test'),
                                        ('6.18.54-gameshellneo20', 'test'),
                                        ('6.18.54-gameshellneo19', 'different')]:
                    with self.assertRaises(ValueError):
                        charge.inspect(kernel, version)
                board.write_bytes(b'some,other-board\0')
                with self.assertRaises(ValueError):
                    charge.inspect('6.18.54-gameshellneo19', 'test')
                reads.assert_not_called()

    def test_failure_emits_partial_result_without_success(self):
        def fail(_kernel, _image, result):
            result['before'] = checkpoint()
            raise OSError('fixture read error')
        output = io.StringIO()
        with patch.object(sys, 'argv', ['charge_inventory.py', '--kernel', 'test', '--image', 'test']), \
                patch.object(charge, 'inspect', side_effect=fail), contextlib.redirect_stdout(output):
            self.assertEqual(charge.main(), 1)
        result = json.loads(output.getvalue())
        self.assertFalse(result['completed'])
        self.assertEqual(result['before']['boot_id'], 'fixture')
        self.assertIn('fixture read error', result['error'])

    def test_standalone_remote_source_does_not_require_repo_imports(self):
        import subprocess
        source = Path(charge.__file__).read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, '-B', '-', '--help'], input=source,
                capture_output=True, cwd=temporary, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'--kernel', result.stdout)


if __name__ == '__main__':
    unittest.main()
