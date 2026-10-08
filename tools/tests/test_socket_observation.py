"""Socket diagnostics must preserve the first SSH outcome, counts and lifecycle."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import paramiko
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import host_timing
import remote
import socket_observation as observer
from test_forward_socket import snapshot, row, TARGET


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.client=MagicMock()
        self.enterContext(patch.object(remote.paramiko,'SSHClient')).return_value.__enter__.return_value=self.client
        self.enterContext(patch.object(remote,'private_path')).return_value.read_text.return_value='ssh-ed25519 AA=='
        self.enterContext(patch.object(remote.paramiko,'Ed25519Key'))
        self.mac=MagicMock()
        self.channel=self.mac.get_transport.return_value.open_channel.return_value
        for key,value in dict(active=True,closed=False,eof_received=False,eof_sent=False).items():
            setattr(self.channel,key,value)
        self.channel.recv_ready.return_value=False
        self.channel.send.side_effect=len
        self.channel.recv.return_value=b''
        transport=self.client.get_transport.return_value
        transport.remote_version='';transport.initial_kex_done=False
        transport.is_authenticated.return_value=False;transport.is_active.return_value=True
        self.order=[]
        self.error=paramiko.SSHException('private original error')
        def connect(*args,**kwargs):
            self.order.append('connect')
            self.sock=kwargs['sock']
            self.sock.send(b'private client data')
            self.sock.recv(4096)
            raise self.error
        self.client.connect.side_effect=connect
        self.snapshots=0
        self.inline=self.enterContext(patch.object(observer,'inline_snapshot',side_effect=self.snapshot))

    def snapshot(self,mac,source):
        self.snapshots+=1
        self.order.append('baseline' if self.snapshots==1 else 'collect')
        if self.snapshots==2:
            # Collection occurs before explicit client/channel cleanup, and
            # after the SSH span's original error and first state were written.
            self.channel.close.assert_not_called()
            self.client.__exit__.assert_not_called()
            records=[json.loads(x) for x in (self.root/'host-timing.jsonl').read_text().splitlines()]
            self.assertEqual(records[-2]['phase'],'device.ssh')
            self.assertEqual(records[-2]['event'],'end')
            self.assertEqual(records[-1]['phase'],'socket.collect')
            self.sock.recv(4096)  # Simulate later activity: original count stays frozen.
        outer=dict(fd=3,local=['192.0.2.1',22],remote=['198.51.100.2',30001],state='ESTABLISHED',
                   receive_queue=0,send_queue=0)
        value=snapshot([outer]+([row()] if self.snapshots==2 else []))
        value.update(schema=1,source_sha256=hashlib.sha256(source).hexdigest())
        return value

    def run_failure(self):
        with observer.capture(self.root),host_timing.capture_timing(self.root):
            with self.assertRaises(paramiko.SSHException) as caught:
                with remote.forwarded_device({},self.mac,*TARGET):self.fail('Unexpected success')
        self.assertIs(caught.exception,self.error)
        self.client.connect.assert_called_once()
        self.channel.close.assert_called_once()

    def test_original_exception_counters_and_order_survive_collection(self):
        self.run_failure()
        self.assertEqual(self.order,['baseline','connect','collect'])
        result=observer.report(self.root)
        self.assertEqual(result['observations'][0]['status'],'unique-worker-candidate')
        self.assertFalse(result['observations'][0]['independently_confirmed'])
        item=json.loads((self.root/'socket-observations/0001.json').read_text())
        self.assertEqual(item['states']['forward']['recv_calls'],1)
        self.assertEqual(self.sock.counts['recv_calls'],2)
        self.assertNotIn('private',json.dumps(item))
        kwargs=self.client.connect.call_args.kwargs
        self.assertEqual([kwargs[k] for k in ('timeout','auth_timeout','banner_timeout')],[10,10,10])
        for path in (self.root/'socket-observations').iterdir():
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_unavailable_baseline_does_not_delay_greeting_or_replace_exception(self):
        self.inline.side_effect=TimeoutError('private command')
        self.run_failure()
        self.inline.assert_called_once()
        self.assertEqual(observer.report(self.root)['observations'][0]['status'],'unavailable')

    def test_unavailable_collection_and_failed_write_preserve_primary(self):
        original=self.snapshot
        def broken(mac,source):
            if self.snapshots:raise OSError('observer command failed')
            return original(mac,source)
        self.inline.side_effect=broken
        self.run_failure()
        self.assertEqual(observer.report(self.root)['observations'][0]['status'],'unavailable')

    def test_disk_full_cannot_replace_primary_or_claim_complete(self):
        with observer.capture(self.root) as capture,host_timing.capture_timing(self.root):
            with patch.object(observer,'write_private',side_effect=OSError('full disk')):
                with self.assertRaises(paramiko.SSHException) as caught:
                    with remote.forwarded_device({},self.mac,*TARGET):self.fail('Unexpected success')
                self.assertIs(caught.exception,self.error)
                self.assertTrue(capture.write_failed)
        with self.assertRaises(ValueError):observer.report(self.root)

    def test_default_off_keeps_exact_original_forward_and_no_mac_commands(self):
        with self.assertRaises(paramiko.SSHException):
            with remote.forwarded_device({},self.mac,*TARGET):self.fail('Unexpected success')
        self.assertIs(self.sock,self.channel)
        self.inline.assert_not_called()
        self.mac.get_transport.return_value.open_session.assert_not_called()

    def test_observer_requires_both_explicit_capture_and_timing(self):
        with observer.capture(self.root):
            self.assertIsNone(observer.prepare(self.mac,*TARGET))
        self.inline.assert_not_called()

    def test_tunnel_error_no_authentication_and_original_exception_retained(self):
        self.mac.get_transport.return_value.open_channel.side_effect=self.error
        with observer.capture(self.root),host_timing.capture_timing(self.root):
            with self.assertRaises(paramiko.SSHException) as caught:
                with remote.forwarded_device({},self.mac,*TARGET):self.fail('Unexpected success')
        self.assertIs(caught.exception,self.error)
        self.client.connect.assert_not_called()
        item=json.loads((self.root/'socket-observations/0001.json').read_text())
        self.assertEqual(item['outcome'],'tunnel-error')
        self.assertEqual(item['states'],{})

    def test_collection_never_runs_inside_successful_handshake(self):
        def success(*args,**kwargs):
            self.order.append('connect');self.sock=kwargs['sock']
        self.client.connect.side_effect=success
        with observer.capture(self.root),host_timing.capture_timing(self.root):
            with remote.forwarded_device({},self.mac,*TARGET) as client:
                self.assertIs(client,self.client)
        self.assertEqual(self.order,['baseline','connect','collect'])
        self.assertEqual(observer.report(self.root)['observations'][0]['outcome'],'ok')

    def test_record_limit_prevents_more_remote_observation_work(self):
        with observer.capture(self.root) as capture,host_timing.capture_timing(self.root):
            capture.attempts=observer.MAX_ATTEMPTS
            self.assertIsNone(observer.prepare(self.mac,*TARGET))
            self.assertTrue(capture.limited)
        self.inline.assert_not_called()

    def test_record_and_source_drift_are_rejected(self):
        self.run_failure()
        root=self.root/'socket-observations'
        index=json.loads((root/'index.json').read_text())
        file=root/'0001.json';value=json.loads(file.read_text())
        value['states']['forward']['received_bytes']=12
        file.write_text(json.dumps(value))
        with self.assertRaises(ValueError):observer.report(self.root)
        index['artifact_sha256'][file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
        (root/'index.json').write_text(json.dumps(index))
        with self.assertRaisesRegex(ValueError,'state changed'):observer.report(self.root)


class InlineObserverTests(unittest.TestCase):
    def test_inline_result_source_mismatch_output_bounds_and_cleanup(self):
        source=b'fixture source'
        cases=[b'{}',b'x'*(65536+1),json.dumps(dict(schema=1,source_sha256=hashlib.sha256(source).hexdigest())).encode()]
        for data in cases:
            mac=MagicMock();channel=mac.get_transport.return_value.open_session.return_value
            channel.recv.side_effect=[data,b''];channel.recv_exit_status.return_value=0
            if data==cases[-1]:self.assertEqual(observer.inline_snapshot(mac,source)['schema'],1)
            else:
                with self.assertRaises(ValueError):observer.inline_snapshot(mac,source)
            channel.sendall.assert_called_once_with(source)
            channel.close.assert_called_once()

    def test_watchdog_closes_blocked_request_without_retry(self):
        import threading
        mac=MagicMock();channel=mac.get_transport.return_value.open_session.return_value
        closed=threading.Event()
        channel.close.side_effect=closed.set
        def blocked(command):
            if not closed.wait(1):raise AssertionError('No request watchdog')
            raise TimeoutError('request closed')
        channel.exec_command.side_effect=blocked
        real_timer=threading.Timer
        with patch.object(observer.threading,'Timer',side_effect=lambda _,callback:real_timer(0.03,callback)):
            start=time.monotonic()
            with self.assertRaises(TimeoutError):observer.inline_snapshot(mac,b'source')
            self.assertLess(time.monotonic()-start,1)
        channel.exec_command.assert_called_once();channel.sendall.assert_not_called()


if __name__=='__main__':unittest.main()
