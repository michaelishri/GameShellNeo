"""PM-clear attribution, IRQ evidence limits and fresh awake handoff guards."""
from copy import deepcopy
from contextlib import contextmanager
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import power_key
import power_key_pm as pm


def event(stamp, value):
    return dict(seconds=stamp, type=1, code=116, value=value)


def irqs(dbf, dbr):
    return dict(cpus=['CPU0','CPU1'],dbf=dict(irq=90, hwirq=22, count=dbf), dbr=dict(irq=91, hwirq=23, count=dbr))


def evidence():
    keys = [event(t,v) for t,v in ((10,1),(10.2,0),(12,1),(12.2,0),
                                  (14,1),(14.1,0),(22,1),(22.2,0))]
    stages = [dict(label=label,prompt_seconds=t-.5,press_seconds=t,release_seconds=t+.2)
              for label,t in (('tap-1',10),('tap-2',12),('tap-4',22))]
    return dict(power_key=dict(events=keys,identity=dict(sysfs='/fixture/input0')),
        physical_power=dict(stages=stages,hold_prompt=13,entry_seconds=14.05,resume_seconds=20,
            irq_initial=irqs(5,5),irq_before_hold=irqs(7,7),irq_held=irqs(8,7),
            irq_after_pm=irqs(8,8),irq_final=irqs(9,9)),
        keypad=dict(trace_overrun=False,trace_restored=True,trace=(
            'python [000] ... 14.099990: device_pm_callback_start: input input0, parent: axp221-pek, type [suspend]\n'
            'python [000] ... 14.100010: device_pm_callback_end: input input0, err=0\n')))


class IRQs(unittest.TestCase):
    def test_identity_cpu_sum_and_exact_pair_deltas(self):
        text = (' CPU0 CPU1\n90: 2 3 axp22x_irq_chip 22 Edge axp20x-pek-dbf\n'
                '91: 1 4 axp22x_irq_chip 23 Edge axp20x-pek-dbr\n')
        sample=pm.irq_counts(text)
        self.assertEqual({k:sample[k] for k in ('cpus','dbf','dbr')},irqs(5,5))
        self.assertEqual(len(sample['rows']),2)
        self.assertLessEqual(sample['sample_start'],sample['sample_end'])
        pm.require_delta(irqs(5,5),irqs(5,6),0,1)
        for change in (text.replace('22','21'),text.replace('CPU0','other'),text+text.splitlines()[-1],
                       text.replace('2 3','2'),text.replace('axp22x','other'),text.replace('91:','90:')):
            with self.subTest(change=change),self.assertRaises(ValueError):pm.irq_counts(change)

    def test_counter_reset_extra_edge_or_remapped_identity_rejected(self):
        for value in (irqs(4,6),irqs(6,6),irqs(5,7),irqs(5,5)):
            with self.assertRaises(ValueError):pm.require_delta(irqs(5,5),value,0,1)
        value=irqs(5,6);value['dbr']['irq']=92
        with self.assertRaises(ValueError):pm.require_delta(irqs(5,5),value,0,1)
        value=irqs(5,6);value['cpus']=['CPU0']
        with self.assertRaises(ValueError):pm.require_delta(irqs(5,5),value,0,1)


class Transcript(unittest.TestCase):
    def test_synthetic_clear_alone_cannot_satisfy_fresh_awake_pair(self):
        record=evidence();pm.validate_input(record)
        record['power_key']['events']=record['power_key']['events'][:6]
        with self.assertRaises(ValueError):pm.validate_input(record)

    def test_early_release_or_missing_dispatch_or_extra_press_rejected(self):
        for field,value in (('entry_seconds',14.2),('resume_seconds',23),('irq_after_pm',irqs(8,7)),
                            ('irq_final',irqs(10,9))):
            record=evidence();record['physical_power'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):pm.validate_input(record)
        record=evidence();record['power_key']['events'] += [event(23,1)]
        with self.assertRaises(ValueError):pm.validate_input(record)

    def test_source_correlated_callback_not_syn_value_establishes_clear(self):
        record=evidence();self.assertEqual(pm.validate_trace(record)['clear_seconds'],14.1)
        for transform in (lambda t:t.replace('14.099990','14.100005'),
                          lambda t:t.replace('type [suspend]','bus [suspend]'),
                          lambda t:t.replace('err=0','err=-5'),lambda t:t+t,
                          lambda t:t+'suspend_resume: s2idle_enter[0] begin\n'):
            bad=deepcopy(record);bad['keypad']['trace']=transform(bad['keypad']['trace'])
            with self.assertRaises(ValueError):pm.validate_trace(bad)
        for field in ('trace_overrun','trace_restored'):
            bad=deepcopy(record);bad['keypad'][field]=not bad['keypad'][field]
            with self.assertRaises(ValueError):pm.validate_trace(bad)


