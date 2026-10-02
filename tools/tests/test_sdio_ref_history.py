import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('sdio_ref_history', Path(__file__).parents[1] / 'check-sdio-ref-history.py')
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


def capture(index, before, after):
    def snapshot(value, time):
        return dict(boot_id='boot', kernel='kernel', monotonic_seconds=time,
                    rsb_links={history.LINK: dict(consumer=dict(power=dict(runtime_usage=str(value),
                        control='on', runtime_enabled='forbidden', runtime_status='active')))})
    return (str(index), dict(passed=True, run_id=f'{index:032x}', stage='devices',
                            before=snapshot(before, index*10), after=snapshot(after, index*10+5)))


class History(unittest.TestCase):
    def test_detects_per_cycle_and_between_cycle_growth(self):
        rows = [capture(n, n+1, n+2) for n in range(1, 8)]
        result = history.summarize(list(reversed(rows)))
        self.assertFalse(result['stable'])
        self.assertEqual([r['delta'] for r in result['cycles']], [1]*7)
        self.assertEqual(result['cycles'][-1]['after'], 9)
        self.assertFalse(history.summarize([capture(1, 2, 2), capture(2, 3, 3)])['stable'])
        self.assertTrue(history.summarize([capture(1, 2, 2), capture(2, 2, 2)])['stable'])
        self.assertFalse(history.summarize([capture(1, 2, 1)])['stable'])

    def test_rejects_unaccepted_mixed_boot_and_incomplete_evidence(self):
        for change in ('failure', 'boot', 'kernel', 'missing', 'negative', 'policy', 'time', 'infinity'):
            path, result = copy.deepcopy(capture(1, 2, 2))
            if change == 'failure': result['passed'] = False
            if change in ('boot', 'kernel'): result['after']['boot_id' if change == 'boot' else 'kernel'] = 'other'
            if change == 'missing': result['after']['rsb_links'] = {}
            if change == 'negative': result['after']['rsb_links'][history.LINK]['consumer']['power']['runtime_usage'] = '-1'
            if change == 'policy': result['after']['rsb_links'][history.LINK]['consumer']['power']['control'] = 'auto'
            if change == 'time': result['after']['monotonic_seconds'] = 0
            if change == 'infinity': result['after']['monotonic_seconds'] = float('inf')
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                history.summarize([(path, result)])
        with self.assertRaises(ValueError): history.summarize([])
        with self.assertRaises(ValueError): history.summarize([capture(1, 2, 2)]*2)


if __name__ == '__main__':
    unittest.main()
