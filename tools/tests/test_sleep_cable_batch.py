"""Alternating cable lineage and interrupted guided sessions; no board access."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_sleep_cable as cable
import test_sleep_chain as chain
import test_sleep_rtc as existing

sleep, host = existing.sleep, existing.host
spec = importlib.util.spec_from_file_location('guided_cable', existing.TOOLS/'check-sleep-cable-batch.py')
guided = importlib.util.module_from_spec(spec); spec.loader.exec_module(guided)
BATCH = dict(id='b'*32, sequence=list(sleep.sleep_cable_batch.SEQUENCE))


def fixture(count=4):
    debug, current = existing.qualified()
    template = cable.MaskedCable().candidate('usb-remove')
    image = template['before']['image']
    image['project_inputs_sha256'] = {sleep.SDIO_PATCH:sleep.SDIO_SHA}
    def prepare(snapshot):
        snapshot.update(image=deepcopy(image), usb_system_wakeup=['disabled'],
            power_supply_system_wakeup={'axp20x-usb':'disabled','axp22x-ac':'disabled'})
    for record in debug:
        for side in ('before','after'):prepare(record[side])
    prepare(current)
    current['journal'] = 'baseline'
    ids = [r['run_id'] for r in debug]
    sleeps, rehearsals, observations = [], [], []
    counts = dict(ACIN_PLUGIN=0,ACIN_REMOVAL=0,VBUS_PLUGIN=0,VBUS_REMOVAL=0)
    pm = Mock(FAULTS=sleep.pm_module().FAULTS)
    for index in range(count):
        profile = BATCH['sequence'][index]
        q = dict(runs=ids,sleep_runs=[r['run_id'] for r in sleeps],connection=profile,
                 cable_batch=deepcopy(BATCH),cable_observations=deepcopy(observations))
        awake_id = f'{200+index:032x}'
        for mode in ('rehearse','rtc-wake'):
            r = cable.MaskedCable().candidate(profile,mode)
            offset = index*100 + (-34 if mode=='rehearse' else 0)
            r['run_id'] = awake_id if mode=='rehearse' else f'{100+index:032x}'
            r['qualification'] = deepcopy(q)
            for side in ('before','after'):
                prepare(r[side])
                r[side]['monotonic_seconds'] += offset
                r[side]['stats']['success'] = str(7+index+(side=='after' and mode=='rtc-wake'))
                r[side]['journal'] = 'baseline'
            if mode=='rehearse':r['after']['monotonic_seconds']=99+index*100
            for sample in (r['entry_clock'],r['returned'],r['rtc']['started']):
                for field in sample:sample[field]+=offset
            r['keypad']['trace']=re.sub(r'(\d+\.\d{6})(?=:)',
                lambda m:f'{float(m[1])+offset:.6f}',r['keypad']['trace'])
            r['rtc']['irq_before']['count']=index*2+(mode=='rtc-wake')
            r['rtc']['irq_after']['count']=index*2+(mode=='rtc-wake')+1
            for side in ('before','entry','after'):
                r['cable'][side]['monotonic_seconds']+=offset
                r['cable'][side]['irqs']['counts']=deepcopy(counts)
            if mode=='rehearse':r['cable']['after']['monotonic_seconds']=98.9+index*100
            if mode=='rtc-wake':
                r['rehearsal']=awake_id
                r['parent_claim']=dict(parent=sleeps[-1]['run_id'] if sleeps else ids[-1],
                                        run_id=r['run_id'],boot_id='boot')
                direction='REMOVAL' if profile=='usb-remove' else 'PLUGIN'
                for name in counts:
                    counts[name]+=int(name.endswith(direction))
                r['cable']['after']['irqs']['counts']=deepcopy(counts)
            sleep.health(pm,r,{})
            if mode=='rehearse':rehearsals.append(r)
            else:
                sleeps.append(r)
                observations.append(dict(run_id=r['run_id'],device_sha256=sleep.digest(r),
                                         action='during-dark',display='normal'))
    if sleeps:
        current=deepcopy(sleeps[-1]['after']);current['monotonic_seconds']+=20
    return debug,sleeps,rehearsals,observations,current


class Lineage(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(sleep,'sources',return_value=chain.SOURCE))
        self.pm=Mock(FAULTS=sleep.pm_module().FAULTS)

    def validate(self,d,r,a,o,c,batch=None):
        connection=BATCH['sequence'][len(r)] if len(r)<4 else 'usb-remove'
        return sleep.history(self.pm,d,r,c,{},connection,batch or BATCH,a,o)

    def test_three_predecessors_admit_fourth_with_one_original_debug_anchor(self):
        for count in range(4):
            d,r,a,o,c=fixture(count)
            q=self.validate(d,r,a,o,c)
            self.assertEqual(q['sleep_runs'],[v['run_id'] for v in r])
            self.assertEqual(q['connection'],BATCH['sequence'][count])
        with self.assertRaisesRegex(ValueError,'four-cycle'):
            self.validate(*fixture(4))

    def test_failed_changed_or_unobserved_predecessors_cannot_continue(self):
        mutations=[lambda d,r,a,o,c:r[0].update(passed=False),
            lambda d,r,a,o,c:r[0].update(event='started'),
            lambda d,r,a,o,c:r[0].update(policy_owner_retained=True),
            lambda d,r,a,o,c:r[0].update(sources={'changed':'code'}),
            lambda d,r,a,o,c:r[0]['after'].update(boot_id='new'),
            lambda d,r,a,o,c:r[0]['delivery'].update(energy_qualified=True),
            lambda d,r,a,o,c:r[1].update(connection='usb-remove'),
            lambda d,r,a,o,c:r[1]['qualification'].update(sleep_runs=[]),
            lambda d,r,a,o,c:r[1]['qualification']['cable_batch'].update(id='c'*32),
            lambda d,r,a,o,c:r[1]['parent_claim'].update(parent='c'*32),
            lambda d,r,a,o,c:a[0].update(passed=False),
            lambda d,r,a,o,c:a[1].update(connection='usb-remove'),
            lambda d,r,a,o,c:a[1]['rtc']['irq_before'].update(count=9),
            lambda d,r,a,o,c:r[1]['rtc']['irq_before'].update(count=9),
            lambda d,r,a,o,c:a[0]['before'].update(monotonic_seconds=60),
            lambda d,r,a,o,c:a[1]['before']['stats'].update(success='7'),
            lambda d,r,a,o,c:c['stats'].update(success='42'),
            lambda d,r,a,o,c:c.update(monotonic_seconds=float('nan')),
            lambda d,r,a,o,c:c.update(journal='lost'),
            lambda d,r,a,o,c:c['power_supply_system_wakeup'].update(**{'axp20x-usb':'enabled'}),
            lambda d,r,a,o,c:o.pop(),
            lambda d,r,a,o,c:o[0].update(action='uncertain'),
            lambda d,r,a,o,c:o[0].update(device_sha256='0'*64),
            lambda d,r,a,o,c:r[1]['qualification']['cable_observations'][0].update(display='abnormal'),
            lambda d,r,a,o,c:a.pop()]
        for mutate in mutations:
            values=fixture(2);mutate(*values)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.validate(*values)

    def test_awake_cable_change_even_with_same_final_endpoint_rejects(self):
        d,r,a,o,c=fixture(2)
        # One extra awake unplug/replug, reconciled endpoints but changed IRQs.
        for value in (a[1],r[1]):
            for sample in value['cable'].values():
                for name in sample['irqs']['counts']:sample['irqs']['counts'][name]+=1
            sleep.health(self.pm,value,{})
        o[1]['device_sha256']=sleep.digest(r[1])
        with self.assertRaisesRegex(ValueError,'Cable interrupt'):
            self.validate(d,r,a,o,c)

    def test_cannot_mix_legacy_one_shots_or_strip_batch_marker(self):
        d,r,a,o,c=fixture(1)
        with self.assertRaisesRegex(ValueError,'ordinary sleep chain'):
            sleep.history(self.pm,d,r,c,{},'usb-remove')
        r[0]['qualification'].pop('cable_batch')
        with self.assertRaisesRegex(ValueError,'ancestry'):
            self.validate(d,r,a,o,c)


class DeviceAdmission(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(sleep,'sources',return_value=chain.SOURCE))
        self.pm=Mock(FAULTS=sleep.pm_module().FAULTS)
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(sleep,'RESULTS',self.root/'sleep'))
        self.enterContext(patch.object(sleep,'OWNED',self.root/'owned'))
        self.pm.RESULTS=self.root/'debug';self.pm.STATE=self.root/'state';self.pm.command.return_value=''
        self.enterContext(patch.object(sleep.pm_platform,'admission',return_value={}))

    def setup_ledger(self):
        d,r,a,o,c=fixture(1)
        for records,root in ((d,self.pm.RESULTS),(r+a,sleep.RESULTS)):
            for item in records:
                path=root/item['run_id'];path.mkdir(parents=True)
                (path/'result.json').write_text(json.dumps(item))
        for item in r:
            sleep.successor_path(self.pm,item['qualification']).write_text(json.dumps(item['parent_claim']))
        entries=lambda values:[dict(run_id=v['run_id'],sha256=sleep.digest(v)) for v in values]
        receipt=dict(boot_id='boot',connection='usb-attach',runs=entries(d),sleeps=entries(r),
                     rehearsals=entries(a),cable_batch=BATCH,cable_observations=o)
        self.enterContext(patch.object(sleep,'rtc_irq',return_value=r[-1]['rtc']['irq_after']))
        return d,r,a,o,c,receipt

    def test_device_originals_and_one_successor_remain_mandatory(self):
        d,r,a,o,c,receipt=self.setup_ledger()
        q=sleep.admission(self.pm,c,{},receipt,'usb-attach')
        sleep.claim_successor(self.pm,q,'d'*32,'boot')
        with self.assertRaisesRegex(ValueError,'already claimed'):
            sleep.admission(self.pm,c,{},receipt,'usb-attach')
        with self.assertRaises(FileExistsError):sleep.claim_successor(self.pm,q,'f'*32,'boot')

    def test_rehearsal_receipt_tampering_and_extra_alarm_rejected(self):
        d,r,a,o,c,receipt=self.setup_ledger()
        receipt['rehearsals'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'rehearsal differs'):
            sleep.admission(self.pm,c,{},receipt,'usb-attach')
        receipt['rehearsals'][0]['sha256']=sleep.digest(a[0])
        with patch.object(sleep,'rtc_irq',return_value={'count':99}),self.assertRaisesRegex(ValueError,'RTC activity'):
            sleep.admission(self.pm,c,{},receipt,'usb-attach')

    def test_next_rehearsal_matches_current_profile_parent_and_alarm(self):
        d,r,a,o,c=fixture(2)
        for item in (r[0],a[1]):
            path=sleep.RESULTS/item['run_id'];path.mkdir(parents=True)
            (path/'result.json').write_text(json.dumps(item))
        q=r[1]['qualification']
        irq=sleep.rehearsal_for_chain(self.pm,r[1]['before'],{},q,a[1]['run_id'])
        self.assertEqual(irq,a[1]['rtc']['irq_after'])
        a[1]['qualification']['sleep_runs']=[]
        (sleep.RESULTS/a[1]['run_id']/'result.json').write_text(json.dumps(a[1]))
        with self.assertRaisesRegex(ValueError,'ancestry'):
            sleep.rehearsal_for_chain(self.pm,r[1]['before'],{},q,a[1]['run_id'])


class GuidedSession(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.baseline=self.root/'input.json';self.baseline.write_text('{"cycles":[]}')
        self.capture=self.root/'capture';self.capture.mkdir()
        self.enterContext(patch.object(sleep,'sources',return_value=chain.SOURCE))
        self.enterContext(patch.object(guided,'sources',return_value={'test':'source'}))
        self.d,self.r,self.a,self.o,self.c=fixture(4)
        self.enterContext(patch.object(sleep,'pm_module',return_value=Mock(FAULTS=())))
        self.calls=[]
        self.enterContext(patch.object(guided.host,'experiment',side_effect=self.attempt))
        self.enterContext(patch.object(guided.host,'inspect_live',side_effect=self.inspect))

    def attempt(self,config,capture,qualification,mode,rehearsal,profile):
        index=int(capture.parent.name.split('-')[1])-1
        q=json.loads(qualification.read_text())
        self.assertEqual(len(q['sleeps']),index)
        self.assertEqual(profile,BATCH['sequence'][index])
        value=deepcopy(self.a[index] if mode=='rehearse' else self.r[index])
        if mode=='rtc-wake':self.assertEqual(rehearsal,self.a[index]['run_id'])
        (capture/'result.json').write_text(json.dumps(value))
        self.calls.append((index,mode))
        return value

    def inspect(self,config,capture,kind,route):
        self.assertEqual((kind,route),('connection','wifi'))
        index=int(capture.parent.name.split('-')[1])-1
        value=deepcopy(self.r[index]['cable']['after']);value['monotonic_seconds']+=1
        (capture/'connection-inspection.json').write_text(json.dumps(dict(sources=chain.SOURCE,connection=value)))

    def state(self):return guided.read(self.capture)

    def test_four_steps_alternate_and_require_each_separate_observation(self):
        guided.start({},self.capture,self.baseline)
        for index in range(4):
            state=self.state();self.assertEqual(state['event'],'awaiting-observation')
            self.assertEqual(len(self.calls),2*(index+1))
            with self.assertRaisesRegex(ValueError,'not ready'):guided.step({},self.capture,state)
            guided.observe(self.capture,state,'during-dark','normal')
            state=self.state()
            self.assertEqual(len(state['completed']),index+1)
            if index<3:guided.step({},self.capture,state)
        self.assertTrue(state['passed']);self.assertEqual(state['event'],'complete')
        with self.assertRaises(ValueError):guided.step({},self.capture,state)
        self.assertEqual(len(self.calls),8)

    def test_uncertain_submission_stops_without_retry_or_continuation(self):
        def uncertain(*args):
            value=self.attempt(*args)
            if args[3]=='rtc-wake':raise TimeoutError('original run uncertain')
            return value
        with patch.object(guided.host,'experiment',side_effect=uncertain),self.assertRaises(TimeoutError):
            guided.start({},self.capture,self.baseline)
        state=self.state();self.assertEqual(state['event'],'failed')
        with self.assertRaises(ValueError):guided.step({},self.capture,state)
        self.assertEqual(len(self.calls),2)
        self.assertFalse((self.capture/'cycle-2').exists())

    def test_unqualified_observation_stops_and_cannot_be_rewritten(self):
        guided.start({},self.capture,self.baseline)
        state=self.state();guided.observe(self.capture,state,'uncertain','normal')
        self.assertEqual(self.state()['event'],'failed')
        with self.assertRaises(ValueError):guided.observe(self.capture,self.state(),'during-dark','normal')
        with self.assertRaises(ValueError):guided.step({},self.capture,self.state())
        path=self.capture/'cycle-1/sleep/result-cable-observation.json'
        self.assertEqual(json.loads(path.read_text())['observer_action'],'uncertain')
        self.assertEqual(len(self.calls),2)

    def test_changed_original_or_sources_blocks_observation(self):
        guided.start({},self.capture,self.baseline)
        path=self.capture/'cycle-1/sleep/result.json';path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'evidence changed'):
            guided.observe(self.capture,self.state(),'during-dark','normal')
        with patch.object(guided,'sources',return_value={'new':'source'}),self.assertRaisesRegex(ValueError,'sources changed'):
            self.state()

    def test_crash_running_marker_cannot_restart_step(self):
        guided.start({},self.capture,self.baseline)
        state=self.state();state['event']='running'
        with self.assertRaises(ValueError):guided.step({},self.capture,state)
        self.assertEqual(len(self.calls),2)

    def test_missing_route_proof_or_endpoint_change_stops_before_observation(self):
        with patch.object(guided,'check_result',side_effect=ValueError('missing route')):
            with self.assertRaisesRegex(ValueError,'missing route'):guided.start({},self.capture,self.baseline)
        self.assertEqual(self.state()['event'],'failed');self.assertEqual(len(self.calls),1)

    def test_missing_final_wifi_proof_stops_before_endpoint_or_observation(self):
        self.r[0]['wifi_ssh_verified']=False
        with patch.object(guided.host,'inspect_live') as inspect,self.assertRaisesRegex(ValueError,'route proofs'):
            guided.start({},self.capture,self.baseline)
        inspect.assert_not_called()
        self.assertEqual(self.state()['event'],'failed');self.assertEqual(len(self.calls),2)

    def test_cable_moved_after_result_blocks_batch_before_observation(self):
        def changed(*args):
            self.inspect(*args)
            path=args[1]/'connection-inspection.json'
            value=json.loads(path.read_text())
            value['connection']['irqs']['counts']['ACIN_PLUGIN']+=1
            path.write_text(json.dumps(value))
        with patch.object(guided.host,'inspect_live',side_effect=changed),self.assertRaisesRegex(ValueError,'Cable interrupt'):
            guided.start({},self.capture,self.baseline)
        self.assertEqual(self.state()['event'],'failed');self.assertEqual(len(self.calls),2)

    def test_missing_readiness_never_loads_credentials_or_contacts_device(self):
        for command in ('--start','--next'):
            for flags in ({},{'NEO_SLEEP_ATTENDED':'1'},{'NEO_SLEEP_CABLE_ACTION':'1'}):
                with patch.dict(os.environ,flags,clear=True),patch.object(sys,'argv',['batch',command]), \
                        patch.object(guided,'load_env') as load,self.assertRaises(SystemExit):guided.main()
                load.assert_not_called()
        self.assertEqual(self.calls,[])

    def test_cannot_adopt_a_consumed_history_as_a_new_batch(self):
        self.baseline.write_text('{"cycles":[],"sleeps":[{}]}')
        with self.assertRaisesRegex(ValueError,'fresh seven-debug'):
            guided.start({},self.capture,self.baseline)
        self.assertEqual(self.calls,[])

    def test_saved_batch_status_is_readable_after_source_changes(self):
        guided.start({},self.capture,self.baseline)
        with patch.object(guided,'sources',return_value={'changed':True}):
            self.assertEqual(guided.read(self.capture,check_sources=False)['event'],'awaiting-observation')
            with self.assertRaisesRegex(ValueError,'sources changed'):guided.read(self.capture)


class HostReceipt(unittest.TestCase):
    def test_observer_hash_and_endpoint_specific_routes_bind_receipt(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(sleep,'sources',return_value=chain.SOURCE), \
                patch.object(sleep,'pm_module',return_value=Mock(FAULTS=())):
            root=Path(temp);private=root/'diagnostics';private.mkdir()
            d,r,a,o,c=fixture(1)
            paths={}
            for value in d+r+a:
                directory=private/value['run_id'];directory.mkdir()
                path=directory/'result.json';path.write_text(json.dumps(value));paths[value['run_id']]=path
            result=paths[r[0]['run_id']]
            guided.report.write_report(result,'during-dark','normal',{})
            summary=dict(cycles=[dict(capture=str(paths[v['run_id']])) for v in d],
                sleeps=[dict(capture=str(result),rehearsal=str(paths[a[0]['run_id']]))],cable_batch=BATCH)
            path=root/'history.json';path.write_text(json.dumps(summary))
            with patch.object(host,'LOCAL',root),patch.object(sleep,'pm_module',return_value=Mock(FAULTS=())):
                receipt=host.receipt(path,c,'usb-attach')
                self.assertEqual(receipt['cable_observations'],o)
                observer=result.with_name('result-cable-observation.json')
                value=json.loads(observer.read_text());value['original_sha256']='0'*64
                observer.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError,'observer report'):host.receipt(path,c,'usb-attach')
