"""Awake physical-edge proof, prompt failures and retained-policy handoff bounds."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import power_key as key
import power_key_input as inputs
import power_key_policy as policy


def event(seconds, value, code=116, kind=1):
    return dict(seconds=seconds, type=kind, code=code, value=value)


def evidence():
    events, stages = [], []
    for i, label in enumerate(inputs.LABELS):
        start = 10 + i*5
        events += [event(start, 1), event(start+1, 0)]
        stage = dict(label=label, prompt_seconds=start-1, press_seconds=start, release_seconds=start+1)
        if label == 'hold': stage.update(worker_killed_seconds=start+0.1, release_prompt_seconds=start+0.8)
        stages.append(stage)
    return events, stages


class Evidence(unittest.TestCase):
    def test_four_pairs_and_held_worker_death_are_required(self):
        events, stages = evidence()
        self.assertEqual(inputs.validate_sequence(events, stages), events)
        with self.assertRaises(ValueError): inputs.validate_sequence(events[:-1], stages)
        with self.assertRaises(ValueError): inputs.validate_sequence(events+[event(31,1),event(32,0)],stages)
        for field,value in (('prompt_seconds',30),('worker_killed_seconds',22),('release_prompt_seconds',22)):
            changed=deepcopy(stages); changed[2][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                inputs.validate_sequence(events,changed)

    def test_duplicate_unpaired_wrong_key_loss_and_reordered_time_rejected(self):
        for events in ([event(1,0)], [event(1,1),event(2,1)], [event(1,1,42)],
                [event(1,2)], [event(1,0,3,0)], [event(2,1),event(1,0)]):
            with self.subTest(events=events), self.assertRaises(ValueError): inputs.edges(events)

    def test_repeat_is_allowed_only_between_press_and_release(self):
        values=[event(1,1),event(2,2),event(3,0)]
        self.assertEqual(inputs.edges(values),[values[0],values[2]])
        with self.assertRaises(ValueError): inputs.edges(values+[event(4,2)])

    def test_overlong_or_zero_duration_is_not_qualified(self):
        events, stages=evidence()
        for end in (10,13):
            changed=deepcopy(events);changed[1]['seconds']=end
            steps=deepcopy(stages);steps[0]['release_seconds']=end
            with self.assertRaises(ValueError): inputs.validate_sequence(changed,steps)


class Handoff(unittest.TestCase):
    def setUp(self):
        self.events,self.stages=evidence()
        self.guard=Mock()
        self.guard.record={'events':deepcopy(self.events)}
        self.guard.consumer=key.Consumer({})
        self.guard.consumer.last_event=0
        self.before={'boot_id':'boot','stats':{'success':'7','fail':'0'}}
        self.state=dict(ioctl_errno=None,hung_up=False,poll_error=False,held_key_codes=[])
        self.enterContext(patch.object(inputs,'handle_state',return_value=self.state))
        self.enterContext(patch.object(inputs,'awake_state',return_value=self.before))
        self.enterContext(patch.object(inputs.time,'monotonic',return_value=100))
        self.inhibitor=self.enterContext(patch.object(key,'verify_inhibitor',return_value={}))

    def test_complete_unchanged_awake_stream_can_hand_back(self):
        proof=inputs.AwakeHandoff(self.guard,self.stages,self.before)
        proof.check();self.assertEqual(self.inhibitor.call_count,2)

    def test_late_event_lost_handle_or_held_bitmap_cannot_hand_back(self):
        proof=inputs.AwakeHandoff(self.guard,self.stages,self.before)
        self.guard.record['events'] += [event(30,1)]
        with self.assertRaises(ValueError): proof.check()
        self.guard.record['events']=self.events.copy()
        for name,value in (('ioctl_errno',19),('hung_up',True),('poll_error',True),('held_key_codes',[116])):
            with patch.object(inputs,'handle_state',return_value=self.state|{name:value}), self.assertRaises(ValueError):
                proof.check()

    def test_pm_or_synthetic_resume_clear_cannot_use_awake_handoff(self):
        proof=inputs.AwakeHandoff(self.guard,self.stages,self.before)
        self.guard.consumer.resumed=12
        with self.assertRaises(ValueError):proof.check()
        self.guard.consumer.resumed=None
        with patch.object(inputs,'awake_state',return_value={'stats':{'success':'8'}}),self.assertRaises(ValueError):proof.check()

    def test_recent_event_and_lost_inhibitor_are_rejected(self):
        proof=inputs.AwakeHandoff(self.guard,self.stages,self.before)
        self.guard.consumer.last_event=99.9
        with self.assertRaises(ValueError):proof.check()
        self.guard.consumer.last_event=0
        self.inhibitor.side_effect=ValueError('inhibitor lost')
        with self.assertRaises(ValueError):proof.check()


class PromptSequence(unittest.TestCase):
    def setUp(self):
        self.now=100.0
        self.pending=[]
        self.guard=Mock(fd=10,record={})
        self.guard.consumer=key.Consumer(self.guard.record)
        self.enterContext(patch.object(inputs.time,'monotonic',side_effect=lambda:self.now))
        self.guard.consumer.last_event=self.now
        self.enterContext(patch.object(Path,'write_text'))
        def drain(wait=0):
            self.now+=max(wait,1)/1000
            due=[e for e in self.pending if e['seconds']<=self.now]
            self.pending=[e for e in self.pending if e['seconds']>self.now]
            for e in sorted(due,key=lambda e:e['seconds']):
                seconds=int(e['seconds']); micros=round((e['seconds']-seconds)*1e6)
                self.guard.consumer.feed(key.EVENT.pack(seconds,micros,e['type'],e['code'],e['value']))
        self.guard.drain.side_effect=drain
        self.enterContext(patch.object(inputs,'handle_state',side_effect=lambda _fd:
            dict(ioctl_errno=None,hung_up=False,poll_error=False,
                 held_key_codes=[116] if self.guard.consumer.down else [])))
        self.cue=Mock()
        self.cue.play.side_effect=lambda _label:setattr(self,'now',self.now+1)
        self.record={};self.seq=inputs.Sequence(self.guard,self.record,self.cue)
        original=self.seq.prompt
        def prompt(*lines):
            stamp=original(*lines)
            if 'Tap POWER' in lines[0]: self.pending += [event(stamp+.1,1),event(stamp+.2,0)]
            if 'HOLD POWER' in lines[0]: self.pending += [event(stamp+.1,1)]
            if lines[0]=='RELEASE POWER NOW.': self.pending += [event(stamp+.1,0)]
            return stamp
        self.seq.prompt=Mock(side_effect=prompt)
        self.kill=self.enterContext(patch.object(policy,'kill_worker',return_value=-9))

    def test_complete_prompt_sequence_confirms_only_after_release(self):
        def cue(_label):
            self.assertFalse(self.guard.consumer.down)
            self.now+=1
        self.cue.play.side_effect=cue
        self.seq.run(Mock())
        inputs.validate_sequence(self.guard.record['events'],self.record['stages'])
        self.assertEqual([c.args[0] for c in self.cue.play.call_args_list],list(inputs.LABELS))
        self.kill.assert_called_once()
        self.assertEqual(self.kill.call_args.kwargs,{'timeout':0.2})

    def test_worker_timeout_still_displays_release_immediately(self):
        self.kill.side_effect=subprocess.TimeoutExpired('worker',.2)
        with self.assertRaises(subprocess.TimeoutExpired):self.seq.run(Mock())
        self.assertEqual(self.seq.prompt.call_args.args[0],'RELEASE POWER NOW.')
        self.assertEqual(self.cue.play.call_count,2)

    def test_extra_tap_during_confirmation_rejects_run(self):
        def extra(_label):
            self.pending += [event(self.now+.1,1),event(self.now+.2,0)]
            self.now+=1
        self.cue.play.side_effect=extra
        with self.assertRaisesRegex(ValueError,'Unexpected power key'):self.seq.run(Mock())
        self.kill.assert_not_called()

    def test_early_hold_release_rejects_run_and_prompts_release(self):
        def early(*_args,**_kwargs):
            self.pending.append(event(self.now+.1,0));return -9
        self.kill.side_effect=early
        with self.assertRaisesRegex(ValueError,'before the release prompt'):self.seq.run(Mock())
        self.assertEqual(self.seq.prompt.call_args.args[0],'RELEASE POWER NOW.')


class Restoration(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.token='a'*32
        for obj,name,value in ((inputs,'UI_OWNED',self.root/'ui'),
                (inputs.speaker_audio,'OWNED',self.root/'audio'),
                (inputs.keypad_input,'CONSOLE_OWNED',self.root/'console'),
                (policy,'BOOT',self.root/'boot')):
            self.enterContext(patch.object(obj,name,value))
        policy.BOOT.write_text('boot')

    def test_failed_audio_cleanup_still_attempts_console_restore(self):
        inputs.claim_ui(self.token)
        with patch.object(inputs.speaker_audio,'restore',side_effect=ValueError('audio')), \
                patch.object(inputs.keypad_input,'restore_console') as console, self.assertRaises(ValueError):
            inputs.restore_ui(self.token)
        console.assert_called_once()
        self.assertTrue(inputs.UI_OWNED.exists())

    def test_absent_or_foreign_ui_owner_never_restores_other_experiment(self):
        with patch.object(inputs.speaker_audio,'restore') as audio, \
                patch.object(inputs.keypad_input,'restore_console') as console:
            inputs.restore_ui(self.token)
            audio.assert_not_called();console.assert_not_called()
            inputs.claim_ui(self.token)
            with self.assertRaises(ValueError):inputs.restore_ui('b'*32)
            audio.assert_not_called();console.assert_not_called()
            policy.BOOT.write_text('other')
            with self.assertRaises(ValueError):inputs.restore_ui(self.token)

    def test_existing_audio_or_console_prevents_ui_claim(self):
        for path in (inputs.speaker_audio.OWNED,inputs.keypad_input.CONSOLE_OWNED):
            path.touch()
            with self.assertRaises(ValueError):inputs.claim_ui(self.token)
            self.assertFalse(inputs.UI_OWNED.exists());path.unlink()

    def test_completed_ui_restore_removes_only_its_owner(self):
        inputs.claim_ui(self.token)
        with patch.object(inputs.speaker_audio,'restore'),patch.object(inputs.keypad_input,'restore_console'):
            inputs.restore_ui(self.token)
        self.assertFalse(inputs.UI_OWNED.exists())

    def test_worker_exit_must_be_sigkill(self):
        child=Mock();child.wait.return_value=0
        with self.assertRaises(ValueError):policy.kill_worker(child)
        child.kill.assert_called_once()


if __name__=='__main__':unittest.main()
