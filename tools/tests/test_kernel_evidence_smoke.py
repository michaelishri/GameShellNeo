"""One awake marker submission, exact original evidence, no PM or silent retry."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import MagicMock,Mock,patch

import test_kernel_evidence as existing

path=Path(__file__).resolve().parents[1]/'check-kernel-evidence.py'
spec=importlib.util.spec_from_file_location('kernel_evidence_smoke',path)
smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)
TOKEN='e'*32


def pair():
    before,lock=existing.snapshot()
    before.update(stats={'success':'53','fail':'0'},backlight={'brightness':'1','bl_power':'0'},
                  inputs=['keypad'],charger={},cpu_policy={},wifi_power_save='on',wifi_config_sha256='fixture')
    after=existing.advance(before,[existing.message(3,'gameshellneo-kernel-evidence-smoke '+TOKEN,15)])
    return before,after,lock


def storage(snapshot):
    file=dict(uid=0,mode=0o600,links=1,regular=True,directory=False,bytes=0,inode=1,mtime_ns=1)
    return dict(boot_id=snapshot['boot_id'],entries=['checkpoint.json','lock'],marker=None,
        directory=dict(uid=0,mode=0o700,links=2,regular=False,directory=True,bytes=4096,inode=2,mtime_ns=1),
        files={'lock':dict(file),'checkpoint.json':dict(file,bytes=len(existing.evidence.encoded(snapshot[existing.evidence.KEY])))})


class Validation(unittest.TestCase):
    def test_original_marker_is_preserved_but_not_used_as_kernel_text(self):
        a,b,lock=pair()
        result=smoke.validate(a,b,TOKEN,lock,existing.pm_tests.pm)
        self.assertTrue(result['passed']);self.assertEqual(result['marker_sequence'],3)
        self.assertEqual(a['journal'],b['journal'])
        smoke.validate_storage(storage(b),b)

    def test_missing_duplicate_kernel_origin_marker_and_pm_change_reject(self):
        a,b,lock=pair()
        duplicate=existing.advance(b,[existing.message(4,'gameshellneo-kernel-evidence-smoke '+TOKEN,15)])
        kernel=existing.advance(a,[existing.message(3,'gameshellneo-kernel-evidence-smoke '+TOKEN,6)])
        changed=deepcopy(b);changed['stats']['success']='54'
        for after in [a,duplicate,kernel,changed]:
            with self.assertRaises(ValueError):smoke.validate(a,after,TOKEN,lock,existing.pm_tests.pm)

    def test_bad_storage_and_interruption_marker_reject(self):
        a,b,lock=pair()
        for change in [lambda r:r['entries'].append('checkpoint.new'),lambda r:r['files'].pop('lock'),
                       lambda r:r['files']['checkpoint.json'].update(bytes=1),
                       lambda r:r['files']['lock'].update(mode=0o644),
                       lambda r:r['files']['checkpoint.json'].update(links=2),
                       lambda r:r['directory'].update(uid=1000),
                       lambda r:r.update(boot_id=existing.SECOND_BOOT)]:
            value=storage(b);change(value)
            with self.assertRaises(ValueError):smoke.validate_storage(value,b)

    def test_probe_invalid_token_rejects_before_any_device_write(self):
        compile(smoke.PROBE,'probe','exec')
        for token in ['', 'x'*32, TOKEN+'\n', '../other']:
            with patch('sys.argv',['probe',token]),patch('os.open') as opened,self.assertRaises(ValueError):
                exec(smoke.PROBE,{'__name__':'__main__'})
            opened.assert_not_called()


class Experiment(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.capture=self.root/'capture';self.capture.mkdir()
        (self.root/'build').mkdir()
        self.a,self.b,self.lock=pair()
        (self.root/'build/sources.lock.json').write_text(json.dumps(self.lock))
        self.enterContext(patch.object(smoke,'ROOT',self.root))
        self.enterContext(patch.object(smoke,'device',return_value=MagicMock()))
        self.host=Mock()
        self.host.module.return_value=existing.pm_tests.pm
        self.host.inline.side_effect=[json.dumps(s).encode() for s in (self.a,self.b)]
        self.responses=[json.dumps(storage(self.a)).encode(),b'gameshellneo-usb.service loaded active running\n',
                        json.dumps(storage(self.a)|{'marker':TOKEN}).encode(),json.dumps(storage(self.b)).encode()]
        self.run=self.enterContext(patch.object(smoke,'run',side_effect=self.responses))

    def submissions(self):
        return [c for c in self.run.call_args_list if c.kwargs.get('command') and
                shlex.split(c.kwargs['command'])[-1]==TOKEN]

    def test_one_marker_and_independent_proof_publish_success(self):
        result=smoke.experiment({},self.capture,self.host,TOKEN)
        self.assertTrue(result['wifi_ssh_verified']);self.assertTrue(result['usb_ssh_verified'])
        self.assertEqual(len(self.submissions()),1)
        self.assertEqual(json.loads((self.capture/'after.json').read_text()),self.b)
        self.host.wifi_proof.assert_called_once_with({},self.b)

    def test_uncertain_submission_is_not_retried(self):
        self.run.side_effect=self.responses[:2]+[OSError('reply lost')]
        with self.assertRaises(OSError):smoke.experiment({},self.capture,self.host,TOKEN)
        self.assertEqual(len(self.submissions()),1)
        self.assertEqual(self.host.inline.call_count,1)
        self.assertFalse((self.capture/'summary.json').exists())
        self.host.wifi_proof.assert_not_called()

    def test_concurrent_diagnostic_stops_before_marker(self):
        self.run.side_effect=[self.responses[0],b'gameshellneo-pm-test.service loaded active running\n']
        with self.assertRaises(ValueError):smoke.experiment({},self.capture,self.host,TOKEN)
        self.assertEqual(len(self.submissions()),0)

    def test_failed_wifi_proof_preserves_original_without_acceptance(self):
        self.host.wifi_proof.side_effect=OSError('unavailable')
        with self.assertRaises(OSError):smoke.experiment({},self.capture,self.host,TOKEN)
        self.assertEqual(len(self.submissions()),1)
        self.assertEqual(json.loads((self.capture/'after.json').read_text()),self.b)
        self.assertFalse((self.capture/'summary.json').exists())


if __name__=='__main__':unittest.main()