class Handoff(unittest.TestCase):
    def setUp(self):
        self.record=evidence()
        self.guard=Mock(fd=10,record=self.record['power_key'])
        self.guard.consumer=power_key.Consumer({});self.guard.consumer.resumed=20
        self.guard.consumer.last_event=22.2
        self.enterContext(patch.object(pm.awake,'awake_state',return_value={'boot':'same','success':8}))
        self.enterContext(patch.object(pm,'irq_counts',return_value=irqs(9,9)))
        self.enterContext(patch.object(pm.time,'monotonic',return_value=24))
        self.state=dict(ioctl_errno=None,hung_up=False,poll_error=False,held_key_codes=[])
        self.enterContext(patch.object(pm.keypad_pm,'handle_state',return_value=self.state))
        self.verify=self.enterContext(patch.object(power_key,'verify_inhibitor',return_value={}))

    def test_fresh_owned_awake_pair_qualifies_only_same_generation(self):
        proof=pm.PostResumeHandoff(self.guard,self.record);proof.check()
        with patch.object(pm.awake,'awake_state',return_value={'boot':'same','success':9}),self.assertRaises(ValueError):proof.check()
        self.guard.consumer.resumed=21
        with self.assertRaises(ValueError):proof.check()

    def test_extra_dispatch_held_lost_input_and_inhibitor_fail_closed(self):
        proof=pm.PostResumeHandoff(self.guard,self.record)
        with patch.object(pm,'irq_counts',return_value=irqs(10,9)),self.assertRaises(ValueError):proof.check()
        for change in (dict(held_key_codes=[116]),dict(ioctl_errno=19),dict(hung_up=True)):
            with patch.object(pm.keypad_pm,'handle_state',return_value=self.state|change),self.assertRaises(ValueError):proof.check()
        self.verify.side_effect=ValueError('inhibitor lost')
        with self.assertRaisesRegex(ValueError,'inhibitor lost'):proof.check()

    def test_old_pair_or_recent_event_cannot_restore_policy(self):
        self.guard.consumer.resumed=23
        with self.assertRaises(ValueError):pm.PostResumeHandoff(self.guard,self.record)
        self.guard.consumer.resumed=20;self.guard.consumer.last_event=23.9
        with self.assertRaises(ValueError):pm.PostResumeHandoff(self.guard,self.record)


class Ownership(unittest.TestCase):
    def test_restore_requires_same_run_and_attempts_all_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);owner=root/'ui';owner.touch()
            with patch.object(pm.awake,'UI_OWNED',owner),patch.object(pm.awake,'ui_owner') as check, \
                 patch.object(pm.keypad_pm,'restore_trace',side_effect=ValueError('trace')) as trace, \
                 patch.object(pm.speaker_audio,'restore') as audio,patch.object(pm.keypad_input,'restore_console') as console, \
                 patch.object(pm.awake,'release_ui_record') as release:
                backend=Mock()
                check.side_effect=ValueError('foreign run')
                with self.assertRaisesRegex(ValueError,'foreign run'):pm.restore(backend,'a'*32)
                trace.assert_not_called();audio.assert_not_called();console.assert_not_called()
                check.side_effect=None
                with self.assertRaisesRegex(ValueError,'trace'):pm.restore(backend,'a'*32)
                backend.restore.assert_called_once();audio.assert_called_once();console.assert_called_once()
                release.assert_not_called()

    def test_only_explicit_devices_mode_can_launch_and_cleanup_has_token(self):
        path=Path(__file__).resolve().parents[1]/'check-pm-stages.py'
        spec=importlib.util.spec_from_file_location('power_pm_host_test',path)
        host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
        options=dict(keypad_trace=True,power_key=True,power_key_input=True)
        command=host.service_command('/tmp/gameshellneo-pm.abcdefgh','devices','a'*32,**options)
        self.assertIn('--power-key-input',command)
        self.assertTrue(any('--restore --power-key-input --run-id '+'a'*32 in c for c in command))
        for changes in (dict(power_key=False),dict(keypad_trace=False),dict(wifi_trace=True),
                        dict(keypad_input=True),dict(keypad_persist='1')):
            with self.assertRaises(ValueError):host.service_command('/tmp/gameshellneo-pm.abcdefgh','devices','a'*32,**(options|changes))
        for stage in ('none','freezer','platform'):
            with self.assertRaises(ValueError):host.service_command('/tmp/gameshellneo-pm.abcdefgh',stage,'a'*32,**options)


