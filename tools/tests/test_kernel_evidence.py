"""Offline printk retention, provenance, storage and PM admission regressions."""
from copy import deepcopy
import errno
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kernel_evidence as evidence
import test_pm_stages as pm_tests
import test_sleep_rtc as sleep_tests

BOOT = '2170b296-d964-4d16-bdb1-c135b0e7b812'
SECOND_BOOT = '1170b296-d964-4d16-bdb1-c135b0e7b812'


def message(sequence, body, priority=6, flags='-'):
    return f'{priority},{sequence},{1000000 + sequence},{flags};{body}\n'


def boot_records():
    return [message(0, 'Booting Linux on physical CPU 0'),
            message(1, 'brcmfmac: brcmf_c_preinit_dcmds: Firmware: expected'),
            message(2, 'ready')]


def snapshot(records=None):
    value, lock = pm_tests.healthy_fixture()
    value.update(boot_id=BOOT, firmware_sha256='f'*64, nvram_sha256='a'*64,
                 pm_source_sha256=evidence.loaded_source(vars(pm_tests.pm)))
    lock['radio']['firmware']['sha256'] = value['firmware_sha256']
    lock['radio']['nvram']['sha256'] = value['nvram_sha256']
    record = evidence.extend(None, evidence.context(value), records or boot_records())
    value[evidence.KEY] = record
    value['journal'] = evidence.validate(record)
    return value, lock


def advance(value, incoming):
    after = deepcopy(value)
    after[evidence.KEY] = evidence.extend(value[evidence.KEY], evidence.context(value), incoming)
    after['journal'] = evidence.validate(after[evidence.KEY])
    return after


