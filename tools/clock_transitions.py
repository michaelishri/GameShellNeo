"""Conditionally reconcile saved publications; never qualify a physical clock."""
from bisect import bisect_left
import hashlib
from pathlib import Path

import clock_provenance as provenance

MAX_BYTES = 16 * 1024 * 1024
U32 = (1 << 32) - 1
BASE_FIELDS = ('mask', 'last', 'xtime', 'base', 'mult', 'shift')
TUPLE_FIELDS = ('xtime_sec', 'raw_sec', 'wall_sec', 'wall_nsec', 'offs_boot',
                'clock_set', 'source_changed')
EXTERNAL_FIELDS = ('max', 'max_raw', 'source_id')


def projection(value):
    """Exclude fields read through the external clocksource pointer."""
    return {**{name: value[name] for name in TUPLE_FIELDS},
            **{name: {field: value[name][field] for field in BASE_FIELDS}
               for name in ('mono', 'raw')}}


def differences(first, second):
    first, second = projection(first), projection(second)
    return [name for name in TUPLE_FIELDS if first[name] != second[name]] + [
        name + '.' + field for name in ('mono', 'raw') for field in BASE_FIELDS
        if first[name][field] != second[name][field]]


def offset(call):
    return call['offset_sec'] * provenance.NS + call['offset_nsec']


def regressions(calls, writers):
    previous, result = {}, []
    for call in calls:
        if not all(call[name] for name in ('accepted', 'valid', 'complete')) or call['error']:
            continue
        value = call['sec'] * provenance.NS + call['nsec']
        before = previous.get(call['clock'])
        previous[call['clock']] = call
        if before is None:
            continue
        delta = value - (before['sec'] * provenance.NS + before['nsec'])
        if delta >= 0:
            continue
        name = 'raw' if call['clock'] == 4 else 'mono'
        old, new = before['tuple'], call['tuple']
        reasons = []
        if (old['source_changed'] != new['source_changed'] or
                any(old[base]['source_id'] != new[base]['source_id'] for base in ('mono', 'raw'))):
            reasons.append('source-generation-or-identity-changed')
        if old[name]['mask'] != new[name]['mask']:
            reasons.append('counter-mask-changed')
        if any(w['kind'] == 4 and before['read_order'] < w['order'] < call['read_order'] for w in writers):
            reasons.append('setup-record-between-read-insertions')
        row = dict(previous=before['ordinal'], ordinal=call['ordinal'], clock=call['clock'],
                   returned_delta_ns=delta, consumed_count_delta=call['cycles'] - before['cycles'],
                   read_cpus=[before['cpu'], call['cpu']], comparable=not reasons, unknown=reasons,
                   namespace_ids=[before['namespace_id'], call['namespace_id']],
                   counter_component_ns=None, namespace_component_ns=None, tuple_component_ns=None,
                   old_conversion_branches=None, hypothetical_old_tuple_at_second_count=not reasons)
        if not reasons:
            hypothetical, branch, _ = provenance.conversion(old[name], call['cycles'])
            _, first_branch, _ = provenance.conversion(old[name], before['cycles'])
            counter = hypothetical - before['ns']
            namespace = offset(call) - offset(before)
            row.update(counter_component_ns=counter, namespace_component_ns=namespace,
                       tuple_component_ns=delta - counter - namespace,
                       old_conversion_branches=[first_branch, branch])
        result.append(row)
    return result


