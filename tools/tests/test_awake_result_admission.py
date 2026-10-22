"""Standalone host admission over scripted local channels; no SSH or sysfs."""
from contextlib import contextmanager, redirect_stdout, ExitStack
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import remote
import awake_result
from awake_fixtures import proof

BOOT = '01234567-1234-1234-1234-123456789abc'
OPERATIONS = ('idle', 'power-profile', 'governor-compare', 'governor-profile', 'rsb-compare')
FILENAMES = dict(zip(OPERATIONS, ('idle-sample.jsonl', 'power-profile.jsonl',
    'governor-comparison.jsonl', 'governor-profile.jsonl', 'rsb-comparison.jsonl')))
SECONDS = dict(zip(OPERATIONS, (60, 120, 60, 30, 60)))


def records(operation):
    seconds = SECONDS[operation]
    ready = dict(event='ready', initial=dict(boot_id=BOOT), seconds=seconds)
    complete = dict(event='complete', passed=True, duration_seconds=seconds)
    if operation == 'idle':
        ready['backlight_mode'] = complete['backlight_mode'] = 'keep'
        ready.update(settle_seconds=60, interval_seconds=10)
        coverage = seconds + 60
    elif operation == 'power-profile':
        ready.update(settle_seconds=30, capabilities={})
        complete.update(interrupts=[], softirqs=[], processes=[])
        coverage = seconds + 30
    elif operation == 'governor-profile':
        ready.update(event_name='cpu-clock:k', sample_frequency_hz=99, callchains=False)
        ready['worker'] = dict(pid=123, start_ticks=456)
        complete.update(final=dict(boot_id=BOOT), worker_after=dict(ready['worker']))
        coverage = seconds
    else:
        ready.pop('seconds')
        ready['seconds_per_phase'] = seconds
        labels = ('original_before', 'slower' if operation == 'governor-compare' else 'shorter', 'original_after')
        if operation == 'governor-compare':
            ready.update(candidate_us=10000, original_us=366, settle_seconds=30, sample_interval_seconds=10)
            complete.update(restored_us=366, phases=[dict(phase=label, rate_limit_us=rate,
                counters=dict(duration_seconds=seconds, interrupts=[], softirqs=[], processes=[]),
                battery=dict(duration_seconds=seconds)) for label, rate in zip(labels, (366, 10000, 366))])
            coverage = 3 * (seconds + 30)
        else:
            ready.update(boot_id=BOOT, candidate_ms=100, original_ms=1000,
                         initial=dict(health=dict(boot_id=BOOT)))
            complete.update(restored_ms=1000, final=dict(health=dict(boot_id=BOOT)),
                phases=[dict(phase=label, delay_ms=delay, residency=dict(seconds=seconds))
                        for label, delay in zip(labels, (1000, 100, 1000))])
            coverage = 3 * (seconds + 15)
    complete['awake_proof'] = proof(coverage, boot=BOOT)
    return [ready, complete]


class Output(io.StringIO):
    def __init__(self):
        super().__init__()
        self.buffer = io.BytesIO()


class ScriptedSftp:
    def __init__(self):
        self.files = {}
        self.removed = []
        self.directories_removed = []
        self.downloaded = []

    def __enter__(self): return self
    def __exit__(self, *_): return False
    def put(self, source, target): self.files[target] = Path(source).read_bytes()
    def chmod(self, _path, _mode): pass
    def posix_rename(self, source, target): self.files[target] = self.files.pop(source)
    def remove(self, target):
        self.removed.append(target)
        del self.files[target]
    def rmdir(self, target):
        if any(path.startswith(target + '/') for path in self.files):
            raise AssertionError('Removing a nonempty fixture stage')
        self.directories_removed.append(target)
    def get(self, source, target):
        self.downloaded.append(source)
        if source not in self.files: raise FileNotFoundError(source)
        Path(target).write_bytes(self.files[source])