class RecordProtocol(unittest.TestCase):
    def test_rotation_of_general_journal_does_not_change_kernel_evidence(self):
        before, lock = snapshot()
        # Ring's boot prefix has also wrapped: existing protected records cover
        # the missing prefix. General journal is never read or substituted.
        after = advance(before, [boot_records()[2], message(3, 'PM: suspend debug: Waiting for 5 second(s).')])
        pm_tests.pm.validate(after, lock)
        self.assertIn('Waiting for 5', evidence.delta(before, after))
        self.assertEqual(after[evidence.KEY]['records'][:3], boot_records())

    def test_ring_can_start_exactly_at_next_uncollected_record(self):
        before, _ = snapshot()
        after = advance(before, [message(3, 'next')])
        self.assertEqual(len(after[evidence.KEY]['records']), 4)

    def test_lost_boot_or_interval_gap_cannot_be_repaired(self):
        before, _ = snapshot()
        cases = [boot_records()[1:], [message(4, 'gap')],
                 [boot_records()[2], message(4, 'gap')],
                 [boot_records()[2], boot_records()[2]],
                 [boot_records()[2], boot_records()[1]]]
        for records in cases:
            with self.subTest(records=records), self.assertRaises(ValueError):
                evidence.extend(None if records == cases[0] else before[evidence.KEY],
                                evidence.context(before), records)

    def test_empty_regressed_and_altered_overlap_stop(self):
        before, _ = snapshot()
        for records in ([], boot_records()[:2], [message(2, 'altered')]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                advance(before, records)

    def test_wrong_boot_image_firmware_and_source_stop(self):
        before, _ = snapshot()
        for field, value in [('boot_id',SECOND_BOOT),('kernel','another'),
                             ('image_sha256','b'*64),('firmware_sha256','c'*64),
                             ('nvram_sha256','d'*64),('collector_sha256','e'*64),
                             ('producer_sha256','0'*64)]:
            ctx = evidence.context(before) | {field:value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                evidence.extend(before[evidence.KEY], ctx, boot_records())

    def test_invalid_record_boundaries_and_kernel_fragments_stop(self):
        records = ['', '6,0,1,-;no newline', '6,0,1,-;x\nnot metadata\n',
                   '6,x,1,-;x\n', '6,0,1;missing flags\n', '2048,0,1,-;x\n',
                   f'6,{2**64},1,-;x\n', '6,0,1,-;é\n', '6,0,1,-;tab\t\n',
                   message(0,'fragment','6','c'), 'x'*(evidence.MAX_RECORD+1)]
        for raw in records:
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                evidence.parse(raw)

    def test_extra_header_fields_and_device_metadata_are_preserved(self):
        raw = '6,2,1,-,caller=T123;ready\n SUBSYSTEM=usb\n DEVICE=+usb:1-1\n'
        before, _ = snapshot(boot_records()[:2]+[raw])
        self.assertEqual(before[evidence.KEY]['records'][2], raw)
        self.assertIn('ready',before['journal'])
        self.assertNotIn('DEVICE=',before['journal'])

    def test_userspace_messages_cannot_supply_firmware_identity(self):
        with self.assertRaisesRegex(ValueError,'lacks kernel firmware'):
            snapshot([message(0,'brcmf_c_preinit_dcmds: Firmware: expected',14)])
        before, lock = snapshot(boot_records()+[message(3,'WARNING: userspace test',14)])
        pm_tests.pm.validate(before,lock)
        self.assertEqual(len(before[evidence.KEY]['records']),4)
        self.assertNotIn('userspace test',before['journal'])

    def test_new_firmware_identity_or_kernel_fault_still_fails_pm(self):
        before, lock = snapshot()
        for body in ('brcmf_c_preinit_dcmds: Firmware: wrong', 'WARNING: real fault',
                     'Firmware has halted or crashed', 'musb-hdrc: resume work failed with -19'):
            after = advance(before, [message(3, body)])
            with self.subTest(body=body), self.assertRaises(ValueError):
                pm_tests.pm.validate(after,lock)

    def test_tampering_and_modified_rendering_fail(self):
        before, _ = snapshot()
        changes = [lambda s:s[evidence.KEY]['records'].__setitem__(2,message(2,'different')),
                   lambda s:s[evidence.KEY]['anchor'].update(count=1),
                   lambda s:s[evidence.KEY].update(sha256='0'*64),
                   lambda s:s.update(journal=s['journal']+'fabricated'),
                   lambda s:s.update(boot_id=SECOND_BOOT),
                   lambda s:s['image'].update(version='changed')]
        for change in changes:
            altered = deepcopy(before);change(altered)
            with self.subTest(change=change),self.assertRaises(ValueError):
                evidence.validate_snapshot(altered)

    def test_incompatible_anchor_and_legacy_cannot_qualify_new_result(self):
        before, _ = snapshot()
        after = advance(before,[message(3,'later')])
        reseeded = deepcopy(after)
        reseeded[evidence.KEY] = evidence.extend(None,evidence.context(after),after[evidence.KEY]['records'])
        legacy = deepcopy(before);legacy.pop(evidence.KEY)
        for a,b in [(before,reseeded),(legacy,after),(before,legacy),(after,before)]:
            with self.assertRaises(ValueError):evidence.delta(a,b)
        self.assertEqual(evidence.delta({'journal':'old'},{'journal':'old new'}),' new')

    def test_capacity_limits_stop_without_truncating_old_record(self):
        before, _ = snapshot();saved = deepcopy(before)
        with patch.object(evidence,'MAX_BYTES',len(evidence.encoded(before[evidence.KEY]))+10):
            with self.assertRaises(ValueError):advance(before,[message(3,'x'*200)])
        with patch.object(evidence,'MAX_RECORDS',3):
            with self.assertRaises(ValueError):advance(before,[message(3,'extra')])
        self.assertEqual(before,saved)

    def test_pm_result_requires_sequence_evidence_and_keeps_legacy_review(self):
        before,_ = snapshot()
        before.update(stats={'success':'2','fail':'0'}, backlight={},inputs=[],
                      wifi_config_sha256='x',wifi_power_save='on',charger={},cpu_policy={})
        before['pm']['pm_async']='1'
        after = advance(before,[message(3,'PM: suspend debug: Waiting for 5 second(s).')])
        after['stats']['success']='3'
        self.assertIn('Waiting',pm_tests.pm.check_result(before,after,'devices',True))
        after[evidence.KEY]['records'][3]=message(4,'PM: suspend debug: Waiting for 5 second(s).')
        with self.assertRaises(ValueError):pm_tests.pm.check_result(before,after,'devices',True)
        legacy,lock=pm_tests.healthy_fixture();pm_tests.pm.validate(legacy,lock)

    def test_legacy_debug_prerequisites_reject_new_current_format(self):
        debug,current=sleep_tests.qualified()
        current[evidence.KEY]=snapshot()[0][evidence.KEY]
        with self.assertRaises(ValueError):sleep_tests.sleep.prerequisite(debug,current)


class KernelReader(unittest.TestCase):
    def setUp(self):
        self.open=self.enterContext(patch.object(evidence.os,'open',return_value=345))
        self.close=self.enterContext(patch.object(evidence.os,'close'))
        info=type('Info',(),{'st_mode':stat.S_IFCHR|0o600})()
        self.enterContext(patch.object(evidence.os,'fstat',return_value=info))

    def test_nonblocking_reads_stop_at_eagain_and_close_descriptor(self):
        raw=boot_records()[0].encode()
        with patch.object(evidence.os,'read',side_effect=[raw,BlockingIOError(errno.EAGAIN,'empty')]):
            self.assertEqual(list(evidence.read_records()),[raw.decode()])
        flags=self.open.call_args.args[1]
        self.assertTrue(flags & os.O_NONBLOCK);self.assertFalse(flags & os.O_WRONLY)
        self.close.assert_called_once_with(345)

    def test_overrun_short_buffer_invalid_encoding_and_eof_stop(self):
        for failure in (BrokenPipeError(errno.EPIPE,'lost'),OSError(errno.EINVAL,'short'),b'\xff',b''):
            with patch.object(evidence.os,'read',side_effect=[failure]),self.assertRaises((OSError,ValueError)):
                list(evidence.read_records())

    def test_capture_deadline_cannot_extend_indefinitely(self):
        with patch.object(evidence.time,'monotonic',side_effect=[0,6]),self.assertRaises(ValueError):
            list(evidence.read_records())


class ProtectedStorage(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.store=self.root/'evidence'
        self.boot=self.root/'boot';self.boot.write_text(BOOT)
        self.enterContext(patch.object(evidence,'STORE',self.store))
        self.enterContext(patch.object(evidence,'BOOT',self.boot))
        self.enterContext(patch.object(evidence,'OWNER_UID',os.geteuid()))
        self.raw=boot_records()
        self.enterContext(patch.object(evidence,'read_records',side_effect=lambda: (r for r in self.raw)))
        self.snapshot,self.lock=snapshot()

    def capture(self):return evidence.capture(self.snapshot)

    def test_atomic_private_bounded_checkpoint_and_no_op_capture(self):
        value=self.capture()
        path=self.store/'checkpoint.json'
        self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(self.store.stat().st_mode),0o700)
        self.assertEqual(json.loads(path.read_text()),value)
        with patch.object(evidence,'commit',side_effect=AssertionError('unnecessary write')):
            self.assertEqual(self.capture(),value)
        self.raw=[self.raw[-1],message(3,'new')]
        result=self.capture();self.assertEqual(len(result['records']),4)
        self.assertEqual(sorted(p.name for p in self.store.iterdir()),['checkpoint.json','lock'])

    def test_read_failure_preserves_checkpoint_and_never_commits_partial(self):
        self.capture();original=(self.store/'checkpoint.json').read_bytes()
        for error in (BrokenPipeError(errno.EPIPE,'lost'),OSError(errno.EIO,'read')):
            def broken():
                yield message(3,'partial')
                raise error
            with patch.object(evidence,'read_records',side_effect=broken),self.assertRaises(OSError):self.capture()
            self.assertEqual((self.store/'checkpoint.json').read_bytes(),original)

    def test_new_boot_requires_fresh_complete_prefix_and_bounds_old_boot_storage(self):
        self.capture();original=(self.store/'checkpoint.json').read_bytes()
        self.boot.write_text(SECOND_BOOT);self.snapshot['boot_id']=SECOND_BOOT
        self.raw=[message(3,'old prefix lost')]
        with self.assertRaises(ValueError):self.capture()
        self.assertEqual((self.store/'checkpoint.json').read_bytes(),original)
        self.raw=boot_records();value=self.capture()
        self.assertEqual(value['context']['boot_id'],SECOND_BOOT)
        self.assertEqual(len(list(self.store.iterdir())),2)

    def test_source_change_same_boot_requires_new_provenance(self):
        self.capture()
        with patch.object(evidence,'source_hash',return_value='1'*64),self.assertRaises(ValueError):self.capture()

    def test_producer_change_rejected_by_pm_even_with_consistent_checkpoint(self):
        self.snapshot['pm_source_sha256']='0'*64
        value=self.capture();self.snapshot[evidence.KEY]=value
        with self.assertRaisesRegex(ValueError,'producer differs'):
            pm_tests.pm.validate(self.snapshot,self.lock)

    def test_corrupt_oversized_or_insecure_file_cannot_be_reseeded(self):
        self.capture();path=self.store/'checkpoint.json';original=path.read_bytes()
        for raw in (b'{bad',b' '* (evidence.MAX_BYTES+1)):
            path.write_bytes(raw)
            with self.assertRaises(ValueError):self.capture()
            self.assertEqual(path.read_bytes(),raw)
        path.write_bytes(original);path.chmod(0o644)
        with self.assertRaises(ValueError):self.capture()

    def test_symlink_and_hardlink_checkpoint_rejected(self):
        self.capture();path=self.store/'checkpoint.json';target=self.root/'preserved'
        path.rename(target);path.symlink_to(target)
        with self.assertRaises(OSError):self.capture()
        path.unlink();os.link(target,path)
        with self.assertRaises(ValueError):self.capture()

    def test_fifo_checkpoint_is_rejected_without_waiting_for_a_writer(self):
        self.capture();path=self.store/'checkpoint.json';path.unlink()
        os.mkfifo(path,0o600)
        with self.assertRaises(ValueError):self.capture()

    def test_symlink_directory_and_world_writable_parent_rejected(self):
        target=self.root/'target';target.mkdir(mode=0o700);self.store.symlink_to(target)
        with self.assertRaises(OSError):self.capture()
        self.store.unlink();self.root.chmod(0o777)
        with self.assertRaises(ValueError):self.capture()

    def test_competing_writer_cannot_collect_or_publish(self):
        self.capture()
        with (self.store/'lock').open('r+') as guard:
            fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch.object(evidence,'read_records') as reader,self.assertRaises(BlockingIOError):self.capture()
            reader.assert_not_called()

    def test_failed_write_preserves_original_and_stops_on_interruption_marker(self):
        self.capture();original=(self.store/'checkpoint.json').read_bytes();self.raw += [message(3,'extra')]
        with patch.object(evidence.os,'fsync',side_effect=OSError(errno.ENOSPC,'full')),self.assertRaises(OSError):self.capture()
        self.assertEqual((self.store/'checkpoint.json').read_bytes(),original)
        self.assertTrue((self.store/'checkpoint.new').exists())
        with self.assertRaisesRegex(ValueError,'Interrupted'):self.capture()

    def test_boot_change_during_read_does_not_publish(self):
        self.capture();original=(self.store/'checkpoint.json').read_bytes()
        def changing():
            yield from self.raw
            self.boot.write_text(SECOND_BOOT)
        with patch.object(evidence,'read_records',side_effect=changing),self.assertRaises(ValueError):self.capture()
        self.assertEqual((self.store/'checkpoint.json').read_bytes(),original)


class SourcePackaging(unittest.TestCase):
    def test_stdin_bundle_carries_exact_collector_source_identity(self):
        with patch.object(pm_tests.host,'run',return_value=b'') as runner:
            pm_tests.host.inline(None,'--help')
        program=runner.call_args.kwargs['input_data'].decode()
        program=program.replace("if __name__ == '__main__':", "if False:")
        program+='\nprint(kernel_evidence.source_hash())\nprint(kernel_evidence.loaded_source(globals()))\n'
        result=subprocess.run([sys.executable,'-B','-'],input=program,text=True,capture_output=True,check=True)
        self.assertEqual(result.stdout.splitlines(),[evidence.source_hash(),
                         evidence.loaded_source(vars(pm_tests.pm))])

    def test_sleep_bundle_includes_collector_and_hash(self):
        self.assertIn('kernel_evidence',sleep_tests.sleep.SOURCES)
        self.assertEqual(sleep_tests.sleep.sources()['kernel_evidence'],evidence.source_hash())


if __name__=='__main__':unittest.main()
