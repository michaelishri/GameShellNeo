"""Failure boundaries of the one-shot sleep controller; never access a real PM device."""
from copy import deepcopy
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import sleep_rtc as sleep
import test_pm_platform as existing
import test_power_key_policy as policy_tests

spec = importlib.util.spec_from_file_location('sleep_host', TOOLS/'check-sleep-rtc.py')
host = importlib.util.module_from_spec(spec); spec.loader.exec_module(host)
spec = importlib.util.spec_from_file_location('sleep_report', TOOLS/'report-sleep-evidence.py')
report = importlib.util.module_from_spec(spec); spec.loader.exec_module(report)
TOKEN = 'a'*32


def qualified():
    power = dict(control='on', runtime_status='active', runtime_usage='2', runtime_enabled='forbidden')
    def snapshot(t, successes):
        return dict(boot_id='boot', image={'v':'17'}, kernel='kernel', monotonic_seconds=t,
                    rsb_links={sleep.SDIO:{'consumer':{'power':deepcopy(power)}}},
                    stats={'success':str(successes),'fail':'0','failed_suspend':'0'})
    records=[]
    for i,stage in enumerate(['freezer','devices']+['platform']*5):
        records.append(dict(run_id=f'{i:032x}', stage=stage,passed=True,event='complete',
            before=snapshot(i*10,i),after=snapshot(i*10+5,i+1),process_memory_ok=True,
            keypad=dict(trace=existing.trace(), trace_overrun=False,trace_restored=True,
                        old_handle_after={'disconnected':False}),power_key={'handed_back':True},
            wifi_trace={'restored':True,'trace_lost':False},usb_ssh_verified=True,wifi_ssh_verified=True))
    return records, snapshot(100,7)


class Admission(unittest.TestCase):
    def test_exact_baseline_and_rejected_evidence(self):
        records,current=qualified()
        self.assertEqual(len(sleep.prerequisite(records,current)),7)
        changes = [lambda r,c:r.pop(), lambda r,c:r[1].update(passed=False),
            lambda r,c:r[1].update(run_id=r[0]['run_id']),
            lambda r,c:r[2]['after'].update(boot_id='other'),
            lambda r,c:r[3]['after'].update(image={'v':'old'}),
            lambda r,c:r[3]['after']['stats'].update(fail='1'),
            lambda r,c:r[4]['before']['stats'].update(success='6'),
            lambda r,c:r[4]['before'].update(monotonic_seconds=1),
            lambda r,c:c['stats'].update(success='8'),
            lambda r,c:c['rsb_links'][sleep.SDIO]['consumer']['power'].update(runtime_usage='3'),
            lambda r,c:r[6]['keypad'].update(trace_overrun=True)]
        for change in changes:
            r,c=deepcopy(records),deepcopy(current); change(r,c)
            with self.subTest(change=change), self.assertRaises(ValueError): sleep.prerequisite(r,c)

    def test_digest_binds_device_content_but_excludes_host_route_receipts(self):
        records,_=qualified(); r=records[0]
        device=deepcopy({k:v for k,v in r.items() if not k.endswith('_ssh_verified')})
        self.assertEqual(sleep.digest(r),sleep.digest(device))
        device['before']['kernel']='other'
        self.assertNotEqual(sleep.digest(r),sleep.digest(device))

    def test_host_does_not_trust_summary_boolean_or_unproved_routes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'diagnostics').mkdir()
            records,current=qualified(); rows=[]
            for i,r in enumerate(records):
                directory=root/'diagnostics'/str(i);directory.mkdir()
                p=directory/'result.json';p.write_text(json.dumps(r));rows.append({'capture':str(p)})
            path=root/'history.json';path.write_text(json.dumps({'stable':True,'cycles':rows}))
            with patch.object(host,'LOCAL',root):
                self.assertEqual(len(host.receipt(path,current)['runs']),7)
                p=Path(rows[0]['capture']);r=records[0];r['usb_ssh_verified']=False;p.write_text(json.dumps(r))
                with self.assertRaisesRegex(ValueError,'route'):host.receipt(path,current)
                rows[0]['capture']=str(root/'outside/result.json');(root/'outside').mkdir()
                (root/'outside/result.json').write_text(json.dumps(records[0]));path.write_text(json.dumps({'cycles':rows}))
                with self.assertRaisesRegex(ValueError,'saved diagnostic'):host.receipt(path,current)


