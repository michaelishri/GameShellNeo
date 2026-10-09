"""Runtime attribution must retain failed evidence and verify copied binaries."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recorder = load('clock_runtime_recorder', 'inspect-clock-runtime.py')
host = load('clock_runtime_host', 'check-clock-runtime.py')
report = load('clock_runtime_report', 'report-clock-runtime.py')


class RuntimeTests(unittest.TestCase):
    def test_offline_disassembly_rejects_unverified_input_before_container(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(report, 'LOCAL', Path(directory)), \
                patch.object(report.subprocess, 'run') as run:
            for value in ('', '../2026', '/tmp/clock', 'latest'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    report.verified_capture(value)
            capture = Path(directory) / 'diagnostics/20261009T230039.014366Z'
            capture.mkdir(parents=True)
            data = b'\x7fELF' + b'x'*32
            receipt = dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())
            (capture / 'inventory.json').write_text(json.dumps(dict(operation='clock-runtime-inventory',
                complete=True, files=dict(python=receipt, libc=receipt))))
            (capture / 'summary.json').write_text(json.dumps(dict(complete=True, binaries_verified=True)))
            for role in ('python', 'libc'):
                (capture / (role + '.elf')).write_bytes(data)
            self.assertEqual(report.verified_capture(capture.name), capture)
            (capture / 'libc.elf').write_bytes(data[:-1] + b'y')
            with self.assertRaisesRegex(ValueError, 'differs'):
                report.verified_capture(capture.name)
            run.assert_not_called()

    def test_mapping_identity_rejects_ambiguous_deleted_and_other_binaries(self):
        line = '1000-2000 r-xp 00000000 00:01 5 '
        mapped = line + '/usr/lib/arm-linux-gnueabihf/libc.so.6\n' + line + '[vdso]\n'
        files, vdso = recorder.binaries(mapped, '/usr/bin/python3.13')
        self.assertTrue(vdso)
        self.assertEqual(files['libc'], '/usr/lib/arm-linux-gnueabihf/libc.so.6')
        for bad in ('', mapped.replace('libc.so.6', 'libc.so.6 (deleted)'),
                    mapped + line + '/lib/arm-linux-gnueabihf/libc.so.6\n'):
            with self.subTest(maps=bad), self.assertRaises(ValueError):
                recorder.binaries(bad, '/usr/bin/python3.13')
        with self.assertRaises(ValueError):
            recorder.binaries(mapped, '/tmp/python3.13')

    def test_binary_transfer_rejects_short_changed_and_oversized_data(self):
        data = b'\x7fELF' + b'x' * 32
        receipt = dict(path='/usr/bin/python3.13', size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'python.elf'
            for content in (data[:-1], data + b'x', data[:-1] + b'y'):
                sftp = Mock(); sftp.open.return_value = io.BytesIO(content)
                with self.subTest(content=content), self.assertRaisesRegex(ValueError, 'differs'):
                    host.save_binary(sftp, receipt, target)
                self.assertTrue(target.exists())
                self.assertLessEqual(target.stat().st_size, receipt['size'] + 1)
            sftp = Mock(); sftp.open.return_value = io.BytesIO(data)
            host.save_binary(sftp, receipt, target)
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(recorder.binary_record(target)['sha256'], receipt['sha256'])

    def test_validation_rejects_changed_boot_environment_paths_and_incomplete_capture(self):
        files = {name: dict(path=path, size=123, sha256='a'*64) for name, path in (
            ('python', '/usr/bin/python3.13'), ('libc', '/usr/lib/arm-linux-gnueabihf/libc.so.6'))}
        value = dict(schema=1, operation='clock-runtime-inventory', complete=True, binaries_unchanged=True,
            boot_id='boot', after_boot_id='boot', kernel='kernel', machine='armv7l', time_module='built-in',
            vdso_mapped=True, files=files,
            loader_environment_present=dict(LD_PRELOAD=False, LD_AUDIT=False, LD_LIBRARY_PATH=False))
        state = Mock()
        with patch.object(host, 'load', return_value=SimpleNamespace(validate_state=state)):
            host.validate_inventory(value, dict(boot_id='boot', kernel='kernel'), {})
            state.assert_called_once()
            for change in ('boot', 'complete', 'library', 'loader', 'size', 'hash', 'changed'):
                bad = deepcopy(value)
                if change == 'boot': bad['after_boot_id'] = 'new'
                if change == 'complete': bad['complete'] = False
                if change == 'library': bad['files']['libc']['path'] = '/etc/shadow'
                if change == 'loader': bad['loader_environment_present']['LD_PRELOAD'] = True
                if change == 'size': bad['files']['libc']['size'] = 33*1024*1024
                if change == 'hash': bad['files']['libc']['sha256'] = 'missing'
                if change == 'changed': bad['binaries_unchanged'] = False
                with self.subTest(change=change), self.assertRaises(ValueError):
                    host.validate_inventory(bad, dict(boot_id='boot', kernel='kernel'), {})

    def test_failed_remote_inventory_preserves_output_and_runs_one_postflight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clock = SimpleNamespace(inspection_program=Mock(return_value='inspect source'),
                                    inspect=Mock(return_value={'pm': {'pm_test': '[none]'}}))
            pm = SimpleNamespace(wifi_proof=Mock())
            def module(name, filename):
                return clock if filename == 'check-clock-paths.py' else pm
            def remote(client, *args, **kwargs):
                if 'output' not in kwargs:
                    return b''
                kwargs['output'].write(b'Traceback: missing runtime configuration\n')
                raise RuntimeError('inventory failed')
            client = MagicMock()
            with patch.object(host, 'LOCAL', root), patch.object(host, 'evidence_directory', return_value=root), \
                    patch.object(host, 'load', side_effect=module), patch.object(host, 'load_env'), \
                    patch.object(host, 'device', return_value=client), patch.object(host, 'run', side_effect=remote) as run, \
                    patch.object(host.subprocess, 'run') as readelf, self.assertRaisesRegex(RuntimeError, 'inventory failed'):
                host.main()
            self.assertEqual(run.call_count, 2)
            self.assertEqual([c.args[-1] for c in clock.inspect.call_args_list], ['before', 'after'])
            self.assertIn(b'missing runtime configuration', (root / 'inventory-output.txt').read_bytes())
            self.assertFalse((root / 'summary.json').exists())
            client.__enter__.return_value.open_sftp.assert_not_called()
            pm.wifi_proof.assert_not_called()
            readelf.assert_not_called()


if __name__ == '__main__':
    unittest.main()
