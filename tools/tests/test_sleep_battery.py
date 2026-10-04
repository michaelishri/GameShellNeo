"""Battery-only admission, cable evidence and Wi-Fi-only transport; no live PM."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_sleep_rtc as existing
import test_sleep_chain as chain
import test_pm_stages as stages
import sleep_connection as connection

sleep, host = existing.sleep, existing.host
IRQ_TEXT = ('           CPU0       CPU1\n'
            ' 40: 1 0 axp22x_irq_chip 2 Edge axp20x-acin\n'
            ' 41: 2 0 axp22x_irq_chip 3 Edge axp20x-acin\n'
            ' 42: 3 0 axp22x_irq_chip 5 Edge axp20x-usb\n'
            ' 43: 4 0 axp22x_irq_chip 6 Edge axp20x-usb\n')


def observation(t=100):
    return dict(boot_id='boot', monotonic_seconds=t, udc='not attached', carrier='0',
        extcon='USB=0\nUSB-HOST=0', irqs=connection.cable_irqs(IRQ_TEXT),
        supplies={'axp20x-usb': dict(type='USB', present='0', online='0'),
                  'axp22x-ac': dict(type='Mains', present='0', online='0')})


def battery_chain(count=2):
    debug, records, current = chain.chain(count)
    for r in records:
        start = r['before']['monotonic_seconds']
        r.update(connection='battery', cable_absent_confirmed=True,
                 cable={side: observation(start+offset) for side, offset in
                        (('before', .1), ('entry', 1), ('after', 35))},
                 usb_ssh_verified=False, wifi_ssh_verified=True)
        r['qualification']['connection'] = 'battery'
        for side in ('before', 'after'):
            r[side]['usb'] = ['not attached']
            r['usb_trace'][side] = dict(state='not attached', carrier='0')
    current['usb'] = ['not attached']
    return debug, records, current


class BatteryAdmission(unittest.TestCase):
    def test_battery_profile_does_not_weaken_usb_or_common_health_gates(self):
        good, lock = stages.healthy_fixture()
        battery = deepcopy(good)
        battery['usb'] = ['not attached']
        battery['battery']['status'] = 'Discharging'
        battery['external_power'] = observation()['supplies']
        stages.pm.validate(good, lock)
        stages.pm.validate(battery, lock, 'battery')
        with self.assertRaises(ValueError): stages.pm.validate(battery, lock)
        with self.assertRaises(ValueError): stages.pm.validate(good, lock, 'battery')
        changes = [lambda s: s.update(usb=['configured']),
                   lambda s: s['external_power']['axp20x-usb'].update(present='1'),
                   lambda s: s['external_power']['axp20x-usb'].update(online='1'),
                   lambda s: s['external_power']['axp22x-ac'].update(online='1'),
                   lambda s: s['external_power'].pop('axp22x-ac'),
                   lambda s: s['battery'].update(status='Charging'),
                   lambda s: s['battery'].update(monitoring='degraded'),
                   lambda s: s['battery'].update(capacity_percent=20),
                   lambda s: s.update(battery_age_seconds=26),
                   lambda s: s.update(taint='1'),
                   lambda s: s.update(wifi='wpa_state=SCANNING'),
                   lambda s: s.update(kernel='wrong')]
        for change in changes:
            value = deepcopy(battery); change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                stages.pm.validate(value, lock, 'battery')
        with self.assertRaises(ValueError): stages.pm.validate(battery, lock, 'anything')

    def test_physical_confirmation_and_attendance_fail_before_network(self):
        for mode in ('--rehearse', '--rtc-wake'):
            with patch.object(sys, 'argv', ['check', mode, '--connection', 'battery']), \
                 patch.dict(os.environ, NEO_SLEEP_CABLE_ABSENT='0', NEO_SLEEP_ATTENDED='1'), \
                 patch.object(host, 'load_env') as load, self.assertRaises(SystemExit):
                host.main()
            load.assert_not_called()
        with patch.object(sys, 'argv', ['check', '--rtc-wake', '--connection', 'battery']), \
             patch.dict(os.environ, NEO_SLEEP_CABLE_ABSENT='1', NEO_SLEEP_ATTENDED='0'), \
             patch.object(host, 'load_env') as load, self.assertRaises(SystemExit):
            host.main()
        load.assert_not_called()
        with patch.object(sys, 'argv', ['device', '--rtc-wake', '--connection', 'battery']), \
             patch.object(sleep, 'pm_module') as pm, self.assertRaises(SystemExit):
            sleep.main()
        pm.assert_not_called()
        with patch.object(sleep, 'RESULTS') as results, self.assertRaises(ValueError):
            sleep.run(Mock(), 'a'*32, 'rtc-wake', {}, {}, connection='battery')
        results.__truediv__.assert_not_called()

    def test_battery_batch_is_not_an_implicit_new_experiment(self):
        with patch.object(sys, 'argv', ['check', '--rtc-batch', '--connection', 'battery']), \
             patch.object(host, 'load_env') as load, self.assertRaises(SystemExit):
            host.main()
        load.assert_not_called()


class CableEvidence(unittest.TestCase):
    def test_inventory_reads_only_the_qualified_phy_and_complete_irq_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {'/proc/sys/kernel/random/boot_id': 'boot', '/proc/interrupts': IRQ_TEXT,
                     '/sys/class/net/usb0/carrier': '0', '/sys/class/udc/test/state': 'not attached',
                     '/sys/devices/1c19400.phy/state': 'USB=0\nUSB-HOST=0'}
            for name, values in observation()['supplies'].items():
                for field, value in values.items():
                    files['/sys/class/power_supply/'+name+'/'+field] = value
            for name, value in files.items():
                p = root/name.lstrip('/'); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
            link = root/'sys/class/extcon/extcon0'; link.mkdir(parents=True)
            (link/'state').symlink_to(root/'sys/devices/1c19400.phy/state')
            with patch.object(connection, 'Path', side_effect=lambda p: root/str(p).lstrip('/')
                              if str(p).startswith(('/proc/', '/sys/')) else Path(p)), \
                 patch.object(connection.time, 'monotonic', return_value=100):
                self.assertEqual(connection.observe(), observation())
                (link/'state').unlink()
                with self.assertRaises(ValueError): connection.observe()

    def test_inspection_never_programs_alarm_or_enters_pm(self):
        with patch.object(sys, 'argv', ['device', '--connection-inspect']), \
             patch.object(connection, 'observe', return_value=observation()) as observe, \
             patch.object(sleep, 'run') as run, patch.object(sleep, 'recover') as recover, \
             patch.object(sleep, 'pm_module') as pm:
            sleep.main()
        observe.assert_called_once(); run.assert_not_called(); recover.assert_not_called(); pm.assert_not_called()

    def test_missing_duplicate_and_negative_irq_evidence_is_rejected(self):
        for text in ('', IRQ_TEXT.replace('CPU0', 'wrong'),
                     '\n'.join(IRQ_TEXT.splitlines()[:-1]),
                     IRQ_TEXT+IRQ_TEXT.splitlines()[-1]+'\n', IRQ_TEXT.replace('1 0', '-1 0')):
            with self.subTest(text=text), self.assertRaises(ValueError): connection.cable_irqs(text)

    def test_unexpected_attach_power_or_irq_change_is_not_accepted(self):
        a, b = observation(1), observation(2)
        connection.unchanged(a, b)
        mutations = [lambda s: s.update(udc='configured'), lambda s: s.update(carrier='1'),
                     lambda s: s.update(extcon='USB=1\nUSB-HOST=0'),
                     lambda s: s.update(extcon='USB=0\nUSB-HOST=1'),
                     lambda s: s['supplies']['axp20x-usb'].update(present='1'),
                     lambda s: s['supplies']['axp22x-ac'].update(online='1'),
                     lambda s: s['irqs']['counts'].update(VBUS_PLUGIN=4),
                     lambda s: s.update(boot_id='other'),
                     lambda s: s.update(monotonic_seconds=1),
                     lambda s: s.update(monotonic_seconds=float('nan'))]
        for mutate in mutations:
            bad = deepcopy(b); mutate(bad)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError): connection.unchanged(a, bad)


class BatteryEntry(unittest.TestCase):
    setUp = existing.Entry.setUp
    enter = existing.Entry.enter

    def test_changed_cable_before_entry_never_writes_handshake_or_state(self):
        self.record.update(connection='battery', cable={'before': observation(100)})
        bad = observation(101); bad['irqs']['counts']['VBUS_PLUGIN'] += 1
        with patch.object(connection, 'observe', return_value=bad), self.assertRaises(ValueError): self.enter()
        self.write.assert_not_called(); self.count.assert_not_called()

    def test_rehearsal_and_actual_entry_share_checked_durable_cable_observation(self):
        for mode in ('rehearse', 'rtc-wake'):
            self.record.update(connection='battery', cable={'before': observation(100)})
            self.write.reset_mock(); persisted = []
            with patch.object(connection, 'observe', return_value=observation(101)):
                self.enter(mode, persist=lambda: persisted.append(deepcopy(self.record)))
            self.assertEqual(persisted[0]['cable']['entry'], observation(101))
            self.assertEqual(self.write.call_count, 0 if mode == 'rehearse' else 2)


class BatteryLineage(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(sleep, 'sources', return_value=chain.SOURCE))
        self.pm = Mock(FAULTS=sleep.pm_module().FAULTS)

    def test_valid_battery_history_cannot_admit_usb_or_mixed_mode(self):
        debug, records, current = battery_chain()
        result = sleep.history(self.pm, debug, records, current, {}, 'battery')
        self.assertEqual(result['connection'], 'battery')
        with self.assertRaisesRegex(ValueError, 'connection profile'):
            sleep.history(self.pm, debug, records, current, {})
        for mutate in (lambda r: r.update(connection='usb'),
                       lambda r: r['qualification'].update(connection='usb'),
                       lambda r: r.update(cable_absent_confirmed=False),
                       lambda r: r['cable']['after']['irqs']['counts'].update(VBUS_REMOVAL=99),
                       lambda r: r['usb_trace']['after'].update(state='configured', carrier='1')):
            changed = deepcopy(records); mutate(changed[0])
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                sleep.history(self.pm, debug, changed, current, {}, 'battery')

    def test_mismatched_receipt_fails_before_device_mutation(self):
        with patch.object(sleep, 'claim_successor') as claim, self.assertRaises(ValueError):
            sleep.admission(self.pm, {}, {}, {'connection': 'usb'}, 'battery')
        claim.assert_not_called(); self.pm.validate.assert_not_called()

    def test_battery_host_proof_requires_wifi_and_explicit_no_usb_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); p = root/'diagnostics/run/result.json'; p.parent.mkdir(parents=True)
            value = dict(wifi_ssh_verified=True, usb_ssh_verified=False)
            p.write_text(json.dumps(value))
            with patch.object(host, 'LOCAL', root):
                self.assertEqual(host.saved_result({'capture': str(p)}, 'battery'), value)
                with self.assertRaises(ValueError): host.saved_result({'capture': str(p)})
                for bad in ({'wifi_ssh_verified': False, 'usb_ssh_verified': False},
                            {'wifi_ssh_verified': True},
                            {'wifi_ssh_verified': True, 'usb_ssh_verified': True}):
                    p.write_text(json.dumps(bad))
                    with self.assertRaises(ValueError): host.saved_result({'capture': str(p)}, 'battery')

    def test_awake_usb_rehearsal_cannot_admit_battery_sleep(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); p = root/chain.REHEARSAL; p.mkdir()
            (p/'result.json').write_text(json.dumps({'connection': 'usb'}))
            with patch.object(sleep, 'RESULTS', root), self.assertRaisesRegex(ValueError, 'connection profile'):
                sleep.rehearsal_for_chain(self.pm, {}, {},
                    dict(sleep_runs=[], connection='battery'), chain.REHEARSAL)


class BatteryTransport(unittest.TestCase):
    setUp = chain.Transport.setUp

    def test_uncertain_wifi_submission_collects_original_once_without_usb_probe(self):
        self.complete['connection'] = 'battery'
        replies = [host.paramiko.SSHException('reassociating'), {'event': 'started'}, self.complete]
        with patch.object(host, 'collect', side_effect=replies) as collect:
            value = host.experiment({}, self.root, self.root/'qualification', 'rtc-wake',
                                    chain.REHEARSAL, 'battery')
        self.assertEqual(len(self.submissions), 1)
        self.assertIn('--connection battery', self.submissions[0])
        self.assertIn('--cable-absent-confirmed', self.submissions[0])
        self.assertTrue(all(c.args == ({}, self.token, 'wifi') for c in collect.call_args_list))
        self.assertTrue(all(c.args[1] == 'wifi' for c in host.device.call_args_list))
        self.assertFalse(value['usb_ssh_verified']); self.assertTrue(value['wifi_ssh_verified'])
        run = json.loads((self.root/'run.json').read_text())
        self.assertEqual((run['connection'], run['route']), ('battery', 'wifi'))

    def test_returned_other_profile_is_rejected_before_health_or_route_acceptance(self):
        # Transport's fixture mocks validation; execute the unmocked module here.
        spec = existing.importlib.util.spec_from_file_location('battery_host_validation',
            existing.TOOLS/'check-sleep-rtc.py')
        module = existing.importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with patch.object(module.diagnostic, 'completed_result') as complete, self.assertRaises(ValueError):
            module.validate_result({'connection': 'usb'}, self.token, {}, 'rtc-wake', 'battery')
        complete.assert_not_called()



if __name__ == '__main__':
    unittest.main()
