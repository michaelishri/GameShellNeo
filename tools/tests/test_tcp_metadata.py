import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tcp_metadata as tcp
import tcp_report as report
from host_timing import capture_timing, phase

SERVER, CLIENT = '192.0.2.1', '192.0.2.2'
TOKEN = 'a'*32
SECRET = b'SSH-2.0-sensitive-version-and-payload'


def frame(payload=SECRET, source=SERVER, destination=CLIENT, sport=22, dport=50000,
          seq=201, ack=101, flags=0x18, options=b'', fragment=0):
    ethernet = b'\0'*12+b'\x08\x00'
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 40+len(options)+len(payload), 7, fragment, 64, 6, 0,
                     socket.inet_aton(source), socket.inet_aton(destination))
    header = struct.pack('!HHIIBBHHH', sport, dport, seq, ack, (5+len(options)//4)<<4, flags, 1024, 0, 0)
    return ethernet+ip+header+options+payload


def packet(**kwargs):
    raw = frame(**kwargs)
    return dict(event='packet', realtime_ns=10**12, observed_monotonic_ns=10**9,
                **tcp.decode(raw[:tcp.SNAPLEN], len(raw), SERVER))


class PacketTests(unittest.TestCase):
    def test_darwin_timeval_ignores_nonzero_padding(self):
        raw=struct.pack('=qiI',1700000000,123456,0xffffffff)
        stamp=tcp.PcapPackets.Timeval.from_buffer_copy(raw)
        self.assertEqual(stamp.microseconds,123456)
        self.assertEqual(stamp.seconds,1700000000)

    def test_payload_never_serialized_and_prefix_is_only_boolean(self):
        p = packet()
        self.assertTrue(p['ssh_prefix'])
        self.assertNotIn(SECRET.decode(), json.dumps(p))
        self.assertEqual(set(p), report.PACKET_KEYS)
        self.assertEqual(p['payload_length'], len(SECRET))
        self.assertIsNone(packet(payload=b'SSH')['ssh_prefix'])
        self.assertFalse(packet(payload=b'abcd')['ssh_prefix'])

    def test_truncated_payload_is_valid_but_truncated_headers_fail(self):
        raw = frame(payload=b'z'*2000, options=b'\x01'*12)
        p = tcp.decode(raw[:128], len(raw), SERVER)
        self.assertEqual(p['payload_length'], 2000)
        with self.assertRaises(ValueError):
            tcp.decode(raw[:53], len(raw), SERVER)
        with self.assertRaises(ValueError):
            tcp.decode(raw[:60], len(raw), SERVER)

    def test_ipv4_options_and_sequence_wrap(self):
        raw = bytearray(frame(seq=0xffffffff))
        raw[14] = 0x46
        struct.pack_into('!H', raw, 16, len(raw)-14+4)
        raw[34:34] = b'\x01'*4
        self.assertTrue(tcp.decode(raw, len(raw), SERVER)['ssh_prefix'])
        self.assertEqual(tcp.decode(raw, len(raw), SERVER)['seq'], 0xffffffff)

    def test_non_target_traffic_ignored_fragments_and_malformed_tcp_fail(self):
        raw = frame(source='192.0.2.3', destination='192.0.2.4')
        self.assertIsNone(tcp.decode(raw, len(raw), SERVER))
        raw = frame(sport=80, dport=40000)
        self.assertIsNone(tcp.decode(raw, len(raw), SERVER))
        for raw in (frame(fragment=0x2000), frame(fragment=1)):
            with self.assertRaises(ValueError):
                tcp.decode(raw, len(raw), SERVER)
        raw = bytearray(frame()); raw[46] = 0x40
        with self.assertRaises(ValueError):
            tcp.decode(raw, len(raw), SERVER)

    def test_linux_time64_timestamp_and_payload_truncation(self):
        with patch.object(socket, 'socket') as factory:
            backend = tcp.LinuxPackets('usb0', SERVER)
            raw = frame(payload=b'x'*1000)
            def receive(buffers, ancsize, flags):
                buffers[0][:] = raw[:128]
                return len(raw), [(socket.SOL_SOCKET, 64, struct.pack('=qq', 1700000000, 123))], socket.MSG_TRUNC, None
            backend.sock.recvmsg_into.side_effect = receive
            data, length, stamp = backend.read()
            self.assertEqual((len(data), length, stamp), (128, len(raw), 1700000000000000123))
            backend.sock.bind.assert_called_once_with(('usb0', 3))
            factory.assert_called_once_with(socket.AF_PACKET, socket.SOCK_RAW, 0)
            backend.sock.recvmsg_into.return_value = (54, [], socket.MSG_CTRUNC, None)
            backend.sock.recvmsg_into.side_effect = None
            with self.assertRaises(ValueError): backend.read()
            backend.close(); backend.sock.close.assert_called_once()

    def test_linux_failed_initialization_closes_socket(self):
        with patch.object(socket, 'socket') as factory:
            factory.return_value.bind.side_effect = OSError('test')
            with self.assertRaises(OSError): tcp.LinuxPackets('usb0', SERVER)
            factory.return_value.close.assert_called_once()


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        index = patch.object(socket, 'if_nametoindex', return_value=5)
        index.start(); self.addCleanup(index.stop)

    def backend(self, dropped=0, stop=True):
        root = self.root
        class Backend:
            closed = False
            def __init__(self, interface, address): pass
            def read(self):
                if stop: tcp.save(root/'stop.json', dict(run_id=TOKEN))
                raw = frame()
                return raw, len(raw), 1700000000000000000
            def stats(self): return dict(received=1, dropped=dropped, interface_dropped=None)
            def close(self): Backend.closed = True
        return Backend

    def test_bounded_success_close_hash_permissions_and_no_payload(self):
        backend = self.backend()
        tcp.capture(self.root, TOKEN, 'usb0', SERVER, 10, backend, str(self.root/'lock'))
        result = json.loads((self.root/'result.json').read_text())
        self.assertTrue(result['passed']); self.assertTrue(backend.closed)
        raw = (self.root/'packets.jsonl').read_bytes()
        self.assertEqual(result['metadata_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertNotIn(SECRET, raw)
        self.assertEqual((self.root/'packets.jsonl').stat().st_mode & 0o777, 0o600)

    def test_packet_cap_is_not_complete_and_closes(self):
        backend = self.backend(stop=False)
        with patch.object(tcp, 'MAX_PACKETS', 1):
            tcp.capture(self.root, TOKEN, 'usb0', SERVER, 10, backend, str(self.root/'lock'))
        result = json.loads((self.root/'result.json').read_text())
        self.assertFalse(result['passed']); self.assertEqual(result['reason'], 'packet-cap')
        self.assertTrue(backend.closed)

    def test_drop_is_not_admitted(self):
        tcp.capture(self.root, TOKEN, 'usb0', SERVER, 10, self.backend(dropped=1), str(self.root/'lock'))
        self.assertFalse(json.loads((self.root/'result.json').read_text())['passed'])

    def test_interface_replacement_is_not_admitted(self):
        with patch.object(socket, 'if_nametoindex', side_effect=[5, 6]):
            tcp.capture(self.root, TOKEN, 'usb0', SERVER, 10, self.backend(), str(self.root/'lock'))
        self.assertFalse(json.loads((self.root/'result.json').read_text())['passed'])

    def test_deadline_is_incomplete_and_closes(self):
        backend = self.backend(stop=False)
        with patch.object(tcp.time, 'monotonic', side_effect=[0, 0, 11]):
            tcp.capture(self.root, TOKEN, 'usb0', SERVER, 10, backend, str(self.root/'lock'))
        result = json.loads((self.root/'result.json').read_text())
        self.assertFalse(result['passed']); self.assertEqual(result['reason'], 'deadline')
        self.assertTrue(backend.closed)

    def test_output_bound_failure_still_closes_and_records_failure(self):
        backend = self.backend()
        with patch.object(tcp, 'MAX_BYTES', 1), self.assertRaises(ValueError):
            tcp.capture(self.root, TOKEN, 'usb0', SERVER, 10, backend, str(self.root/'lock'))
        result = json.loads((self.root/'result.json').read_text())
        self.assertFalse(result['passed']); self.assertTrue(backend.closed)

    def test_output_never_overwrites_or_follows_symlinks(self):
        target = self.root/'target'; target.write_text('keep')
        (self.root/'packets.jsonl').symlink_to(target)
        with self.assertRaises(OSError):
            tcp.capture(self.root, TOKEN, 'usb0', SERVER, 10, self.backend(), str(self.root/'lock'))
        self.assertEqual(target.read_text(), 'keep')


class CorrelationTests(unittest.TestCase):
    def handshake(self, port=50000, client_seq=100):
        return [packet(payload=b'', source=CLIENT, destination=SERVER, sport=port, dport=22, seq=client_seq, ack=0, flags=2),
                packet(payload=b'', dport=port, seq=200, ack=(client_seq+1)%2**32, flags=18),
                packet(dport=port, ack=(client_seq+1)%2**32)]

    def test_flow_identity_retransmission_and_wrapping_isn(self):
        rows = self.handshake(client_seq=0xffffffff)
        values = report.flows(rows+[rows[0]], SERVER)
        self.assertEqual(len(values), 1)
        flow = next(iter(values.values()))
        self.assertEqual(flow['syn_observations'], 2)
        self.assertTrue(flow['server_first_payload']['ssh_prefix'])

    def test_tuple_reuse_and_missing_syn_cannot_claim_one_flow(self):
        self.assertFalse(report.flows(self.handshake()+self.handshake(client_seq=101), SERVER))
        self.assertFalse(report.flows(self.handshake()[1:], SERVER))

    def test_wrong_ack_or_missing_greeting_not_invented(self):
        rows = self.handshake(); rows[1]['ack'] += 1
        flow = next(iter(report.flows(rows, SERVER).values()))
        self.assertIsNone(flow['server_isn']); self.assertIsNone(flow['server_first_payload'])

    def test_clock_brackets_reject_steps(self):
        a = dict(host_before_ns=10**12, host_after_ns=10**12+10**6, clock=dict(realtime_ns=2*10**12))
        self.assertLess(report.host_offset([a])[0], report.host_offset([a])[1])
        b = dict(a, clock=dict(realtime_ns=2*10**12+10**9))
        with self.assertRaises(ValueError): report.host_offset([a, b])

    def test_full_report_matches_flow_and_host_tunnel_without_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = 'b'*64
            with capture_timing(root), phase('route.usb'), phase('device.tunnel'):
                pass
            events = [json.loads(l) for l in (root/'host-timing.jsonl').read_text().splitlines()]
            tunnel = next(e for e in events if e.get('phase')=='device.tunnel' and e['event']=='begin')
            syn_time = tunnel['host_monotonic_ns']
            clocks = [dict(event='clock', realtime_ns=syn_time, monotonic_before_ns=syn_time,
                           monotonic_after_ns=syn_time, boottime_ns=syn_time)]*2
            packets = self.handshake()
            for p in packets: p['realtime_ns']=syn_time
            raw = ''.join(json.dumps(r)+'\n' for r in clocks[:1]+packets+clocks[1:]).encode()
            state = dict(schema=1, run_id=TOKEN, source_sha256=source, address=SERVER, passed=True,
                         reason='stopped', rejected=0, packets=3, reads=3, bytes=len(raw),
                         interface_index=5, final_interface_index=5, stats=dict(received=3,dropped=0, interface_dropped=0),
                         metadata_sha256=hashlib.sha256(raw).hexdigest())
            for side in ('mac','device'):
                p=root/('tcp-'+side);p.mkdir();(p/'packets.jsonl').write_bytes(raw);(p/'result.json').write_text(json.dumps(state))
            manifest=dict(run_id=TOKEN, source_sha256=source, address=SERVER,
                          mac_clocks=[dict(host_before_ns=syn_time,host_after_ns=syn_time,clock=dict(realtime_ns=syn_time))]*2)
            (root/'tcp-run.json').write_text(json.dumps(manifest))
            summary=report.report(root)
            self.assertEqual(summary['matched_greeting_flows'],1)
            self.assertTrue(summary['flows'][0]['host_tunnel_unique'])
            self.assertFalse(summary['flows'][0]['host_tunnel_identity_verified'])
            self.assertNotIn(SECRET.decode(),json.dumps(summary))
            manifest['mac_clocks'].append(dict(host_before_ns=0,host_after_ns=0,clock=dict(realtime_ns=0)))
            (root/'tcp-run.json').write_text(json.dumps(manifest))
            self.assertEqual(report.report(root),summary)
            manifest.update(mode='smoke', device=dict(sleep_unit=True), supervisor_sha256='c'*64)
            (root/'tcp-run.json').write_text(json.dumps(manifest))
            supervised=dict(run_id=TOKEN, source_sha256='c'*64, passed=True, command_started=True,
                            command_returncode=0, recorder_returncode=0, cleanup_errors=[],
                            cgroup='0::/system.slice/gameshellneo-sleep-test.service\n')
            smoke=dict(run_id=TOKEN, passed=True, cgroup=supervised['cgroup'],
                       active_units=['gameshellneo-sleep-test.service'])
            (root/'tcp-device/supervisor.json').write_text(json.dumps(supervised))
            (root/'tcp-device/smoke.json').write_text(json.dumps(smoke))
            self.assertEqual(report.report(root)['matched_greeting_flows'],1)
            for field, bad in [('run_id','f'*32),('source_sha256','d'*64),('passed',False),
                               ('command_started',False),('command_returncode',7),('recorder_returncode',1),
                               ('cleanup_errors',['OSError']),('cgroup','0::/other\n')]:
                (root/'tcp-device/supervisor.json').write_text(json.dumps(supervised|{field:bad}))
                with self.assertRaisesRegex(ValueError,'lifecycle'):report.report(root)
            (root/'tcp-device/supervisor.json').write_text(json.dumps(supervised))
            (root/'tcp-device/smoke.json').write_text(json.dumps(smoke|{'active_units':['gameshellneo-foreign.service']}))
            with self.assertRaisesRegex(ValueError,'ownership'):report.report(root)
            (root/'tcp-device/smoke.json').write_text(json.dumps(smoke))
            state['stats']['dropped']=1
            (root/'tcp-device/result.json').write_text(json.dumps(state))
            with self.assertRaises(ValueError): report.report(root)


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('ssh_trace', Path(__file__).resolve().parents[1]/'check-ssh-trace.py')
        cls.runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.runner)

    def test_sleep_readiness_gate_precedes_any_connection(self):
        with patch.object(sys,'argv',['check-ssh-trace.py','--sleep']), patch.dict(os.environ,{},clear=True), \
                patch.object(self.runner,'load_env') as load, self.assertRaises(ValueError):
            self.runner.main()
        load.assert_not_called()

    def test_collection_attempts_both_sides_when_mac_fails(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.runner,'connect_mac',side_effect=OSError), \
                patch.object(self.runner,'device') as device, patch.object(self.runner,'finish_side') as finish:
            manifest=dict(mac=dict(launch_requested=True),device=dict(launch_requested=True))
            with self.assertRaises(RuntimeError): self.runner.collect({},Path(tmp),manifest)
            self.assertEqual(finish.call_args.args[3],'device')
            device.assert_called_once()

    def test_setup_failure_keeps_original_when_cleanup_fails(self):
        original = OSError('primary')
        with tempfile.TemporaryDirectory() as tmp, patch.object(self.runner,'connect_mac',side_effect=original), \
                patch.object(self.runner,'collect',side_effect=RuntimeError('cleanup')) as cleanup:
            with self.assertRaises(OSError) as caught:
                self.runner.execute({},Path(tmp))
            self.assertIs(caught.exception,original)
            cleanup.assert_called_once()


if __name__ == '__main__':
    unittest.main()
