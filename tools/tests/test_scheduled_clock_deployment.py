"""Scheduled mode requires explicit source admission and retains every failed stage."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import clock_deployment as cd
import clock_scheduled as cs
import development_clock as dc
from test_development_clock import contract as development_contract
from test_clock_deployment import snapshot as original_snapshot
from test_clock_scheduled import fixture, pause_value


def load(name):
    spec = importlib.util.spec_from_file_location('test_scheduled_' + name.replace('-', '_'), ROOT / 'tools' / (name + '.py'))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def contract():
    value, _ = development_contract()
    value['scheduled'] = dict(schema=1, operation=cs.OPERATION, schedule=cs.schedule(),
        files={name: '56' * 32 for name in cs.FILES}, pause_receipt_sha256='67' * 32,
        pm_admission=False, clock_reliability_qualified=False)
    return value


def snapshot(value):
    return original_snapshot(value) | {'scheduled': copy.deepcopy(value['scheduled']),
        'development': {'source_image_sha256': value['development']['source_image_sha256']}}


class ContractTests(unittest.TestCase):
    def test_complete_explicit_contract_and_unchanged_384_mode(self):
        value = contract(); cs.validate_contract(value)
        for key, changed in (('schema', True), ('operation', 'clock-boundary-capture'),
                ('files', {}), ('pause_receipt_sha256', 'not-a-digest'), ('pm_admission', True),
                ('clock_reliability_qualified', True)):
            wrong = copy.deepcopy(value); wrong['scheduled'][key] = changed
            with self.subTest(key=key), self.assertRaises(ValueError): cs.validate_contract(wrong)
        value['scheduled']['schedule']['rounds'] = 32.0
        with self.assertRaises(ValueError): cs.validate_contract(value)
        with self.assertRaises(KeyError): cs.validate_contract(development_contract()[0])

    def test_original_and_development_runners_refuse_scheduled_contract_before_ssh(self):
        host = load('check-clock-boundary')
        value = contract()
        with patch.object(host, 'run') as run:
            for runner, extra in (('capture-clock-boundary.py', {}),
                    ('capture-development-clock.py', {name: ROOT / 'tools' / name for name in dc.ADAPTERS}),
                    ('capture-scheduled-clock.py', {}), ('capture-scheduled-clock.py', {'wrong': ROOT / 'tools/clock_scheduled.py'})):
                with self.subTest(runner=runner), self.assertRaises(ValueError):
                    host.execute(None, ROOT, value, ROOT, extra_files=extra, runner=runner)
            old = development_contract()[0]
            with self.assertRaises(ValueError):
                host.execute(None, ROOT, old, ROOT, extra_files={'wrong': ROOT}, runner='capture-scheduled-clock.py')
            run.assert_not_called()

    def test_actual_staging_transfers_all_three_new_inputs_and_exact_bounded_contract(self):
        host, value = load('check-clock-boundary'), contract()
        release = value['development']['release']
        release['immutable_files'].update({'usr/' + str(i) + '/path': 'a' * 64 for i in range(23000)})
        value['development']['release_sha256'] = dc.digest(dc.json_bytes(release))
        stage, staged = '/tmp/gameshellneo-clock-boundary.12345678', {}
        sftp = Mock(); sftp.__enter__ = Mock(return_value=sftp); sftp.__exit__ = Mock(return_value=False)
        sftp.open.side_effect = lambda path, mode: io.BytesIO(staged[path])
        sftp.stat.side_effect = FileNotFoundError
        client = Mock(); client.open_sftp.return_value = sftp
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); reader = root / 'reader'; capture = root / 'capture'
            (reader / 'tools').mkdir(parents=True); capture.mkdir()
            for name in cd.FILES:
                path = reader / name if name.endswith('.so') else reader / 'tools' / name
                path.write_bytes(name.encode()); value['files'][name] = dc.sha(path)
            pause = root / 'clock-pause.so'; pause.write_bytes(b'test pause artifact')
            extras = {name: ROOT / 'tools' / name for name in (*dc.ADAPTERS, *cs.FILES) if not name.endswith('.so')}
            extras['clock-pause.so'] = pause
            value['development']['adapter_files'] = {name: dc.sha(extras[name]) for name in dc.ADAPTERS}
            value['scheduled']['files'] = {name: dc.sha(extras[name]) for name in cs.FILES}

            def upload(sftp, source, target): staged[target] = Path(source).read_bytes()

            with patch.object(host, 'run', return_value=stage.encode()), patch.object(host, 'upload', side_effect=upload), \
                    patch.object(host, 'supervise', return_value={'terminal': True}) as supervise:
                host.execute(client, reader, value, capture, extra_files=extras, runner='capture-scheduled-clock.py')
                self.assertGreater(len(json.dumps(value, indent=2).encode()), 2 * 1024 * 1024)
                self.assertLessEqual(len(staged[stage + '/contract.json']), 2 * 1024 * 1024)
                self.assertEqual(staged[stage + '/contract.json'], host.contract_bytes(value))
                for name in extras: self.assertEqual(staged[stage + '/' + name], extras[name].read_bytes())
                supervise.assert_called_once_with(client, unittest.mock.ANY, stage, capture, runner='capture-scheduled-clock.py')

    def test_staged_workload_imports_and_validates_without_unprovided_dependencies(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (*dc.ADAPTERS, 'clock_boundary.py', 'clock_provenance.py', 'clock_deployment.py',
                         'clock_scheduled.py', 'capture-scheduled-clock.py'):
                (root / name).write_bytes((ROOT / 'tools' / name).read_bytes())
            (root / 'contract.json').write_text(json.dumps(contract()))
            source = ('import sys,json;sys.path.insert(0,sys.argv[1]);import clock_scheduled as c;'
                'c.validate_contract(json.load(open(sys.argv[1]+"/contract.json")))')
            subprocess.run([sys.executable, '-I', '-S', '-B', '-c', source, directory], check=True, capture_output=True, timeout=10)

    def test_original_or_pause_offline_refusal_never_loads_hardware(self):
        host = load('check-scheduled-clock')
        with tempfile.TemporaryDirectory() as directory:
            argv = ['entry']
            for name in ('image-checkout', 'reader-build', 'runtime-capture', 'release-manifest', 'pause-build', 'hardware-checkout'):
                argv.extend(['--' + name, directory])
            argv += ['--boot-id', 'wrong', '--card-cid', 'wrong', '--store-uuid', 'wrong', '--apply']
            for original_failure in (True, False):
                with patch.object(sys, 'argv', argv), patch.object(host, 'offline_inputs',
                        side_effect=ValueError('original image differs') if original_failure else None,
                        return_value=contract()), patch.object(host, 'pause_inputs', side_effect=ValueError('pause differs')), \
                        patch.object(host, 'load_hardware') as hardware:
                    with self.assertRaises(ValueError): host.main()
                    hardware.assert_not_called()


class PersistenceTests(unittest.TestCase):
    def evidence(self):
        records, users = fixture()
        return users, ''.join(json.dumps(value) + '\n' for value in records).encode()

    def test_originals_precede_failed_postflight_and_bad_replay(self):
        for failed_postflight in (True, False):
            value = contract(); users, raw = self.evidence()
            if not failed_postflight: raw = b'original malformed bytes\n'
            observe = Mock(side_effect=[snapshot(value), OSError('postflight lost') if failed_postflight else snapshot(value)])
            control = Mock()
            with tempfile.TemporaryDirectory() as directory, patch.object(cs, 'collect', return_value=(users, raw)):
                result = cs.execute(Path(directory), value, observe, None, None, None, lambda: control)
                self.assertFalse(result['complete'])
                self.assertEqual((Path(directory) / 'kernel.ndjson').read_bytes(), raw)
                self.assertEqual(json.loads((Path(directory) / 'users.json').read_text()), users)
                self.assertEqual(result['errors'][0]['stage'], 'postflight' if failed_postflight else 'replay')
                control.close.assert_called_once()

    def test_preflight_source_mismatch_never_opens_or_starts_recorder(self):
        value = contract(); wrong = snapshot(value); wrong['scheduled'] = {}
        opened = Mock()
        with tempfile.TemporaryDirectory() as directory:
            result = cs.execute(Path(directory), value, lambda: wrong, None, None, None, opened)
            self.assertFalse(result['complete']); opened.assert_not_called()
            self.assertFalse((Path(directory) / 'kernel.ndjson').exists())

    def test_preallocation_failure_still_closes_owned_descriptor_and_never_relaunches(self):
        value = contract(); control, opened = Mock(), Mock()
        opened.return_value = control
        with tempfile.TemporaryDirectory() as directory, patch.object(cs, 'collect', side_effect=MemoryError('preallocation')):
            result = cs.execute(Path(directory), value, lambda: snapshot(value), None, None, None, opened)
            self.assertFalse(result['complete']); opened.assert_called_once(); control.close.assert_called_once()
            self.assertEqual(result['errors'][0]['stage'], 'capture')


class HostOwnershipTests(unittest.TestCase):
    def run_host(self, mode):
        host, value = load('check-scheduled-clock'), contract()
        records, users = fixture()
        users['context']['source_id'] = value['source_id']
        for call in records[1:]:
            for kind in ('mono', 'raw'): call['tuple'][kind]['source_id'] = value['source_id']
        raw = ''.join(json.dumps(v) + '\n' for v in records).encode()
        analysis = cs.join(records, users)
        self.assertTrue(analysis['complete'])
        remote, clock, pm, observation, runner = Mock(), Mock(), Mock(), Mock(), Mock()
        runner.OUTPUTS = load('check-clock-boundary').OUTPUTS
        health = dict(boot_id=value['boot_id'], kernel=value['kernel'], pm={'pm_test': '[none]'}, failed_units='')
        clock.inspect.side_effect = [health, health]
        if mode == 'postflight': observation.validate_state.side_effect = ValueError('health changed')
        remote.run.return_value = b''
        client, sftp, connection = Mock(), Mock(), Mock()
        connection.__enter__ = Mock(return_value=client); connection.__exit__ = Mock(return_value=False)
        remote.device.return_value = connection
        sftp.__enter__ = Mock(return_value=sftp); sftp.__exit__ = Mock(return_value=False)
        client.open_sftp.return_value = sftp
        if mode == 'cleanup': sftp.rmdir.side_effect = OSError('owned cleanup interrupted')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'tools').mkdir(); (root / 'reader').mkdir(); (root / 'pause').mkdir()
            for name in (*dc.ADAPTERS, *cs.FILES):
                if not name.endswith('.so'): (root / 'tools' / name).write_bytes((ROOT / 'tools' / name).read_bytes())
            remote.LOCAL, remote.ROOT = root / '.local', ROOT

            def execute(client, reader, current, capture, **kwargs):
                if mode == 'timeout': raise TimeoutError('observe original unit; no relaunch')
                outputs = {'users.json': users, 'analysis.json': analysis, 'before.json': snapshot(current),
                    'after.json': snapshot(current), 'remote-stage.json': {'directory': '/tmp/gameshellneo-clock-boundary.12345678'},
                    'result.json': {'complete': mode != 'incomplete', 'state_unchanged': True}}
                (capture / 'kernel.ndjson').write_bytes(raw)
                (capture / 'contract.json').write_bytes(dc.json_bytes(current))
                for name, content in outputs.items(): (capture / name).write_text(json.dumps(content))
                return dict(error=False, terminal=mode != 'unterminated', execution_succeeded=True)

            runner.execute.side_effect = execute
            modules = {'check-clock-boundary': runner, 'check-clock-paths': clock, 'check-pm-stages': pm,
                       'check-clock-observation': observation}
            argv = ['entry']
            for name, path in (('image-checkout', root), ('reader-build', root / 'reader'), ('runtime-capture', root),
                    ('release-manifest', root), ('pause-build', root / 'pause'), ('hardware-checkout', root)):
                argv.extend(['--' + name, str(path)])
            argv += ['--boot-id', value['boot_id'], '--card-cid', value['development']['card_cid'],
                     '--store-uuid', value['development']['store_uuid'], '--apply']
            with patch.object(host, 'ROOT', root), patch.object(sys, 'argv', argv), patch.object(sys, 'stdout', io.StringIO()), \
                    patch.object(host, 'offline_inputs', return_value=value), \
                    patch.object(host, 'pause_inputs', return_value=(b'fixture receipt', {'outputs': {'clock-pause.so': 'a' * 64}})), \
                    patch.object(host, 'load_hardware', return_value=(remote, {})), \
                    patch.object(host, 'module', side_effect=lambda name, *args: modules[name]):
                if mode == 'success': host.main()
                else:
                    with self.assertRaises((OSError, ValueError)): host.main()
            runner.execute.assert_called_once()
            self.assertEqual(clock.inspect.call_count, 2)
            capture = next((root / '.local/diagnostics').iterdir())
            if mode == 'success':
                self.assertTrue(json.loads((capture / 'host-summary.json').read_text())['remote_stage_removed'])
                expected = set((*cd.FILES, *dc.ADAPTERS, *cs.FILES, 'contract.json', *load('check-clock-boundary').OUTPUTS))
                self.assertEqual({v.args[0].rsplit('/', 1)[1] for v in sftp.remove.call_args_list}, expected)
                sftp.rmdir.assert_called_once_with('/tmp/gameshellneo-clock-boundary.12345678')
            else:
                self.assertFalse((capture / 'host-summary.json').exists())
                if mode != 'cleanup': client.open_sftp.assert_not_called()
                if mode != 'timeout': self.assertEqual((capture / 'kernel.ndjson').read_bytes(), raw)

    def test_success_cleans_only_owned_stage_after_independent_replay(self):
        self.run_host('success')

    def test_timeout_unterminated_failed_result_and_postflight_never_cleanup_or_relaunch(self):
        for mode in ('timeout', 'unterminated', 'incomplete', 'postflight', 'cleanup'):
            with self.subTest(mode=mode): self.run_host(mode)


class PauseAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.host = load('check-scheduled-clock')
        self.builder = self.host.module('build-scheduled-clock')
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        fake = []
        for scenario, status in enumerate(((0, 0), (-1, 4), (-1, 14), (0, 0))):
            value = pause_value(); value.update(scenario=scenario, rc=status[0], errno=status[1])
            if scenario == 1: value['remaining'] = struct.pack('<qq', 0, 30_000_000).hex()
            if scenario == 3: value['request_after'] = struct.pack('<qq', 0, 1).hex()
            fake.append(value)
        text = '\n'.join('NEO_PAUSE_FIXTURE ' + json.dumps(v) for v in fake) + '\npause fixtures passed:'
        success, interrupted = pause_value(), pause_value()
        success['mode'] = 'success'
        interrupted.update(mode='interrupted', rc=-1, errno=4, remaining=struct.pack('<qq', 0, 30_000_000).hex())
        real = 'NEO_PAUSE_REAL ' + json.dumps(success) + '\nNEO_PAUSE_REAL ' + json.dumps(interrupted)
        real += '\nARM production pause library passed:'
        for name in self.builder.INPUTS:
            target = self.root / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        for name in self.builder.OUTPUTS:
            (self.root / name).write_text(text if name.endswith('fixtures.txt') else real if name == 'arm-production.txt' else name)
        self.abi = dict(linux=lock['linux'], files={name: 'a' * 64 for name in self.builder.ABI_FILES},
                        syscall=407, clock=1, flags=0, timespec_bytes=16, relative_pause_ns=100_000_000)
        self.receipt = dict(schema=1, operation='clock-pause-build', complete=True, builder=lock['builder'],
            no_hardware_contact=True, inputs={name: dc.sha(self.root / name) for name in self.builder.INPUTS},
            outputs={name: dc.sha(self.root / name) for name in self.builder.OUTPUTS}, abi=self.abi,
            native_fixture_count=4, arm_fixture_count=4, production_calls=2,
            source_archive_sha256=lock['linux']['tarball_sha256'], managed_run='a' * 32,
            tests=['native-ubsan-error-buffers', 'arm-qemu-error-buffers',
                   'arm-production-relative-pause', 'arm-production-signal-eintr-no-retry'])
        self.identity = dict(stage='scheduled-clock-pause', run='a' * 32)
        self.result = dict(outcome='exited', exit_code=0, returncode=0, stop_requested=False,
            state=dict(Running=False, Status='exited', ExitCode=0, OOMKilled=False, Error=''))
        self.write_receipt(self.receipt)
        self.addCleanup(patch.stopall)
        patch.object(self.host, 'module', return_value=self.builder).start()
        patch.object(self.builder, 'abi_sources', side_effect=lambda *args: self.abi).start()
        patch.object(self.host, 'result_for', side_effect=lambda *args: (self.identity, self.result, self.root)).start()
        patch.object(self.host.subprocess, 'check_output', side_effect=self.elf).start()

    def elf(self, args, **kwargs):
        return 'syscall@@GLIBC_2.4' if args[-1].endswith('libc.elf') else '0 UND syscall@GLIBC_2.4'

    def write_receipt(self, value):
        (self.root / 'build-receipt.json').write_text(json.dumps(value))

    def observe(self):
        return self.host.pause_inputs(self.root, self.root, self.root)

    def test_complete_current_receipt_and_actual_owned_result_are_required(self):
        raw, value = self.observe()
        self.assertEqual(value, self.receipt)
        self.assertEqual(raw, (self.root / 'build-receipt.json').read_bytes())

    def test_empty_partial_extra_source_output_or_abi_map_is_refused(self):
        for role in ('inputs', 'outputs', 'abi-files'):
            for mode in ('empty', 'partial', 'extra'):
                value = copy.deepcopy(self.receipt)
                owner, key = (value['abi'], 'files') if role == 'abi-files' else (value, role)
                if mode == 'empty': owner[key] = {}
                elif mode == 'partial': owner[key].pop(next(iter(owner[key])))
                else: owner[key]['unexpected'] = 'a' * 64
                self.write_receipt(value)
                with self.subTest(role=role, mode=mode), self.assertRaises(ValueError): self.observe()

    def test_changed_snapshotted_input_or_built_output_is_refused(self):
        for name in ('tools/clock-pause.c', 'clock-pause.so'):
            target = self.root / name; original = target.read_bytes(); target.write_bytes(b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError): self.observe()
            target.write_bytes(original)

    def test_stopped_failed_running_oom_or_wrong_identity_is_never_admitted(self):
        for field, changed in (('stop_requested', True), ('outcome', 'stopped'), ('exit_code', 1)):
            before = self.result[field]; self.result[field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError): self.observe()
            self.result[field] = before
        for field, changed in (('Running', True), ('Status', 'running'), ('OOMKilled', True), ('Error', 'failed')):
            before = self.result['state'][field]; self.result['state'][field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError): self.observe()
            self.result['state'][field] = before
        for field, changed in (('run', 'b' * 32), ('stage', 'other')):
            before = self.identity[field]; self.identity[field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError): self.observe()
            self.identity[field] = before

    def test_clock_read_or_unsupported_libc_imports_refuse_new_library(self):
        for bad in ('0 UND syscall@GLIBC_9.0', '0 UND syscall@GLIBC_2.4\n0 UND clock_gettime@GLIBC_2.4'):
            with patch.object(self.host.subprocess, 'check_output', side_effect=lambda args, **kw:
                    'syscall@@GLIBC_2.4\nclock_gettime@@GLIBC_2.4' if args[-1].endswith('libc.elf') else bad):
                with self.subTest(symbols=bad), self.assertRaises(ValueError): self.observe()


if __name__ == '__main__':
    unittest.main()