class Collection(unittest.TestCase):
    def test_explicit_wifi_preserves_failed_original_and_rejects_wrong_run(self):
        value = dict(run_id=TOKEN, event='failed', passed=False,
                     error='USB did not return', policy_owner_retained=True)
        with patch.object(host, 'device', return_value=nullcontext('client')) as device, \
                patch.object(host, 'run', return_value=json.dumps(value).encode()):
            self.assertEqual(host.collect({}, TOKEN, 'wifi'), value)
            device.assert_called_once_with({}, 'wifi')
            value['run_id'] = 'b'*32
            with patch.object(host, 'run', return_value=json.dumps(value).encode()), \
                    self.assertRaisesRegex(ValueError, 'another run'):
                host.collect({}, TOKEN, 'wifi')

    def test_bad_route_or_token_never_contacts_device(self):
        with patch.object(host, 'device') as device:
            for token, route in ((TOKEN, 'other'), ('../other', 'wifi')):
                with self.assertRaises(ValueError):
                    host.collect({}, token, route)
            device.assert_not_called()

    def test_collect_mode_never_submits_or_cleans_up_and_marks_a_changed_boot(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); capture=root/'capture'; capture.mkdir()
            value=dict(run_id=TOKEN, event='failed', passed=False, before={'boot_id':'old'})
            with patch.object(host, 'LOCAL', root), \
                    patch.object(host, 'evidence_directory', return_value=capture), \
                    patch.object(host, 'load_env', return_value={}), \
                    patch.object(host, 'collect', return_value=value) as collect, \
                    patch.object(host, 'device', return_value=nullcontext('client')), \
                    patch.object(host, 'run', return_value=b'{"boot_id":"new"}') as run, \
                    patch.object(host, 'service') as service, patch.object(host, 'upload') as upload, \
                    patch.object(host, 'pm_host') as pm, \
                    patch.dict(os.environ, NEO_PM_RUN=TOKEN, NEO_SLEEP_COLLECT_ROUTE='wifi'), \
                    patch.object(sys, 'argv', ['check-sleep-rtc.py', '--collect']):
                host.main()
                collect.assert_called_once_with({}, TOKEN, 'wifi')
                service.assert_not_called(); upload.assert_not_called(); pm.assert_not_called()
                self.assertEqual(run.call_count, 1)
            self.assertEqual(json.loads((capture/'result.json').read_text()), value)
            self.assertEqual(json.loads((capture/'collection.json').read_text()), dict(
                route='wifi', run_id=TOKEN, original_event='failed', same_boot=False))


