"""Keep incomplete, mismatched or wrong-duration captures out of comparisons."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('usb_idle_report',
    Path(__file__).resolve().parents[1] / 'report-usb-idle.py')
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


def fixture(root):
    phases = []
    for index, mode in enumerate(('experimental', 'stock', 'experimental')):
        boot = 'boot-' + str(index)
        idle = root / str(index) / 'idle'
        profile = root / str(index) / 'profile'
        idle.mkdir(parents=True)
        profile.mkdir()
        power = [1000, 1100, 1200][index]
        samples = [dict(event='sample', boot_id=boot, voltage_uv=4000000,
                        temperature_millic=40000, capacity_percent=90) for _ in range(31)]
        idle_summary = dict(event='complete', passed=True, duration_seconds=300.01,
                            time_weighted_current_ma=power / 4, time_weighted_power_mw=power,
                            wifi_signal_dbm=-50)
        profile_summary = dict(event='complete', passed=True, duration_seconds=120.1,
            cpu={'cpu': dict(busy_percent=2, accounting_coverage_percent=97)},
            interrupts=[dict(description='GICv2 71 Level sunxi-rsb', per_second=10)],
            radio_before=dict(signal_dbm=-51), radio_after=dict(signal_dbm=-52),
            network=dict(rx_bytes=1000, tx_bytes=2000, rx_packets=10, tx_packets=20))
        raw = dict(event='raw', before={'health': dict(boot_id=boot)}, after={'health': dict(boot_id=boot)})
        (idle / 'idle-sample.jsonl').write_text('\n'.join(json.dumps(row) for row in
            [dict(event='ready', seconds=300, wifi_signal_dbm=-49), *samples, idle_summary]) + '\n')
        (profile / 'power-profile.jsonl').write_text('\n'.join(json.dumps(row) for row in [raw, profile_summary]) + '\n')
        phases.append(dict(mode=mode, boot_id=boot, passed=True,
                           idle=dict(capture=str(idle), summary=idle_summary),
                           profile=dict(capture=str(profile), summary=profile_summary)))
    return dict(passed=True, phases=phases)


class ReportTests(unittest.TestCase):
    def test_differences_preserve_opposite_bracketing_results(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = reporter.summarize(fixture(Path(directory)))
            differences = summary['experimental_minus_stock']
            self.assertEqual(differences[0]['power_mw']['difference'], -100)
            self.assertEqual(differences[1]['power_mw']['difference'], 100)
            self.assertFalse(summary['calibrated'])
            self.assertIn('RSB IRQs are neither USB poll counts', reporter.markdown(summary))

    def test_partial_or_same_boot_comparisons_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            good = fixture(Path(directory))
            for change in ('unfinished', 'phase-failed', 'missing', 'same-boot', 'order'):
                value = copy.deepcopy(good)
                if change == 'unfinished':
                    value['passed'] = False
                elif change == 'phase-failed':
                    value['phases'][1]['passed'] = False
                elif change == 'missing':
                    value['phases'].pop()
                elif change == 'same-boot':
                    value['phases'][2]['boot_id'] = value['phases'][0]['boot_id']
                else:
                    value['phases'][1]['mode'] = 'experimental'
                with self.subTest(change=change), self.assertRaises(ValueError):
                    reporter.summarize(value)

    def test_raw_mismatch_wrong_boot_or_wrong_duration_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            value = fixture(Path(directory))
            path = Path(value['phases'][0]['idle']['capture']) / 'idle-sample.jsonl'
            good = path.read_text()
            for change in ('incomplete', 'boot', 'duration', 'summary'):
                rows = [json.loads(line) for line in good.splitlines()]
                if change == 'incomplete':
                    rows.pop()
                elif change == 'boot':
                    rows[1]['boot_id'] = 'another-boot'
                elif change == 'duration':
                    rows[0]['seconds'] = 600
                else:
                    rows[-1]['time_weighted_power_mw'] = 1
                path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
                with self.subTest(change=change), self.assertRaises(ValueError):
                    reporter.summarize(value)


if __name__ == '__main__':
    unittest.main()