class ScriptedChannel:
    def __init__(self, client):
        self.client = client
        self.chunks = []
        self.closed = False
        self.timeout = None
        self.exit_code = 0
        self.runner = False
    def settimeout(self, value): self.timeout = value
    def set_combine_stderr(self, value): assert value is True
    def exec_command(self, command):
        self.client.commands.append(dict(command=command, timeout=self.timeout))
        if 'mktemp -d ' in command:
            self.client.stage = shlex.split(command)[-1].replace('XXXXXXXX', 'LOCAL1234')
            raw = (self.client.stage + '\n').encode()
        elif command.startswith('systemctl show gameshellneo-rsb-comparison '):
            raw = b'not-found\n'
        elif 'systemd-run' in command:
            self.runner = True
            self.exit_code = self.client.runner_exit
            self.client.launches += 1
            self.client.run_command = command
            raw = self.client.raw
            if self.client.operation == 'governor-profile':
                for name in ('perf.data', 'perf-record.txt', 'perf-report.txt', 'kallsyms.txt'):
                    self.client.sftp.files[self.client.stage + '/' + name] = b'OFFLINE fixture artifact\n'
        else:
            raise AssertionError('Unexpected fixture command: ' + command)
        self.chunks = [raw[:7], raw[7:], b'']
    def sendall(self, _value): raise AssertionError('Unexpected fixture stdin')
    def shutdown_write(self): pass
    def recv(self, _size):
        if self.runner and self.client.response_error is not None and len(self.chunks) == 2:
            raise self.client.response_error
        return self.chunks.pop(0)
    def recv_exit_status(self): return self.exit_code
    def close(self): self.closed = True


class ScriptedClient:
    def __init__(self, operation, rows, *, runner_exit=0, response_error=None):
        self.operation = operation
        self.raw = ('\n'.join(json.dumps(row) for row in rows) + '\n').encode()
        self.sftp = ScriptedSftp()
        self.commands = []
        self.channels = []
        self.launches = 0
        self.stage = None
        self.run_command = None
        self.runner_exit = runner_exit
        self.response_error = response_error
    def get_transport(self): return self
    def open_session(self, timeout):
        assert timeout == 10
        channel = ScriptedChannel(self); self.channels.append(channel)
        return channel
    def open_sftp(self): return self.sftp


@contextmanager
def local_device(client):
    yield client


