"""Malformed collection replies never cause a second sleep or relaxed evidence."""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_sleep_chain as chain

host = chain.host
TOKEN = 'a' * 32
CLOCK = dict(boot_id='12345678-1234-1234-1234-123456789abc', boottime_ns=100)
BAD = b'{"result":{"journal":"private fixture text'


def reply(result):
    return json.dumps(dict(result=result, clock=CLOCK)).encode()


class ReplyEvidence(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(host, 'device', return_value=nullcontext('client')))

    def malformed(self, raw=BAD):
        with patch.object(host, 'run', return_value=raw), self.assertRaises(host.MalformedReply) as caught:
            host.collect({}, TOKEN, 'wifi')
        return caught.exception

    def test_invalid_json_and_encoding_preserve_exact_bytes_without_payload_in_error(self):
        for raw, kind in ((BAD, 'json'), (b'', 'json'), (b'\xffprivate fixture text', 'encoding')):
            with self.subTest(kind=kind, raw=raw):
                error = self.malformed(raw)
                self.assertEqual(error.raw, raw)
                self.assertEqual(error.kind, kind)
                self.assertNotIn('private fixture text', str(error))
                host.save_bad_reply(self.root, error, TOKEN, 'wifi')
        rows = [json.loads(line) for line in (self.root/'collection-bad-replies.jsonl').read_text().splitlines()]
        for row, raw in zip(rows, (BAD, b'', b'\xffprivate fixture text')):
            self.assertEqual((self.root/row['saved_file']).read_bytes(), raw)
            self.assertEqual(row['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(row['received_bytes'], len(raw))
            self.assertFalse(row['truncated'])
        self.assertFalse((self.root/'result.json').exists())

    def test_capture_is_private_bounded_and_never_overwrites_earlier_bytes(self):
        raw = b'"' + b'x' * (host.MAX_BAD_REPLY_BYTES + 17)
        error = self.malformed(raw)
        old_umask = os.umask(0)
        try:
            for _ in range(host.MAX_BAD_REPLY_FILES + 1):
                host.save_bad_reply(self.root, error, TOKEN, 'wifi')
        finally:
            os.umask(old_umask)
        files = sorted(self.root.glob('collection-bad-reply-*.bin'))
        self.assertEqual(len(files), host.MAX_BAD_REPLY_FILES)
        for path in files:
            self.assertEqual(path.read_bytes(), raw[:host.MAX_BAD_REPLY_BYTES])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        metadata = self.root/'collection-bad-replies.jsonl'
        self.assertEqual(stat.S_IMODE(metadata.stat().st_mode), 0o600)
        rows = [json.loads(line) for line in metadata.read_text().splitlines()]
        self.assertTrue(all(row['truncated'] for row in rows))
        self.assertIsNone(rows[-1]['saved_file'])
        self.assertEqual(rows[-1]['saved_bytes'], 0)
        self.assertTrue(all(row['sha256'] == hashlib.sha256(raw).hexdigest() for row in rows))

    def test_decoded_protocol_and_clock_errors_are_fatal_not_malformed_replies(self):
        good = dict(result=dict(run_id=TOKEN, event='complete'), clock=CLOCK)
        invalid = [[], {}, {**good, 'result': []}, {**good, 'extra': 1},
                   {**good, 'result': dict(run_id='b'*32, event='complete')},
                   {**good, 'result': dict(run_id=TOKEN, event='unknown')},
                   {**good, 'clock': {**CLOCK, 'boottime_ns': -1}}]
        for envelope in invalid:
            with self.subTest(envelope=envelope), patch.object(host, 'run', return_value=json.dumps(envelope).encode()):
                with self.assertRaises(ValueError) as caught:
                    host.collect({}, TOKEN, 'wifi')
                self.assertNotIsInstance(caught.exception, host.MalformedReply)

    def test_manual_collection_saves_bad_reply_and_fails_without_submission(self):
        with patch.object(host, 'LOCAL', self.root), \
                patch.object(host, 'evidence_directory', return_value=self.root), \
                patch.object(host, 'load_env', return_value={}), \
                patch.object(host, 'run', return_value=BAD) as run, \
                patch.object(host, 'service') as service, patch.object(host, 'upload') as upload, \
                patch.object(host, 'experiment') as experiment, \
                patch.dict(os.environ, NEO_PM_RUN=TOKEN, NEO_SLEEP_COLLECT_ROUTE='wifi',
                           NEO_SLEEP_ALARM_SECONDS='30'), \
                patch.object(sys, 'argv', ['check', '--collect']), \
                self.assertRaisesRegex(ValueError, 'Collect original RUN='+TOKEN):
            host.main()
        run.assert_called_once()
        service.assert_not_called(); upload.assert_not_called(); experiment.assert_not_called()
        self.assertEqual((self.root/'collection-bad-reply-1.bin').read_bytes(), BAD)
        self.assertFalse((self.root/'result.json').exists())
        self.assertFalse((self.root/'collection.json').exists())


class CollectionLoop(unittest.TestCase):
    def setUp(self):
        # Reuse admission/transport fixtures, but exercise real collect()/decode.
        chain.Transport.setUp(self)
        self.responses = iter(())
        self.retrievals = []
        remote = host.run.side_effect
        def run(client, command, **kwargs):
            if '/var/lib/gameshellneo/sleep-tests/' in command:
                self.assertIn('/var/lib/gameshellneo/sleep-tests/'+self.token, command)
                self.retrievals.append(command)
                return next(self.responses)
            return remote(client, command, **kwargs)
        host.run.side_effect = run
        self.stdout = self.enterContext(patch.object(sys, 'stdout', new_callable=io.StringIO))

    def attempt(self):
        return host.experiment({}, self.root, self.root/'qualification', 'rtc-wake',
                               chain.REHEARSAL, connection='battery', seconds=60)

    def test_malformed_then_started_then_complete_retrieves_same_run_and_submits_once(self):
        original = deepcopy(self.complete)
        self.responses = iter([BAD, reply(dict(run_id=TOKEN, event='started')), reply(original)])
        result = self.attempt()
        self.assertEqual(len(self.submissions), 1)
        self.assertEqual(len(self.retrievals), 3)
        self.assertEqual((self.root/'collection-bad-reply-1.bin').read_bytes(), BAD)
        self.assertFalse(result['usb_ssh_verified'])
        self.assertTrue(result['wifi_ssh_verified'])
        self.assertEqual({k: v for k, v in result.items() if not k.endswith('_ssh_verified')}, original)
        self.assertEqual(self.helper.wifi_proof.call_count, 2)  # Before and after validation.
        self.assertNotIn('private fixture text', self.stdout.getvalue())

    def test_repeated_bad_replies_use_original_deadline_and_preserve_last_good_record(self):
        started = dict(run_id=TOKEN, event='started')
        self.responses = iter([reply(started), BAD, b'\xff'])
        with patch.object(host.time, 'monotonic', side_effect=[0, 0, 1, 2, 240]), \
                self.assertRaisesRegex(TimeoutError, 'Do not retry sleep'):
            self.attempt()
        self.assertEqual(len(self.submissions), 1)
        self.assertEqual(len(self.retrievals), 3)
        self.assertEqual(json.loads((self.root/'result.json').read_text()), started)
        self.assertEqual(json.loads((self.root/'run.json').read_text())['budgets']['collection_seconds'], 240)
        host.validate_result.assert_not_called()
        self.assertEqual(self.helper.wifi_proof.call_count, 1)
        self.assertFalse((self.root/'qualification-next.json').exists())

    def test_wrong_identity_stops_before_further_retrieval_or_proofs(self):
        self.responses = iter([BAD, reply(dict(run_id='b'*32, event='complete')), reply(self.complete)])
        with self.assertRaisesRegex(ValueError, 'another run'):
            self.attempt()
        self.assertEqual(len(self.submissions), 1)
        self.assertEqual(len(self.retrievals), 2)
        host.validate_result.assert_not_called()
        self.assertEqual(self.helper.wifi_proof.call_count, 1)
        self.assertFalse((self.root/'result.json').exists())

    def test_completed_evidence_validation_failure_stops_without_route_proofs(self):
        self.responses = iter([BAD, reply(self.complete)])
        host.validate_result.side_effect = ValueError('source or restoration mismatch')
        with self.assertRaisesRegex(ValueError, 'restoration mismatch'):
            self.attempt()
        self.assertEqual(len(self.submissions), 1)
        self.assertEqual(len(self.retrievals), 2)
        self.assertEqual(json.loads((self.root/'result.json').read_text()), self.complete)
        self.assertEqual(self.helper.wifi_proof.call_count, 1)

    def test_failed_wifi_proof_preserves_unqualified_original_after_bad_reply(self):
        self.responses = iter([BAD, reply(self.complete)])
        self.helper.wifi_proof.side_effect = [None, ValueError('Wi-Fi proof failed')]
        with self.assertRaisesRegex(ValueError, 'Wi-Fi proof'):
            self.attempt()
        self.assertEqual(len(self.submissions), 1)
        self.assertEqual(json.loads((self.root/'result.json').read_text()), self.complete)

    def test_failure_to_preserve_bad_reply_stops_without_resubmission(self):
        self.responses = iter([BAD, reply(self.complete)])
        with patch.object(host, 'save_bad_reply', side_effect=OSError('disk full')), \
                self.assertRaisesRegex(OSError, 'disk full'):
            self.attempt()
        self.assertEqual(len(self.submissions), 1)
        self.assertEqual(len(self.retrievals), 1)
        host.validate_result.assert_not_called()
        self.assertFalse((self.root/'result.json').exists())


if __name__ == '__main__':
    unittest.main()
