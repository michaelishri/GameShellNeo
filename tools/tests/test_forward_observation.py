"""Observe forwarding without retries, read-ahead, payloads or error replacement."""
import json
import logging
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import host_timing as timing
import remote

SECRET=b'private address password banner payload'


class ForwardObservation(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_unrecorded_channel_is_unchanged(self):
        channel=object()
        self.assertIs(timing.observe_forward(channel),channel)

    def test_partial_io_errors_and_timeout_delegate_exactly_without_payload(self):
        channel=MagicMock(active=True,closed=False,eof_received=False,eof_sent=False)
        channel.recv_ready.return_value=False
        error=OSError('private failure')
        timeout=socket.timeout('private timeout')
        channel.send.side_effect=[2,error]
        channel.recv.side_effect=[SECRET,timeout,b'']
        with timing.capture_timing(self.root):
            with timing.phase('device.tunnel'):wrapped=timing.observe_forward(channel)
            with timing.phase('device.ssh'):
                self.assertEqual(wrapped.send(SECRET),2)
                with self.assertRaises(OSError) as caught:wrapped.send(SECRET)
                self.assertIs(caught.exception,error)
                self.assertEqual(wrapped.recv(128),SECRET)
                with self.assertRaises(socket.timeout) as caught:wrapped.recv(128)
                self.assertIs(caught.exception,timeout)
                self.assertEqual(wrapped.recv(128),b'')
                wrapped.settimeout(0.125)
                timing.forward_state(wrapped)
        channel.settimeout.assert_called_once_with(0.125)
        self.assertEqual(channel.recv.call_count,3)
        end=timing.summarize(self.root)['forward_states'][-1]
        self.assertEqual((end['sent_bytes'],end['received_bytes']),(2,len(SECRET)))
        self.assertEqual((end['send_errors'],end['recv_timeouts']),(1,1))
        self.assertNotIn(SECRET.decode(),(self.root/'host-timing.jsonl').read_text())

    def test_failed_inspection_keeps_counts_and_original_connect_failure(self):
        class Channel:
            def __getattr__(self,name):raise RuntimeError('private inspection failure')
        original=ValueError('original')
        with self.assertRaises(ValueError) as caught,timing.capture_timing(self.root):
            with timing.phase('device.tunnel'):wrapped=timing.observe_forward(Channel())
            with timing.phase('device.ssh'):
                try:raise original
                finally:timing.forward_state(wrapped)
        self.assertIs(caught.exception,original)
        end=timing.summarize(self.root)['forward_states'][-1]
        self.assertTrue(all(end[k] is None for k in timing.FORWARD_FLAGS))
        self.assertTrue(all(end[k]==0 for k in timing.FORWARD_COUNTS))

    def test_channel_integer_flags_are_boolean_but_other_values_stay_unknown(self):
        channel=MagicMock(active=1,closed=False,eof_received=0,eof_sent=1)
        channel.recv_ready.return_value=False
        with timing.capture_timing(self.root):
            with timing.phase('device.tunnel'):wrapped=timing.observe_forward(channel)
            with timing.phase('device.ssh'):
                channel.active=0;channel.closed=True
                channel.eof_received=2;channel.eof_sent='1'
                channel.recv_ready.return_value=0.0
                timing.forward_state(wrapped)
        opened,finished=timing.summarize(self.root)['forward_states']
        self.assertIs(opened['active'],True)
        self.assertIs(opened['closed'],False)
        self.assertIs(opened['eof_received'],False)
        self.assertIs(opened['eof_sent'],True)
        self.assertIs(finished['active'],False)
        self.assertIs(finished['closed'],True)
        for name in ('eof_received','eof_sent','recv_ready'):
            self.assertIsNone(finished[name])

    def test_remote_observes_before_cleanup_and_preserves_original_error_and_timeouts(self):
        mac=MagicMock();channel=mac.get_transport.return_value.open_channel.return_value
        channel.active=True;channel.closed=False;channel.eof_received=False;channel.eof_sent=False
        channel.recv_ready.return_value=False
        channel.send.return_value=2
        client=MagicMock();client.__enter__.return_value=client
        original=remote.paramiko.SSHException('original')
        def connect(*args,**kwargs):
            kwargs['sock'].send(SECRET)
            raise original
        client.connect.side_effect=connect
        channel.close.side_effect=lambda:setattr(channel,'closed',True)
        with timing.capture_timing(self.root),patch.object(remote,'connect_mac',return_value=nullcontext(mac)), \
                patch.object(remote.paramiko,'SSHClient',return_value=client),patch.object(remote,'private_path') as path, \
                patch.object(remote.paramiko,'Ed25519Key'),self.assertRaises(remote.paramiko.SSHException) as caught:
            path.return_value.read_text.return_value='ssh-ed25519 AA=='
            with remote.device({},'usb'):self.fail('No successful connection')
        self.assertIs(caught.exception,original)
        client.connect.assert_called_once();channel.close.assert_called_once()
        for name in ('timeout','banner_timeout','auth_timeout'):
            self.assertEqual(client.connect.call_args.kwargs[name],10)
        states=timing.summarize(self.root)['forward_states']
        self.assertEqual([r['stage'] for r in states],['opened','connect-finished'])
        self.assertEqual(states[-1]['sent_bytes'],2);self.assertFalse(states[-1]['closed'])

    def real_peer(self,banner):
        local,peer=socket.socketpair();release=threading.Event()
        def serve():
            with peer:
                if banner:peer.sendall(b'SSH-2.0-private-peer\r\n')
                release.wait(3)
        thread=threading.Thread(target=serve,daemon=True);thread.start()
        client=remote.paramiko.SSHClient();client.set_log_channel('forward-test')
        self.enterContext(patch.object(logging.getLogger('forward-test'),'disabled',True))
        try:
            with timing.capture_timing(self.root):
                with timing.phase('device.tunnel'):wrapped=timing.observe_forward(local)
                with self.assertRaises(remote.paramiko.SSHException),timing.phase('device.ssh'):
                    try:
                        client.connect('fixture',sock=wrapped,username='fixture',look_for_keys=False,
                                       allow_agent=False,timeout=0.3,banner_timeout=1,auth_timeout=0.3)
                    finally:
                        timing.ssh_state(client);timing.forward_state(wrapped)
        finally:
            transport=client.get_transport();client.close();local.close();release.set();thread.join(4)
            if transport is not None:transport.join(2)
        self.assertFalse(thread.is_alive())
        self.assertFalse(transport.is_alive())
        self.assertNotIn('private-peer',(self.root/'host-timing.jsonl').read_text())
        return timing.summarize(self.root)

    def test_real_transport_silent_peer_has_sent_bytes_and_no_received_bytes(self):
        report=self.real_peer(False);state=report['forward_states'][-1]
        self.assertGreater(state['sent_bytes'],0);self.assertEqual(state['received_bytes'],0)
        self.assertFalse(report['ssh_states'][0]['banner_received'])

    def test_real_transport_greeting_only_peer_is_distinguishable(self):
        report=self.real_peer(True);state=report['forward_states'][-1]
        self.assertGreater(state['sent_bytes'],0);self.assertGreater(state['received_bytes'],0)
        self.assertTrue(report['ssh_states'][0]['banner_received'])
        self.assertFalse(report['ssh_states'][0]['initial_kex_complete'])

    def test_report_rejects_payload_fields_wrong_phase_duplicate_and_invalid_counts(self):
        with timing.capture_timing(self.root):
            with timing.phase('device.tunnel'):timing.observe_forward(MagicMock())
        file=self.root/'host-timing.jsonl';original=file.read_text()
        for field,value in [('sent_bytes',-1),('received_bytes',True),('active','private'),('stage','connect-finished'),('payload','private')]:
            rows=[json.loads(l) for l in original.splitlines()]
            next(r for r in rows if r['event']=='forward_state')[field]=value
            file.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            with self.assertRaises(ValueError):timing.summarize(self.root)
        rows=[json.loads(l) for l in original.splitlines()]
        index=next(i for i,r in enumerate(rows) if r['event']=='forward_state')
        rows.insert(index,dict(rows[index]));file.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        with self.assertRaises(ValueError):timing.summarize(self.root)


if __name__=='__main__':unittest.main()
