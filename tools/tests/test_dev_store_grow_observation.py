"""A stale, unexecuted, running or failed unit must never qualify disk writes."""
import contextlib
import ast
import base64
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
import zlib

SPEC = importlib.util.spec_from_file_location('grow_host_observation',
    Path(__file__).resolve().parents[1] / 'grow-dev-store.py')
HOST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOST)
TOKEN = '1' * 32
BOOT = '926d517d-1a83-43d6-8702-1a83008025b5'


class GrowthObservation(unittest.TestCase):
    def setUp(self):
        self.planned = {'id': TOKEN, 'unit': 'gameshellneo-store-grow-' + TOKEN,
                        'remote_directory': '/var/lib/gameshellneo/development-store-growth-' + TOKEN,
                        'boot_id': BOOT}
        self.worker = {'operation': 'development-store-growth', 'completed': True,
                       'write_started': True, 'admission': {'boot_id': BOOT}}
        self.observation = {'boot_id': BOOT, 'unit': self.planned['unit'],
            'properties': {'Id': self.planned['unit'] + '.service', 'LoadState': 'loaded',
                           'ActiveState': 'active', 'SubState': 'exited', 'MainPID': '0',
                           'ExecMainPID': '123', 'ExecMainCode': '1', 'ExecMainStatus': '0',
                           'ExecMainStartTimestamp': 'Thu 2026-10-22 08:00:00 UTC',
                           'Result': 'success', 'Job': ''}, 'files': {}}

    def observe(self, observation=None, worker=None):
        observed = deepcopy(self.observation if observation is None else observation)
        if worker is not False:
            observed['files']['operation/state.json'] = {'text': json.dumps(
                self.worker if worker is None else worker)}
        remote = SimpleNamespace(device=lambda *args: contextlib.nullcontext(object()),
                                 python_command=lambda *args: {},
                                 run=lambda *args, **kwargs: json.dumps(observed))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'planned.json').write_text(json.dumps(self.planned))
            with contextlib.redirect_stdout(io.StringIO()):
                code = HOST.observe(remote, {}, directory)
            receipts = list(directory.glob('observation-*.json'))
            self.assertEqual(len(receipts), 1)
            return code, json.loads(receipts[0].read_text())

    def test_original_loaded_executed_exited_worker_can_qualify(self):
        code, receipt = self.observe()
        self.assertEqual(code, 0)
        self.assertTrue(receipt['accepted_success'])

    def test_stale_or_nonexecuted_units_cannot_qualify(self):
        for field, value in [('LoadState', 'not-found'), ('ExecMainPID', '0'),
                             ('ExecMainStartTimestamp', ''), ('MainPID', '123'), ('Job', '9'),
                             ('ExecMainCode', '2'), ('ExecMainStatus', '1'), ('Result', 'exit-code')]:
            with self.subTest(field=field, value=value):
                observation = deepcopy(self.observation)
                observation['properties'][field] = value
                code, receipt = self.observe(observation)
                self.assertNotEqual(code, 0)
                self.assertFalse(receipt['accepted_success'])

    def test_matching_boot_and_exact_unit_are_required(self):
        for target in ('boot', 'unit'):
            with self.subTest(target=target):
                observation = deepcopy(self.observation)
                if target == 'boot':
                    observation['boot_id'] = '840a8868-c8ef-48bd-b051-32dc979c14da'
                else:
                    observation['properties']['Id'] = 'a-different-unit.service'
                self.assertNotEqual(self.observe(observation)[0], 0)

    def test_worker_must_be_original_growth_and_complete(self):
        variants = [False, dict(self.worker, completed=False), dict(self.worker, write_started=False),
                    dict(self.worker, operation='development-store-install'),
                    dict(self.worker, admission={'boot_id': '840a8868-c8ef-48bd-b051-32dc979c14da'})]
        for worker in variants:
            with self.subTest(worker=worker):
                self.assertNotEqual(self.observe(worker=worker)[0], 0)

    def test_retained_submission_cannot_redirect_unit_or_evidence(self):
        for field, value in [('id', 'x' * 32), ('unit', 'another.service'),
                             ('remote_directory', '/etc'), ('boot_id', '-' * 36)]:
            with self.subTest(field=field):
                with self.assertRaises((ValueError, TypeError, AttributeError)):
                    HOST.validate_submission(dict(self.planned, **{field: value}))

    def test_missing_or_symlink_receipts_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            with self.assertRaises(ValueError):
                HOST.read_json(path / 'missing')
            (path / 'real').write_text('{}')
            (path / 'alias').symlink_to(path / 'real')
            with self.assertRaises(ValueError):
                HOST.read_json(path / 'alias')


class GrowthSubmission(unittest.TestCase):
    def test_large_receipt_and_sources_are_literal_stdin_data(self):
        # This realistic receipt exceeds Linux's per-argument bound even before
        # its staged sources are included. No remote program is executed here.
        payload = {'backup': {'store_files': {
            'systems/diag27/root/etc/setting-' + str(index): 'a' * 64
            for index in range(2500)}},
            'sources': {'worker.py': {'base64': 'b' * 120000}},
            'literal': "quotes' and $(commands) `stay data`\n"}
        self.assertGreater(len(json.dumps(payload).encode()), 131072)
        source = HOST.submission_source(payload)
        program = ast.parse(source)
        packed = ast.literal_eval(program.body[1].value)
        self.assertEqual(json.loads(zlib.decompress(base64.b64decode(packed))), payload)
        self.assertEqual(program.body[1].targets[0].id, 'PAYLOAD_B64')
        self.assertIn('v=PAYLOAD;', source)
        self.assertNotIn('v=json.loads(sys.argv[1])', source)
        self.assertLess(len(source.encode()), 1024 * 1024)

    def test_transport_bound_is_checked_before_submission(self):
        with self.assertRaisesRegex(ValueError, 'SSH stdin helper bound'):
            HOST.submission_source({'oversized': random.Random(1).randbytes(2 * 1024 * 1024).hex()})


if __name__ == '__main__':
    unittest.main()