class PromptedCycle(unittest.TestCase):
    def setUp(self):
        self.now=100.0;self.pending=[];self.dbf=5;self.dbr=5
        self.record=dict(power_key={},physical_power={})
        self.guard=Mock(fd=10,record=self.record['power_key'])
        self.guard.consumer=power_key.Consumer(self.guard.record)
        self.enterContext(patch.object(pm.time,'monotonic',side_effect=lambda:self.now))
        self.enterContext(patch.object(Path,'write_text'))
        self.enterContext(patch.object(pm.os,'sync'))
        self.enterContext(patch.object(power_key,'verify_inhibitor'))
        self.enterContext(patch.object(pm,'irq_counts',side_effect=lambda:irqs(self.dbf,self.dbr)))
        def feed(e,physical=True):
            if physical:
                if e['value']:self.dbf+=1
                else:self.dbr+=1
            seconds=int(e['seconds']);micros=round((e['seconds']-seconds)*1e6)
            self.guard.consumer.feed(power_key.EVENT.pack(seconds,micros,1,116,e['value']))
        self.feed=feed
        def drain(wait=0):
            self.now+=max(wait,1)/1000
            due=[e for e in self.pending if e['seconds']<=self.now]
            self.pending=[e for e in self.pending if e['seconds']>self.now]
            for e in due:feed(e)
        self.guard.drain.side_effect=drain
        self.guard.after_entry.side_effect=lambda:setattr(self.guard.consumer,'resumed',self.now)
        handle=lambda _fd:dict(ioctl_errno=None,hung_up=False,poll_error=False,
                              held_key_codes=[116] if self.guard.consumer.down else [])
        self.enterContext(patch.object(pm.keypad_pm,'handle_state',side_effect=handle))
        self.enterContext(patch.object(pm.awake,'handle_state',side_effect=handle))
        self.cue=Mock()
        def play(_label):
            self.assertFalse(self.guard.consumer.down)
            self.now+=1
        self.cue.play.side_effect=play
        self.seq=pm.Sequence(self.guard,self.record['physical_power'],self.cue)
        original=self.seq.prompt
        def prompt(*lines):
            stamp=original(*lines)
            if 'Tap POWER' in lines[0]:self.pending += [event(stamp+.1,1),event(stamp+.2,0)]
            if lines[0]=='3/4: Press POWER.':self.pending += [event(stamp+.1,1)]
            return stamp
        self.seq.prompt=Mock(side_effect=prompt)
        @contextmanager
        def controls(stage):
            self.assertEqual(stage,'devices');yield
        def enter(stage):
            self.assertEqual(stage,'devices')
            self.assertTrue(self.guard.consumer.down)
            self.now+=.01;feed(event(self.now,0),physical=False)
            self.now+=5;self.dbr+=1  # Actual release IRQ; duplicate KEY_POWER is filtered.
        self.backend=SimpleNamespace(stage_controls=controls,enter_stage=Mock(side_effect=enter))

    def test_complete_sequence_uses_independent_release_and_fresh_tap(self):
        self.seq.run_pm(self.backend,Mock())
        pm.validate_input(self.record)
        self.backend.enter_stage.assert_called_once_with('devices')
        self.assertEqual([c.args[0] for c in self.cue.play.call_args_list],
                         ['tap-1','tap-2','screen-blank','release-during-pm','tap-4'])
        lines=self.record['physical_power']['prompts']
        hold=next(p for p in lines if p['lines'][0]=='3/4: Press POWER.')
        self.assertIn('Release even if screen is dark!',hold['lines'])
        self.assertIn('Never hold longer than 2 seconds.',hold['lines'])

    def test_extra_dispatch_during_pm_stops_before_fresh_tap(self):
        original=self.backend.enter_stage.side_effect
        def extra(stage):original(stage);self.dbf+=1
        self.backend.enter_stage.side_effect=extra
        with self.assertRaisesRegex(ValueError,'dispatch delta'):self.seq.run_pm(self.backend,Mock())
        self.assertNotIn('tap-4',[c.args[0] for c in self.cue.play.call_args_list])

    def test_release_before_admission_never_submits_pm(self):
        original=self.seq.wait
        def wait(count,seconds):
            value=original(count,seconds)
            if count==5:self.feed(event(self.now,0))
            return value
        self.seq.wait=wait
        with self.assertRaisesRegex(ValueError,'dispatch delta'):self.seq.run_pm(self.backend,Mock())
        self.backend.enter_stage.assert_not_called()


if __name__=='__main__':unittest.main()
