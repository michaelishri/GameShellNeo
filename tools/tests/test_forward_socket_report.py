"""Independent endpoint evidence must survive recollection and reject drift."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import forward_socket as observer
from test_forward_socket import snapshot, row, TARGET, PEER

spec=importlib.util.spec_from_file_location('socket_host',Path(__file__).resolve().parents[1]/'check-forward-socket.py')
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)


class SavedSocketTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in ('forward_socket.py','check-forward-socket.py'):
            (self.root/name).write_text('saved source')
        source=hashlib.sha256(b'saved source').hexdigest()
        values={'baseline':snapshot([]),'opened':snapshot([row()]),
                'two-forwards':snapshot([row(),row(40002,10)]),'other-transport':snapshot([row()])}
        for name,value in values.items():
            value.update(schema=1,source_sha256=source)
            self.save(name+'.json',dict(host_before_ns=1,host_after_ns=2,snapshot=value))
        health=dict(boot_id='same-boot',pm=dict(success=11,fail=0))
        self.save('board-identity.json',dict(connection=PEER,health=health))
        self.save('other-board-identity.json',dict(connection=PEER.replace('40001','50001'),health=health))
        self.result=dict(schema=1,passed=True,cleanup_errors=[],route='usb',source_sha256=source,
                         before=health,after=health,limits='fixture',
                         binding=observer.correlate(values['baseline'],values['opened'],TARGET,PEER))
        self.rehash()

    def save(self,name,value):
        (self.root/name).write_text(json.dumps(value))

    def rehash(self):
        self.result['artifact_sha256']={name:hashlib.sha256((self.root/name).read_bytes()).hexdigest() for name in host.ARTIFACTS}
        self.save('socket-smoke.json',self.result)

    def test_saved_endpoint_comparison_passes_without_network(self):
        result=host.report(self.root)
        self.assertTrue(result['awake_controls_passed'])
        self.assertNotIn('192.0.2',json.dumps(result))

    def test_unrecorded_source_or_raw_observation_change_rejected(self):
        (self.root/'opened.json').write_text('{}')
        with self.assertRaises(ValueError):host.report(self.root)

    def test_even_rehashed_wrong_board_endpoint_rejected(self):
        value=json.loads((self.root/'board-identity.json').read_text())
        value['connection']=PEER.replace('40001','60001');self.save('board-identity.json',value);self.rehash()
        with self.assertRaises(ValueError):host.report(self.root)

    def test_rehashed_other_transport_and_source_inconsistency_rejected(self):
        value=json.loads((self.root/'other-board-identity.json').read_text())
        value['connection']=PEER;self.save('other-board-identity.json',value);self.rehash()
        with self.assertRaises(ValueError):host.report(self.root)
        value['connection']=PEER.replace('40001','50001');self.save('other-board-identity.json',value)
        snap=json.loads((self.root/'opened.json').read_text());snap['snapshot']['source_sha256']='f'*64
        self.save('opened.json',snap);self.rehash()
        with self.assertRaises(ValueError):host.report(self.root)

    def test_failed_or_incomplete_capture_cannot_be_requalified(self):
        self.result['passed']=False;self.rehash()
        with self.assertRaises(ValueError):host.report(self.root)
        self.result['passed']=True;self.result['artifact_sha256'].pop('board-identity.json')
        self.save('socket-smoke.json',self.result)
        with self.assertRaises(ValueError):host.report(self.root)

    def test_cleanup_failure_retains_primary_failure_and_records_cleanup_problem(self):
        mac=MagicMock();mac.open_sftp.return_value.__enter__.return_value.remove.side_effect=OSError('cleanup failed')
        cleanup=[];original=ValueError('first failure')
        with patch.object(host,'run',return_value=b'/tmp/gameshellneo-socket.12345678'),patch.object(host,'upload'), \
                self.assertRaises(ValueError) as caught:
            with host.helper(mac,cleanup):raise original
        self.assertIs(caught.exception,original)
        self.assertEqual(cleanup,['mac-helper-cleanup-failed'])


if __name__=='__main__':unittest.main()
