"""Admission must precede arming; failures must retain original evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import clock_boundary as cb
import clock_deployment as cd
from test_clock_boundary import fixture

SPEC = importlib.util.spec_from_file_location('clock_boundary_host', ROOT / 'tools/check-clock-boundary.py')
HOST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOST)


def contract():
    return dict(schema=1, operation='clock-boundary-contract', boot_id='a' * 8 + '-1111-2222-3333-' + 'b' * 12,
                kernel='6.18.54-gameshellneo-test', build_id='ab' * 20, image_sha256='c' * 64,
                config_sha256='d' * 64, time_namespaces=True, source_id=1,
                files={name: 'e' * 64 for name in cd.FILES},
                runtime=dict(python=dict(path='/usr/bin/python3.13', size=100, sha256='a' * 64),
                             libc=dict(path='/lib/arm-linux-gnueabihf/libc.so.6', size=200, sha256='b' * 64)))


def snapshot(c=None):
    c = c or contract()
    return {key: copy.deepcopy(c[key]) for key in
            ('boot_id', 'kernel', 'build_id', 'image_sha256', 'config_sha256', 'files', 'runtime')} | dict(
        clocksource='arch_sys_counter', vdso=cd.VDSO.copy(),
        platform=dict(machine='armv7l', byteorder='little', pointer_bytes=4, long_bytes=4,
                      isolated=1, no_site=1, uid=0), loader_environment=[], preload_configured=False,
        tracing=False, taint='0', tid=42, tgid=42, nspid=[42], nstgid=[42], task_ids=[42],
        namespace_id=99, affinity=[0, 1, 2, 3], pm_test='[none] freezer devices platform', pm_units='',
        pm_stats=dict(success='53', fail='0'), usb=['configured'], usb_power=dict(present='1', online='1'),
        services={name: dict(ActiveState='active', NRestarts='1' if 'battery' in name else '0')
                  for name in cd.SERVICES})


def records():
    kernel, users = fixture()
    users['context']['source_id'] = cd.SOURCE_ID
    for k in kernel[1:]:
        for name in ('mono', 'raw'):
            k['tuple'][name]['source_id'] = cd.SOURCE_ID
    raw = ''.join(json.dumps(k) + '\n' for k in kernel).encode()
    return users, raw


class AdmissionTests(unittest.TestCase):
    def test_valid_context_preserves_existing_fault_count(self):
        cd.validate_snapshot(snapshot(), contract())
        self.assertEqual(cd.context(snapshot()), records()[0]['context'])

    def test_mutations_rejected_before_device_capture(self):
        mutations = [('boot_id', '0' * 36), ('kernel', 'other'), ('build_id', 'cd' * 20),
            ('image_sha256', 'f' * 64), ('config_sha256', 'f' * 64), ('clocksource', 'other'),
            ('vdso', dict(cd.VDSO, time32_exported=1)), ('loader_environment', ['LD_PRELOAD']),
            ('preload_configured', True), ('tracing', True), ('taint', '1'), ('tid', 43),
            ('namespace_id', 0), ('affinity', [0, 4]), ('task_ids', [42, 43]), ('nspid', [22, 42]),
            ('pm_units', 'another PM test'), ('usb', ['not attached']), ('services', {}),
            ('usb_power', dict(present='0', online='0')), ('pm_test', 'none [devices]'), ('pm_stats', {})]
        for key, value in mutations:
            s = snapshot(); s[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                cd.validate_snapshot(s, contract())
        for section, key, value in [('platform', 'long_bytes', 8), ('files', 'clock-boundary.so', 'f' * 64),
                                    ('runtime', 'libc', {})]:
            s = snapshot(); s[section][key] = value
            with self.subTest(section=section), self.assertRaises(ValueError):
                cd.validate_snapshot(s, contract())

    def test_build_id_requires_one_complete_gnu_note(self):
        def note(name, value, kind=3):
            return (struct.pack('<III', len(name), len(value), kind) + name + b'\0' * (-len(name) % 4) +
                    value + b'\0' * (-len(value) % 4))
        value = bytes.fromhex(contract()['build_id'])
        raw = note(b'Linux\0', b'ignored', 1) + note(b'GNU\0', value)
        self.assertEqual(cd.build_id(raw), value.hex())
        for bad in (b'', raw[:-1], raw + b'\0', raw + note(b'GNU\0', value), note(b'GNU\0', b'bad')):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                cd.build_id(bad)

    def test_configuration_requires_real_hooks_and_no_test_counter(self):
        keys = ('NEO_CLOCK_DIAG', 'DEBUG_FS', 'ARM_ARCH_TIMER', 'IKCONFIG', 'IKCONFIG_PROC', 'ARM', 'AEABI')
        raw = ''.join('CONFIG_' + key + '=y\n' for key in keys).encode()
        self.assertEqual(cd.configuration(raw)['CONFIG_NEO_CLOCK_DIAG'], 'y')
        for bad in (raw.replace(b'CONFIG_NEO_CLOCK_DIAG=y', b'# CONFIG_NEO_CLOCK_DIAG is not set'),
                    raw + b'CONFIG_NEO_CLOCK_DIAG_KUNIT_TEST=y\n'):
            with self.assertRaises(ValueError):
                cd.configuration(bad)

    def test_staged_hashes_checked_and_originals_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            c = contract()
            for name in cd.FILES:
                data = name.encode()
                (Path(d) / name).write_bytes(data)
                c['files'][name] = cd.digest(data)
            cd.validate_files(d, c)
            (Path(d) / cd.FILES[0]).write_bytes(b'changed')
            with self.assertRaises(ValueError):
                cd.validate_files(d, c)
            cd.save(d, 'original.json', {'value': 1})
            with self.assertRaises(FileExistsError):
                cd.save(d, 'original.json', {'value': 2})
            self.assertEqual(json.loads((Path(d) / 'original.json').read_text()), {'value': 1})


class PersistenceTests(unittest.TestCase):
    def run_capture(self, d, before=None, after=None, raw=None):
        users, kernel = records()
        observe = Mock(side_effect=[before or snapshot(), after or snapshot()])
        opening = Mock(return_value=Mock(spec=['close']))
        with patch.object(cb, 'collect', return_value=(users, kernel if raw is None else raw)) as collect:
            result = cd.execute(d, contract(), observe, None, {}, opening)
        return result, opening, collect, kernel

    def test_success_replays_original_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            result, opening, collect, kernel = self.run_capture(d)
            self.assertTrue(result['complete'])
            self.assertFalse(result['pm_admission'])
            opening.assert_called_once(); collect.assert_called_once()
            self.assertEqual((Path(d) / 'kernel.ndjson').read_bytes(), kernel)

    def test_bad_preflight_never_opens_or_arms(self):
        with tempfile.TemporaryDirectory() as d:
            before = snapshot(); before['build_id'] = '11' * 20
            result, opening, collect, _ = self.run_capture(d, before=before)
            self.assertFalse(result['complete'])
            self.assertEqual(result['errors'][0]['stage'], 'preflight')
            opening.assert_not_called(); collect.assert_not_called()
            self.assertFalse((Path(d) / 'kernel.ndjson').exists())

    def test_preallocation_failure_still_closes_owned_descriptor(self):
        with tempfile.TemporaryDirectory() as d:
            control = Mock(spec=['close'])
            with patch.object(cb, 'collect', side_effect=MemoryError('allocation')):
                result = cd.execute(d, contract(), snapshot, None, {}, lambda: control)
            control.close.assert_called_once()
            self.assertFalse(result['complete'])
            self.assertEqual(result['errors'][0]['type'], 'MemoryError')

    def test_changed_postflight_does_not_destroy_capture(self):
        with tempfile.TemporaryDirectory() as d:
            after = snapshot(); after['pm_stats']['success'] = '54'
            result, _, collect, kernel = self.run_capture(d, after=after)
            self.assertFalse(result['complete'])
            self.assertEqual(result['errors'][0]['stage'], 'postflight')
            collect.assert_called_once()
            self.assertEqual((Path(d) / 'kernel.ndjson').read_bytes(), kernel)
            self.assertTrue((Path(d) / 'users.json').exists())

    def test_corrupt_export_saved_before_replay_failure(self):
        with tempfile.TemporaryDirectory() as d:
            raw = b'original broken JSON\n'
            result, _, _, _ = self.run_capture(d, raw=raw)
            self.assertFalse(result['complete'])
            self.assertEqual(result['errors'][0]['stage'], 'replay')
            self.assertEqual((Path(d) / 'kernel.ndjson').read_bytes(), raw)


def unit(active='active', sub='running', pid='42', result='success', status='0', code='0'):
    return dict(LoadState='loaded', ActiveState=active, SubState=sub, MainPID=pid, ControlPID='0',
                Result=result, ExecMainStatus=status, ExecMainCode=code)


class SupervisionTests(unittest.TestCase):
    def supervise(self, states, ticks=(0, 1), launch_error=None):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(HOST, 'run', side_effect=[launch_error, b''] if launch_error else None) as run:
                with patch.object(HOST, 'unit_state', side_effect=states):
                    result = HOST.supervise(None, 'owned.service', '/tmp/owned', Path(d),
                                            now=Mock(side_effect=ticks), pause=Mock())
            self.assertEqual(json.loads((Path(d) / 'unit.json').read_text()), result)
            commands = [c.args[1] for c in run.call_args_list]
        return result, commands

    def test_completion_captures_exit_before_retiring_unit(self):
        result, commands = self.supervise([unit(), unit(sub='exited', pid='0', code='1'),
                                            unit(active='inactive', sub='dead', pid='0', code='1')])
        self.assertTrue(result['terminal'])
        self.assertTrue(result['execution_succeeded'])
        self.assertIsNone(result['error'])
        self.assertEqual(len(commands), 2)
        self.assertIn('systemd-run', commands[0]); self.assertIn('-I -S -B', commands[0])
        self.assertEqual(commands[1], 'sudo -n systemctl stop owned.service')

    def test_host_deadline_stops_once_and_retains_failure(self):
        result, commands = self.supervise([unit(), unit(active='failed', sub='failed', pid='0')], ticks=(0, 61))
        self.assertTrue(result['terminal'])
        self.assertFalse(result['execution_succeeded'])
        self.assertEqual(result['error']['type'], 'TimeoutError')
        self.assertEqual(len(commands), 2)

    def test_lost_launch_ack_stops_original_unit_without_relaunch(self):
        result, commands = self.supervise([unit(active='inactive', sub='dead', pid='0')],
                                          ticks=(0,), launch_error=TimeoutError('ack lost'))
        self.assertTrue(result['terminal'])
        self.assertFalse(result['execution_succeeded'])
        self.assertEqual(sum('systemd-run' in c for c in commands), 1)
        self.assertEqual(commands[-1], 'sudo -n systemctl stop owned.service')

    def test_stop_does_not_prove_termination_or_erase_failure(self):
        result, _ = self.supervise([unit(), unit()], ticks=(0, 61))
        self.assertFalse(result['terminal'])
        result, _ = self.supervise([unit(active='failed', sub='failed', pid='0', result='exit-code', status='1', code='1'),
                                   unit(active='inactive', sub='dead', pid='0', code='1')], ticks=(0,))
        self.assertTrue(result['terminal'])
        self.assertFalse(result['execution_succeeded'])


class HostInputsTests(unittest.TestCase):
    def setup_inputs(self, root):
        local = root / '.local'
        build = local / 'diagnostics/build'
        runtime = local / 'diagnostics/runtime'
        artifacts = local / 'artifacts'
        for d in (build, runtime, artifacts, local / 'build/kernel'):
            d.mkdir(parents=True)
        lock = dict(builder={'image': 'pinned'}, experiments={'clock_provenance': True},
                    linux=dict(tag='v6.18.54', localversion='-gameshellneo-test'), image_version='test')
        names = ['tools/clock-boundary.c', 'tools/clock_boundary.py', 'tools/clock_provenance.py',
            'tools/clock_deployment.py', 'tools/capture-clock-boundary.py', 'tools/build-clock-boundary.py',
            'tools/check-clock-paths.py', 'build/sources.lock.json']
        hashes = {}
        for name in names:
            data = json.dumps(lock).encode() if name.endswith('lock.json') else name.encode()
            for directory in (root, build):
                p = directory / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            hashes[name] = cd.digest(data)
        outputs = ('clock-boundary.so', 'test-host', 'test-arm', 'reader-readelf.txt',
                   'reader-disassembly.txt', 'build.sh', 'build-output.txt', 'host-fixtures.txt', 'arm-fixtures.txt')
        for name in outputs:
            (build / name).write_bytes(name.encode())
        receipt = dict(schema=1, operation='clock-boundary-build', complete=True,
            builder=lock['builder'], abi={'linux': lock['linux']}, inputs=hashes,
            outputs={name: cd.digest(name.encode()) for name in outputs}, arm_raw_buffer_fixtures=27,
            tests=['host-ubsan-fixtures', 'arm-qemu-fixtures', 'arm-production-layout-assertions'])
        (build / 'build-receipt.json').write_text(json.dumps(receipt))
        (runtime / 'inventory.json').write_text(json.dumps({'files': contract()['runtime']}))
        config = ''.join('CONFIG_' + k + '=y\n' for k in (
            'NEO_CLOCK_DIAG', 'DEBUG_FS', 'ARM_ARCH_TIMER', 'IKCONFIG', 'IKCONFIG_PROC', 'ARM', 'AEABI', 'TIME_NS')).encode()
        (artifacts / 'kernel.config').write_bytes(config)
        kernel = dict(files={'.local/build/kernel/.config': cd.digest(config)}, patches={})
        for path in (artifacts / 'kernel-completed.json', local / 'build/kernel-completed.json'):
            path.write_text(json.dumps(kernel))
        image = dict(sources=lock, version='test', kernel=contract()['kernel'], project_inputs_sha256=hashes)
        (artifacts / 'image-manifest.json').write_text(json.dumps(image))
        payload = b'test-image'
        digest = cd.digest(payload)
        image_name = 'GameShellNeo-test-cpi31-' + digest[:12] + '.img'
        (artifacts / image_name).write_bytes(payload)
        (artifacts / 'verification.json').write_text(json.dumps(dict(image=image_name,
            offline_verification='passed', bytes=len(payload), sha256=digest)))
        modules = {'check-native-clocks': SimpleNamespace(capture_path=lambda name: build),
            'report-clock-runtime': SimpleNamespace(verified_capture=lambda name: runtime),
            'build-clock-boundary': SimpleNamespace(verify_elf=Mock(), verify_arm_fixture=Mock()),
            'build-native-clocks': SimpleNamespace(symbols=lambda text: {('clock', 'GLIBC_2.34')}),
            'kernel-artifacts': SimpleNamespace(inventory=lambda: kernel)}
        return local, build, artifacts, modules

    def verify(self, root, local, modules):
        with patch.object(HOST, 'ROOT', root), patch.object(HOST, 'LOCAL', local), \
                patch.object(HOST, 'module', side_effect=modules.__getitem__), \
                patch.object(HOST.subprocess, 'check_output', return_value='Build ID: ' + 'ab' * 20):
            return HOST.verified_inputs('build', 'runtime')

    def test_matching_inputs_generate_contract_then_need_fresh_boot_id(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            local, build, _, modules = self.setup_inputs(root)
            directory, c = self.verify(root, local, modules)
            self.assertEqual(directory, build)
            self.assertIsNone(c['boot_id'])
            c['boot_id'] = contract()['boot_id']
            cd.validate_contract(c)
            modules['build-clock-boundary'].verify_arm_fixture.assert_called_once()

    def test_stale_build_image_or_kernel_never_admitted(self):
        for changed in ('library', 'source', 'unqualified-config', 'image-inputs', 'kernel-receipt', 'raw-image'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                local, build, artifacts, modules = self.setup_inputs(root)
                if changed == 'library':
                    (build / 'clock-boundary.so').write_bytes(b'changed')
                elif changed == 'source':
                    (root / 'tools/clock_deployment.py').write_bytes(b'changed')
                elif changed == 'unqualified-config':
                    p = artifacts / 'kernel.config'
                    p.write_bytes(p.read_bytes().replace(b'CONFIG_NEO_CLOCK_DIAG=y', b'# CONFIG_NEO_CLOCK_DIAG is not set'))
                elif changed == 'image-inputs':
                    p = artifacts / 'image-manifest.json'
                    v = json.loads(p.read_text()); v['project_inputs_sha256'].pop('tools/clock_boundary.py')
                    p.write_text(json.dumps(v))
                elif changed == 'kernel-receipt':
                    (local / 'build/kernel-completed.json').write_text('{}')
                else:
                    next(artifacts.glob('*.img')).write_bytes(b'changed')
                with self.assertRaises(ValueError):
                    self.verify(root, local, modules)

    def test_offline_rejection_does_not_contact_device(self):
        with patch.object(HOST, 'verified_inputs', side_effect=ValueError('old image')), \
                patch.object(HOST, 'device') as device:
            with self.assertRaises(ValueError):
                HOST.main()
        device.assert_not_called()


if __name__ == '__main__':
    unittest.main()
