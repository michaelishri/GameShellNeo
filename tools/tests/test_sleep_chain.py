"""Sleep evidence lineage, durable admission and stop-on-failure batch behavior."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_sleep_rtc as existing

sleep, host = existing.sleep, existing.host
SOURCE = {'sleep_rtc': 'current-test-source'}
REHEARSAL = 'e'*32


def chain(count=2):
    debug, current = existing.qualified()
    ids = [r['run_id'] for r in debug]
    records = []
    for index in range(count):
        start = 100+100*index
        a = deepcopy(current)
        a.update(monotonic_seconds=start, stats=dict(success=str(7+index), fail='0', failed_suspend='0'),
                 journal='baseline', usb=['configured'])
        for key in ('pm','pm_test_delay','masks','inputs','backlight','wifi_config_sha256',
                    'wifi_power_save','charger','cpu_policy'):
            a[key] = {}
        b = deepcopy(a);b['monotonic_seconds'] = start+40;b['stats']['success'] = str(8+index)
        b['journal'] += '\nPM completion'
        record = existing.Evidence().delivery_record()
        for key in ('entry_clock', 'returned'):
            for field in record[key]: record[key][field] += index*100
        for field in record['rtc']['started']: record['rtc']['started'][field] += index*100
        record['keypad'] = existing.Evidence.sleep_trace()
        record['keypad']['trace'] = record['keypad']['trace'].replace('103.000000',f'{103+index*100}.000000').replace('130.000000',f'{130+index*100}.000000')
        record['rtc']['irq_before']['count'] = index+1
        record['rtc']['irq_after']['count'] = index+2
        record['keypad'].update(before={'usb':{'attributes':{}},'inputs':[]},
            after={'usb':{'attributes':{}},'inputs':[]},
            old_handle_after={'disconnected':False,'ioctl_errno':None})
        previous = records[-1]['run_id'] if records else ids[-1]
        token = f'{100+index:032x}'
        record.update(run_id=token, before=a, after=b, event='complete',passed=True,sources=deepcopy(SOURCE),
            process_memory_ok=True,policy_restored=True,policy_before={},policy_after={},
            policy_owner_retained=False,dropin_retained=False,controls_retained=False,rtc_owner_retained=False,
            audio_before={},audio_after={},rehearsal=REHEARSAL,
            parent_claim=dict(parent=previous,run_id=token,boot_id='boot'),
            qualification=dict(runs=ids,sleep_runs=[r['run_id'] for r in records]),
            power_key=dict(events=[],handed_back=True,logical_release_verified=True,descriptor_closed=True),
            wifi_trace=dict(restored=True,trace_lost=False),
            usb_trace=dict(restored=True,trace_lost=False,before={'state':'configured','carrier':'1'},
                           after={'state':'configured','carrier':'1'}))
        sleep.health(Mock(FAULTS=sleep.pm_module().FAULTS), record, {})
        records.append(record)
    if records:
        current = deepcopy(records[-1]['after']); current['monotonic_seconds'] += 10
    return debug, records, current


class Lineage(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(sleep, 'sources', return_value=SOURCE))
        self.pm = Mock(FAULTS=sleep.pm_module().FAULTS)

    def test_valid_chain_rechecks_health_and_original_debug_anchor(self):
        for count in (0,1,4,sleep.MAX_SLEEP_CHAIN):
            debug, records, current = chain(count)
            result = sleep.history(self.pm, debug, records, current, {})
            self.assertEqual(result['sleep_runs'],[r['run_id'] for r in records])
            self.assertEqual(len(result['runs']),7)
            for record in records:
                self.assertTrue(record['delivery']['functional_rtc_wake'])
                self.assertFalse(record['delivery']['energy_qualified'])
        self.assertGreater(self.pm.validate.call_count,0)

    def test_failures_sources_ownership_trace_usb_and_ancestry_are_not_requalified(self):
        mutations = [
            lambda d,r,c:r[0].update(passed=False),
            lambda d,r,c:r[0].update(event='started'),
            lambda d,r,c:r[0].update(sources={'sleep_rtc':'old'}),
            lambda d,r,c:r[0].update(controls_retained=True),
            lambda d,r,c:r[0]['delivery'].update(energy_qualified=True),
            lambda d,r,c:r[0]['power_key'].update(descriptor_closed=False),
            lambda d,r,c:r[0]['usb_trace']['after'].update(carrier='0'),
            lambda d,r,c:r[0]['wifi_trace'].update(trace_lost=True),
            lambda d,r,c:r[0]['keypad'].update(trace_overrun=True),
            lambda d,r,c:r[0]['after']['stats'].update(success='9'),
            lambda d,r,c:r[0]['after'].update(boot_id='rebooted'),
            lambda d,r,c:r[0]['after'].update(image={'other':True}),
            lambda d,r,c:r[0]['parent_claim'].update(run_id='f'*32),
            lambda d,r,c:r[1].update(run_id=r[0]['run_id']),
            lambda d,r,c:r[1]['qualification'].update(sleep_runs=[]),
            lambda d,r,c:r[1].update(rehearsal='f'*32),
            lambda d,r,c:r[1]['before'].update(monotonic_seconds=120),
            lambda d,r,c:r[1]['rtc']['irq_before'].update(count=9),
            lambda d,r,c:c['stats'].update(success='10'),
            lambda d,r,c:c.update(monotonic_seconds=float('nan')),
            lambda d,r,c:c['rsb_links'][sleep.SDIO]['consumer']['power'].update(runtime_usage='3'),
            lambda d,r,c:d[-1]['after']['stats'].update(success='8'),
        ]
        for mutate in mutations:
            debug, records, current = chain()
            mutate(debug,records,current)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                sleep.history(self.pm,debug,records,current,{})

    def test_reordering_omission_and_bound_are_rejected(self):
        d,r,c=chain(3)
        for changed in (r[::-1],r[1:],r[:1]+r[2:],r+[deepcopy(r[0])]*sleep.MAX_SLEEP_CHAIN):
            with self.assertRaises(ValueError):sleep.history(self.pm,d,changed,c,{})


class DeviceLedger(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(sleep,'sources',return_value=SOURCE))
        self.enterContext(patch.object(sleep,'RESULTS',self.root/'sleep'))
        self.enterContext(patch.object(sleep,'OWNED',self.root/'owned'))
        self.enterContext(patch.object(sleep.pm_platform,'admission',return_value={'run_id':REHEARSAL}))
        self.pm = Mock(RESULTS=self.root/'debug',STATE=self.root/'state',FAULTS=sleep.pm_module().FAULTS)
        self.pm.command.return_value=''
        self.debug,self.records,self.current=chain(2)
        for r in self.debug+self.records:
            for side in ('before','after'):
                r[side]['image']['project_inputs_sha256']={sleep.SDIO_PATCH:sleep.SDIO_SHA}
        self.current['image']['project_inputs_sha256']={sleep.SDIO_PATCH:sleep.SDIO_SHA}
        self.irq=self.enterContext(patch.object(sleep,'rtc_irq',return_value=self.records[-1]['rtc']['irq_after']))
        self.receipt=dict(boot_id='boot',runs=[],sleeps=[])
        for records,root,key in ((self.debug,self.pm.RESULTS,'runs'),(self.records,sleep.RESULTS,'sleeps')):
            for r in records:
                directory=root/r['run_id'];directory.mkdir(parents=True)
                (directory/'result.json').write_text(json.dumps(r))
                self.receipt[key].append(dict(run_id=r['run_id'],sha256=sleep.digest(r)))
        for r in self.records:
            path=sleep.successor_path(self.pm,r['qualification'])
            path.write_text(json.dumps(r['parent_claim']))

    def test_device_revalidates_original_files_and_durable_claim(self):
        q=sleep.admission(self.pm,self.current,{},self.receipt)
        self.assertEqual(q['sleep_runs'],[r['run_id'] for r in self.records])
        claim=sleep.claim_successor(self.pm,q,'f'*32,'boot')
        self.assertEqual(json.loads(sleep.successor_path(self.pm,q).read_text()),claim)
        with self.assertRaises(FileExistsError):sleep.claim_successor(self.pm,q,'d'*32,'boot')
        with self.assertRaisesRegex(ValueError,'already claimed'):
            sleep.admission(self.pm,self.current,{},self.receipt)

    def test_hash_mismatch_prevents_consumption(self):
        self.receipt['sleeps'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'both-route'):
            sleep.admission(self.pm,self.current,{},self.receipt)
        q={'runs':[r['run_id'] for r in self.debug], 'sleep_runs':[r['run_id'] for r in self.records]}
        self.assertFalse(sleep.successor_path(self.pm,q).exists())

    def test_foreign_ledger_or_new_rtc_activity_rejects(self):
        q=self.records[1]['qualification'];path=sleep.successor_path(self.pm,q)
        original=path.read_text();path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'ledger'):sleep.admission(self.pm,self.current,{},self.receipt)
        path.write_text(original)
        self.irq.return_value={'irq':31,'count':99,'cpus':['CPU0']}
        with self.assertRaisesRegex(ValueError,'RTC activity'):sleep.admission(self.pm,self.current,{},self.receipt)


class Batches(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.qualification=self.root/'baseline.json'
        self.qualification.write_text(json.dumps({'cycles':[{'capture':'original'}]}))
        self.capture=self.root/'capture';self.capture.mkdir()
        self.pause=self.enterContext(patch.object(host.time,'sleep'))

    def fake_success(self,config,capture,qualification,mode,rehearsal):
        previous=json.loads(qualification.read_text()).get('sleeps',[])
        self.assertEqual(len(previous),int(capture.name.split('-')[1])-1)
        self.assertEqual(mode,'rtc-wake');self.assertEqual(rehearsal,REHEARSAL)
        value=dict(run_id=f'{100+len(previous):032x}',passed=True,event='complete',
                   usb_ssh_verified=True,wifi_ssh_verified=True)
        (capture/'result.json').write_text(json.dumps(value))
        return value

    def test_four_independent_attempts_publish_history_only_after_both_route_proofs(self):
        with patch.object(host,'experiment',side_effect=self.fake_success) as run:
            host.batch({},self.capture,self.qualification,REHEARSAL,4)
        self.assertEqual(run.call_count,4)
        summary=json.loads((self.capture/'batch.json').read_text())
        self.assertTrue(summary['passed']);self.assertEqual(len(summary['completed']),4)
        continuation=json.loads(Path(summary['qualification_next']).read_text())
        self.assertEqual(len(continuation['sleeps']),4)
        self.assertEqual(continuation['cycles'],[{'capture':'original'}])
        self.assertEqual(self.pause.call_count,3)

    def test_uncertain_second_attempt_stops_and_preserves_only_first_success(self):
        calls=[]
        def attempt(*args):
            calls.append(args)
            if len(calls)==2:raise TimeoutError('original run is uncertain')
            return self.fake_success(*args)
        with patch.object(host,'experiment',side_effect=attempt),self.assertRaises(TimeoutError):
            host.batch({},self.capture,self.qualification,REHEARSAL,4)
        self.assertEqual(len(calls),2)
        summary=json.loads((self.capture/'batch.json').read_text())
        self.assertEqual(summary['event'],'failed');self.assertFalse(summary['passed'])
        self.assertEqual(len(summary['completed']),1)
        self.assertFalse((self.capture/'cycle-2/qualification-next.json').exists())
        self.assertFalse((self.capture/'cycle-3').exists())

    def test_missing_route_proof_never_advances_or_sleeps_again(self):
        with patch.object(host,'experiment',return_value=dict(passed=True,event='complete',usb_ssh_verified=True)) as run:
            with self.assertRaisesRegex(ValueError,'SSH proofs'):
                host.batch({},self.capture,self.qualification,REHEARSAL,4)
        run.assert_called_once();self.pause.assert_not_called()
        self.assertFalse((self.capture/'cycle-1/qualification-next.json').exists())

    def test_invalid_count_never_calls_experiment(self):
        with patch.object(host,'experiment') as run:
            for count in (0,5,True,'4'):
                with self.assertRaises(ValueError):host.batch({},self.capture,self.qualification,REHEARSAL,count)
            self.qualification.write_text(json.dumps({'sleeps':[{}]*15}))
            with self.assertRaises(ValueError):host.batch({},self.capture,self.qualification,REHEARSAL,4)
        run.assert_not_called()


class Transport(unittest.TestCase):
    def setUp(self):
        from contextlib import nullcontext
        from unittest.mock import MagicMock
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.token='a'*32
        self.enterContext(patch.object(host.uuid,'uuid4',return_value=Mock(hex=self.token)))
        self.enterContext(patch.object(host,'device',side_effect=lambda *a:nullcontext(MagicMock())))
        self.enterContext(patch.object(host,'upload'))
        self.enterContext(patch.object(host,'receipt',return_value={'runs':[]}))
        self.enterContext(patch.object(host.diagnostic,'sources',return_value=SOURCE))
        self.enterContext(patch.object(host.diagnostic,'pm_module',return_value=Mock()))
        self.helper=Mock();self.helper.inline.return_value=b'{"boot_id":"boot"}'
        self.enterContext(patch.object(host,'pm_host',return_value=self.helper))
        self.enterContext(patch.object(host,'validate_result'))
        self.enterContext(patch.object(host.time,'sleep'))
        self.enterContext(patch.object(host.time,'monotonic',return_value=0))
        self.submissions=[]
        def remote(client,command,**kwargs):
            if command.startswith('systemctl show'):return b'not-found'
            if 'mktemp' in command:return b'/tmp/gameshellneo-sleep.test'
            if 'systemd-run' in command:
                self.submissions.append(command)
                raise host.paramiko.SSHException('lost after submission')
            if command=='cat /proc/sys/kernel/random/boot_id':return b'boot'
            raise AssertionError(command)
        self.enterContext(patch.object(host,'run',side_effect=remote))
        self.complete=dict(run_id=self.token,event='complete',passed=True,after={'boot_id':'boot'})

    def test_lost_submission_collects_same_id_without_a_second_submission(self):
        responses=[host.paramiko.SSHException('recovering'),{'event':'started'},self.complete]
        with patch.object(host,'collect',side_effect=responses) as collect:
            value=host.experiment({},self.root,self.root/'qualification','rtc-wake',REHEARSAL)
        self.assertEqual(len(self.submissions),1)
        self.assertEqual([call.args[1] for call in collect.call_args_list],[self.token]*3)
        self.assertTrue(value['usb_ssh_verified']);self.assertTrue(value['wifi_ssh_verified'])
        self.assertTrue((self.root/'submission-error.txt').exists())
        self.assertTrue((self.root/'collection-errors.txt').exists())

    def test_timeout_keeps_run_identity_and_never_resubmits(self):
        with patch.object(host.time,'monotonic',side_effect=[0,211]),patch.object(host,'collect') as collect:
            with self.assertRaisesRegex(TimeoutError,self.token):
                host.experiment({},self.root,self.root/'qualification','rtc-wake',REHEARSAL)
        self.assertEqual(len(self.submissions),1);collect.assert_not_called()
        self.assertEqual(json.loads((self.root/'run.json').read_text())['run_id'],self.token)

    def test_failed_wifi_proof_does_not_publish_route_acceptance(self):
        self.helper.wifi_proof.side_effect=[None,ValueError('Wi-Fi proof failed')]
        with patch.object(host,'collect',return_value=self.complete),self.assertRaisesRegex(ValueError,'Wi-Fi'):
            host.experiment({},self.root,self.root/'qualification','rtc-wake',REHEARSAL)
        self.assertEqual(len(self.submissions),1)
        saved=json.loads((self.root/'result.json').read_text())
        self.assertNotIn('usb_ssh_verified',saved);self.assertNotIn('wifi_ssh_verified',saved)


class RehearsalLineage(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(sleep,'RESULTS',self.root))
        self.enterContext(patch.object(sleep,'sources',return_value=SOURCE))
        self.pm=Mock(FAULTS=sleep.pm_module().FAULTS)
        self.debug,self.records,self.current=chain(2)
        self.prior=deepcopy(self.records[0])
        self.prior.update(run_id=REHEARSAL,mode='rehearse')
        self.prior['keypad']['trace']=''
        for key in ('entry_clock','returned'):
            for field in self.prior[key]:self.prior[key][field]-=34
        for field in self.prior['rtc']['started']:self.prior['rtc']['started'][field]-=34
        self.prior['rtc']['irq_before']['count']=0;self.prior['rtc']['irq_after']['count']=1
        self.prior['before']['monotonic_seconds']=66
        self.prior['after']['monotonic_seconds']=98
        self.prior['after']['stats']['success']='7'
        self.prior['qualification']['sleep_runs']=[]
        self.prior.pop('sleep_trace');self.prior.pop('parent_claim')
        sleep.health(self.pm,self.prior,{})
        for r in self.records+[self.prior]:
            directory=self.root/r['run_id'];directory.mkdir()
            (directory/'result.json').write_text(json.dumps(r))
        self.q=dict(runs=[r['run_id'] for r in self.debug],sleep_runs=[r['run_id'] for r in self.records])

    def test_initial_and_repeat_chain_keep_the_original_alarm_and_rehearsal(self):
        first=sleep.rehearsal_for_chain(self.pm,self.records[0]['before'],{},self.q|{'sleep_runs':[]},REHEARSAL)
        self.assertEqual(first,self.prior['rtc']['irq_after'])
        latest=sleep.rehearsal_for_chain(self.pm,self.current,{},self.q,REHEARSAL)
        self.assertEqual(latest,self.records[-1]['rtc']['irq_after'])

    def test_wrong_identity_changed_sources_or_consumed_rehearsal_are_rejected(self):
        changes=[lambda r:r.update(run_id='f'*32),lambda r:r.update(sources={'other':'hash'}),
                 lambda r:r['qualification'].update(sleep_runs=['f'*32]),
                 lambda r:r['after'].update(monotonic_seconds=101),
                 lambda r:r['rtc']['irq_after'].update(count=2)]
        for change in changes:
            value=deepcopy(self.prior);change(value)
            (self.root/REHEARSAL/'result.json').write_text(json.dumps(value))
            with self.subTest(change=change),self.assertRaises(ValueError):
                sleep.rehearsal_for_chain(self.pm,self.current,{},self.q,REHEARSAL)
