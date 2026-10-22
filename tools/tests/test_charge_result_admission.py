"""Actual charging host control flow over local scripted channels; no SSH/sysfs."""
from contextlib import contextmanager, redirect_stdout
import copy
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from test_charge_baseline import host, sampler, sample, checkpoint
import charge_result

SECONDS = 60
LOCK = json.loads((host.ROOT/'build/sources.lock.json').read_text())
KERNEL = LOCK['linux']['tag'][1:] + LOCK['linux']['localversion']
IMAGE = LOCK['image_version']


def records():
    samples=[sample(index) for index in range(7)]
    inventory=dict(schema_version=4,kind='axp223-charge-inventory',completed=True,
        kernel=KERNEL,image=dict(kernel=KERNEL,version=IMAGE,board='gameshellneo-cpi31'),
        before=checkpoint(98_000_000_000),after=checkpoint(99_000_000_000))
    return [dict(event='started',schema_version=1,seconds=SECONDS,interval_seconds=10,
                 inventory=inventory,limits=sampler.LIMITS),
            *[dict(event='sample',sample=value) for value in samples],
            dict(event='completed',passed=True,summary=sampler.summary(samples,SECONDS))]


class ScriptedChannel:
    def __init__(self,client):
        self.client=client
        self.chunks=[]
        self.closed=False
        self.timeout=None
    def settimeout(self,value):self.timeout=value
    def set_combine_stderr(self,value):assert value is True
    def exec_command(self,command):
        self.client.command=command
        self.client.launches+=1
        with (self.client.local/'pm-stages.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:self.client.pm_lock_held=True
            else:raise AssertionError('Original PM lock is not held during command')
        raw=self.client.raw
        self.chunks=[raw[:7],raw[7:],b'']
    def sendall(self,value):self.client.stdin+=value
    def shutdown_write(self):self.client.stdin_closed=True
    def recv(self,_size):
        if self.client.response_error and len(self.chunks)==2:raise self.client.response_error
        return self.chunks.pop(0)
    def recv_exit_status(self):return self.client.exit_code
    def close(self):self.closed=True


class ScriptedClient:
    def __init__(self,rows,*,exit_code=0,response_error=None):
        self.raw=('\n'.join(json.dumps(row) for row in rows)+'\n').encode()
        self.exit_code=exit_code
        self.response_error=response_error
        self.local=None
        self.channel=None
        self.command=None
        self.launches=0
        self.stdin=b''
        self.stdin_closed=False
        self.pm_lock_held=False
    def get_transport(self):return self
    def open_session(self,timeout):
        assert timeout==10
        self.channel=ScriptedChannel(self)
        return self.channel


@contextmanager
def local_device(client):yield client


def consume(rows,root,*,client=None):
    client=client or ScriptedClient(rows)
    capture=root/'capture';capture.mkdir()
    local=root/'local';local.mkdir();client.local=local
    output=io.StringIO()
    with patch.object(host,'LOCAL',local),patch.object(host,'evidence_directory',return_value=capture), \
            patch.object(host,'load_env',return_value={}), \
            patch.object(host,'device',side_effect=lambda *_:local_device(client)), \
            patch.dict(os.environ,NEO_CHARGE_SECONDS='60'),redirect_stdout(output):
        host.main()
    return client,capture,output.getvalue()


class HostResultAdmission(unittest.TestCase):
    def exercise(self,name,rows,*,family,accept=False,client=None,error=ValueError):
        client=client or ScriptedClient(rows)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);caught=None
            if accept:
                consume(rows,root,client=client)
            else:
                with self.assertRaises(error) as failure:consume(rows,root,client=client)
                caught=failure.exception
            capture=root/'capture'
            self.assertEqual(client.launches,1)
            self.assertTrue(client.channel.closed and client.stdin_closed and client.pm_lock_held)
            self.assertEqual(client.stdin,host.payload()[0])
            self.assertEqual(client.channel.timeout,40)
            args=shlex.split(client.command)
            self.assertEqual(args[:8],['sudo','-n','/usr/bin/timeout','--signal=TERM','--kill-after=5',
                                      '80','/usr/bin/python3','-B'])
            self.assertEqual(args[8:],['-','--kernel',KERNEL,'--image',IMAGE,'--seconds','60'])
            raw=(capture/'charge-baseline.jsonl').read_bytes()
            self.assertEqual(raw,client.raw[:7] if client.response_error else client.raw)
            provenance=json.loads((capture/'provenance.json').read_text())
            self.assertEqual(provenance['payload_sha256'],hashlib.sha256(client.stdin).hexdigest())
            self.assertEqual(provenance['seconds'],60)
            admitted=capture/'charge-baseline.admission.json'
            self.assertEqual(admitted.exists(),accept)
            if accept:
                receipt=json.loads(admitted.read_text())
                self.assertEqual(receipt['raw_sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(receipt['sample_count'],7)
                self.assertEqual(receipt['summary'],sampler.summary([sample(i) for i in range(7)],60))
                self.assertFalse(receipt['calibrated'] or receipt['charging_safety_qualified'] or
                                 receipt['sleep_charge_measured'] or receipt['current_device_or_image_admitted'] or
                                 receipt['clock_reliability_qualified'])
            with (client.local/'pm-stages.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if client.response_error:self.assertIs(caught,client.response_error)
            if client.exit_code:self.assertIn('exit 7',str(caught))
            target=os.environ.get('NEO_CHARGE_ADMISSION_RESULTS_DIR')
            if target:
                out=Path(target)/name;out.mkdir(parents=True)
                (out/'raw.jsonl').write_bytes(raw)
                (out/'provenance.json').write_bytes((capture/'provenance.json').read_bytes())
                (out/'observed.json').write_text(json.dumps(dict(schema=1,variant=name,family=family,
                    admitted=accept,error_type=type(caught).__name__ if caught else None,
                    error=str(caught) if caught else None,raw_sha256=hashlib.sha256(raw).hexdigest(),
                    actual_remote_run_used=True,payload_sha256=hashlib.sha256(client.stdin).hexdigest(),
                    payload_bytes_unchanged=True,pm_lock_held=True,pm_lock_released_after_result=True,channels_closed=True,
                    command=client.command,response_timeout=client.channel.timeout,
                    no_collector_executed=True,no_ssh_connection=True),indent=2)+'\n')

    def test_valid_raw_samples_and_ignored_stored_offset_fields(self):
        self.exercise('valid',records(),family='valid',accept=True)
        rows=records()
        for row in rows[1:-1]:
            for point in ('before','after'):
                row['sample'][point]['clock']['offset_low_ns']=-123456789
                row['sample'][point]['clock']['offset_high_ns']=123456789
        self.exercise('valid-raw-forged-stored-offsets',rows,family='offset-forged',accept=True)

    def test_missing_raw_and_legacy_streams_reject(self):
        original=records()
        variants={'completion-only':[original[-1]],'no-started':original[1:],
                  'no-completed':original[:-1],'empty':[]}
        legacy=records();legacy[0]['schema_version']=0;variants['legacy']=legacy
        for name,rows in variants.items():
            with self.subTest(variant=name):self.exercise(name,rows,family='missing-legacy')

    def test_changed_pm_counters_reject_despite_forged_success(self):
        for counter in ('success','fail'):
            rows=records()
            for point in ('before','after'):rows[4]['sample'][point]['pm'][counter]='12'
            self.exercise('changed-pm-'+counter,rows,family='changed-pm')

    def test_raw_offset_shift_rejects_even_with_forged_stored_bounds(self):
        for direction in (-1,1):
            rows=records()
            for row in rows[4:-1]:
                for point in ('before','after'):
                    row['sample'][point]['clock']['boottime_ns']+=direction*500_000_000
            self.exercise('changed-offset-'+str(direction),rows,family='offset-forged')

    def test_raw_samples_must_match_the_initial_stream_boot(self):
        for all_samples in (False,True):
            rows=records()
            for row in rows[1:-1] if all_samples else rows[4:5]:
                for point in ('before','after'):row['sample'][point]['boot_id']='different-boot'
            self.exercise('wrong-boot-'+str(all_samples),rows,family='wrong-boot')

    def test_missing_duplicate_trailing_failed_and_truncated_samples_reject(self):
        original=records()
        variants={'missing-sample':original[:4]+original[5:],
                  'duplicate-sample':original[:4]+[copy.deepcopy(original[3])]+original[4:],
                  'after-complete':original+[dict(event='sample',sample=sample(7))],
                  'failed-then-completed':original[:-1]+[dict(event='failed'),original[-1]]}
        rows=records();rows[1]['sample']['index']=False;variants['boolean-index']=rows
        for name,rows in variants.items():self.exercise(name,rows,family='incomplete-stream')
        client=ScriptedClient(original);client.raw=client.raw[:-4]
        self.exercise('truncated-json',original,client=client,family='incomplete-stream')

    def test_stored_summary_must_equal_independent_raw_recomputation(self):
        for key,value in [('sampled_net_charge_estimate_uah',123456789),('samples',6),
                          ('elapsed_seconds',59.5),('sleep_charge_measured',True),('limits',[])]:
            rows=records();rows[-1]['summary'][key]=value
            self.exercise('forged-summary-'+key,rows,family='forged-summary')

    def test_expected_operation_identity_is_checked(self):
        for name in ('seconds','interval','kernel','image','inventory','passed'):
            rows=records()
            if name=='seconds':rows[0]['seconds']=True
            elif name=='interval':rows[0]['interval_seconds']=30
            elif name=='kernel':rows[0]['inventory']['kernel']='wrong'
            elif name=='image':rows[0]['inventory']['image']['version']='wrong'
            elif name=='inventory':rows[0]['inventory']['completed']=False
            else:rows[-1]['passed']=1
            self.exercise('operation-'+name,rows,family='operation-identity')

    def test_raw_clock_values_require_integers_and_bounded_ordered_brackets(self):
        for name in ('boolean','float','negative','missing','wide','backwards'):
            rows=records();clock=rows[4]['sample']['before']['clock']
            if name=='boolean':clock['boottime_ns']=True
            elif name=='float':clock['boottime_ns']=float(clock['boottime_ns'])
            elif name=='negative':clock['boottime_ns']=-1
            elif name=='missing':del clock['monotonic_before_ns']
            elif name=='wide':clock['monotonic_after_ns']+=1_000_001
            else:clock['monotonic_after_ns']=clock['monotonic_before_ns']-1
            self.exercise('raw-clock-'+name,rows,family='raw-bracket')

    def test_raw_proof_cannot_be_shorter_than_the_requested_operation(self):
        rows=records()
        for index,row in enumerate(rows[1:-1]):
            for point in ('before','after'):
                clock=row['sample'][point]['clock']
                for key in ('monotonic_before_ns','boottime_ns','monotonic_after_ns'):
                    clock[key]-=index*100_000_000
        # Individual spacings and the existing +/-2 s summary tolerance permit
        # this 59.4 s stream; the new host's explicit 60 s raw floor must reject.
        rows[-1]['summary']=sampler.summary([row['sample'] for row in rows[1:-1]],60)
        self.exercise('short-request-coverage',rows,family='raw-bracket')

    def test_original_command_exit_and_response_timeout_are_preserved(self):
        rows=records()
        self.exercise('original-exit',rows,client=ScriptedClient(rows,exit_code=7),
                      family='original-errors',error=RuntimeError)
        self.exercise('original-timeout',rows,client=ScriptedClient(rows,response_error=TimeoutError('scripted response deadline')),
                      family='original-errors',error=TimeoutError)

    def test_admission_derives_offsets_without_mutating_raw_records(self):
        rows=records()
        for row in rows[1:-1]:
            for point in ('before','after'):
                del row['sample'][point]['clock']['offset_low_ns']
                del row['sample'][point]['clock']['offset_high_ns']
        original=copy.deepcopy(rows)
        admitted=charge_result.admit(rows,seconds=60,kernel=KERNEL,image=IMAGE)
        self.assertEqual(rows,original)
        self.assertEqual(admitted['awake_validation']['observation_count'],14)

    def test_reuse_boundary_calls_only_existing_pure_summary_and_validation(self):
        rows=records()
        def forbidden(*_args,**_kwargs):raise AssertionError('Collector I/O must not execute on the host')
        with patch.object(charge_result.sampler,'capture',side_effect=forbidden), \
                patch.object(charge_result.sampler,'collect',side_effect=forbidden), \
                patch.object(charge_result.inventory,'inspect',side_effect=forbidden), \
                patch.object(charge_result.inventory,'read',side_effect=forbidden), \
                patch.object(charge_result.sampler,'summary',wraps=charge_result.sampler.summary) as summarize:
            charge_result.admit(rows,seconds=60,kernel=KERNEL,image=IMAGE)
            summarize.assert_called_once()

    def test_success_receipt_is_separate_and_never_overwrites_prior_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'charge-baseline.jsonl'
            raw=ScriptedClient(records()).raw;path.write_bytes(raw)
            charge_result.admit_capture(path,seconds=60,kernel=KERNEL,image=IMAGE)
            receipt=path.with_suffix('.admission.json').read_bytes()
            with self.assertRaises(FileExistsError):
                charge_result.admit_capture(path,seconds=60,kernel=KERNEL,image=IMAGE)
            self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(path.with_suffix('.admission.json').read_bytes(),receipt)


if __name__=='__main__':unittest.main()
