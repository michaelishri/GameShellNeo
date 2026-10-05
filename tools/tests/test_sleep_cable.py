"""Cable-transition failure boundaries; no real board, alarm or PM access."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_sleep_battery as battery
import test_sleep_chain as chain
import test_sleep_rtc as existing
import sleep_cable as cable
import sleep_connection as connection

sleep, host = existing.sleep, existing.host
spec = importlib.util.spec_from_file_location('cable_report', existing.TOOLS/'report-sleep-cable.py')
report = importlib.util.module_from_spec(spec); spec.loader.exec_module(report)


def observation(connected, t):
    value = battery.observation(t)
    if connected:
        value.update(udc='configured', carrier='1', extcon='USB=1\nUSB-HOST=0')
        for supply in value['supplies'].values():
            supply.update(present='1', online='1')
    return value


def record(scenario='usb-remove', mode='rtc-wake'):
    _, records, _ = chain.chain(1)
    value = records[0]
    value.update(connection=scenario, mode=mode, cable_action_confirmed=True,
                 cable_absent_confirmed=scenario == 'usb-attach', console_owner_retained=False,
                 cable_console=dict(restored=True), cable={})
    value['qualification']['connection'] = scenario
    if mode == 'rehearse':
        value['keypad']['trace'] = ''
        value['after']['stats'] = deepcopy(value['before']['stats'])
        value.pop('sleep_trace'); value.pop('parent_claim')
    for side, t in (('before', 100.1), ('entry', 101), ('after', 135)):
        endpoint = connection.endpoint(scenario, mode, 'after' if side == 'after' else 'before')
        value['cable'][side] = observation(endpoint == 'usb', t)
        if side != 'entry':
            value[side]['usb'] = ['configured' if endpoint == 'usb' else 'not attached']
            value['usb_trace'][side] = dict(state=value[side]['usb'][0], carrier='1' if endpoint == 'usb' else '0')
    if mode == 'rtc-wake':
        direction = 'PLUGIN' if scenario == 'usb-attach' else 'REMOVAL'
        counts = value['cable']['after']['irqs']['counts']
        for name in counts:
            counts[name] += int(name.endswith(direction))
        value['wake_observation'] = cable.wake_observation(value)
    value.update(wifi_ssh_verified=True,
                 usb_ssh_verified=connection.endpoint(scenario, mode, 'after') == 'usb')
    sleep.health(Mock(FAULTS=sleep.pm_module().FAULTS), value, {})
    return value


class StateEvidence(unittest.TestCase):
    def test_start_and_end_health_gates_stay_distinct(self):
        for scenario in ('usb-remove', 'usb-attach'):
            for mode in ('rehearse', 'rtc-wake'):
                value = record(scenario, mode)
                connection.validate(value)
                initial = 'usb' if scenario == 'usb-remove' else 'battery'
                final = initial if mode == 'rehearse' else ('battery' if initial == 'usb' else 'usb')
                self.assertEqual(connection.endpoint(scenario, mode), initial)
                self.assertEqual(connection.endpoint(scenario, mode, 'after'), final)
                value['cable']['after']['udc'] = 'unknown'
                with self.assertRaises(ValueError): connection.validate(value)

    def test_extra_missing_reversed_or_pre_entry_cable_events_reject(self):
        mutations = [lambda r: r['cable']['after']['irqs']['counts'].update(VBUS_REMOVAL=99),
                     lambda r: r['cable']['entry']['irqs']['counts'].update(ACIN_PLUGIN=99),
                     lambda r: r['cable']['after'].update(boot_id='other'),
                     lambda r: r['cable']['after'].update(monotonic_seconds=100),
                     lambda r: r['cable']['after']['irqs'].update(cpus=['CPU7']),
                     lambda r: r['cable']['after']['irqs']['counts'].update(VBUS_PLUGIN=99),
                     lambda r: r['cable']['after'].update(irqs=deepcopy(r['cable']['entry']['irqs'])),
                     lambda r: r.update(cable_action_confirmed=False)]
        for scenario in ('usb-remove', 'usb-attach'):
            for mutate in mutations:
                value = record(scenario); mutate(value)
                with self.subTest(scenario=scenario, mutate=mutate), self.assertRaises(ValueError):
                    connection.validate(value)

    def test_rehearsal_rejects_the_planned_transition(self):
        for scenario in ('usb-remove', 'usb-attach'):
            value = record(scenario, 'rehearse')
            value['cable']['after'] = record(scenario)['cable']['after']
            with self.assertRaises(ValueError): connection.validate(value)

    def test_attach_cannot_drop_physical_absence_confirmation_from_accepted_evidence(self):
        value=record('usb-attach');value['cable_absent_confirmed']=False
        with self.assertRaisesRegex(ValueError,'physical cable-absence'): connection.validate(value)

    def test_positive_results_revalidate_and_cannot_seed_a_mixed_or_repeat_chain(self):
        with patch.object(sleep, 'sources', return_value=chain.SOURCE):
            pm = Mock(FAULTS=sleep.pm_module().FAULTS)
            for scenario in ('usb-remove', 'usb-attach'):
                value = record(scenario)
                sleep.completed_result(pm, value, {}, 'rtc-wake')
                self.assertEqual(pm.validate.call_args.args[-1], connection.endpoint(scenario, 'rtc-wake', 'after'))
                for change in (lambda r:r.update(console_owner_retained=True),
                               lambda r:r['cable_console'].update(restored=False),
                               lambda r:r['wake_observation'].update(cable_wake_proven=True),
                               lambda r:r['usb_trace']['after'].update(carrier='wrong')):
                    bad=deepcopy(value);change(bad)
                    with self.assertRaises(ValueError): sleep.completed_result(pm,bad,{},'rtc-wake')
                debug, current = existing.qualified()
                with self.assertRaisesRegex(ValueError, 'one-shot baseline'):
                    sleep.history(pm, debug, [value], current, {}, scenario)
                with self.assertRaises(ValueError): sleep.history(pm, debug, [value], current, {}, 'usb')


class MaskedCable(unittest.TestCase):
    def candidate(self, scenario='usb-attach', mode='rtc-wake'):
        value = MaskedRemoval().candidate(scenario, mode)
        for side in ('before', 'after'):
            value[side]['image']['version'] = '0.1.0-diagnostic.20'
            value[side]['image']['sources']['features'].update(
                power_supply_system_wakeup=False, sleep_cable_irq_policy='masked-cable-v2')
            value[side]['power_supply_system_wakeup'] = {'axp20x-usb': 'disabled', 'axp22x-ac': 'disabled'}
        return value

    def test_either_masked_direction_records_zero_or_one_without_synthetic_dispatch(self):
        for scenario, direction in (('usb-attach', 'PLUGIN'), ('usb-remove', 'REMOVAL')):
            for ac, usb in ((0, 0), (0, 1), (1, 0), (1, 1)):
                value = self.candidate(scenario)
                initial = value['cable']['entry']['irqs']['counts']
                final = value['cable']['after']['irqs']['counts']
                final['ACIN_' + direction] = initial['ACIN_' + direction] + ac
                final['VBUS_' + direction] = initial['VBUS_' + direction] + usb
                assessment = connection.validate(value)
                self.assertEqual(assessment['deltas']['ACIN_' + direction], ac)
                self.assertEqual(assessment['deltas']['VBUS_' + direction], usb)
                self.assertEqual(assessment['insertion_dispatch_may_be_masked'], scenario == 'usb-attach')
                self.assertEqual(assessment['removal_dispatch_may_be_masked'], scenario == 'usb-remove')
                self.assertFalse(assessment['electrical_edge_timing_qualified'])

    def test_policy_requires_matching_image_and_disabled_controls_on_both_sides(self):
        for side in ('before', 'after'):
            for supply in ('axp20x-usb', 'axp22x-ac'):
                for state in ('enabled', None):
                    value = self.candidate()
                    value[side]['power_supply_system_wakeup'][supply] = state
                    with self.assertRaises(ValueError): connection.validate(value)
            value = self.candidate(); value[side].pop('power_supply_system_wakeup')
            with self.assertRaises(ValueError): connection.validate(value)
        for policy in (True, 0, None):
            value = self.candidate()
            for side in ('before', 'after'):
                value[side]['image']['sources']['features']['power_supply_system_wakeup'] = policy
            with self.assertRaises(ValueError): connection.validate(value)
        value = self.candidate(); value['after']['image']['version'] = 'old'
        with self.assertRaises(ValueError): connection.validate(value)

    def test_wrong_endpoints_extra_opposite_or_regressed_events_still_fail(self):
        for scenario in ('usb-attach', 'usb-remove'):
            for name in ('ACIN_PLUGIN', 'ACIN_REMOVAL', 'VBUS_PLUGIN', 'VBUS_REMOVAL'):
                for delta in (-1, 2):
                    value = self.candidate(scenario)
                    value['cable']['after']['irqs']['counts'][name] = value['cable']['entry']['irqs']['counts'][name] + delta
                    with self.assertRaises(ValueError): connection.validate(value)
            value = self.candidate(scenario)
            opposite = 'REMOVAL' if scenario == 'usb-attach' else 'PLUGIN'
            value['cable']['after']['irqs']['counts']['ACIN_' + opposite] += 1
            with self.assertRaises(ValueError): connection.validate(value)
            for key in ('udc', 'carrier', 'extcon', 'supplies'):
                value = self.candidate(scenario)
                value['cable']['after'][key] = deepcopy(value['cable']['before'][key])
                with self.assertRaises(ValueError): connection.validate(value)

    def test_rtc_missing_and_rehearsal_transitions_remain_failures(self):
        value = self.candidate()
        value['rtc']['interrupt'] = None
        with self.assertRaisesRegex(ValueError, 'RTC event'):
            sleep.health(Mock(FAULTS=sleep.pm_module().FAULTS), value, {})
        for scenario in ('usb-attach', 'usb-remove'):
            value = self.candidate(scenario, 'rehearse')
            connection.validate(value)
            value['cable']['after']['irqs']['counts']['VBUS_PLUGIN'] += 1
            with self.assertRaises(ValueError): connection.validate(value)


class MaskedRemoval(unittest.TestCase):
    def candidate(self, scenario='usb-remove', mode='rtc-wake'):
        value = record(scenario, mode)
        image = dict(board='gameshellneo-cpi31', version='0.1.0-diagnostic.19',
                     sources=dict(board='gameshellneo-cpi31', features={
                         'usb_system_wakeup': False, 'sleep_cable_irq_policy': 'masked-removal-v1'}))
        for side in ('before', 'after'):
            value[side]['image'] = deepcopy(image)
        return value

    def test_masked_removal_records_each_actual_dispatch_without_inventing_edges(self):
        for ac, usb in ((0, 0), (0, 1), (1, 0), (1, 1)):
            value = self.candidate()
            initial = value['cable']['entry']['irqs']['counts']
            counts = value['cable']['after']['irqs']['counts']
            counts['ACIN_REMOVAL'] = initial['ACIN_REMOVAL'] + ac
            counts['VBUS_REMOVAL'] = initial['VBUS_REMOVAL'] + usb
            with self.subTest(ac=ac, usb=usb):
                assessment = connection.validate(value)
                self.assertEqual(assessment['deltas']['ACIN_REMOVAL'], ac)
                self.assertEqual(assessment['deltas']['VBUS_REMOVAL'], usb)
                self.assertEqual(assessment['requested_handlers_observed'], bool(ac and usb))
                self.assertTrue(assessment['removal_dispatch_may_be_masked'])
                self.assertFalse(assessment['electrical_edge_timing_qualified'])

    def test_old_policy_does_not_accept_missing_removal(self):
        value = record()
        value['cable']['after']['irqs'] = deepcopy(value['cable']['entry']['irqs'])
        with self.assertRaises(ValueError): connection.validate(value)

    def test_mask_policy_never_allows_extra_reverse_or_regressed_counters(self):
        for name in ('ACIN_REMOVAL', 'VBUS_REMOVAL', 'ACIN_PLUGIN', 'VBUS_PLUGIN'):
            for delta in (-1, 2):
                value = self.candidate()
                value['cable']['after']['irqs']['counts'][name] = value['cable']['entry']['irqs']['counts'][name] + delta
                with self.subTest(name=name, delta=delta), self.assertRaises(ValueError):
                    connection.validate(value)
        value = self.candidate()
        value['cable']['after']['irqs']['counts']['ACIN_PLUGIN'] += 1
        with self.assertRaises(ValueError): connection.validate(value)

    def test_stale_usb_missing_power_or_changed_provenance_still_fail(self):
        mutations = (
            lambda r: r['cable']['after'].update(udc='configured'),
            lambda r: r['cable']['after'].update(carrier='1'),
            lambda r: r['cable']['after'].update(extcon='USB=1\nUSB-HOST=0'),
            lambda r: r['cable']['after']['supplies']['axp20x-usb'].update(present='1'),
            lambda r: r['cable']['after'].update(boot_id='other'),
            lambda r: r['cable']['after']['irqs'].update(cpus=['CPU7']),
            lambda r: r['before']['image']['sources'].update(board='other'),
            lambda r: r['before']['image']['sources']['features'].update(usb_system_wakeup=True),
            lambda r: r['before']['image']['sources']['features'].update(sleep_cable_irq_policy='unknown'),
            lambda r: r['after']['image'].update(version='other'),
            lambda r: r.update(cable_action_confirmed=False))
        for mutate in mutations:
            value = self.candidate(); mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): connection.validate(value)

    def test_attach_and_awake_rehearsal_keep_their_strict_counter_contract(self):
        value = self.candidate('usb-attach')
        connection.validate(value)
        value['cable']['after']['irqs'] = deepcopy(value['cable']['entry']['irqs'])
        with self.assertRaises(ValueError): connection.validate(value)
        value = self.candidate(mode='rehearse')
        connection.validate(value)
        value['cable']['after']['irqs']['counts']['ACIN_REMOVAL'] += 1
        with self.assertRaises(ValueError): connection.validate(value)

    def test_assessment_revalidated_and_failed_original_cannot_be_promoted(self):
        value = self.candidate()
        value['cable']['after']['irqs'] = deepcopy(value['cable']['entry']['irqs'])
        pm = Mock(FAULTS=sleep.pm_module().FAULTS)
        sleep.health(pm, value, {})
        with patch.object(sleep, 'sources', return_value=chain.SOURCE), \
                patch.object(sleep, 'pm_module', return_value=pm):
            sleep.completed_result(pm, value, {}, 'rtc-wake')
            good = report.assessment(value, 'during-dark', 'normal', {})
            self.assertTrue(good['attended_case_passed'])
            self.assertFalse(good['cable_irq_observation']['requested_handlers_observed'])
            bad = deepcopy(value); bad['cable_irq_observation']['requested_handlers_observed'] = True
            with self.assertRaises(ValueError): sleep.completed_result(pm, bad, {}, 'rtc-wake')
            bad = deepcopy(value); bad.pop('cable_irq_observation')
            with self.assertRaises(ValueError): sleep.completed_result(pm, bad, {}, 'rtc-wake')
            value.update(event='failed', passed=False, error='usb_absent')
            self.assertFalse(report.assessment(value, 'during-dark', 'normal', {})['attended_case_passed'])


class Entry(unittest.TestCase):
    setUp = existing.Entry.setUp
    enter = existing.Entry.enter

    def prepare(self, scenario='usb-remove'):
        self.record.update(connection=scenario, cable={'before': observation(scenario == 'usb-remove', 100)})
        self.record['rtc']['irq_before'] = {'irq':31,'count':1}

    def test_premature_cable_change_never_writes_handshake_or_state(self):
        for scenario in ('usb-remove','usb-attach'):
            self.prepare(scenario)
            with patch.object(connection,'observe',return_value=observation(scenario != 'usb-remove',101)), \
                 self.assertRaises(ValueError): self.enter()
            self.write.assert_not_called();self.count.assert_not_called()

    def test_early_return_is_saved_without_awaiting_or_claiming_later_alarm(self):
        self.prepare(); poll=Mock();poll.poll.return_value=[]
        with patch.object(connection,'observe',return_value=observation(True,101)), \
             patch.object(sleep.select,'poll',return_value=poll), patch.object(sleep.os,'read') as read:
            self.enter()
        poll.poll.assert_called_once_with(0);read.assert_not_called();self.delivery.assert_not_called()
        self.assertIsNone(self.record['rtc']['interrupt'])
        self.assertEqual(self.write.call_count,2)
        self.assertEqual(self.record['wake_observation']['kind'],'no-rtc-event-at-return')
        self.assertFalse(self.record['wake_observation']['cable_wake_proven'])
        with self.assertRaisesRegex(ValueError,'early/unattributed'):
            sleep.validate_delivery(self.record | {'mode':'rtc-wake'})

    def test_rtc_event_is_read_once_immediately_and_wrong_wake_source_stays_distinct(self):
        self.prepare();poll=Mock();poll.poll.return_value=[(10,sleep.select.POLLIN)]
        (self.root/'pm_wakeup_irq').write_text('99')
        with patch.object(connection,'observe',return_value=observation(True,101)), \
             patch.object(sleep.select,'poll',return_value=poll), \
             patch.object(sleep.os,'read',return_value=struct.pack('@L',(1<<8)|0xa0)) as read:
            self.enter()
        poll.poll.assert_called_once_with(0);read.assert_called_once();self.delivery.assert_not_called()
        self.assertEqual(self.record['wake_observation']['kind'],'rtc-event-with-other-wake-irq')
        self.assertEqual(self.write.call_count,2)

    def test_rehearsal_keeps_existing_awake_delivery_and_never_submits_pm(self):
        self.prepare()
        with patch.object(connection,'observe',return_value=observation(True,101)):
            self.enter('rehearse')
        self.write.assert_not_called();self.delivery.assert_called_once_with(10,35000)


class Gates(unittest.TestCase):
    def test_missing_action_or_starting_absence_fails_before_network_and_disk(self):
        for scenario, absent in (('usb-remove','0'),('usb-attach','1')):
            with patch.object(sys,'argv',['check','--rtc-wake','--connection',scenario]), \
                 patch.dict(os.environ,NEO_SLEEP_CABLE_ACTION='0',NEO_SLEEP_CABLE_ABSENT=absent,NEO_SLEEP_ATTENDED='1'), \
                 patch.object(host,'load_env') as load,self.assertRaises(SystemExit): host.main()
            load.assert_not_called()
            with patch.object(sleep,'RESULTS') as results,self.assertRaises(ValueError):
                sleep.run(Mock(),'a'*32,'rtc-wake',{}, {},connection=scenario,cable_absent=True)
            results.__truediv__.assert_not_called()
        with patch.object(sys,'argv',['check','--rtc-wake','--connection','usb-attach']), \
             patch.dict(os.environ,NEO_SLEEP_CABLE_ACTION='1',NEO_SLEEP_CABLE_ABSENT='0',NEO_SLEEP_ATTENDED='1'), \
             patch.object(host,'load_env') as load,self.assertRaises(SystemExit): host.main()
        load.assert_not_called()

    def test_no_transition_batch_or_implicit_device_readiness(self):
        for scenario in ('usb-remove','usb-attach'):
            with patch.object(sys,'argv',['check','--rtc-batch','--connection',scenario]), \
                 patch.object(host,'load_env') as load,self.assertRaises(SystemExit): host.main()
            load.assert_not_called()
            with patch.object(sys,'argv',['device','--rtc-wake','--connection',scenario]), \
                 patch.object(sleep,'pm_module') as pm,self.assertRaises(SystemExit): sleep.main()
            pm.assert_not_called()

    def test_changed_rehearsal_scenario_rejects_before_alarm_or_parent_consumption(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/chain.REHEARSAL;p.mkdir()
            (p/'result.json').write_text(json.dumps(record('usb-remove','rehearse')))
            with patch.object(sleep,'RESULTS',root),patch.object(sleep,'claim_successor') as claim, \
                 self.assertRaisesRegex(ValueError,'connection profile'):
                sleep.rehearsal_for_chain(Mock(),{}, {},dict(connection='usb-attach',sleep_runs=[]),chain.REHEARSAL)
            claim.assert_not_called()

    def test_valid_transition_does_not_publish_a_repeat_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'diagnostics').mkdir()
            capture=root/'diagnostics/test';capture.mkdir()
            with patch.object(host,'LOCAL',root),patch.object(host,'evidence_directory',return_value=capture), \
                 patch.object(host,'load_env',return_value={}),patch.object(host,'experiment',return_value={'passed':True}) as run, \
                 patch.object(sys,'argv',['check','--rtc-wake','--connection','usb-remove']), \
                 patch.dict(os.environ,NEO_SLEEP_CABLE_ACTION='1',NEO_SLEEP_ATTENDED='1',
                            NEO_SLEEP_QUALIFICATION='unused-qualification',NEO_SLEEP_REHEARSAL=chain.REHEARSAL):
                host.main()
            run.assert_called_once();self.assertFalse((capture/'qualification-next.json').exists())


class Console(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(cable,'OWNED',self.root/'owned'))
        self.enterContext(patch.object(cable.keypad_input,'CONSOLE_OWNED',self.root/'keypad-owned'))
        self.enterContext(patch.object(cable.keypad_input,'SCREEN',self.root/'screen'))
        self.enterContext(patch.object(cable.keypad_input,'TTY',self.root/'tty'))
        self.enterContext(patch.object(cable.keypad_pm,'optional',side_effect=lambda p:'tty1' if p.endswith('/active') else 'boot'))
        self.pause=self.enterContext(patch.object(cable.time,'sleep'))
        self.screen=bytes([2,2,0,0])+b'x '*4
        (self.root/'screen').write_bytes(self.screen)
        self.value={'connection':'usb-remove','mode':'rtc-wake','before':{'boot_id':'boot'}}

    def test_prompts_restore_on_success_and_interruption_without_pm(self):
        for abort in (False,True):
            try:
                with cable.console(self.value,'a'*32):
                    self.assertTrue(cable.OWNED.exists())
                    self.assertIn('UNPLUG', (self.root/'tty').read_text())
                    self.assertIn('10 seconds', (self.root/'tty').read_text())
                    cable.returned(self.value)
                    self.assertIn('Do not touch', (self.root/'tty').read_text())
                    (self.root/'screen').write_bytes(self.screen[:4]+b'y '*4)
                    if abort: raise InterruptedError('worker interrupted')
            except InterruptedError: pass
            self.assertEqual((self.root/'screen').read_bytes(),self.screen)
            self.assertFalse(cable.OWNED.exists())
            self.assertTrue(self.value['cable_console']['restored'])

    def test_foreign_owner_geometry_and_other_console_are_not_overwritten(self):
        (self.root/'keypad-owned').write_text('foreign')
        with self.assertRaises(ValueError):
            with cable.console(self.value,'a'*32): self.fail()
        (self.root/'keypad-owned').unlink()
        with cable.console(self.value,'a'*32):
            saved=cable.OWNED.read_bytes()
            with self.assertRaises(ValueError): cable.restore('b'*32)
            self.assertEqual(saved,cable.OWNED.read_bytes())
            (self.root/'screen').write_bytes(bytes([1,1,0,0])+b'z ')
            with self.assertRaises(ValueError): cable.restore('a'*32)
            self.assertTrue(cable.OWNED.exists())
            (self.root/'screen').write_bytes(self.screen)

    def test_rehearsal_has_no_console_or_delay(self):
        with cable.console(self.value|{'mode':'rehearse'},'a'*32): pass
        self.pause.assert_not_called();self.assertFalse(cable.OWNED.exists())


class Transport(unittest.TestCase):
    setUp = chain.Transport.setUp

    def test_lost_remove_submission_collects_original_wifi_once(self):
        self.complete['connection']='usb-remove'
        with patch.object(host,'collect',side_effect=[host.paramiko.SSHException('returning'),self.complete]) as collect, \
             patch.object(host,'usb_proof') as usb:
            value=host.experiment({},self.root,self.root/'q','rtc-wake',chain.REHEARSAL,'usb-remove')
        usb.assert_called_once_with({},'boot')  # Starting configuration only.
        self.assertEqual(len(self.submissions),1)
        self.assertIn('--cable-action-confirmed',self.submissions[0])
        self.assertTrue(all(c.args==({},self.token,'wifi') for c in collect.call_args_list))
        self.assertFalse(value['usb_ssh_verified']);self.assertTrue(value['wifi_ssh_verified'])

    def test_attach_requires_separate_usb_recovery_and_lost_proof_is_not_accepted(self):
        self.complete['connection']='usb-attach'
        with patch.object(host,'collect',return_value=self.complete),patch.object(host,'usb_proof') as usb:
            value=host.experiment({},self.root,self.root/'q','rtc-wake',chain.REHEARSAL,'usb-attach')
        usb.assert_called_once_with({},'boot');self.assertTrue(value['usb_ssh_verified'])
        self.complete.pop('usb_ssh_verified');self.complete.pop('wifi_ssh_verified')
        with patch.object(host,'collect',return_value=self.complete), \
             patch.object(host,'usb_proof',side_effect=ValueError('USB missing')),self.assertRaises(ValueError):
            host.experiment({},self.root,self.root/'q','rtc-wake',chain.REHEARSAL,'usb-attach')
        saved=json.loads((self.root/'result.json').read_text())
        self.assertNotIn('usb_ssh_verified',saved)


class ObserverReport(unittest.TestCase):
    def test_observer_does_not_override_automated_failure_or_claim_edge_timing(self):
        value=record()
        with patch.object(sleep,'sources',return_value=chain.SOURCE),patch.object(sleep,'pm_module',return_value=Mock(FAULTS=())):
            good=report.assessment(value,'during-dark','normal',{})
            self.assertTrue(good['attended_case_passed']);self.assertFalse(good['electrical_edge_timing_qualified'])
            for action,display in (('uncertain','normal'),('after-return','normal'),('no-action','normal'),('during-dark','abnormal')):
                self.assertFalse(report.assessment(value,action,display,{})['attended_case_passed'])
            value.update(event='failed',passed=False,error='early wake')
            self.assertFalse(report.assessment(value,'during-dark','normal',{})['attended_case_passed'])

    def test_report_preserves_original_and_refuses_to_overwrite_an_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'result.json';value=record();value.update(event='failed',passed=False)
            source.write_text(json.dumps(value));original=source.read_bytes()
            target,_=report.write_report(source,'uncertain','normal',{})
            self.assertEqual(source.read_bytes(),original);first=target.read_bytes()
            with self.assertRaises(FileExistsError): report.write_report(source,'during-dark','normal',{})
            self.assertEqual(first,target.read_bytes());self.assertEqual(source.read_bytes(),original)


if __name__ == '__main__':
    unittest.main()
