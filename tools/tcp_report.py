"""Validate private TCP metadata and match flows without exposing payloads."""
import hashlib
import ipaddress
import json
from pathlib import Path

from host_timing import summarize
from tcp_metadata import MAX_BYTES, MAX_PACKETS

PACKET_KEYS = {'event', 'realtime_ns', 'observed_monotonic_ns', 'source', 'destination',
               'source_port', 'destination_port', 'seq', 'ack', 'flags', 'window',
               'ip_id', 'payload_length', 'ssh_prefix'}
CLOCK_KEYS = {'event', 'monotonic_before_ns', 'monotonic_after_ns', 'realtime_ns', 'boottime_ns'}


def integer(value, maximum=2**63-1):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Invalid metadata integer')
    return value


def boundary(stamp):
    if not isinstance(stamp, dict) or set(stamp) != CLOCK_KEYS-{'event'}:
        raise ValueError('Incomplete capture boundary')
    for name in ('realtime_ns', 'monotonic_before_ns', 'monotonic_after_ns'):
        integer(stamp[name])
    if stamp['boottime_ns'] is not None:
        integer(stamp['boottime_ns'])
    if stamp['monotonic_after_ns'] < stamp['monotonic_before_ns']:
        raise ValueError('Reversed capture boundary')


def load_side(root, identity, source, address, partial=False):
    result = json.loads((root/'result.json').read_text())
    raw = (root/'packets.jsonl').read_bytes()
    if (len(raw) > MAX_BYTES or result.get('schema') not in (1, 2, 3) or result.get('run_id') != identity or
            result.get('source_sha256') != source or result.get('address') != address or
            result.get('metadata_sha256') != hashlib.sha256(raw).hexdigest() or
            result.get('reason') != 'stopped' or result.get('rejected') != 0):
        raise ValueError('Incomplete, mismatched or lossy TCP capture')
    integer(result.get('interface_index'))
    for field in ('packets', 'rejected', 'reads', 'bytes'):
        integer(result.get(field))
    if result['bytes'] != len(raw) or result['reads'] < result['packets']:
        raise ValueError('Capture counters differ from metadata')
    if result['schema'] in (2, 3):
        if (result.get('selection') != 'flow-prefix16-control-first-payload' or
                integer(result.get('matched')) != result['packets']+integer(result.get('selected_out')) or
                result['matched'] > result['reads']):
            raise ValueError('Unaccounted packet selection')
    for field in ('received', 'dropped'):
        integer(result['stats'].get(field))
    if result['stats'].get('interface_dropped') is not None:
        integer(result['stats']['interface_dropped'])
    rows = [json.loads(line) for line in raw.splitlines()]
    packets, clocks = [], []
    for row in rows:
        if row.get('event') == 'packet':
            if set(row) != PACKET_KEYS | ({'segment'} if result['schema'] == 3 else set()):
                raise ValueError('Unexpected packet fields')
            for name in ('source', 'destination'):
                if str(ipaddress.IPv4Address(row[name])) != row[name]:
                    raise ValueError('Invalid endpoint')
            if address not in (row['source'], row['destination']) or 22 not in (row['source_port'], row['destination_port']):
                raise ValueError('Packet outside capture scope')
            for name in ('source_port', 'destination_port', 'window', 'ip_id', 'payload_length'):
                integer(row[name], 65535)
            for name in ('seq', 'ack'):
                integer(row[name], 2**32-1)
            integer(row['flags'], 255)
            integer(row['realtime_ns']); integer(row['observed_monotonic_ns'])
            if row['ssh_prefix'] is not None and type(row['ssh_prefix']) is not bool:
                raise ValueError('Invalid greeting observation')
            if result['schema'] == 3:
                integer(row['segment'], 3)
            packets.append(row)
        elif row.get('event') == 'clock':
            if set(row) != CLOCK_KEYS:
                raise ValueError('Unexpected clock fields')
            for name in ('monotonic_before_ns', 'monotonic_after_ns', 'realtime_ns'):
                integer(row[name])
            if row['boottime_ns'] is not None:
                integer(row['boottime_ns'])
            if row['monotonic_after_ns'] < row['monotonic_before_ns']:
                raise ValueError('Reversed clock bracket')
            clocks.append(row)
        else:
            raise ValueError('Unknown metadata event')
    if len(packets) != result['packets'] or len(packets) > MAX_PACKETS or len(clocks) < 2:
        raise ValueError('Incomplete metadata records')
    # CLOCK_BOOTTIME permits real Linux suspend; Mac MONOTONIC is valid only
    # while it remains awake. Reject a large clock step rather than align it.
    offsets = [r['realtime_ns']-(r['boottime_ns'] if r['boottime_ns'] is not None else
                               (r['monotonic_before_ns']+r['monotonic_after_ns'])//2) for r in clocks]
    if max(offsets)-min(offsets) > 100_000_000:
        raise ValueError('Clock step or host sleep makes packet alignment ambiguous')
    complete = (result.get('passed') is True and result['interface_index'] == result.get('final_interface_index') and
                result['stats']['dropped'] == 0 and result['stats']['interface_dropped'] in (0, None))
    qualified = [0] if complete else []
    if result['schema'] == 3:
        segments, gaps = result.get('segments'), result.get('gaps')
        if not isinstance(segments, list) or not 1 <= len(segments) <= 4 or not isinstance(gaps, list) or len(gaps) > 3:
            raise ValueError('Invalid bounded segment history')
        if result.get('test_gap_after') not in (0, 32):
            raise ValueError('Unknown capture injection')
        if len(gaps) not in (len(segments)-1, len(segments)) or any(p['segment'] >= len(segments) for p in packets):
            raise ValueError('Missing segment/gap identity')
        qualified = []
        previous_end = None
        for index, segment in enumerate(segments):
            if set(segment) != {'id', 'interface_index', 'opened', 'closed', 'stats', 'error'} or segment['id'] != index:
                raise ValueError('Segment identity mismatch')
            integer(segment['interface_index'])
            for stamp in (segment['opened'], segment['closed']):
                boundary(stamp)
            start, end = segment['opened']['monotonic_before_ns'], segment['closed']['monotonic_after_ns']
            if end < start or (previous_end is not None and start < previous_end):
                raise ValueError('Overlapping/reversed capture segments')
            previous_end = end
            if any(not start <= p['observed_monotonic_ns'] <= end for p in packets if p['segment'] == index):
                raise ValueError('Packet observed outside its segment')
            stats = segment['stats']
            if stats is not None:
                for name in ('received', 'dropped'): integer(stats[name])
                if stats['interface_dropped'] is not None: integer(stats['interface_dropped'])
            if segment['error'] is None and stats is not None and stats['dropped'] == 0 and stats['interface_dropped'] in (0, None):
                qualified.append(index)
        for gap_index, gap in enumerate(gaps):
            if (set(gap) != {'after_segment', 'started', 'ended', 'error', 'reopen_attempts'} or
                    gap['after_segment'] != gap_index or not 0 <= integer(gap['reopen_attempts']) <= 60):
                raise ValueError('Invalid capture gap')
            boundary(gap['started'])
            preceding = segments[gap_index]
            if (gap['error'] != preceding['error'] or not isinstance(gap['error'], dict) or
                    set(gap['error']) != {'phase', 'category', 'status', 'errno'} or
                    gap['error']['phase'] != 'read' or gap['error']['category'] not in
                    ('interface-disappeared', 'injected-interface-gap') or
                    gap['started']['monotonic_before_ns'] < preceding['closed']['monotonic_after_ns']):
                raise ValueError('Gap does not follow the recorded read interruption')
            if gap['error']['category'] == 'injected-interface-gap' and result['test_gap_after'] != 32:
                raise ValueError('Unmarked capture injection')
            if gap_index+1 < len(segments):
                following = segments[gap_index+1]
                boundary(gap['ended'])
                if (gap['reopen_attempts'] < 1 or
                        following['opened']['monotonic_before_ns'] < gap['started']['monotonic_after_ns'] or
                        gap['ended']['monotonic_before_ns'] < following['opened']['monotonic_after_ns'] or
                        gap['ended']['monotonic_after_ns'] > following['closed']['monotonic_before_ns']):
                    raise ValueError('Gap recovery boundary differs from its segment')
            elif gap['ended'] is not None:
                raise ValueError('Gap recovered without a new segment')
        if sum(g['reopen_attempts'] for g in gaps) > 60:
            raise ValueError('Capture exceeded the global reopen budget')
        known = [s['stats'] for s in segments if s['stats'] is not None]
        totals = dict(received=sum(s['received'] for s in known), dropped=sum(s['dropped'] for s in known),
                      interface_dropped=None if len(known) != len(segments) or
                          any(s['interface_dropped'] is None for s in known) else
                          sum(s['interface_dropped'] for s in known))
        if result['stats'] != totals or result['interface_index'] != segments[0]['interface_index']:
            raise ValueError('Aggregate capture identity/counters differ from segments')
        if result.get('final_interface_index') != segments[-1]['interface_index']:
            qualified = [s for s in qualified if s != len(segments)-1]
        complete = complete and not gaps and result['test_gap_after'] == 0 and qualified == [0]
        packets = [p for p in packets if p['segment'] in qualified]
    if not complete and not (partial and result['schema'] == 3):
        raise ValueError('Incomplete, mismatched or lossy TCP capture')
    return packets, dict(result, complete=complete, qualified_segments=qualified)


def flows(packets, server):
    groups = {}
    for p in packets:
        outbound = p['source'] == server and p['source_port'] == 22
        inbound = p['destination'] == server and p['destination_port'] == 22
        if outbound == inbound:
            continue
        key = (p['destination'], p['destination_port']) if outbound else (p['source'], p['source_port'])
        groups.setdefault(key+(p.get('segment', 0),), []).append((outbound, p))
    values, ambiguous = {}, set()
    for segmented_key, rows in groups.items():
        key = segmented_key[:2]
        syns = [p for outgoing, p in rows if not outgoing and p['flags'] & 0x12 == 0x02]
        initial = {p['seq'] for p in syns}
        if len(initial) != 1:
            continue  # Partial or tuple-reused window cannot identify one connection.
        client_seq = initial.pop()
        replies = [p for outgoing, p in rows if outgoing and p['flags'] & 0x12 == 0x12 and
                   p['ack'] == (client_seq+1) % 2**32]
        server_seqs = {p['seq'] for p in replies}
        if len(server_seqs) != 1:
            server_seq = None
        else:
            server_seq = server_seqs.pop()
        greeting = [p for outgoing, p in rows if outgoing and p['payload_length'] and server_seq is not None and
                    p['seq'] == (server_seq+1) % 2**32]
        greeting.sort(key=lambda p:p['realtime_ns'])
        identity = key+(client_seq,)
        if identity in values: ambiguous.add(identity)
        values[identity] = dict(client_isn=client_seq, server_isn=server_seq,
            syn_realtime_ns=min(p['realtime_ns'] for p in syns), syn_observations=len(syns),
            server_first_payload=greeting[0] if greeting else None, packets=len(rows))
    return {k:v for k,v in values.items() if k not in ambiguous}


def host_offset(anchors):
    ranges = []
    for anchor in anchors:
        a, b = integer(anchor['host_before_ns']), integer(anchor['host_after_ns'])
        wall = integer(anchor['clock']['realtime_ns'])
        if b < a:
            raise ValueError('Reversed host clock bracket')
        # Allow 50 ms for bounded slew between anchors; not precision latency.
        ranges.append((a-wall-50_000_000, b-wall+50_000_000))
    low, high = max(a for a, _ in ranges), min(b for _, b in ranges)
    if low > high:
        raise ValueError('Host/Mac clock brackets do not overlap')
    return low, high


def report(path, partial=False):
    manifest = json.loads((path/'tcp-run.json').read_text())
    identity, source, server = (manifest[k] for k in ('run_id', 'source_sha256', 'address'))
    mac, ms = load_side(path/'tcp-mac', identity, source, server, partial)
    board, bs = load_side(path/'tcp-device', identity, source, server, partial)
    if manifest.get('device', {}).get('sleep_unit'):
        supervisor = json.loads((path/'tcp-device/supervisor.json').read_text())
        if (supervisor.get('run_id') != identity or supervisor.get('source_sha256') != manifest.get('supervisor_sha256') or
                (not partial and supervisor.get('passed') is not True) or supervisor.get('command_started') is not True or
                supervisor.get('cleanup_errors') != [] or
                supervisor.get('command_returncode') != 0 or supervisor.get('recorder_returncode') != 0 or
                supervisor.get('cgroup') != '0::/system.slice/gameshellneo-sleep-test.service\n'):
            raise ValueError('Incomplete observer unit lifecycle')
        if manifest['mode'] in ('smoke', 'burst', 'gap-smoke'):
            smoke = json.loads((path/'tcp-device/smoke.json').read_text())
            allowed = {'gameshellneo-usb.service', 'gameshellneo-ready.service',
                       'gameshellneo-battery.service', 'gameshellneo-sleep-test.service'}
            active = smoke.get('active_units', [])
            if (smoke.get('run_id') != identity or smoke.get('passed') is not True or
                    smoke.get('cgroup') != supervisor['cgroup'] or
                    'gameshellneo-sleep-test.service' not in active or any(unit not in allowed for unit in active)):
                raise ValueError('Observer smoke did not establish diagnostic ownership')
    timing = summarize(path)  # Includes SSH observations, rejects truncated nesting.
    events = [json.loads(line) for line in (path/'host-timing.jsonl').read_text().splitlines()]
    begins = {r['span']: r for r in events if r['event'] == 'begin'}
    ends = {r['span']: r for r in events if r['event'] == 'end'}
    def usb(row):
        while row:
            if row['phase'].startswith('route.'):
                return row['phase'] == 'route.usb'
            row = begins.get(row['parent'])
        return False
    tunnels = [(sid, r['host_monotonic_ns'], ends[sid]['host_monotonic_ns'])
               for sid, r in begins.items() if r['phase'] == 'device.tunnel' and usb(r)]
    if len(manifest['mac_clocks']) < 2:
        raise ValueError('Require original before/after host-Mac clock anchors')
    # Later recollection cannot improve/redefine the original clock mapping.
    low, high = host_offset(manifest['mac_clocks'][:2])
    mf, bf = flows(mac, server), flows(board, server)
    rows = []
    for key, flow in mf.items():
        peer = bf.get(key)
        match = peer is not None and flow['server_isn'] is not None and peer['server_isn'] == flow['server_isn']
        stamp = flow['syn_realtime_ns']
        candidates = [sid for sid, a, b in tunnels if stamp+low <= b and stamp+high >= a]
        prefix = lambda x: x['server_first_payload']['ssh_prefix'] if x and x['server_first_payload'] else None
        rows.append(dict(client_address=key[0], client_port=key[1], client_isn=key[2],
            server_isn=flow['server_isn'], matched_handshake=match,
            mac_greeting_prefix=prefix(flow), device_greeting_prefix=prefix(peer),
            host_tunnel_candidates=candidates, host_tunnel_unique=len(candidates)==1,
            mac=flow, device=peer))
    # Do not silently choose between two flows associated with the same host span.
    for row in rows:
        if row['host_tunnel_unique'] and sum(row['host_tunnel_candidates']==r['host_tunnel_candidates'] for r in rows) != 1:
            row['host_tunnel_unique'] = False
    verified = [r for r in rows if r['matched_handshake'] and r['host_tunnel_unique'] and
                r['mac_greeting_prefix'] is True and r['device_greeting_prefix'] is True]
    return dict(schema=1, run_id=identity, metadata_valid=ms['complete'] and bs['complete'],
                mac_complete=ms['complete'], device_complete=bs['complete'],
                mac_qualified_segments=ms['qualified_segments'], device_qualified_segments=bs['qualified_segments'], flows=rows,
                device_only_flows=[dict(client_address=k[0], client_port=k[1], client_isn=k[2], device=v)
                                   for k, v in bf.items() if k not in mf],
                matched_greeting_flows=len(verified), mac_packets=ms['packets'], device_packets=bs['packets'],
                capture_outcome=timing['capture_outcome'], clock_offset_bounds_ns=[low, high],
                limits='Capture boundaries, not wire delivery or server scheduling proof. Prefix is not a '
                'complete SSH banner. Flow selection omits bulk; incomplete segments are excluded. '
                'Partial reports provide positive presence only, never absence across a gap. '
                'Partial, reused or ambiguous flows remain unqualified. '
                'Zero reported drops do not prove zero loss; segmentation/offload can differ between endpoints.')