class Entry(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.pm=sleep.pm_module();self.pm.POWER=self.root
        (self.root/'pm_test').write_text('[none]');(self.root/'pm_async').write_text('0')
        (self.root/'pm_wakeup_irq').write_text('31')
        self.guard=Mock();self.record={'rtc':{}};self.target=[1,0]+sleep.rtc.rtc_time(1030)
        self.count=self.enterContext(patch.object(sleep,'wakeup_count',return_value='12'))
        self.margin=self.enterContext(patch.object(sleep,'margin',return_value=30))
        self.delivery=self.enterContext(patch.object(sleep,'delivery',return_value={'count':1,'flags':0xa0}))
        self.enterContext(patch.object(sleep.rtc,'snapshot',return_value={'rtc_time':sleep.rtc.rtc_time(1030)}))
        self.enterContext(patch.object(sleep,'rtc_irq',return_value={'irq':31,'count':2}))
        self.write=self.enterContext(patch.object(sleep,'single_write'))

    def enter(self,mode='rtc-wake',persist=lambda:None):
        return sleep.enter(self.pm,self.record,self.guard,10,self.target,persist,mode)

    def test_awake_rehearsal_never_writes_wakeup_count_or_state(self):
        self.enter('rehearse');self.write.assert_not_called()
        self.delivery.assert_called_once_with(10,35000)
        self.assertIsNone(self.record['entry_intent']['state'])

    def test_exact_single_handshake_then_single_sleep_write(self):
        persisted=[]
        self.enter(persist=lambda:persisted.append(deepcopy(self.record)))
        self.assertEqual(self.write.call_args_list, [unittest.mock.call(self.root/'wakeup_count','12\n'),
                                                    unittest.mock.call(self.root/'state','freeze\n')])
        self.assertEqual(persisted[0]['entry_intent']['state'],'freeze')
        self.delivery.assert_called_once_with(10,0)

    def test_timeout_stale_counter_margin_and_intent_failure_never_submit(self):
        for fault in ('count','margin','persist','key','controls'):
            self.write.reset_mock();self.count.side_effect=None;self.margin.side_effect=None
            self.guard.before_entry.side_effect=None;(self.root/'pm_async').write_text('0')
            def persist():
                if fault=='persist':raise OSError('disk')
            if fault=='count':self.count.side_effect=subprocess.TimeoutExpired('cat',3)
            if fault=='margin':self.margin.side_effect=ValueError('expired')
            if fault=='key':self.guard.before_entry.side_effect=ValueError('pressed')
            if fault=='controls':(self.root/'pm_async').write_text('1')
            with self.subTest(fault=fault),self.assertRaises((OSError,ValueError,subprocess.TimeoutExpired)):
                self.enter(persist=persist)
            self.write.assert_not_called()

    def test_failed_handshake_never_writes_state_and_failed_state_is_not_retried(self):
        for fail_call in (1,2):
            calls=[]
            def write(path,value):
                calls.append(path.name)
                if len(calls)==fail_call:raise OSError('interrupted')
            self.write.side_effect=write
            with self.assertRaises(OSError):self.enter()
            self.assertEqual(calls,['wakeup_count','state'][:fail_call])

    def test_short_write_is_error_without_loop(self):
        with patch.object(sleep.os,'open',return_value=123),patch.object(sleep.os,'close'), \
                patch.object(sleep.os,'write',return_value=2) as write:
            # Bypass the fixture mock to execute the real single_write function.
            other=sleep.pm_module()  # No PM access; module load only.
            self.assertIsNotNone(other)
            spec=importlib.util.spec_from_file_location('sleep_write',TOOLS/'sleep_rtc.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            with self.assertRaises(OSError):module.single_write('/fake','freeze\n')
            write.assert_called_once()

    def test_bounded_wakeup_read_rejects_invalid_values(self):
        spec=importlib.util.spec_from_file_location('sleep_read',TOOLS/'sleep_rtc.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for text in ('', '-1', '12 13', str(2**32)):
            with patch.object(module.subprocess,'check_output',return_value=text) as command:
                with self.assertRaises(ValueError):module.wakeup_count()
                self.assertEqual(command.call_args.kwargs['timeout'],3)


class Alarm(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(sleep.rtc,'OWNED',self.root/'rtc'))
        self.enterContext(patch.object(sleep.rtc,'RTC',self.root/'rtc-device'))
        (self.root/'rtc-device').touch()
        self.before=dict(boot_id='boot',identity='rtc',alarm=[0,0]+sleep.rtc.rtc_time(0),rtc_time=sleep.rtc.rtc_time(1000))
        self.enterContext(patch.object(sleep.rtc,'snapshot',return_value=self.before))
        self.target=[1,0]+sleep.rtc.rtc_time(1030)
        self.enterContext(patch.object(sleep.rtc,'alarm',return_value=self.target))
        self.ioctl=self.enterContext(patch.object(sleep.fcntl,'ioctl'))
        self.restore=self.enterContext(patch.object(sleep.rtc,'restore_fd'))

    def test_owned_intent_precedes_alarm_write_and_failures_restore(self):
        for fault in ('none','persist','arm','body'):
            sleep.rtc.OWNED.unlink(missing_ok=True);self.restore.reset_mock();self.ioctl.reset_mock()
            record={}
            def persist():
                self.assertTrue(sleep.rtc.OWNED.exists())
                self.ioctl.assert_not_called()
                if fault=='persist':raise OSError('disk')
            self.ioctl.side_effect=OSError('io') if fault=='arm' else None
            try:
                with sleep.deadline(record,persist,TOKEN):
                    if fault=='body':raise InterruptedError('signal')
            except OSError:
                self.assertNotEqual(fault,'none')
            self.restore.assert_called_once()
            self.assertTrue(record['restored'])

    def test_existing_and_foreign_alarms_are_never_overwritten(self):
        sleep.rtc.OWNED.write_text('other')
        with self.assertRaises(ValueError):
            with sleep.deadline({},lambda:None,TOKEN):self.fail()
        self.ioctl.assert_not_called();self.restore.assert_not_called()
        sleep.rtc.OWNED.unlink();self.before['alarm'][0]=1
        with self.assertRaises(ValueError):
            with sleep.deadline({},lambda:None,TOKEN):self.fail()
        self.ioctl.assert_not_called();self.restore.assert_not_called()

    def test_expired_or_changed_alarm_cannot_admit_entry(self):
        for changed in ({'rtc_time':sleep.rtc.rtc_time(1020)}, {'alarm':[0,0]+self.target[2:]},
                        {'alarm':[1,1]+self.target[2:]}, {'rtc_time':sleep.rtc.rtc_time(990)}):
            current=self.before|{'alarm':self.target}|changed
            with patch.object(sleep.rtc,'snapshot',return_value=current),self.assertRaises(ValueError):sleep.margin(10,self.target)

    def test_new_owner_is_preserved_on_unwind(self):
        with self.assertRaisesRegex(ValueError,'ownership changed'):
            with sleep.deadline({},lambda:None,TOKEN):
                sleep.rtc.OWNED.write_text('{}')
        self.restore.assert_not_called()


class Evidence(unittest.TestCase):
    @staticmethod
    def clock(boot, mono):
        return dict(boot=boot, mono=mono, mono_before=mono-1e-6, mono_after=mono+1e-6)

    @staticmethod
    def sleep_trace(end=130, freeze=''):
        marker=(' python3-10 [003] ..... 103.000000: suspend_resume: machine_suspend[1] begin\n'+freeze+
                f' python3-10 [003] ..... {end:.6f}: suspend_resume: machine_suspend[1] end\n')
        text=existing.trace().replace('suspend_resume: dpm_resume_noirq',marker+'suspend_resume: dpm_resume_noirq',1)
        return dict(trace=text,trace_restored=True,trace_overrun=False)

    def delivery_record(self):
        return dict(mode='rtc-wake', entry_clock=self.clock(102,102),returned=self.clock(131,131),wake_irq='31',
            entry_intent=dict(mode='rtc-wake',state='freeze',pm_test='none',pm_async='0'),keypad=self.sleep_trace(),
            rtc=dict(started=self.clock(101,101), margin_seconds=29, entry_margin_seconds=29,
                irq_before={'irq':31,'count':1,'cpus':['CPU0']},
                irq_after={'irq':31,'count':2,'cpus':['CPU0']},interrupt={'flags':0xa0,'count':1},restored=True,
                after_delivery={'rtc_time':sleep.rtc.rtc_time(1031)}, requested=[1,0]+sleep.rtc.rtc_time(1030)))

    def test_functional_rtc_wake_accepts_running_timekeeping_without_claiming_energy(self):
        result=sleep.validate_delivery(self.delivery_record())
        self.assertTrue(result['functional_rtc_wake'])
        self.assertEqual(result['interval']['clock_gap_seconds'],0)
        self.assertEqual(result['s2idle_trace']['s2idle_monotonic_seconds'],27)
        self.assertEqual(result['timekeeping']['observation'],'not_observed')
        self.assertFalse(result['energy_qualified']);self.assertFalse(result['cpu_retention_qualified'])
        self.assertNotIn('suspended_seconds',result)

    def test_deadline_wake_identity_intent_and_restoration_stay_mandatory(self):
        good=self.delivery_record()
        bad=[lambda r:r.update(wake_irq='90'), lambda r:r['entry_intent'].update(pm_test='platform'),
             lambda r:r['returned'].update(boot=104),lambda r:r['rtc'].update(restored=False),
             lambda r:r['rtc']['irq_after'].update(count=1),lambda r:r['rtc']['interrupt'].update(count=2),
             lambda r:r['rtc']['after_delivery'].update(rtc_time=sleep.rtc.rtc_time(1045)),
             lambda r:r.update(mode='unknown'),lambda r:r['rtc'].update(entry_margin_seconds=14),
             lambda r:r.update(entry_clock=self.clock(125,125)),
             lambda r:r['keypad'].update(trace=existing.trace()),
             lambda r:r['keypad'].update(trace_overrun=True),
             lambda r:r['rtc']['irq_after'].update(irq=32),lambda r:r['rtc']['interrupt'].update(flags=0x80)]
        for change in bad:
            r=deepcopy(good);change(r)
            with self.subTest(change=change),self.assertRaises(ValueError):sleep.validate_delivery(r)

    def test_timer_freeze_is_separate_and_can_resume_on_another_cpu(self):
        r=self.delivery_record();r['returned']=self.clock(131,106)
        freezes=(' swapper-0 [003] ..... 103.100000: suspend_resume: timekeeping_freeze[3] begin\n'
                 ' swapper-0 [000] ..... 103.100001: suspend_resume: timekeeping_freeze[0] end\n')
        r['keypad']=self.sleep_trace(105,freezes)
        result=sleep.validate_delivery(r)
        self.assertEqual(result['timekeeping'],dict(freeze_pairs=1,observation='observed'))
        self.assertEqual(result['interval']['clock_gap_seconds'],25)
        self.assertTrue(result['functional_rtc_wake']);self.assertFalse(result['energy_qualified'])
        r['keypad']=self.sleep_trace(105)
        with self.assertRaisesRegex(ValueError,'discontinuity'):sleep.validate_delivery(r)

    def test_small_clock_skew_and_legacy_unbracketed_records_are_not_sleep_residency(self):
        r=self.delivery_record();r['returned']['boot']+=1e-6
        result=sleep.validate_delivery(r)
        self.assertEqual(result['timekeeping']['observation'],'not_observed')
        for key in ('entry_clock','returned'):
            r[key]={k:v for k,v in r[key].items() if k in ('mono','boot')}
        r['rtc']['started']={k:v for k,v in r['rtc']['started'].items() if k in ('mono','boot')}
        result=sleep.validate_delivery(r)
        self.assertIsNone(result['interval']['sampling_uncertainty_seconds'])
        self.assertFalse(result['energy_qualified'])

    def test_clocks_reject_nan_infinity_backwards_or_unbounded_reads(self):
        for value in (float('nan'),float('inf'),-1,True,'131'):
            r=self.delivery_record();r['returned']['boot']=value
            with self.assertRaises(ValueError):sleep.validate_delivery(r)
        for change in (lambda r:r['returned'].update(mono_before=120),
                       lambda r:r['returned'].pop('mono_after'),
                       lambda r:r.update(returned=self.clock(131,132)),
                       lambda r:r.update(returned=self.clock(100,100))):
            r=self.delivery_record();change(r)
            with self.assertRaises(ValueError):sleep.validate_delivery(r)

    def test_awake_rehearsal_never_claims_functional_sleep(self):
        r=self.delivery_record();r['mode']='rehearse';r['keypad']['trace']=''
        result=sleep.validate_delivery(r)
        self.assertFalse(result['functional_rtc_wake']);self.assertFalse(result['energy_qualified'])
        r['keypad']=self.sleep_trace()
        with self.assertRaisesRegex(ValueError,'awake rehearsal'):sleep.validate_delivery(r)

    def test_late_rtc_after_an_early_loop_exit_cannot_be_counted_as_sleep(self):
        r=self.delivery_record();r['keypad']=self.sleep_trace(108)
        with self.assertRaisesRegex(ValueError,'wait inside s2idle'):sleep.validate_delivery(r)

    def test_bracketed_clock_capture(self):
        with patch.object(sleep.time,'monotonic',side_effect=[12,12.002]), \
                patch.object(sleep.time,'clock_gettime',return_value=20):
            value=sleep.clock_pair()
            self.assertAlmostEqual(value.pop('mono'),12.001)
            self.assertEqual(value,dict(boot=20,mono_before=12,mono_after=12.002))

    def test_timer_freeze_incomplete_nested_or_outside_boundary_rejected(self):
        a=' idle-0 [003] ..... 103.100000: suspend_resume: timekeeping_freeze[3] begin\n'
        b=' idle-0 [002] ..... 103.100001: suspend_resume: timekeeping_freeze[2] end\n'
        for freeze in (a,b,b+a,a+a+b+b,a+b.replace('103.100001','102.000000'),a+b.replace('[2]','[x]')):
            with self.assertRaises(ValueError):sleep.validate_trace(self.sleep_trace(130,freeze))
        record=self.sleep_trace();record['trace']+=a+b
        with self.assertRaises(ValueError):sleep.validate_trace(record)

    def test_usb_failure_still_rejects_after_wake_assessment_is_saved(self):
        r=self.delivery_record();r.update(before={},after={})
        pm=Mock();pm.validate.side_effect=ValueError('usb_configured')
        with self.assertRaisesRegex(ValueError,'usb_configured'):sleep.health(pm,r,{})
        self.assertTrue(r['delivery']['functional_rtc_wake'])
        self.assertFalse(r['delivery']['energy_qualified'])

    def test_offline_assessment_keeps_original_usb_failure_and_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'result.json'
            value=self.delivery_record()|dict(event='failed',passed=False,error='usb_configured',run_id=TOKEN)
            path.write_text(json.dumps(value));original=path.read_bytes()
            result=report.assess(path)
            self.assertTrue(result['measurement_checks_passed'])
            self.assertFalse(result['original_passed']);self.assertFalse(result['overall_requalified'])
            self.assertEqual(result['original_error'],'usb_configured')
            self.assertEqual(path.read_bytes(),original)
            value['wake_irq']='99';path.write_text(json.dumps(value))
            result=report.assess(path)
            self.assertFalse(result['measurement_checks_passed'])
            value['event']='started';path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):report.assess(path)

    def test_sleep_trace_boundaries_errors_and_debug_trace_rejected(self):
        record=self.sleep_trace();good=record['trace']
        marker='suspend_resume: machine_suspend[1] begin\nsuspend_resume: machine_suspend[1] end\n'
        self.assertTrue(sleep.validate_trace(record)['s2idle_boundary'])
        for bad in (existing.trace(),good+marker,good.replace('err=0','err=-5'),
                    good.replace('machine_suspend[1]','machine_suspend[3]'),marker+existing.trace()):
            with self.assertRaises(ValueError):sleep.validate_trace(record|{'trace':bad})
        with self.assertRaises(ValueError):sleep.validate_trace(record|{'trace_overrun':True})

    def test_missing_irq_does_not_wait_for_later_awake_delivery(self):
        poll=Mock();poll.poll.return_value=[]
        with patch.object(sleep.select,'poll',return_value=poll),patch.object(sleep.os,'read') as read:
            with self.assertRaisesRegex(ValueError,'early/unrelated'):sleep.delivery(10,0)
            poll.poll.assert_called_once_with(0);read.assert_not_called()

    def test_irq_mapping_rejects_changed_controller(self):
        text=' CPU0 CPU1\n 31: 1 2 sun6i-r-intc 40 Level 1f00000.rtc\n'
        self.assertEqual(sleep.rtc_irq(text)['count'],3)
        for bad in (text+text.splitlines()[-1],text.replace('40 Level','41 Edge'),text.replace('1 2','1 x')):
            with self.assertRaises(ValueError):sleep.rtc_irq(bad)


class ControlOwnership(unittest.TestCase):
    def test_restore_never_removes_foreign_or_cross_boot_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);pm=sleep.pm_module();pm.POWER=root;pm.BOOT=root/'boot'
            pm.BOOT.write_text('boot');(root/'pm_test').write_text('[none]');(root/'pm_async').write_text('1')
            with patch.object(sleep,'OWNED',root/'owned'):
                for abort in (False,True):
                    try:
                        with sleep.controls(pm,TOKEN):
                            self.assertEqual(pm.read(root/'pm_async'),'0')
                            if abort:raise InterruptedError('abort')
                    except InterruptedError:pass
                    self.assertFalse(sleep.OWNED.exists());self.assertEqual(pm.read(root/'pm_async'),'1')
                with sleep.controls(pm,TOKEN):
                    with self.assertRaises(ValueError):sleep.restore_controls(pm,'b'*32)
                    self.assertTrue(sleep.OWNED.exists())


class UntouchedPolicy(unittest.TestCase):
    setUp = policy_tests.Policy.setUp

    def test_late_cleanup_error_rearms_ignore_before_ancestor_inhibitor_exits(self):
        record={'policy_restored':True,'before':{'boot_id':'boot'}}
        sleep.retain_failed_handoff(record,TOKEN)
        self.assertFalse(record['policy_restored'])
        self.assertTrue(record['policy_rearmed_after_failure'])
        sleep.policy.verify(TOKEN)
        with patch.object(sleep.policy,'acquire') as acquire:
            sleep.retain_failed_handoff(record,TOKEN)
            acquire.assert_not_called()

    def test_foreign_owner_is_retained_if_late_policy_rearm_cannot_acquire(self):
        sleep.policy.OWNED.write_text('foreign')
        record={'policy_restored':True,'before':{'boot_id':'boot'}}
        sleep.retain_failed_handoff(record,TOKEN)
        self.assertIn('policy_rearm_error',record)
        self.assertEqual(sleep.policy.OWNED.read_text(),'foreign')
    def test_post_sleep_handoff_rejects_events_or_pek_irq_even_if_logically_up(self):
        policy=sleep.policy;policy.acquire(TOKEN,'boot')
        guard=Mock();guard.record={'events':[]};guard.fd=10
        guard.consumer.released.return_value=True
        with patch.object(sleep.power_key_pm,'irq_counts',return_value={}), \
                patch.object(sleep.power_key_pm,'require_delta') as delta, \
                patch.object(sleep.keypad_pm,'handle_state',return_value={}), \
                patch.object(Path,'iterdir',return_value=iter([])):
            handoff=sleep.UntouchedHandoff(guard,{}, {})
            handoff.check()
            guard.record['events']=[{'type':1,'code':116,'value':0}]  # Could be synthetic clearing.
            with self.assertRaises(ValueError):policy._restore_checked(TOKEN,handoff.check)
            self.assertTrue(policy.DROPIN.exists())
            guard.record['events']=[];delta.side_effect=ValueError('PEK changed')
            with self.assertRaises(ValueError):policy._restore_checked(TOKEN,handoff.check)
            self.assertTrue(policy.DROPIN.exists())


class Recovery(unittest.TestCase):
    def test_cleanup_is_run_scoped_attempts_all_resources_and_never_restores_poweroff(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);results=root/'results';directory=results/TOKEN;directory.mkdir(parents=True)
            (directory/'started.json').write_text(json.dumps({'run_id':TOKEN,'before':{'boot_id':'boot'}}))
            pm=sleep.pm_module();pm.BOOT=root/'boot';pm.BOOT.write_text('boot')
            paths={'rtc':root/'rtc','controls':root/'controls','wifi':root/'wifi','keypad':root/'keypad','usb':root/'usb'}
            for name,path in paths.items():
                key='sleep_run' if name in ('wifi','keypad') else 'run_id'
                path.write_text(json.dumps({key:TOKEN}));path.chmod(0o600)
            with patch.object(sleep,'RESULTS',results),patch.object(sleep,'OWNED',paths['controls']), \
                    patch.object(sleep.rtc,'OWNED',paths['rtc']),patch.object(sleep.wifi_trace,'OWNED',paths['wifi']), \
                    patch.object(sleep.keypad_pm,'OWNED',paths['keypad']), \
                    patch.object(sleep.usb_trace,'OWNED',paths['usb']),patch.object(sleep.usb_trace,'restore') as usb, \
                    patch.object(sleep.rtc,'restore',side_effect=OSError('rtc failed')) as rtc, \
                    patch.object(sleep,'restore_controls') as controls,patch.object(sleep.wifi_trace,'restore') as wifi, \
                    patch.object(sleep.keypad_pm,'restore_trace') as keypad, \
                    patch.object(sleep.policy,'_restore_checked') as poweroff:
                with self.assertRaisesRegex(ValueError,'Incomplete recovery'):sleep.recover(pm,TOKEN)
                rtc.assert_called_once();controls.assert_called_once();wifi.assert_called_once();keypad.assert_called_once()
                usb.assert_called_once_with(TOKEN)
                poweroff.assert_not_called()
                record=json.loads((directory/'recovery.json').read_text())
                self.assertFalse(record['controls_restored'])
                paths['rtc'].write_text(json.dumps({'run_id':'b'*32}));rtc.reset_mock()
                with self.assertRaisesRegex(ValueError,'foreign ownership'):sleep.recover(pm,TOKEN)
                rtc.assert_not_called();self.assertTrue(paths['rtc'].exists())
                pm.BOOT.write_text('other');controls.reset_mock()
                with self.assertRaisesRegex(ValueError,'another boot'):sleep.recover(pm,TOKEN)
                controls.assert_not_called()


class HostCommand(unittest.TestCase):
    def test_device_clock_inspection_never_enters_or_recovers_pm(self):
        with patch.object(sys,'argv',['sleep_rtc.py','--clock-inspect']), \
                patch.object(sleep,'inspect_clocks',return_value={}) as inspect, \
                patch.object(sleep,'run') as run,patch.object(sleep,'recover') as recover, \
                patch.object(sleep,'pm_module') as pm:
            sleep.main()
            inspect.assert_called_once();run.assert_not_called();recover.assert_not_called();pm.assert_not_called()

    def test_awake_and_real_entry_are_distinct_no_pipe_or_retries(self):
        awake=host.service('/tmp/gameshellneo-sleep.test',TOKEN,'rehearse','')
        real=host.service('/tmp/gameshellneo-sleep.test',TOKEN,'rtc-wake','b'*32)
        self.assertIn('--rehearse',awake);self.assertNotIn('--rtc-wake',awake)
        self.assertIn('--rtc-wake',real);self.assertIn('--attended',real)
        self.assertNotIn('--pipe',real);self.assertNotIn('--wait',real)
        cleanup=[x for x in real if x.startswith('--property=ExecStopPost=')][0]
        self.assertIn('--recover --run-id '+TOKEN,cleanup);self.assertNotIn('power_key_policy',cleanup)
        for mode in ('none','devices','freeze',''):
            with self.assertRaises(ValueError):host.service('/tmp/gameshellneo-sleep.test',TOKEN,mode,'')

    def test_actual_sleep_requires_explicit_attended_flag_before_network(self):
        with patch.object(sys,'argv',['test','--rtc-wake']),patch.dict(os.environ,{'NEO_SLEEP_ATTENDED':'0'}), \
                patch.object(host,'load_env') as load:
            with self.assertRaises(SystemExit):host.main()
            load.assert_not_called()


if __name__=='__main__':unittest.main()
