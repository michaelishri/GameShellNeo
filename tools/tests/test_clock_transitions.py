"""Keep publication consistency separate from clock health and legal ambiguity."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import clock_transitions as transitions
from test_clock_provenance import call as original_call

CLI = ROOT/'tools/report-clock-transitions.py'
FAMILIES = {
    'anchored': ('published-new', 'initial-old', 'publication-chain', 'three-clocks',
                 'u32-wrap', 'external-bound-change'),
    'ambiguity': ('unanchored', 'leap-sequence-gap', 'mid-call-publication',
                  'rejected-attempt-order-gap', 'setup-nonpublication-seed'),
    'consistency': ('publication-chain-old-mismatch', 'postpublication-reader-mismatch',
                    'initial-old-reader-mismatch'),
    'delta': ('unchanged-raw-minus750', 'changed-tuple-regression', 'namespace-only-delta',
              'source-generation-incomparable'),
    'refusal': ('duplicate-json', 'truncated-json', 'oversized-stream', 'writer-loss',
                'unfinished-call', 'odd-accepted-sequence'),
}


def call(ordinal=1, read=3, **changes):
    value = original_call(ordinal)
    value.update(read_order=read, end_order=read+1)
    value.update(changes)
    return value


def publication(order=1, seq=7, old=None, new=None):
    old = original_call()['tuple'] if old is None else old
    return dict(type='writer', order=order, cpu=0, kind=0, seq=seq, action=0,
                cycles=0, delta=0, delta_valid=0, old=copy.deepcopy(old),
                new=copy.deepcopy(old if new is None else new))


def capture(*calls, writers=()):
    return [dict(type='header', schema=1, reason=1, calls=len(calls), writers=len(writers),
                 writer_lost=0, limit=1024, time_ns=99), *calls, *writers]


def changed_pair(*, generation=False):
    first, second = call(), call(2, read=7, seq=10, cycles=1224, ns=7100)
    if generation:
        second.update(cycles=1176, ns=5600, nsec=5600)
        second['tuple']['source_changed'] += 1
    else:
        second['tuple']['raw_sec'] = second['sec'] = 6
        second['nsec'] = 7100
    return capture(first, second, writers=[publication(),
        publication(5, 9, first['tuple'], second['tuple'])])


class ClockTransitions(unittest.TestCase):
    def run_case(self, name, records=None, *, raw=None, refused=False):
        family = next(family for family, names in FAMILIES.items() if name in names)
        if raw is None:
            raw = ''.join(json.dumps(row, sort_keys=True)+'\n' for row in records).encode()
        original = copy.deepcopy(records)
        origins = {name: str(Path(module.__file__).resolve()) for name, module in (
            ('clock_transitions', transitions), ('clock_provenance', transitions.provenance))}
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)/'kernel.ndjson'
            source.write_bytes(raw)
            command = [sys.executable, '-B', str(CLI), str(source)]
            child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = child.communicate(timeout=15)
            result = json.loads(stdout) if child.returncode == 0 else None
            direct = transitions.analyze(records) if result is not None else None
            observed = dict(schema=1, case=name, family=family, command=command, child_pid=child.pid,
                terminal_exit=child.returncode, expected_refusal=refused, raw_bytes=len(raw),
                raw_sha256=hashlib.sha256(raw).hexdigest(), raw_unchanged=source.read_bytes() == raw,
                input_object_unchanged=records == original, actual_cli=True, current_module_same_result=(
                    direct == {k: v for k, v in result.items() if k not in ('input_bytes', 'input_sha256')}
                    if result is not None else None), actual_import_origins=origins,
                original_replay_reused=transitions.provenance is sys.modules['clock_provenance'],
                no_device_or_collector=True)
            saved = os.environ.get('NEO_CLOCK_TRANSITION_RESULTS_DIR')
            if saved:
                directory = Path(saved)/name; directory.mkdir(parents=True, exist_ok=False)
                for filename, data in [('kernel.ndjson', raw), ('stdout.json', stdout), ('stderr.txt', stderr)]:
                    (directory/filename).write_bytes(data)
                (directory/'observed.json').write_text(json.dumps(observed, indent=2)+'\n')
            # Retain the actual result before assertions, including unexpected failures.
            self.assertEqual(child.returncode == 0, not refused, stderr.decode())
            self.assertTrue(observed['raw_unchanged'])
            self.assertTrue(observed['input_object_unchanged'])
            self.assertEqual(origins, {name: str(ROOT/'tools'/(name+'.py')) for name in origins})
            self.assertTrue(observed['original_replay_reused'])
            if result is not None:
                self.assertTrue(observed['current_module_same_result'])
                self.assertEqual(result['input_sha256'], observed['raw_sha256'])
                for flag in ('source_attested', 'hardware_qualified', 'clock_reliability_qualified', 'pm_admission'):
                    self.assertIs(result[flag], False)
            return result

    def test_six_anchored_controls(self):
        cases = {
            'published-new': capture(call(), writers=[publication()]),
            'initial-old': capture(call(read=1), writers=[publication(3, 9)]),
            'publication-chain': capture(call(), call(2, read=7, seq=10),
                writers=[publication(), publication(5, 9)]),
            'three-clocks': capture(*[call(i+1, read=3+i*2, clock=clock,
                sec=16 if clock == 7 else 7) for i, clock in enumerate((1, 4, 7))],
                writers=[publication()]),
            'u32-wrap': capture(call(seq=0), call(2, read=7, seq=2),
                writers=[publication(seq=transitions.U32), publication(5, 1)]),
        }
        external = call()
        for base in ('mono', 'raw'):
            external['tuple'][base].update(max=1 << 39, max_raw=1 << 54)
        cases['external-bound-change'] = capture(external, writers=[publication()])
        for name, records in cases.items():
            with self.subTest(case=name):
                result = self.run_case(name, records)
                self.assertTrue(result['record_complete'])
                self.assertTrue(result['reconciliation_complete'])
                self.assertIs(result['consistent'], True)
                self.assertEqual(result['findings'], [])
                self.assertEqual(result['unknown'], [])
                self.assertTrue(all(row['matched'] for row in result['reader_links']))

    def test_five_legitimate_ambiguities_and_interleavings(self):
        retry = call(read=4, attempts=3)
        seed = dict(type='writer', order=1, cpu=0, kind=4, seq=0, action=0,
                    cycles=1200, delta=0, delta_valid=0, old=original_call()['tuple'], new={})
        mid = call(read=1, end_order=4)
        cases = {
            'unanchored': (capture(call()), False, 'no-publication-anchor'),
            'leap-sequence-gap': (capture(call(seq=10), writers=[publication()]), False, 'reader-sequence-gap'),
            'mid-call-publication': (capture(mid, writers=[publication(2, 9)]), True, None),
            'rejected-attempt-order-gap': (capture(retry, writers=[publication(3, 7)]), True, None),
            'setup-nonpublication-seed': (capture(call(), writers=[seed]), False, 'no-publication-anchor'),
        }
        for name, (records, complete, reason) in cases.items():
            with self.subTest(case=name):
                result = self.run_case(name, records)
                self.assertEqual(result['findings'], [])
                self.assertEqual(result['reconciliation_complete'], complete)
                self.assertIs(result['consistent'], True if complete else None)
                if reason:
                    self.assertIn(reason, [row['reason'] for row in result['unknown']])
        self.assertLess(mid['read_order'], 2)
        self.assertGreater(mid['end_order'], 2)

    def test_three_consistency_findings_preserve_arithmetic(self):
        chain = capture(call(), call(2, read=7, seq=10), writers=[publication(), publication(5, 9)])
        chain[-1]['old']['raw_sec'] += 1
        changed = call(sec=8)
        changed['tuple']['raw_sec'] = 8
        initial = call(read=1, sec=8)
        initial['tuple']['raw_sec'] = 8
        cases = {
            'publication-chain-old-mismatch': (chain, 'publication-chain-mismatch'),
            'postpublication-reader-mismatch': (capture(changed, writers=[publication()]), 'reader-publication-mismatch'),
            'initial-old-reader-mismatch': (capture(initial, writers=[publication(3, 9)]), 'reader-publication-mismatch'),
        }
        for name, (records, kind) in cases.items():
            with self.subTest(case=name):
                result = self.run_case(name, records)
                self.assertTrue(result['original_replay']['complete'])
                self.assertIs(result['consistent'], False)
                self.assertFalse(result['reconciliation_complete'])
                self.assertIn(kind, [row['kind'] for row in result['findings']])
                self.assertIn('raw_sec', result['findings'][0]['fields'])

    def test_four_regression_decompositions(self):
        first = call(offset_sec=1, sec=8)
        second = call(2, read=5, namespace_id=100)
        cases = {
            'unchanged-raw-minus750': (capture(call(), call(2, read=5, cycles=1176, ns=5600, nsec=5600),
                writers=[publication()]), (-750, -750, 0, 0)),
            'changed-tuple-regression': (changed_pair(), (-999_999_250, 750, 0, -1_000_000_000)),
            'namespace-only-delta': (capture(first, second, writers=[publication()]), (-1_000_000_000, 0, -1_000_000_000, 0)),
            'source-generation-incomparable': (changed_pair(generation=True), (-750, None, None, None)),
        }
        for name, (records, expected) in cases.items():
            with self.subTest(case=name):
                result = self.run_case(name, records)
                self.assertEqual(result['findings'], [])
                self.assertEqual(len(result['regressions']), 1)
                row = result['regressions'][0]
                self.assertEqual(tuple(row[k] for k in ('returned_delta_ns', 'counter_component_ns',
                    'namespace_component_ns', 'tuple_component_ns')), expected)
                if row['comparable']:
                    self.assertEqual(sum(expected[1:]), expected[0])
                    self.assertEqual(row['old_conversion_branches'], ['normal', 'normal'])
                else:
                    self.assertIn('source-generation-or-identity-changed', row['unknown'])
                    self.assertFalse(result['reconciliation_complete'])
        # The established fixture's -750ns is 24 ticks at its declared 125/4
        # conversion. It is not a claim about the historical 24MHz hardware event.

    def test_six_original_refusals_and_incomplete_streams(self):
        good = ''.join(json.dumps(row, sort_keys=True)+'\n' for row in capture(call())).encode()
        bad = call(seq=9)
        unfinished = call(complete=0)
        losses = [dict(type='writer', order=i+5, cpu=0, kind=2, seq=0, action=0, cycles=1200,
                       delta=200, delta_valid=1, old=original_call()['tuple'], new={}) for i in range(2048)]
        lost = capture(call(), writers=losses)
        lost[0].update(reason=3, writer_lost=1)
        cases = {
            'duplicate-json': (None, good.replace(b'"schema": 1', b'"schema": 1, "schema": 1', 1), True),
            'truncated-json': (None, b'{"type":', True),
            'oversized-stream': (None, b'x' * (transitions.MAX_BYTES+1), True),
            'writer-loss': (lost, None, False),
            'unfinished-call': (capture(unfinished), None, False),
            'odd-accepted-sequence': (capture(bad), None, True),
        }
        for name, (records, raw, refused) in cases.items():
            with self.subTest(case=name):
                result = self.run_case(name, records, raw=raw, refused=refused)
                if not refused:
                    self.assertFalse(result['record_complete'])
                    self.assertFalse(result['reconciliation_complete'])
                    self.assertIs(result['consistent'], None)
                    self.assertIn('original-record-stream-incomplete', [row['reason'] for row in result['unknown']])


if __name__ == '__main__':
    unittest.main()
