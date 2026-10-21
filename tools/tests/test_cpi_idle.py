"""Reject incomplete WFI/timer evidence without performing real suspend."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import cpi_idle
import keypad_supply
import sleep_rtc
from test_pm_stages import healthy_fixture, pm, host, load
from test_battery_sample import reading


def inventory():
    return dict(schema=1, online='0-3', possible='0-3', driver='cpi_wfi', governor='menu',
                clocksource='arch_sys_counter', broadcast='sun4i_tick',
                timer_dt=dict(board=['clockwork,clockworkpi-cpi3', 'allwinner,sun8i-a33'],
                    compatible=['arm,armv7-timer'], frequency=[24000000],
                    interrupts=[cell for irq in (13,14,11,10) for cell in (1,irq,0xf08)],
                    registers_not_fw_configured=True, no_tick_in_suspend=False, always_on=False),
                clockevents={f'clockevent{i}': 'arch_sys_timer' for i in range(4)},
                states={f'cpu{i}/cpuidle/state0': dict(name='WFI', desc='ARM WFI', latency='1',
                    residency='1', disable='0', usage='40', time='200', s2idle_usage='2', s2idle_time='0')
                    for i in range(4)})


def lock():
    return dict(experiments=dict(suspend_diagnostics=True, keypad_supply_retention=True, cpi_wfi_s2idle=True),
                features=dict(battery_sample_clock='CLOCK_BOOTTIME'))


class WfiEvidence(unittest.TestCase):
    def test_all_cpu_callbacks_and_clock_freeze_are_required_separately(self):
        a, b = inventory(), inventory()
        delivery = dict(timekeeping=dict(observation='observed'))
        for state in b['states'].values():
            state['s2idle_usage'] = '3'
        outcome = cpi_idle.assess(a, b, 'rtc-wake', delivery)
        self.assertTrue(outcome['all_cpu_s2idle_callbacks'])
        self.assertFalse(outcome['energy_qualified'])
        # Zero scheduler-clock time during freeze is not missing physical sleep.
        self.assertEqual({s['s2idle_time'] for s in b['states'].values()}, {'0'})
        for path in b['states']:
            bad = deepcopy(b); bad['states'][path]['s2idle_usage'] = '2'
            with self.assertRaisesRegex(ValueError, 'all-CPU'):
                cpi_idle.assess(a, bad, 'rtc-wake', delivery)
        for observation in ('not_observed', 'inconclusive', None):
            with self.assertRaisesRegex(ValueError, 'timekeeping'):
                cpi_idle.assess(a, b, 'rtc-wake', dict(timekeeping=dict(observation=observation)))

    def test_awake_rehearsal_and_counter_reset_reject(self):
        a = inventory()
        self.assertFalse(cpi_idle.assess(a, a, 'rehearse', {})['all_cpu_s2idle_callbacks'])
        for field, number in (('usage', '1'), ('s2idle_usage', '3'), ('s2idle_time', '-1')):
            b = deepcopy(a); b['states']['cpu0/cpuidle/state0'][field] = number
            with self.assertRaises(ValueError): cpi_idle.assess(a, b, 'rehearse', {})

    def test_wrong_driver_missing_cpu_disabled_state_or_timer_rejected(self):
        mutations = [lambda v: v.update(driver='none'), lambda v: v.update(online='0-2'),
            lambda v: v.update(possible='0-7'), lambda v: v.update(schema=True),
            lambda v: v['states'].pop('cpu3/cpuidle/state0'),
            lambda v: v['states']['cpu0/cpuidle/state0'].update(disable='1'),
            lambda v: v['states']['cpu0/cpuidle/state0'].update(s2idle_usage=None),
            lambda v: v['states'].update({'cpu0/cpuidle/state1': {}}),
            lambda v: v.update(clocksource='jiffies'), lambda v: v.update(broadcast='other'),
            lambda v: v['clockevents'].pop('clockevent2'),
            lambda v: v['clockevents'].update(clockevent2='none'),
            lambda v: v['timer_dt'].update(frequency=[12000000]),
            lambda v: v['timer_dt'].update(interrupts=[1,13,0x108]),
            lambda v: v['timer_dt'].update(no_tick_in_suspend=True),
            lambda v: v['timer_dt'].update(registers_not_fw_configured=False),
            lambda v: v['timer_dt'].update(always_on=True),
            lambda v: v['timer_dt'].update(board=None)]
        cpi_idle.validate(inventory())
        for mutate in mutations:
            v = inventory(); mutate(v)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): cpi_idle.validate(v)

    def test_reads_real_grouped_sysfs_paths_and_retains_missing_fields(self):
        expected = inventory()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {'cpu/online': '0-3', 'cpu/possible': '0-3', 'cpu/cpuidle/current_driver': 'cpi_wfi',
                     'cpu/cpuidle/current_governor_ro': 'menu',
                     'clocksource/clocksource0/current_clocksource': 'arch_sys_counter',
                     'clockevents/broadcast/current_device': 'sun4i_tick'}
            files.update({f'clockevents/{name}/current_device': value for name, value in expected['clockevents'].items()})
            for path, state in expected['states'].items():
                for name, value in state.items():
                    field = name.replace('s2idle_', 's2idle/')
                    files['cpu/'+path+'/'+field] = value
            for name, value in files.items():
                p = root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value+'\n')
            dt = root/'dt'
            (dt/'timer').mkdir(parents=True)
            (dt/'compatible').write_bytes(b'clockwork,clockworkpi-cpi3\0allwinner,sun8i-a33\0')
            (dt/'timer/compatible').write_bytes(b'arm,armv7-timer\0')
            (dt/'timer/arm,cpu-registers-not-fw-configured').touch()
            for prop, key in (('clock-frequency', 'frequency'), ('interrupts', 'interrupts')):
                (dt/'timer'/prop).write_bytes(b''.join(n.to_bytes(4, 'big') for n in expected['timer_dt'][key]))
            self.assertEqual(cpi_idle.snapshot(root, dt), expected)
            (root/'cpu/cpu2/cpuidle/state0/s2idle/usage').unlink()
            with self.assertRaises(ValueError): cpi_idle.validate(cpi_idle.snapshot(root, dt))
            (dt/'timer/clock-frequency').write_bytes(b'\x01')
            self.assertIsNone(cpi_idle.timer_dt(dt)['frequency'])

    def test_lock_requires_battery_prerequisite_and_preserves_experiment_isolation(self):
        self.assertTrue(cpi_idle.enabled(lock()))
        self.assertTrue(keypad_supply.enabled(lock()))
        self.assertFalse(cpi_idle.enabled({}))
        for mutate in (lambda v: v.pop('features'),
                       lambda v: v['experiments'].update(cpi_wfi_s2idle=1),
                       lambda v: v['experiments'].update(cpi_wfi_s2idle=False),
                       lambda v: v['experiments'].update(usb_absent_poll=True)):
            v = lock(); mutate(v)
            with self.assertRaises(ValueError): keypad_supply.enabled(v)

    def test_pm_admission_requires_live_state_and_correct_battery_age(self):
        good, source = healthy_fixture()
        source.update(lock()); good.update(cpu_idle=inventory(), boot_id='boot', boottime_seconds=102,
                                          battery=reading() | dict(status='Charging'), keypad_retains_supply=True)
        good['kernel_config'] += 'CONFIG_ARM_CPI_WFI_CPUIDLE=y\n'
        pm.validate(good, source)
        for mutate in (lambda v: v['cpu_idle'].update(driver='none'),
                       lambda v: v.update(battery_age_seconds=0),
                       lambda v: v.update(kernel_config=v['kernel_config'].replace('CONFIG_ARM_CPI_WFI_CPUIDLE=y\n',''))):
            bad = deepcopy(good); mutate(bad)
            with self.assertRaises(ValueError): pm.validate(bad, source)

    def test_inline_pm_transport_has_new_dependencies_outside_repo(self):
        sent = {}
        def run(client, **kwargs): sent.update(kwargs); return b'{}'
        with patch.object(host, 'run', side_effect=run): host.inline(None, '--help')
        with tempfile.TemporaryDirectory() as directory:
            output = subprocess.run([sys.executable, '-I', '-B', '-', '--help'],
                                    input=sent['input_data'], cwd=directory, capture_output=True)
        self.assertEqual(output.returncode, 0, output.stderr.decode())

    def test_offline_report_recomputes_cpu_evidence_not_saved_pass_boolean(self):
        report = load('cpi_sleep_report', 'report-sleep-evidence.py')
        record = dict(event='complete', passed=True, run_id='a'*32, mode='rtc-wake',
                      before=dict(image=dict(sources=lock())), cpu_idle_before=inventory(),
                      cpu_idle_after=inventory(), cpi_wfi=dict(all_cpu_s2idle_callbacks=True))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'result.json'; path.write_text(json.dumps(record))
            raw = path.read_bytes()
            with patch.object(sleep_rtc, 'validate_delivery', return_value=dict(timekeeping=dict(observation='observed'))):
                result = report.assess(path)
            self.assertFalse(result['measurement_checks_passed'])
            self.assertIn('all-CPU', result['measurement_error'])
            self.assertEqual(path.read_bytes(), raw)


if __name__ == '__main__': unittest.main()
