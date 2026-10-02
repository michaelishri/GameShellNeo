"""Exercise RTC alarm ownership/cleanup and native ioctl layouts without hardware."""
import sys
from pathlib import Path
import struct
import tempfile
import json
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rtc_alarm as rtc


class Calendar(unittest.TestCase):
    def test_native_abi_and_date_rollover(self):
        self.assertEqual(rtc.TIME.size, 36)
        self.assertEqual(rtc.ALARM.size, 40)
        for stamp in (0, 1709251195, 1790899195):
            self.assertEqual(rtc.instant(rtc.rtc_time(stamp)), stamp)
            self.assertEqual(rtc.instant(rtc.rtc_time(stamp+10)), stamp+10)
        with self.assertRaises(ValueError):
            rtc.instant([0,0,0,31,1,126,0,0,0])

    def test_only_alarm_irq_is_accepted(self):
        self.assertEqual(rtc.irq_event(struct.pack('@L', 0x1a0)), dict(count=1,flags=0xa0))
        for value in (0xa0, 0x190, 0x1c0, 0x180):
            with self.assertRaises(ValueError):
                rtc.irq_event(struct.pack('@L', value))
        with self.assertRaises(ValueError):
            rtc.irq_event(b'bad')


class Alarm(unittest.TestCase):
    def setUp(self):
        temporary=self.enterContext(tempfile.TemporaryDirectory())
        self.root=Path(temporary); self.owned=self.root/'owned'; self.boot=self.root/'boot'; self.boot.write_text('boot')
        self.enterContext(patch.object(rtc,'OWNED',self.owned))
        self.enterContext(patch.object(rtc,'BOOT',self.boot))
        self.enterContext(patch.object(rtc,'identity',return_value='rtc'))
        self.original=[0,0]+rtc.rtc_time(0)
        self.target=[1,0]+rtc.rtc_time(1000)
        self.saved=dict(boot_id='boot',identity='rtc',original=self.original,requested=self.target)

    def test_restore_disabled_logical_alarm_and_verify(self):
        self.owned.write_text('owned')
        with patch.object(rtc,'alarm',side_effect=[self.target,self.original]),patch.object(rtc.fcntl,'ioctl') as ioctl:
            rtc.restore_fd(10,self.saved)
            ioctl.assert_called_once_with(10,rtc.SET_ALARM,rtc.ALARM.pack(*self.original))
        self.assertFalse(self.owned.exists())

    def test_foreign_alarm_or_identity_never_overwritten(self):
        for changes, current in (({'boot_id':'other'},self.target),({},[1,0]+rtc.rtc_time(2000)),
                                  ({'original':self.target},self.target)):
            self.owned.write_text('owned')
            with patch.object(rtc,'alarm',return_value=current),patch.object(rtc.fcntl,'ioctl') as ioctl:
                with self.assertRaises(ValueError): rtc.restore_fd(10,self.saved|changes)
                ioctl.assert_not_called()
            self.assertTrue(self.owned.exists())

    def test_restore_failure_retains_owner(self):
        self.owned.write_text('owned')
        with patch.object(rtc,'alarm',return_value=self.target),patch.object(rtc.fcntl,'ioctl',side_effect=OSError('io')):
            with self.assertRaises(OSError): rtc.restore_fd(10,self.saved)
        self.assertTrue(self.owned.exists())

    def test_existing_alarm_is_refused_before_mutation(self):
        with patch.object(rtc,'snapshot',return_value=dict(alarm=self.target)),patch.object(rtc.fcntl,'ioctl') as ioctl:
            with self.assertRaisesRegex(ValueError,'Existing active'): rtc.smoke(10,{})
            ioctl.assert_not_called()
        self.assertFalse(self.owned.exists())

    def test_running_pm_owner_prevents_alarm_mutation(self):
        from keypad_pm import exclusive_pm
        with exclusive_pm(self.root), patch.object(rtc, 'snapshot') as snapshot:
            with self.assertRaises(BlockingIOError):
                rtc.smoke(10,{})
            snapshot.assert_not_called()
        # The process-local context releases ownership even on exceptions.
        with exclusive_pm(self.root):
            pass

    def test_success_and_timeout_both_restore(self):
        before=dict(alarm=self.original,rtc_time=rtc.rtc_time(990),boot_id='boot',identity='rtc')
        for timeout in (False,True):
            with self.subTest(timeout=timeout):
                record={}; self.owned.unlink(missing_ok=True)
                poll=Mock();poll.poll.return_value=[] if timeout else [(10,1)]
                def restore(fd,saved): self.assertTrue(self.owned.exists());self.owned.unlink()
                with patch.object(rtc,'snapshot',return_value=before),patch.object(rtc.fcntl,'ioctl'), \
                        patch.object(rtc,'alarm',return_value=self.target),patch.object(rtc.select,'poll',return_value=poll), \
                        patch.object(rtc.os,'read',return_value=struct.pack('@L',0x1a0)), \
                        patch.object(rtc.time,'monotonic',side_effect=[0,10]), \
                        patch.object(rtc,'restore_fd',side_effect=restore) as recovered:
                    if timeout:
                        with self.assertRaises(TimeoutError): rtc.smoke(10,record)
                    else:
                        rtc.smoke(10,record);self.assertTrue(record['passed'])
                    recovered.assert_called_once()
                    self.assertTrue(record['restored'])


class Qualification(unittest.TestCase):
    def test_requires_same_boot_kernel_restoration_and_idle_alarm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); (root/'run').mkdir()
            path=root/'run/result.json'
            good=dict(passed=True,restored=True,mode='awake-only',run_id='run',
                      before=dict(boot_id='boot',kernel='kernel'),interrupt=dict(flags=0xa0),elapsed_seconds=10)
            def write(value): path.write_text(json.dumps(value))
            with patch.object(rtc,'RESULTS',root),patch.object(rtc,'OWNED',root/'owned'), \
                    patch.object(rtc.os,'open',return_value=10),patch.object(rtc.os,'close') as close, \
                    patch.object(rtc,'snapshot',return_value=dict(boot_id='boot',kernel='kernel',alarm=[0,0])) as snapshot:
                write(good)
                self.assertEqual(rtc.qualification('boot','kernel')['run_id'],'run')
                close.assert_called_once_with(10)
                for changes in (dict(passed=False),dict(restored=False),dict(before={'boot_id':'other','kernel':'kernel'}),
                                dict(before={'boot_id':'boot','kernel':'other'}),dict(elapsed_seconds=30)):
                    write(good|changes)
                    with self.assertRaises(ValueError): rtc.qualification('boot','kernel')
                write(good)
                snapshot.return_value=dict(boot_id='boot',kernel='kernel',alarm=[1,0])
                with self.assertRaisesRegex(ValueError,'changed'): rtc.qualification('boot','kernel')


class HostResult(unittest.TestCase):
    def test_cleanup_output_cannot_replace_exact_run_result(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('rtc_host',Path(rtc.__file__).with_name('check-rtc-alarm.py'))
        host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
        data=b'{"run_id":"one","passed":true,"restored":true}\n{"restored":true}\n'
        self.assertTrue(host.result_for(data,'one')['passed'])
        for candidate in (b'{"restored":true}\n',data+data):
            with self.assertRaises(ValueError): host.result_for(candidate,'one')


if __name__=='__main__': unittest.main()
