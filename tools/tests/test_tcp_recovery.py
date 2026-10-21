"""Capture pressure selection and explicit discontinuity boundaries."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tcp_metadata as tcp
import tcp_report as report
from test_tcp_metadata import packet, SERVER, CLIENT, TOKEN
import test_tcp_metadata as fixtures
from host_timing import capture_timing, phase


class Selection(unittest.TestCase):
    def test_bulk_is_countably_omitted_but_late_first_payload_and_controls_survive(self):
        selector=tcp.FlowSelection(SERVER)
        selector.keep(packet(payload=b'',seq=200,flags=18))
        for _ in range(15): self.assertTrue(selector.keep(packet(seq=900)))
        self.assertFalse(selector.keep(packet(payload=b'encrypted',seq=900)))
        self.assertTrue(selector.keep(packet(payload=b'not-an-ssh-prefix',seq=201)))
        for flags in (2,18,1,4):
            self.assertTrue(selector.keep(packet(payload=b'',flags=flags)))
        zero=packet(payload=b'',seq=901);zero['window']=0
        self.assertTrue(selector.keep(zero))

    def test_flow_memory_bound_and_tuple_reuse_syn_retained(self):
        selector=tcp.FlowSelection(SERVER)
        for port in range(tcp.MAX_FLOWS): selector.keep(packet(dport=50000+port))
        with self.assertRaises(ValueError):selector.keep(packet(dport=60000))
        for _ in range(20): selector.keep(packet(payload=b'bulk',seq=900))
        self.assertTrue(selector.keep(packet(payload=b'', source=CLIENT,destination=SERVER,
                                             sport=50000,dport=22,flags=2,seq=1234)))


class Reopen(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(tcp.socket,'if_nametoindex',return_value=27))
        self.now=0
        self.enterContext(patch.object(tcp.time,'monotonic',side_effect=lambda:self.now))
        self.first=Mock();self.second=Mock()
        for backend in (self.first,self.second):
            backend.stats.return_value=dict(received=1,dropped=0,interface_dropped=0)
            backend.read.return_value=None
        self.factory=Mock(side_effect=[self.first,self.second])

    def test_disappearance_reopens_in_new_segment_and_retains_gap(self):
        backend=tcp.ReopeningPcap('en1',SERVER,factory=self.factory)
        self.first.read.side_effect=tcp.CaptureError('read','interface-disappeared',-1,6)
        self.assertIsNone(backend.read());self.assertIsNone(backend.fileno())
        self.first.close.assert_called_once();self.assertEqual(len(backend.gaps),1)
        self.assertEqual(self.factory.call_count,1)
        backend.read();self.assertEqual(self.factory.call_count,1)
        self.now=2;backend.read()
        self.assertEqual(backend.segment,1);self.assertIsNotNone(backend.gaps[0]['ended'])
        self.assertEqual(backend.segments[0]['error']['category'],'interface-disappeared')
        backend.stats();backend.close();self.second.close.assert_called_once()
        self.assertIsNone(backend.segments[1]['error'])

    def test_unknown_read_error_is_not_retried(self):
        backend=tcp.ReopeningPcap('en1',SERVER,factory=self.factory)
        self.first.read.side_effect=tcp.CaptureError('read','read-failed',-1,5)
        with self.assertRaises(tcp.CaptureError):backend.read()
        self.assertEqual(self.factory.call_count,1);self.assertFalse(backend.gaps)
        backend.close()

    def test_retry_budget_is_global_and_stops(self):
        self.factory.side_effect=None;self.factory.return_value=self.first
        backend=tcp.ReopeningPcap('en1',SERVER,factory=self.factory)
        self.first.read.side_effect=tcp.CaptureError('read','interface-disappeared')
        backend.read();self.factory.side_effect=tcp.CaptureError('open','unavailable')
        for n in range(60):self.now=n+2;backend.read()
        self.now=63
        with self.assertRaises(tcp.CaptureError) as caught:backend.read()
        self.assertEqual(caught.exception.category,'attempt-limit')
        self.assertEqual(backend.attempts,60);self.assertIsNone(backend.gaps[0]['ended'])
        backend.close()

    def test_unavailable_stats_never_look_clean(self):
        backend=tcp.ReopeningPcap('en1',SERVER,factory=self.factory)
        self.first.stats.side_effect=tcp.CaptureError('stats','unavailable')
        backend.stats();backend.close()
        self.assertIsNone(backend.segments[0]['stats'])
        self.assertEqual(backend.segments[0]['error']['phase'],'stats')

    def test_synthetic_gap_only_closes_handle(self):
        backend=tcp.ReopeningPcap('en1',SERVER,32,factory=self.factory)
        backend.reads=32;backend.read()
        self.assertTrue(backend.injected)
        self.assertEqual(backend.gaps[0]['error']['category'],'injected-interface-gap')
        self.now=2;backend.read();backend.read()
        self.assertEqual(len(backend.gaps),1);backend.close()

    def test_pcap_error_does_not_persist_backend_message(self):
        backend=tcp.PcapPackets.__new__(tcp.PcapPackets)
        backend.Header=type('Header',(tcp.C.Structure,),{'_fields_':[]})
        backend.handle=123;backend.lib=Mock()
        backend.lib.pcap_next_ex.return_value=-1
        for message,category in [(b'The interface disappeared','interface-disappeared'),
                                 (b'private endpoint and secret details','read-failed')]:
            backend.lib.pcap_geterr.return_value=message
            with self.assertRaises(tcp.CaptureError) as caught:backend.read()
            self.assertEqual(caught.exception.record()['category'],category)
            self.assertNotIn(message.decode(),json.dumps(caught.exception.record()))


class SegmentReports(unittest.TestCase):
    def fixture(self, root):
        with capture_timing(root),phase('route.usb'),phase('device.tunnel'):pass
        events=[json.loads(l) for l in (root/'host-timing.jsonl').read_text().splitlines()]
        t=next(e['host_monotonic_ns'] for e in events if e['event']=='begin' and e['phase']=='device.tunnel')
        stamp=lambda n:dict(realtime_ns=n,monotonic_before_ns=n,monotonic_after_ns=n,boottime_ns=n)
        good=dict(received=3,dropped=0,interface_dropped=0)
        for side in ('mac','device'):
            path=root/('tcp-'+side);path.mkdir()
            packets=fixtures.CorrelationTests().handshake()
            for p in packets:p.update(segment=int(side=='mac'),realtime_ns=t,observed_monotonic_ns=t)
            rows=[dict(event='clock',**stamp(t-3000))]+packets+[dict(event='clock',**stamp(t+3000))]
            raw=''.join(json.dumps(r)+'\n' for r in rows).encode();(path/'packets.jsonl').write_bytes(raw)
            segments=[dict(id=0,interface_index=5,opened=stamp(t-2000),closed=stamp(t+2000),stats=good,error=None)]
            gaps=[]
            if side=='mac':
                segments[0].update(closed=stamp(t-1000),stats=None,error=dict(phase='read',category='interface-disappeared',status=-1,errno=6))
                segments.append(dict(id=1,interface_index=5,opened=stamp(t-500),closed=stamp(t+2000),stats=good,error=None))
                gaps=[dict(after_segment=0,started=stamp(t-1000),ended=stamp(t-500),error=segments[0]['error'],reopen_attempts=1)]
            result=dict(schema=3,run_id=TOKEN,source_sha256='b'*64,address=SERVER,passed=side!='mac',reason='stopped',
                rejected=0,packets=3,reads=3,matched=3,selected_out=0,selection='flow-prefix16-control-first-payload',
                bytes=len(raw),interface_index=5,final_interface_index=5,
                stats=good if side=='device' else dict(good,interface_dropped=None),segments=segments,gaps=gaps,test_gap_after=0,
                metadata_sha256=hashlib.sha256(raw).hexdigest())
            (path/'result.json').write_text(json.dumps(result))
        manifest=dict(run_id=TOKEN,source_sha256='b'*64,address=SERVER,
                      mac_clocks=[dict(host_before_ns=t,host_after_ns=t,clock=dict(realtime_ns=t))]*2)
        (root/'tcp-run.json').write_text(json.dumps(manifest))

    def test_gap_fails_strict_but_positive_flow_in_clean_segment_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            with self.assertRaises(ValueError):report.report(root)
            value=report.report(root,partial=True)
            self.assertFalse(value['metadata_valid']);self.assertEqual(value['mac_qualified_segments'],[1])
            self.assertEqual(value['matched_greeting_flows'],1)
            f=root/'tcp-mac/result.json';d=json.loads(f.read_text());d['passed']=True;f.write_text(json.dumps(d))
            with self.assertRaises(ValueError):report.report(root)
            d['segments'][1]['stats']['dropped']=1;d['stats']['dropped']=1;f.write_text(json.dumps(d))
            value=report.report(root,partial=True)
            self.assertFalse(value['mac_qualified_segments']);self.assertEqual(value['matched_greeting_flows'],0)

    def test_partial_cannot_join_handshake_across_segments(self):
        packets=fixtures.CorrelationTests().handshake()
        for p in packets:p['segment']=0
        packets[-1]['segment']=1
        flow=next(iter(report.flows(packets,SERVER).values()))
        self.assertIsNone(flow['server_first_payload'])
        # A retransmitted SYN/handshake in two segments is ambiguous.
        other=[dict(p,segment=2) for p in fixtures.CorrelationTests().handshake()]
        self.assertFalse(report.flows(packets+other,SERVER))

    def test_missing_gap_and_selection_mismatch_rejected_even_in_partial_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            f=root/'tcp-mac/result.json';d=json.loads(f.read_text())
            f.write_text(json.dumps(d|{'gaps':[]}))
            with self.assertRaises(ValueError):report.report(root,partial=True)
            f.write_text(json.dumps(d|{'matched':4}))
            with self.assertRaises(ValueError):report.report(root,partial=True)

    def test_gap_boundaries_counters_and_interface_must_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.fixture(root)
            f=root/'tcp-mac/result.json';original=f.read_text()
            for change in ('unknown_end','reversed_start','wrong_error','zero_attempts','hidden_drop','unmarked_injection'):
                with self.subTest(change=change):
                    d=json.loads(original);g=d['gaps'][0]
                    if change=='unknown_end':g['ended']=None
                    elif change=='reversed_start':g['started']=d['segments'][0]['opened']
                    elif change=='wrong_error':g['error']['category']='read-failed'
                    elif change=='zero_attempts':g['reopen_attempts']=0
                    elif change=='hidden_drop':d['segments'][1]['stats']['dropped']=1
                    elif change=='unmarked_injection':
                        g['error']['category']='injected-interface-gap'
                        d['segments'][0]['error']=g['error']
                    f.write_text(json.dumps(d))
                    with self.assertRaises(ValueError):report.report(root,partial=True)
            d=json.loads(original);d['final_interface_index']=99;f.write_text(json.dumps(d))
            self.assertEqual(report.report(root,partial=True)['matched_greeting_flows'],0)


class HostModes(unittest.TestCase):
    def test_injection_cannot_be_combined_with_sleep_or_another_operation(self):
        spec=importlib.util.spec_from_file_location('trace_host',Path(tcp.__file__).with_name('check-ssh-trace.py'))
        host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
        for other in ('sleep','smoke','burst'):
            with patch.object(host,'connect_mac') as connect:
                with self.assertRaisesRegex(ValueError,'injection cannot accompany sleep'):
                    host.execute({},Path('/unused'),gap_smoke=True,**{other:True})
                connect.assert_not_called()


if __name__=='__main__':unittest.main()
