"""Reject ambiguous socket identity, retain bounded metadata and reap observers."""
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import forward_socket as observer

OUTER = '198.51.100.2 30001 192.0.2.1 22'
TARGET = ['192.0.2.10',22]
PEER = '192.0.2.1 40001 192.0.2.10 22'


def row(port=40001, fd=9):
    return dict(fd=fd,local=['192.0.2.1',port],remote=TARGET.copy(),state='ESTABLISHED',
                receive_queue=0,send_queue=0)


def snapshot(rows):
    return dict(worker=dict(pid=123,ppid=122,started='Thu Oct 8 07:00:00 2026',sshd=True),
                outer=observer.connection(OUTER),sockets=rows)


def raw():
    return b'p123\0\nf9\0PTCP\0n192.0.2.1:40001->192.0.2.10:22\0TST=ESTABLISHED\0TQR=0\0TQS=5\0\n'


class SocketIdentityTests(unittest.TestCase):
    def test_lsof_fields_and_ipv6_are_parsed_without_payload_or_command_names(self):
        result=observer.parse_lsof(raw(),123)
        self.assertEqual(result,[dict(row(),send_queue=5)])
        data=raw().replace(b'192.0.2.1:40001->192.0.2.10:22',b'[2001:db8::1]:40001->[2001:db8::2]:22')
        self.assertEqual(observer.parse_lsof(data,123)[0]['local'],['2001:db8::1',40001])

    def test_bad_listings_fail_closed(self):
        variants=[raw()[:-1],raw().replace(b'p123',b'p124'),raw().replace(b'PTCP',b'PUDP'),
                  raw().replace(b'TQS=5',b'TQS=5\0TQS=7'),raw().replace(b'TST=ESTABLISHED',b'TST=UNKNOWN'),
                  raw().replace(b'f9',b'f-9'),raw().replace(b'TQR=0',b'TQR=-1'),
                  raw().replace(b'n192.0.2.1:40001->192.0.2.10:22\0',b''),
                  raw().replace(b'192.0.2.1',b'private-hostname'), b'x'*(observer.MAX_BYTES+1),
                  raw()+raw()]
        for data in variants:
            with self.subTest(data=data[:20]),self.assertRaises(ValueError):observer.parse_lsof(data,123)

    def test_missing_queues_are_unknown_and_duplicate_fds_rejected(self):
        data=raw().replace(b'TQR=0\0TQS=5\0',b'')
        self.assertIsNone(observer.parse_lsof(data,123)[0]['receive_queue'])
        with self.assertRaises(ValueError):observer.parse_lsof(raw()+raw().split(b'\n',1)[1],123)

    def test_board_endpoint_independently_confirms_new_flow_with_duplicate_descriptors(self):
        result=observer.correlate(snapshot([]),snapshot([row(),row(fd=10)]),TARGET,PEER)
        self.assertTrue(result['independently_confirmed']);self.assertEqual(result['fds'],[9,10])

    def test_two_new_flows_and_existing_flow_are_not_unique_requests(self):
        with self.assertRaises(ValueError):
            observer.correlate(snapshot([]),snapshot([row(),row(40002,10)]),TARGET,PEER)
        with self.assertRaises(ValueError):
            observer.correlate(snapshot([row()]),snapshot([row()]),TARGET,PEER)

    def test_pid_reuse_outer_change_and_wrong_board_endpoint_are_rejected(self):
        before=snapshot([])
        for name in ('pid','ppid','started'):
            after=snapshot([row()]);after['worker'][name]='changed'
            with self.assertRaises(ValueError):observer.correlate(before,after,TARGET,PEER)
        after=snapshot([row()]);after['outer']['client'][1]+=1
        with self.assertRaises(ValueError):observer.correlate(before,after,TARGET,PEER)
        for peer in (PEER.replace('40001','40002'),PEER.replace('192.0.2.10','192.0.2.11')):
            with self.assertRaises(ValueError):observer.correlate(before,snapshot([row()]),TARGET,peer)

    def test_nonestablished_state_cannot_confirm_a_healthy_board_connection(self):
        after=snapshot([dict(row(),state='SYN_SENT')])
        with self.assertRaises(ValueError):observer.correlate(snapshot([]),after,TARGET,PEER)

    def test_snapshot_requires_worker_to_own_exact_outer_transport(self):
        identity=snapshot([])['worker']
        for payload in (raw(),raw().replace(b'192.0.2.1:40001->192.0.2.10:22',b'192.0.2.1:22->198.51.100.2:30001')):
            with patch.object(observer.sys,'platform','darwin'),patch.dict(os.environ,SSH_CONNECTION=OUTER), \
                    patch.object(observer.os,'getppid',return_value=123), \
                    patch.object(observer,'process',return_value=identity),patch.object(observer,'bounded_command',return_value=payload):
                if payload==raw():
                    with self.assertRaises(ValueError):observer.snapshot()
                else:
                    result=observer.snapshot();self.assertEqual(result['worker'],identity)
                    self.assertNotIn('command',result['worker'])

    def test_process_change_during_lsof_is_rejected(self):
        first=snapshot([])['worker'];second=dict(first,started='changed')
        with patch.object(observer.sys,'platform','darwin'),patch.dict(os.environ,SSH_CONNECTION=OUTER), \
                patch.object(observer.os,'getppid',return_value=123), \
                patch.object(observer,'process',side_effect=[first,second]),patch.object(observer,'bounded_command',return_value=raw()):
            with self.assertRaises(ValueError):observer.snapshot()

    def test_bounded_subprocess_drains_both_streams_and_rejects_warning(self):
        self.assertEqual(observer.bounded_command([sys.executable,'-c','print(123)'],time.monotonic()+2),b'123\n')
        with self.assertRaises(ValueError):
            observer.bounded_command([sys.executable,'-c','import sys;sys.stderr.write("warning")'],time.monotonic()+2)

    def test_subprocess_timeout_and_output_overflow_are_bounded(self):
        start=time.monotonic()
        with self.assertRaises(TimeoutError):
            observer.bounded_command([sys.executable,'-c','import time;time.sleep(20)'],time.monotonic()+0.2)
        with self.assertRaises(ValueError):
            observer.bounded_command([sys.executable,'-c','import sys,time;sys.stdout.write("x"*100000);sys.stdout.flush();time.sleep(20)'],time.monotonic()+2)
        self.assertLess(time.monotonic()-start,3)


if __name__=='__main__':unittest.main()
