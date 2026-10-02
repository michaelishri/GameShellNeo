"""Validate late/noirq traces and reject entry without all diagnostic owners."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pm_platform as platform
import test_pm_stages as existing


def trace():
    lines=[]
    for phase in platform.PHASES:
        lines.append(f'suspend_resume: {phase}[2] begin')
        if phase in ('dpm_suspend_noirq','dpm_resume_noirq'):
            verb='suspend' if phase=='dpm_suspend_noirq' else 'resume'
            lines += [f'device_pm_callback_start: sunxi-rsb 1f03400.rsb, parent: soc, noirq bus [{verb}]',
                      'device_pm_callback_end: sunxi-rsb 1f03400.rsb, err=0']
        lines.append(f'suspend_resume: {phase}[2] end')
    return '\n'.join(lines)


class Evidence(unittest.TestCase):
    def test_complete_trace_and_mutated_boundaries(self):
        text=trace(); record=dict(trace=text,trace_overrun=False,trace_restored=True)
        result=platform.validate_trace(record)
        self.assertEqual(result['rsb_noirq'],['suspend','resume'])
        bad=[text.replace('dpm_suspend_late','missing'),text+text,text.replace('err=0','err=-5'),
             text.replace('sunxi-rsb','other'),text.replace('noirq bus [resume]','bus [resume]'),
             text+'\nsuspend_resume: s2idle_enter[0] begin']
        for candidate in bad:
            with self.subTest(candidate=candidate),self.assertRaises(ValueError):
                platform.validate_trace(record|dict(trace=candidate))
        for flags in (dict(trace_overrun=True),dict(trace_restored=False)):
            with self.assertRaises(ValueError): platform.validate_trace(record|flags)

    def test_admission_requires_patch_owners_journal_and_same_boot_rtc(self):
        snapshot=dict(image={'project_inputs_sha256':{platform.WAKE_PATCH:platform.WAKE_SHA}},boot_id='b',kernel='k')
        with patch.object(Path,'read_text',return_value='# comment\nENABLED=false\n'), \
                patch('subprocess.check_output',return_value='\n'), \
                patch('rtc_alarm.qualification',return_value={'run_id':'r'}) as rtc:
            self.assertEqual(platform.admission(snapshot,True,True),{'run_id':'r'})
            rtc.assert_called_once_with('b','k')
            for power, tracing in ((False,True),(True,False)):
                with self.assertRaises(ValueError): platform.admission(snapshot,power,tracing)
            with self.assertRaises(ValueError): platform.admission(snapshot|{'image':{}},True,True)
            with patch.object(Path,'read_text',return_value='ENABLED=true\n'):
                with self.assertRaises(ValueError): platform.admission(snapshot,True,True)
            with patch('subprocess.check_output',return_value='/usr/lib/armbian/armbian-ramlog write'):
                with self.assertRaises(ValueError): platform.admission(snapshot,True,True)
            rtc.side_effect=ValueError('RTC not qualified')
            with self.assertRaisesRegex(ValueError,'RTC not qualified'): platform.admission(snapshot,True,True)

    def test_service_requires_both_owners_and_never_real_sleep(self):
        host=existing.host
        for kwargs in ({},{'power_key':True},{'keypad_trace':True}):
            with self.assertRaises(ValueError):
                host.service_command('/tmp/gameshellneo-pm.test','platform','a'*32,**kwargs)
        args=host.service_command('/tmp/gameshellneo-pm.test','platform','a'*32,keypad_trace=True,power_key=True,wifi_trace=True)
        self.assertIn('--power-key',args);self.assertIn('--keypad-trace',args)
        self.assertIn('--property=RuntimeMaxSec=120',args)
        for stage in ('none','core','processors','mem'):
            with self.assertRaises(ValueError):
                host.service_command('/tmp/gameshellneo-pm.test',stage,'a'*32,keypad_trace=True,power_key=True)


class Controls(unittest.TestCase):
    setUp = existing.Controls.setUp

    def test_explicit_restore_cannot_overlap_an_experiment(self):
        from keypad_pm import exclusive_pm
        pm = existing.pm
        with exclusive_pm(pm.STATE.parent), patch.object(sys, 'argv', ['pm-test', '--restore']), \
                patch.object(pm, 'restore') as restore:
            with self.assertRaises(BlockingIOError):
                pm.main()
            restore.assert_not_called()

    def test_platform_requires_admission_for_both_control_and_entry(self):
        pm=existing.pm
        with self.assertRaises(ValueError):
            with pm.stage_controls('platform'): self.fail('unguarded')
        with pm.stage_controls('platform',late_ready=True):
            with self.assertRaises(ValueError): pm.enter_stage('platform')
            self.assertEqual(pm.read(pm.POWER/'state'),'untouched')
            pm.enter_stage('platform',late_ready=True)
            self.assertEqual(pm.read(pm.POWER/'state'),'freeze')
        self.assertEqual(pm.selected(pm.read(pm.POWER/'pm_test')),'none')
        for stage in ('none','core','processors'):
            with self.assertRaises(ValueError): pm.enter_stage(stage,late_ready=True)


if __name__=='__main__': unittest.main()