def rsb_host():
    spec = importlib.util.spec_from_file_location('local_awake_rsb_host', TOOLS/'check-rsb-runtime.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def consume(operation, rows, root, *, client=None):
    """Run the actual host branch and actual remote.run, replacing only local I/O endpoints."""
    capture = root/'capture'; capture.mkdir()
    local = root/'local'; local.mkdir()
    client = client or ScriptedClient(operation, rows)
    output = Output()
    with ExitStack() as stack, redirect_stdout(output):
        stack.enter_context(patch.object(remote, 'LOCAL', local))
        stack.enter_context(patch.object(remote, 'evidence_directory', return_value=capture))
        stack.enter_context(patch.object(remote, 'device', side_effect=lambda *_: local_device(client)))
        env = dict(NEO_IDLE_SECONDS='60', NEO_IDLE_BACKLIGHT='keep', NEO_PROFILE_SECONDS=str(SECONDS[operation]),
                   NEO_GOVERNOR_RATE_US='10000', NEO_PERF_SECONDS='30', NEO_RSB_SECONDS='60', NEO_RSB_DELAY_MS='100')
        stack.enter_context(patch.dict(os.environ, env))
        if operation == 'governor-profile':
            binary = local/'build/perf/perf'; binary.parent.mkdir(parents=True)
            binary.write_bytes(b'OFFLINE fixture perf; never executed\n')
            binary.with_suffix('.sha256').write_text(hashlib.sha256(binary.read_bytes()).hexdigest() + '\n')
        if operation == 'rsb-compare':
            host = rsb_host()
            stack.enter_context(patch.object(host, 'LOCAL', local))
            stack.enter_context(patch.object(host, 'evidence_directory', return_value=capture))
            stack.enter_context(patch.object(host, 'load_env', return_value={}))
            stack.enter_context(patch.object(host, 'device', side_effect=lambda *_: local_device(client)))
            stack.enter_context(patch.object(sys, 'argv', ['check-rsb-runtime.py']))
            host.main()
        else:
            remote.device_action({}, 'idle-sample' if operation == 'idle' else operation, 'wifi')
    assert client.launches == 1 and all(channel.closed for channel in client.channels)
    assert (capture/FILENAMES[operation]).read_bytes() == client.raw
    return client, capture, output.getvalue()


def setting(operation):
    return {'idle': 'keep', 'governor-compare': 10000, 'rsb-compare': 100}.get(operation)


def rounded_duration_records(operation):
    """Reported rounding never lowers the raw proof's requested coverage floor."""
    rows = records(operation)
    if operation == 'governor-compare':
        for phase in rows[-1]['phases']:
            phase['counters']['duration_seconds'] -= 0.5
            phase['battery']['duration_seconds'] -= 0.5
    elif operation == 'rsb-compare':
        for phase in rows[-1]['phases']:
            phase['residency']['seconds'] -= 0.5
    else:
        rows[-1]['duration_seconds'] -= 0.5
    return rows


class HostResultAdmission(unittest.TestCase):
    def exercise(self, operation, variant, rows, *, family, accept=False, client=None, error=ValueError):
        client = client or ScriptedClient(operation, rows)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            caught = None
            if accept:
                consume(operation, rows, root, client=client)
            else:
                with self.assertRaises(error) as failure:
                    consume(operation, rows, root, client=client)
                caught = failure.exception
            raw_path = root/'capture'/FILENAMES[operation]
            expected_raw = client.raw[:7] if client.response_error else client.raw
            self.assertEqual(raw_path.read_bytes(), expected_raw)
            self.assertEqual(client.launches, 1)
            self.assertTrue(all(channel.closed for channel in client.channels))
            context = json.loads((root/'capture/awake-result-context.json').read_text())
            self.assertEqual((context['operation'], context['remote_stage']), (operation, client.stage))
            self.assertEqual(context['requested_seconds'], SECONDS[operation])
            admitted = raw_path.with_suffix('.admission.json')
            self.assertEqual(admitted.exists(), accept)
            if accept:
                value = json.loads(admitted.read_text())
                self.assertEqual(value['raw_sha256'], hashlib.sha256(client.raw).hexdigest())
                self.assertEqual(value['boot_id'], BOOT)
                self.assertFalse(value['pm_admission'])
                self.assertFalse(value['clock_reliability_qualified'])
                self.assertEqual(client.stage in client.sftp.directories_removed,
                                 operation in ('governor-compare', 'governor-profile', 'rsb-compare'))
            else:
                self.assertEqual(client.sftp.removed, [])
                self.assertEqual(client.sftp.directories_removed, [])
            if operation == 'governor-profile':
                self.assertEqual(len(client.sftp.downloaded), 4)
                self.assertTrue((root/'capture/perf-report.txt').is_file())
            if client.response_error:
                self.assertIs(caught, client.response_error)
            if client.runner_exit:
                self.assertIn('exit 7', str(caught))
            # The new admission cannot change original unit recovery/deadlines.
            expected_timeout = {'idle': 90, 'power-profile': 210, 'governor-compare': 360,
                                'governor-profile': 120, 'rsb-compare': 150}[operation]
            self.assertEqual(next(c['timeout'] for c in client.commands if c['command']==client.run_command),
                             expected_timeout)
            args = shlex.split(client.run_command)
            maximum = {'idle': 180, 'power-profile': 210, 'governor-compare': 330,
                       'governor-profile': 90, 'rsb-compare': 315}[operation]
            self.assertIn('--property=RuntimeMaxSec='+str(maximum), args)
            restores = [arg for arg in args if arg.startswith('--property=ExecStopPost=')]
            self.assertEqual(bool(restores), operation in ('idle', 'governor-compare', 'rsb-compare'))
            if restores:
                self.assertIn('--restore', restores[0])
            target = os.environ.get('NEO_AWAKE_ADMISSION_RESULTS_DIR')
            if target:
                out=Path(target)/(operation+'-'+variant);out.mkdir(parents=True)
                (out/'raw.jsonl').write_bytes(raw_path.read_bytes())
                (out/'observed.json').write_text(json.dumps(dict(schema=1,operation=operation,variant=variant,
                    family=family,admitted=accept,error_type=type(caught).__name__ if caught else None,
                    error=str(caught) if caught else None,raw_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                    launches=client.launches,channels_closed=True,owned_context=context,
                    stage_removed=client.stage in client.sftp.directories_removed,
                    original_command=client.run_command,original_response_timeout=expected_timeout,
                    no_ssh_connection=True,no_collector_executed=True),indent=2)+'\n')

    def test_valid_raw_proof_at_each_actual_host_consumer(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                self.exercise(operation,'valid',records(operation),family='valid',accept=True)

    def test_prior_sleep_offset_and_false_stored_summary_do_not_override_valid_raw_proof(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                rows=records(operation)
                for observation in rows[-1]['awake_proof']['observations']:
                    observation['boottime_ns']+=3600_000_000_000
                rows[-1]['awake_proof']['validation']=dict(passed=False,boot_id='forged')
                self.exercise(operation,'valid-raw-forged-summary',rows,family='forged-summary',accept=True)

    def test_missing_and_legacy_proof_variants_reject_without_stage_deletion(self):
        for operation in OPERATIONS:
            for name,value in (('absent','absent'),('null',None),('legacy',dict(schema_version=0)),
                               ('summary-only',dict(schema_version=1,validation=dict(passed=True))),
                               ('empty-observations',dict(schema_version=1,observations=[]))):
                with self.subTest(operation=operation,variant=name):
                    rows=records(operation)
                    if name=='absent':del rows[-1]['awake_proof']
                    else:rows[-1]['awake_proof']=value
                    self.exercise(operation,'missing-'+name,rows,family='missing-legacy')

    def test_changed_success_and_failure_counters_reject(self):
        for operation in OPERATIONS:
            for counter in ('success','fail'):
                with self.subTest(operation=operation,counter=counter):
                    rows=records(operation)
                    rows[-1]['awake_proof']['observations'][-1]['pm_counts'][counter]+=1
                    self.exercise(operation,'pm-'+counter,rows,family='changed-pm')

    def test_changed_clock_offset_rejects_without_new_pm_count(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                rows=records(operation)
                rows[-1]['awake_proof']['observations'][-1]['boottime_ns']+=1_000_000_000
                self.exercise(operation,'changed-offset',rows,family='changed-offset')

    def test_proof_must_match_the_ready_boot_identity(self):
        for operation in OPERATIONS:
            for all_rows in (False,True):
                with self.subTest(operation=operation,all_rows=all_rows):
                    rows=records(operation);observations=rows[-1]['awake_proof']['observations']
                    for observation in observations if all_rows else observations[-1:]:
                        observation['boot_id']='another-boot'
                    self.exercise(operation,'wrong-boot-'+str(all_rows),rows,family='wrong-boot')

    def test_short_coverage_rejects_even_with_successful_completion(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                rows=records(operation)
                rows[-1]['awake_proof']=proof(SECONDS[operation]-2,boot=BOOT)
                self.exercise(operation,'short-coverage',rows,family='short-coverage')

    def test_reported_rounding_cannot_lower_the_requested_proof_coverage(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                rows=rounded_duration_records(operation)
                coverage={'idle':120,'power-profile':150,'governor-compare':270,
                          'governor-profile':30,'rsb-compare':225}[operation]
                shortage=1.5 if operation in ('governor-compare','rsb-compare') else 0.5
                rows[-1]['awake_proof']=proof(coverage-shortage,boot=BOOT)
                self.exercise(operation,'rounded-short-coverage',rows,family='short-coverage')

    def test_reported_rounding_with_full_requested_proof_coverage_is_valid(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                self.exercise(operation,'rounded-full-coverage',rounded_duration_records(operation),
                              family='short-coverage',accept=True)

    def test_forged_validation_cannot_hide_disturbed_observations(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                rows=records(operation)
                rows[-1]['awake_proof']['observations'][-1]['pm_counts']['success']=1
                rows[-1]['awake_proof']['validation']=dict(passed=True,observation_count=2,boot_id=BOOT)
                self.exercise(operation,'forged-valid-summary',rows,family='forged-summary')

    def test_incomplete_duplicate_trailing_and_truncated_streams_reject(self):
        for operation in OPERATIONS:
            original=records(operation)
            variants={'no-complete':original[:-1],'empty':[],
                      'duplicate-complete':original+[copy.deepcopy(original[-1])],
                      'after-complete':original+[dict(event='sample')],
                      'failed-then-complete':[original[0],dict(event='failed',passed=False),original[-1]]}
            for name,rows in variants.items():
                with self.subTest(operation=operation,variant=name):
                    self.exercise(operation,name,rows,family='incomplete-stream')
            client=ScriptedClient(operation,original);client.raw=client.raw[:-4]
            self.exercise(operation,'truncated-json',original,client=client,family='incomplete-stream')

    def test_expected_operation_duration_and_setting_identities_reject(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                rows=records(operation)
                key='seconds_per_phase' if operation in ('governor-compare','rsb-compare') else 'seconds'
                rows[0][key]+=1
                self.exercise(operation,'wrong-request-duration',rows,family='operation-identity')
            rows=records(operation)
            if operation=='idle':rows[0]['backlight_mode']='off'
            elif operation=='power-profile':rows[0]['settle_seconds']=60
            elif operation=='governor-profile':rows[-1]['worker_after']['pid']+=1
            elif operation=='governor-compare':rows[-1]['phases'][1]['rate_limit_us']+=1
            else:rows[-1]['restored_ms']+=1
            self.exercise(operation,'wrong-operation-identity',rows,family='operation-identity')

    def test_original_command_errors_and_timeouts_are_not_replaced_by_proof_errors(self):
        for operation in OPERATIONS:
            rows=records(operation)
            with self.subTest(operation=operation,error='exit'):
                client=ScriptedClient(operation,rows,runner_exit=7)
                self.exercise(operation,'original-exit',rows,client=client,error=RuntimeError,family='original-errors')
            with self.subTest(operation=operation,error='timeout'):
                client=ScriptedClient(operation,rows,response_error=TimeoutError('scripted response deadline'))
                self.exercise(operation,'original-timeout',rows,client=client,error=TimeoutError,family='original-errors')

    def test_admission_recomputes_without_mutating_raw_records(self):
        for operation in OPERATIONS:
            rows=records(operation);original=copy.deepcopy(rows)
            result=awake_result.admit(rows,operation=operation,seconds=SECONDS[operation],setting=setting(operation))
            self.assertEqual(rows,original)
            self.assertEqual(result['awake_validation']['observation_count'],2)
            self.assertFalse(result['pm_admission'])
        for value in (True,float('nan'),float('inf'),-1,2**2048):
            rows=records('power-profile');rows[-1]['duration_seconds']=value
            with self.assertRaises(ValueError):
                awake_result.admit(rows,operation='power-profile',seconds=120)

    def test_context_rejects_foreign_stage_and_never_overwrites_owned_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaises(ValueError):
                awake_result.save_context(root,'power-profile',120,'/tmp/foreign.123')
            self.assertEqual(list(root.iterdir()),[])
            awake_result.save_context(root,'power-profile',120,'/tmp/gameshellneo-power-profile.LOCAL1234')
            original=(root/'awake-result-context.json').read_bytes()
            with self.assertRaises(FileExistsError):
                awake_result.save_context(root,'power-profile',120,'/tmp/gameshellneo-power-profile.LOCAL1234')
            self.assertEqual((root/'awake-result-context.json').read_bytes(),original)


if __name__ == '__main__': unittest.main()
