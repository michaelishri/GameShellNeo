"""Policy mutation, process-death persistence and refusal to hand back unknown input."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import power_key_policy as policy
import power_key

spec = importlib.util.spec_from_file_location('policy_host', TOOLS/'check-power-key-policy.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
TOKEN = 'a' * 32
PID = dict(MainPID='42', ExecMainStartTimestampMonotonic='100', ActiveState='active')
BASE = dict.fromkeys(policy.PROPERTIES, 'ignore') | dict.fromkeys(policy.KEYS, 'poweroff')


class Policy(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, value in dict(BOOT=self.root/'boot', OWNED=self.root/'owned',
                DROPIN=self.root/'run/systemd/logind.conf.d/zz-gameshellneo-pm-guard.conf',
                CONFIG_ROOTS=(self.root/'etc', self.root/'run')).items():
            self.enterContext(patch.object(policy, name, value))
        policy.BOOT.write_text('boot')
        self.other = self.root/'etc/systemd/logind.conf.d/50-test.conf'
        self.other.parent.mkdir(parents=True)
        self.other.write_text('[Login]\nHandlePowerKey=poweroff\n')
        self.effective = BASE.copy()
        self.enterContext(patch.object(power_key, 'verify_inhibitor', return_value={}))
        self.enterContext(patch.object(policy, 'policy', side_effect=lambda: self.effective.copy()))
        self.enterContext(patch.object(policy, 'identity', return_value=PID.copy()))
        def reload(expected, process):
            self.assertEqual(process, PID)
            self.assertTrue(policy.OWNED.exists())
            if policy.DROPIN.exists():
                self.assertEqual(policy.DROPIN.read_text(), policy.content(TOKEN))
                self.effective = BASE | policy.IGNORE
            else:
                self.effective = BASE.copy()
            self.assertEqual(self.effective, expected)
        self.reload = self.enterContext(patch.object(policy, 'reload_policy', side_effect=reload))

    def test_acquire_verify_and_untouched_restore_leave_exact_baseline(self):
        before = policy.inspect()
        policy.acquire(TOKEN, 'boot')
        self.assertEqual(policy.verify(TOKEN)['before'], before)
        self.assertEqual(self.effective, BASE | policy.IGNORE)
        guard = Mock()
        policy.restore_untouched(TOKEN, guard)
        self.assertEqual(guard.before_entry.call_count, 3)
        self.assertEqual(policy.inspect(), before)

    def test_mutation_is_preceded_by_owned_intent(self):
        actual = policy.write_exclusive
        def write(path, text):
            self.assertEqual(json.loads(policy.OWNED.read_text())['run_id'], TOKEN)
            actual(path, text)
        with patch.object(policy, 'write_exclusive', side_effect=write):
            policy.acquire(TOKEN, 'boot')

    def test_preexisting_owner_foreign_dropin_and_wrong_boot_do_not_mutate(self):
        for name in ('owner', 'dropin', 'boot', 'policy'):
            with self.subTest(name=name):
                if name == 'owner': policy.OWNED.write_text('foreign')
                if name == 'dropin':
                    policy.DROPIN.parent.mkdir(parents=True, exist_ok=True)
                    policy.DROPIN.write_text('foreign')
                if name == 'policy': self.effective[policy.KEYS[0]] = 'ignore'
                with self.assertRaises(ValueError):
                    policy.acquire(TOKEN, 'wrong' if name == 'boot' else 'boot')
                self.reload.assert_not_called()
                if policy.OWNED.exists():
                    self.assertEqual(policy.OWNED.read_text(), 'foreign'); policy.OWNED.unlink()
                if policy.DROPIN.exists():
                    self.assertEqual(policy.DROPIN.read_text(), 'foreign'); policy.DROPIN.unlink()

    def test_failed_acquisition_reload_retains_intent_and_dropin(self):
        self.reload.side_effect = TimeoutError('not applied')
        with self.assertRaises(TimeoutError): policy.acquire(TOKEN, 'boot')
        self.assertEqual(json.loads(policy.OWNED.read_text())['run_id'], TOKEN)
        self.assertEqual(policy.DROPIN.read_text(), policy.content(TOKEN))

    def test_conflicting_configuration_blocks_restore_without_removal(self):
        policy.acquire(TOKEN, 'boot')
        self.other.write_text('foreign update')
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            policy.restore_untouched(TOKEN, Mock())
        self.assertTrue(policy.OWNED.exists()); self.assertTrue(policy.DROPIN.exists())
        self.assertEqual(self.other.read_text(), 'foreign update')

    def test_boot_owner_file_and_effective_policy_changes_reject_verification(self):
        policy.acquire(TOKEN, 'boot')
        for target, value in ((policy.BOOT, 'other'), (policy.DROPIN, 'foreign')):
            original = target.read_text(); target.write_text(value)
            with self.assertRaises(ValueError): policy.verify(TOKEN)
            target.write_text(original)
        with self.assertRaises(ValueError): policy.verify('b'*32)
        self.effective[policy.KEYS[0]] = 'poweroff'
        with self.assertRaises(ValueError): policy.verify(TOKEN)

    def test_symlink_or_loosened_owner_permissions_cannot_be_trusted(self):
        policy.acquire(TOKEN, 'boot')
        os.chmod(policy.OWNED, 0o644)
        with self.assertRaises(ValueError): policy.verify(TOKEN)
        os.chmod(policy.OWNED, 0o600)
        policy.DROPIN.unlink(); policy.DROPIN.symlink_to(self.other)
        with self.assertRaises(ValueError): policy.verify(TOKEN)
        self.assertEqual(self.other.read_text(), '[Login]\nHandlePowerKey=poweroff\n')

    def test_touched_or_lost_guard_cannot_reenable_poweroff(self):
        policy.acquire(TOKEN, 'boot')
        guard = Mock(); guard.before_entry.side_effect = ValueError('held/lost input')
        with self.assertRaises(ValueError): policy.restore_untouched(TOKEN, guard)
        self.assertTrue(policy.DROPIN.exists()); self.assertEqual(self.effective, BASE | policy.IGNORE)

    def test_failed_restore_reinstates_ignore_and_keeps_owner(self):
        policy.acquire(TOKEN, 'boot')
        real = self.reload.side_effect
        def reload(expected, process):
            if not policy.DROPIN.exists(): raise TimeoutError('restore failed')
            real(expected, process)
        self.reload.side_effect = reload
        with self.assertRaises(TimeoutError): policy.restore_untouched(TOKEN, Mock())
        policy.verify(TOKEN)

    def test_key_event_during_handoff_reinstates_ignore(self):
        policy.acquire(TOKEN, 'boot')
        guard = Mock(); guard.before_entry.side_effect = [None, None, ValueError('new key')]
        with self.assertRaisesRegex(ValueError, 'new key'): policy.restore_untouched(TOKEN, guard)
        policy.verify(TOKEN)

    def test_foreign_replacement_is_not_removed_on_restore_failure(self):
        policy.acquire(TOKEN, 'boot')
        def fail(*_):
            policy.DROPIN.write_text('foreign')
            raise ValueError('external change')
        self.reload.side_effect = fail
        with self.assertRaises(ValueError): policy.restore_untouched(TOKEN, Mock())
        self.assertEqual(policy.DROPIN.read_text(), 'foreign')
        self.assertTrue(policy.OWNED.exists())

    def test_foreign_owner_during_restore_is_preserved(self):
        policy.acquire(TOKEN, 'boot')
        original = self.reload.side_effect
        def changed(expected, process):
            original(expected, process)
            if not policy.DROPIN.exists():
                policy.OWNED.write_text(json.dumps(dict(run_id='b'*32)))
        self.reload.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'owner or boot changed'):
            policy.restore_untouched(TOKEN, Mock())
        self.assertEqual(json.loads(policy.OWNED.read_text())['run_id'], 'b'*32)
        self.assertEqual(self.effective, BASE | policy.IGNORE)

    def test_missing_marker_cannot_be_silently_handed_back(self):
        policy.acquire(TOKEN, 'boot')
        def changed(expected, process):
            self.effective = expected.copy()
            if not policy.DROPIN.exists():
                policy.OWNED.unlink()
        self.reload.side_effect = changed
        with self.assertRaises(FileNotFoundError):
            policy.restore_untouched(TOKEN, Mock())
        self.assertTrue(policy.DROPIN.exists())
        self.assertEqual(self.effective, BASE | policy.IGNORE)

    def test_new_input_owner_rejects_interrupted_policy(self):
        policy.acquire(TOKEN, 'boot')
        with patch.object(power_key, 'POLICY_OWNED', policy.OWNED), \
                patch.object(power_key, 'OWNED', self.root/'key-owner'), \
                patch.object(power_key, 'verify_inhibitor') as inhibitor:
            with self.assertRaises(ValueError):
                with power_key.own({}, Mock()): self.fail('Unresolved policy accepted')
            inhibitor.assert_not_called()

    def test_orphan_dropin_blocks_new_input_owner(self):
        policy.DROPIN.parent.mkdir(parents=True, exist_ok=True)
        policy.DROPIN.write_text('retained without marker')
        with patch.object(power_key, 'POLICY_DROPIN', policy.DROPIN), \
                patch.object(power_key, 'POLICY_OWNED', self.root/'absent'), \
                patch.object(power_key, 'OWNED', self.root/'key-owner'), \
                patch.object(power_key, 'verify_inhibitor') as inhibitor:
            with self.assertRaises(ValueError):
                with power_key.own({}, Mock()): self.fail('Orphan drop-in accepted')
            inhibitor.assert_not_called()

    def test_acquire_requires_inhibitor_before_any_mutation(self):
        with patch.object(power_key, 'verify_inhibitor', side_effect=ValueError('missing inhibitor')):
            with self.assertRaises(ValueError): policy.acquire(TOKEN, 'boot')
        self.assertFalse(policy.OWNED.exists()); self.assertFalse(policy.DROPIN.exists())

    def test_real_process_kill_preserves_policy_ownership(self):
        # The real filesystem mutation code runs in a disposable process; only
        # login1 reads/reload are replaced. There is no fake destructor cleanup.
        program = '''
import sys,json,signal
from pathlib import Path
sys.path.insert(0,sys.argv[1]);import power_key_policy as p
p.power_key.verify_inhibitor=lambda:{}
r=Path(sys.argv[2]);p.BOOT=r/'boot';p.OWNED=r/'owned'
p.DROPIN=r/'run/systemd/logind.conf.d/zz-gameshellneo-pm-guard.conf'
p.CONFIG_ROOTS=(r/'etc',r/'run')
base=dict.fromkeys(p.PROPERTIES,'ignore')|dict.fromkeys(p.KEYS,'poweroff')
p.identity=lambda:dict(MainPID='42',ExecMainStartTimestampMonotonic='100',ActiveState='active')
p.policy=lambda:base.copy()
def reload(expected,process): p.policy=lambda:expected.copy()
p.reload_policy=reload;p.acquire('a'*32,'boot')
print('ready',flush=True)
signal.pause()
'''
        child = subprocess.Popen([sys.executable, '-c', program, str(TOOLS), str(self.root)], stdout=subprocess.PIPE)
        try:
            import select
            self.assertTrue(select.select([child.stdout], [], [], 5)[0])
            self.assertEqual(child.stdout.readline(), b'ready\n')
            child.kill(); self.assertEqual(child.wait(timeout=5), -signal.SIGKILL)
            self.effective = BASE | policy.IGNORE
            policy.verify(TOKEN)
            with self.assertRaises(ValueError): policy.acquire(TOKEN, 'boot')
        finally:
            if child.poll() is None: child.kill(); child.wait(timeout=5)
            child.stdout.close()


class Interfaces(unittest.TestCase):
    def test_policy_response_order_shape_and_type(self):
        data = '\n'.join(json.dumps(dict(type='s', data=BASE[k])) for k in policy.PROPERTIES)
        with patch.object(policy, 'command', return_value=data): self.assertEqual(policy.policy(), BASE)
        for bad in (data+'\n'+data, '{"type":"u","data":1}', '{}'):
            with patch.object(policy, 'command', return_value=bad), self.assertRaises(ValueError): policy.policy()

    def test_reload_polls_effective_policy_without_restart(self):
        with patch.object(policy, 'identity', return_value=PID), \
                patch.object(policy, 'policy', side_effect=[BASE, BASE | policy.IGNORE]), \
                patch.object(policy, 'command') as cmd, patch.object(policy.time, 'sleep'):
            policy.reload_policy(BASE | policy.IGNORE, PID)
        cmd.assert_called_once_with('systemctl','kill','--kill-whom=main','--signal=HUP','systemd-logind.service')

    def test_reload_rejects_restart_and_timeout(self):
        with patch.object(policy, 'identity', side_effect=[PID, PID | {'MainPID':'99'}]), \
                patch.object(policy, 'command'), self.assertRaises(ValueError):
            policy.reload_policy(BASE | policy.IGNORE, PID)
        with patch.object(policy, 'identity', return_value=PID), patch.object(policy, 'command'), \
                patch.object(policy.time, 'monotonic', side_effect=[0, 6]), self.assertRaises(TimeoutError):
            policy.reload_policy(BASE | policy.IGNORE, PID)

    def test_host_rejects_false_success_and_changed_outcomes(self):
        before = dict(boot_id='boot', logind=PID, config={}, policy=BASE)
        held = before | dict(owned=True, dropin=True, policy=BASE | policy.IGNORE)
        value = dict(run_id=TOKEN, passed=True, restored=True, worker_returncode=-9,
            policy_owner_retained=False, dropin_retained=False, before=before, after=before,
            survived_worker_death=held, power_key=dict(events=[], handed_back=True,
                logical_release_verified=True, descriptor_closed=True))
        host.validate_result(value,TOKEN,'boot')
        for k,v in (('restored',False),('worker_returncode',0),('dropin_retained',True),
                    ('after',{}),('power_key',dict(events=[116]))):
            with self.subTest(key=k), self.assertRaises(ValueError):
                host.validate_result(value | {k:v},TOKEN,'boot')


if __name__ == '__main__':
    unittest.main()
