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


def load_side(root, identity, source, address):
    result = json.loads((root/'result.json').read_text())
    raw = (root/'packets.jsonl').read_bytes()
    if (len(raw) > MAX_BYTES or result.get('schema') != 1 or result.get('run_id') != identity or
            result.get('source_sha256') != source or result.get('address') != address or
            result.get('metadata_sha256') != hashlib.sha256(raw).hexdigest() or
            result.get('passed') is not True or result.get('reason') != 'stopped' or
            result.get('interface_index') != result.get('final_interface_index') or
            result.get('rejected') != 0 or result.get('stats', {}).get('dropped') != 0 or
            result['stats'].get('interface_dropped') not in (0, None)):
        raise ValueError('Incomplete, mismatched or lossy TCP capture')
    integer(result.get('interface_index'))
    for field in ('packets', 'rejected', 'reads', 'bytes'):
        integer(result.get(field))
    if result['bytes'] != len(raw) or result['reads'] < result['packets']:
        raise ValueError('Capture counters differ from metadata')
    for field in ('received', 'dropped'):
        integer(result['stats'].get(field))
    if result['stats'].get('interface_dropped') is not None:
        integer(result['stats']['interface_dropped'])
    rows = [json.loads(line) for line in raw.splitlines()]
    packets, clocks = [], []
    for row in rows:
        if row.get('event') == 'packet':
            if set(row) != PACKET_KEYS:
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
    return packets, result


def flows(packets, server):
    groups = {}
    for p in packets:
        outbound = p['source'] == server and p['source_port'] == 22
        inbound = p['destination'] == server and p['destination_port'] == 22
        if outbound == inbound:
            continue
        key = (p['destination'], p['destination_port']) if outbound else (p['source'], p['source_port'])
        groups.setdefault(key, []).append((outbound, p))
    values = {}
    for key, rows in groups.items():
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
        values[key+(client_seq,)] = dict(client_isn=client_seq, server_isn=server_seq,
            syn_realtime_ns=min(p['realtime_ns'] for p in syns), syn_observations=len(syns),
            server_first_payload=greeting[0] if greeting else None, packets=len(rows))
    return values


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


def report(path):
    manifest = json.loads((path/'tcp-run.json').read_text())
    identity, source, server = (manifest[k] for k in ('run_id', 'source_sha256', 'address'))
    mac, ms = load_side(path/'tcp-mac', identity, source, server)
    board, bs = load_side(path/'tcp-device', identity, source, server)
    if manifest.get('device', {}).get('sleep_unit'):
        supervisor = json.loads((path/'tcp-device/supervisor.json').read_text())
        if (supervisor.get('run_id') != identity or supervisor.get('source_sha256') != manifest.get('supervisor_sha256') or
                supervisor.get('passed') is not True or supervisor.get('command_started') is not True or
                supervisor.get('cleanup_errors') != [] or
                supervisor.get('command_returncode') != 0 or supervisor.get('recorder_returncode') != 0 or
                supervisor.get('cgroup') != '0::/system.slice/gameshellneo-sleep-test.service\n'):
            raise ValueError('Incomplete observer unit lifecycle')
        if manifest['mode'] == 'smoke':
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
    return dict(schema=1, run_id=identity, metadata_valid=True, flows=rows,
                device_only_flows=[dict(client_address=k[0], client_port=k[1], client_isn=k[2], device=v)
                                   for k, v in bf.items() if k not in mf],
                matched_greeting_flows=len(verified), mac_packets=ms['packets'], device_packets=bs['packets'],
                capture_outcome=timing['capture_outcome'], clock_offset_bounds_ns=[low, high],
                limits='Capture boundaries, not wire delivery or server scheduling proof. Prefix is not a '
                'complete SSH banner. Partial, reused or ambiguous flows remain unqualified. '
                'Zero reported drops do not prove zero loss; segmentation/offload can differ between endpoints.')
