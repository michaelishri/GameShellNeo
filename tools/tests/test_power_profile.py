import importlib.util
from pathlib import Path
import unittest
from awake_fixtures import window

source = Path(__file__).resolve().parents[1] / 'profile-power.py'
spec = importlib.util.spec_from_file_location('power_profile', source)
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class CounterParsing(unittest.TestCase):
    def test_guest_time_is_not_double_counted(self):
        value = profile.proc_stat('cpu 100 20 30 800 10 5 35 0 50 10\nctxt 12\nintr 34 1 2')
        self.assertEqual(sum(value['cpus']['cpu']), 1000)
        self.assertEqual(value['counters'], {'ctxt': 12, 'intr': 34})

    def test_interrupt_columns_and_named_ipis(self):
        left = profile.interrupts(' CPU0 CPU1\n 65: 10 20 GICv2 71 Level sunxi-rsb\n'
                                  'IPI2: 3 4 Rescheduling interrupts\nErr: 0')
        right = profile.interrupts(' CPU0 CPU1\n 65: 20 30 GICv2 71 Level sunxi-rsb\n'
                                   'IPI2: 8 9 Rescheduling interrupts\nErr: 0')
        rows = profile.interrupt_rates(left, right, 10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['counts'], [10, 10])
        self.assertEqual(rows[0]['per_second'], 2)
        self.assertEqual(rows[1]['description'], 'Rescheduling interrupts')
        self.assertNotIn('Err', left['rows'])

    def test_reset_or_cpu_column_change_is_rejected(self):
        with self.assertRaises(ValueError):
            profile.delta(20, 10)
        with self.assertRaises(ValueError):
            profile.interrupt_rates(profile.interrupts(' CPU0\n1: 1 timer'),
                                    profile.interrupts(' CPU0 CPU1\n1: 1 1 timer'), 10)

    def test_process_name_parentheses_and_field_positions(self):
        # Real proc layout: state (field 3), utime/stime (14/15), starttime (22).
        fields = ['0'] * 20
        fields[0], fields[11], fields[12], fields[19] = 'S', '17', '23', '999'
        result = profile.process_stat('42 (worker ) test) ' + ' '.join(fields))
        self.assertEqual(result, dict(pid=42, comm='worker ) test', start_ticks=999, cpu_ticks=40))

    def test_pid_reuse_cannot_create_false_cpu_usage(self):
        before = {'42': dict(comm='old', start_ticks=100, cpu_ticks=10)}
        after = {'42': dict(comm='new', start_ticks=200, cpu_ticks=999)}
        self.assertEqual(profile.process_rates(before, after, 10, 100), [])
        after['42']['start_ticks'] = 100
        after['42']['cpu_ticks'] = 60
        result = profile.process_rates(before, after, 10, 100)[0]
        self.assertEqual(result['cpu_seconds'], 0.5)
        self.assertEqual(result['percent_one_cpu'], 5)

    def test_cpu_busy_iowait_and_wall_time_units(self):
        def snapshot(seconds, cpu):
            return dict(monotonic_seconds=seconds, awake_window=window(seconds), stat={'cpus': {'cpu': cpu}, 'counters': {}},
                        interrupts={'cpus': ['CPU0'], 'rows': {}},
                        softirqs={'cpus': ['CPU0'], 'rows': {}},
                        processes={}, network={}, radio={})
        result = profile.summarize(snapshot(10, [0] * 8),
                                   snapshot(20, [100, 0, 100, 700, 100, 0, 0, 0]), 100)
        self.assertEqual(result['duration_seconds'], 10)
        self.assertEqual(result['cpu']['cpu']['busy_percent'], 20)
        self.assertEqual(result['cpu']['cpu']['idle_percent'], 70)
        self.assertEqual(result['cpu']['cpu']['iowait_percent'], 10)
        self.assertEqual(result['cpu']['cpu']['accounted_cpu_seconds'], 10)

    def test_short_cpu_accounting_is_visible(self):
        empty = dict(interrupts={'cpus': ['CPU0'], 'rows': {}},
                     softirqs={'cpus': ['CPU0'], 'rows': {}}, processes={}, network={}, radio={})
        before = dict(empty, monotonic_seconds=0, awake_window=window(0),
                      stat={'cpus': {'cpu': [0] * 8, 'cpu0': [0] * 8}, 'counters': {}})
        after = dict(empty, monotonic_seconds=20, awake_window=window(20),
                     stat={'cpus': {'cpu': [0, 0, 100, 900, 0, 0, 0, 0],
                                    'cpu0': [0, 0, 100, 900, 0, 0, 0, 0]}, 'counters': {}})
        result = profile.summarize(before, after, 100)
        self.assertEqual(result['cpu']['cpu']['accounting_coverage_percent'], 50)
        self.assertEqual(result['cpu']['cpu0']['accounting_coverage_percent'], 50)