def analyze(records):
    """Check recorded software invariants under the declared producer contract.

    Insertion order is not counter-instruction time. Sequence gaps can come from
    the unhooked leap-state writer, and an external source object is not covered
    by the timekeeper sequence. No raw record is modified or repaired here.
    """
    replay = provenance.replay(records)
    calls = records[1:1 + replay['calls']]
    writers = records[1 + replay['calls']:]
    publications = [row for row in writers if row['kind'] == 0]
    orders = [row['order'] for row in publications]
    findings, unknown, links, readers = [], [], [], []
    if not replay['complete']:
        unknown.append(dict(reason='original-record-stream-incomplete', details=replay['incomplete']))
    for first, second in zip(publications, publications[1:]):
        changed = differences(first['new'], second['old'])
        links.append(dict(previous_order=first['order'], order=second['order'], matched=not changed))
        if changed:
            findings.append(dict(kind='publication-chain-mismatch', previous_order=first['order'],
                                 order=second['order'], fields=changed))
        expected = (first['seq'] + 2) & U32
        if second['seq'] != expected:
            unknown.append(dict(reason='publication-sequence-gap', order=second['order'],
                                expected_sequence=expected, observed_sequence=second['seq']))
    for call in calls:
        if not all(call[name] for name in ('accepted', 'valid', 'complete')) or call['error']:
            unknown.append(dict(reason='call-incomplete-or-error', ordinal=call['ordinal']))
            continue
        index = bisect_left(orders, call['read_order']) - 1
        if not publications:
            readers.append(dict(ordinal=call['ordinal'], anchor=None, matched=None))
            unknown.append(dict(reason='no-publication-anchor', ordinal=call['ordinal']))
            continue
        writer = publications[max(index, 0)]
        side = 'new' if index >= 0 else 'old'
        expected = (writer['seq'] + (1 if side == 'new' else -1)) & U32
        changed = differences(writer[side], call['tuple'])
        readers.append(dict(ordinal=call['ordinal'], anchor=side, publication_order=writer['order'],
                            matched=not changed, sequence_matched=call['seq'] == expected,
                            external_fields_compared=False))
        if changed:
            findings.append(dict(kind='reader-publication-mismatch', ordinal=call['ordinal'],
                                 publication_order=writer['order'], anchor=side, fields=changed))
        if call['seq'] != expected:
            unknown.append(dict(reason='reader-sequence-gap', ordinal=call['ordinal'],
                                expected_sequence=expected, observed_sequence=call['seq']))
    deltas = regressions(calls, writers)
    for row in deltas:
        if not row['comparable']:
            unknown.append(dict(reason='regression-source-incomparable', ordinal=row['ordinal'],
                                details=row['unknown']))
    complete = replay['complete'] and not findings and not unknown
    return dict(schema=1, operation='clock-publication-reconciliation',
                producer_contract='linux-6.18.54-neo-clock-schema1', source_attested=False,
                record_complete=replay['complete'], reconciliation_complete=complete,
                consistent=False if findings else (True if complete else None),
                calls=len(calls), publications=len(publications), writers=len(writers),
                publication_links=links, reader_links=readers, findings=findings, unknown=unknown,
                regressions=deltas, original_replay=replay,
                protected_projection=dict(base_fields=list(BASE_FIELDS), tuple_fields=list(TUPLE_FIELDS),
                                          excluded_external_clocksource_fields=list(EXTERNAL_FIELDS)),
                nonpublication_writer_transitions_reconstructed=False,
                clock_reliability_qualified=False, hardware_qualified=False, pm_admission=False,
                scope=['Conditional saved-record software consistency; producer provenance is separate.',
                       'Diagnostic insertion order is not counter-instruction time.',
                       'Sequence gaps may be unhooked leap-state updates, not missing publications.',
                       'Nonpublication writer sites, incomplete setup seeds and action flags do not identify causes.',
                       'Delta components are old-tuple hypothetical arithmetic, not independent counter evidence.',
                       'No reconstruction of historical faults lacking event-time records; no MMIO STOP or PM clearance.'])


def read_saved(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Oversized capture')
    return raw, [provenance.loads(line) for line in raw.decode().splitlines()]


def report(path):
    raw, records = read_saved(path)
    return dict(analyze(records), input_sha256=hashlib.sha256(raw).hexdigest(), input_bytes=len(raw))
