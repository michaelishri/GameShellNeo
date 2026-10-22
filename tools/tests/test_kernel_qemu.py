"""Repository pinning and actual QMP reply acceptance for the SMP environment."""
import copy
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import kernel_qemu as qemu


class KernelQemuTests(unittest.TestCase):
    def test_snapshot_inputs_reject_unpinned_base_or_repository(self):
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        files = qemu.inputs(lock)
        self.assertIn(lock['builder']['image'], files['Dockerfile'])
        self.assertEqual(json.loads(files['releases.json']), {
            'trixie': lock['debian']['inrelease_sha256'],
            'trixie-security': lock['debian']['security_inrelease_sha256']})
        for section, field, value in [('builder', 'image', 'debian:latest'),
                                       ('builder', 'platform', 'linux/arm64'),
                                       ('debian', 'snapshot', 'latest'),
                                       ('debian', 'inrelease_sha256', '')]:
            changed = copy.deepcopy(lock)
            changed[section][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                qemu.inputs(changed)

    def test_qmp_requires_two_cpus_and_normal_ordered_exit(self):
        records = [{'QMP': {'version': {}}}, {'return': {}, 'id': 'capabilities'},
                   {'return': [{'cpu-index': i, 'thread-id': i + 1, 'qom-path': '/cpu/' + str(i), 'target': 'arm'}
                               for i in range(2)], 'id': 'cpus'},
                   {'event': 'SHUTDOWN'}, {'return': {}, 'id': 'quit'}]
        encode = lambda r: '\n'.join(json.dumps(x) for x in r)
        self.assertEqual(len(qemu.checked_qmp(encode(records))), 2)
        for kind in ('one_cpu', 'duplicate_cpu', 'wrong_type', 'no_quit', 'qmp_error', 'reordered',
                     'wrong_target', 'one_thread'):
            changed = copy.deepcopy(records)
            if kind == 'one_cpu':
                changed[2]['return'].pop()
            elif kind == 'duplicate_cpu':
                changed[2]['return'][1]['cpu-index'] = 0
            elif kind == 'wrong_type':
                changed[2]['return'][1]['cpu-index'] = True
            elif kind == 'wrong_target':
                changed[2]['return'][1]['target'] = 'x86_64'
            elif kind == 'one_thread':
                changed[2]['return'][1]['thread-id'] = 1
            elif kind == 'no_quit':
                changed.pop()
            elif kind == 'qmp_error':
                changed[2] = {'error': {'desc': 'failed'}, 'id': 'cpus'}
            else:
                changed[1], changed[2] = changed[2], changed[1]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                qemu.checked_qmp(encode(changed))

    def test_smoke_uses_a_managed_foreground_pipe_and_preserves_failure(self):
        def run(stage, arguments, destination, *, timeout):
            self.assertEqual(stage, 'qemu-smoke')
            self.assertNotIn('-i', arguments)
            self.assertNotIn('--name', arguments)
            self.assertIn('--read-only', arguments)
            self.assertIn('--network=none', arguments)
            self.assertIn('--entrypoint=python3', arguments)
            client = arguments[-2]
            self.assertIn('timeout=25', client)
            self.assertEqual([json.loads(line)['id'] for line in arguments[-1].splitlines()],
                             ['capabilities', 'cpus', 'quit'])
            raise subprocess.TimeoutExpired(arguments, timeout)
        with tempfile.TemporaryDirectory() as directory, patch.object(qemu, 'run_managed', side_effect=run):
            with self.assertRaises(subprocess.TimeoutExpired):
                qemu.smoke('sha256:' + 'a' * 64, Path(directory))
            self.assertEqual(json.loads((Path(directory) / 'smoke-error.json').read_text())['type'],
                             'TimeoutExpired')


if __name__ == '__main__':
    unittest.main()
