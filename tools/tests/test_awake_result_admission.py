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
        coverage = seconds + 60
    elif operation == 'power-profile':
        complete.update(interrupts=[], softirqs=[], processes=[])
        coverage = seconds + 30
    elif operation == 'governor-profile':
        ready['worker'] = dict(pid=123, start_ticks=456)
        complete.update(final=dict(boot_id=BOOT), worker_after=dict(ready['worker']))
        coverage = seconds
    else:
        ready.pop('seconds')
        ready['seconds_per_phase'] = seconds
        labels = ('original_before', 'slower' if operation == 'governor-compare' else 'shorter', 'original_after')
        if operation == 'governor-compare':
            ready.update(candidate_us=10000, original_us=366)
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
    def recv(self, _size): return self.chunks.pop(0)
    def recv_exit_status(self): return 0
    def close(self): self.closed = True


class ScriptedClient:
    def __init__(self, operation, rows):
        self.operation = operation
        self.raw = ('\n'.join(json.dumps(row) for row in rows) + '\n').encode()
        self.sftp = ScriptedSftp()
        self.commands = []
        self.channels = []
        self.launches = 0
        self.stage = None
        self.run_command = None
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


def consume(operation, rows, root):
    """Run the actual host branch and actual remote.run, replacing only local I/O endpoints."""
    capture = root/'capture'; capture.mkdir()
    local = root/'local'; local.mkdir()
    client = ScriptedClient(operation, rows)
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


class BaselineConsumerAcceptance(unittest.TestCase):
    def retain(self, operation, variant, client, capture):
        target = os.environ.get('NEO_AWAKE_ADMISSION_BASELINE_DIR')
        if not target: return
        out = Path(target)/(operation+'-'+variant); out.mkdir(parents=True)
        (out/'result.jsonl').write_bytes((capture/FILENAMES[operation]).read_bytes())
        (out/'actual-host-result.json').write_text(json.dumps(dict(operation=operation, variant=variant,
            accepted_by_original_host=True, commands=client.commands, launches=client.launches,
            channels_closed=all(c.closed for c in client.channels),removed=client.sftp.removed,
            owned_stage=client.stage,owned_stage_removed=client.stage in client.sftp.directories_removed,
            no_ssh_connection=True,device_contact=False),indent=2)+'\n')

    def test_original_five_consumers_accept_missing_raw_proof(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                rows = records(operation); del rows[-1]['awake_proof']
                client,capture,_ = consume(operation,rows,Path(directory))
                self.retain(operation,'missing-proof',client,capture)

    def test_original_five_consumers_accept_changed_pm_with_forged_summary(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                rows = records(operation)
                rows[-1]['awake_proof']['observations'][-1]['pm_counts']['success']=1
                rows[-1]['awake_proof']['validation']=dict(passed=True)
                client,capture,_ = consume(operation,rows,Path(directory))
                self.retain(operation,'changed-pm-forged-summary',client,capture)


if __name__ == '__main__': unittest.main()
