"""Bounded waveform, mixer ownership and PM isolation for physical speaker cues."""
import importlib.util
from contextlib import contextmanager, nullcontext
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import speaker_audio as audio


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, TOOLS / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


host = load('audio_pm_host', 'check-pm-stages.py')
pm = load('audio_pm_device', 'test-pm-stages.py')
audio_host = load('audio_host', 'check-audio.py')


class Tone(unittest.TestCase):
    def test_quiet_short_stereo_waveform_has_zero_endpoints(self):
        with wave.open(io.BytesIO(audio.waveform())) as source:
            self.assertEqual((source.getnchannels(), source.getsampwidth(), source.getframerate(),
                              source.getnframes()), (2, 2, 48000, 3840))
            values = list(struct.iter_unpack('<hh', source.readframes(3840)))
        self.assertTrue(all(left == right for left, right in values))
        self.assertEqual(values[0], (0, 0))
        self.assertEqual(values[-1], (0, 0))
        self.assertLessEqual(max(abs(value[0]) for value in values), 3276)
        self.assertGreater(max(abs(value[0]) for value in values), 3000)

    def test_invalid_levels_never_open_pcm(self):
        for level in (0, 5, True, '3', -1):
            with patch.object(audio.subprocess, 'Popen') as start, self.assertRaises(ValueError):
                audio.Cue({}).play('fixture', level)
            start.assert_not_called()

    def test_control_names_and_values_are_not_command_injection(self):
        for name, value in [('Speaker Switch; id', 'on'), ('Speaker Switch', 'on; id'),
                            ('Headphone Playback Volume', '-1')]:
            with patch.object(audio, 'command') as command, self.assertRaises(ValueError):
                audio.set_control(name, value)
            command.assert_not_called()

    def test_failed_playback_is_killed_and_never_recorded_as_a_cue(self):
        process = Mock()
        process.communicate.side_effect = KeyboardInterrupt()
        process.poll.return_value = None
        record = {}
        with patch.object(audio, 'idle'), patch.object(audio, 'set_control'), \
                patch.object(audio.subprocess, 'Popen', return_value=process), \
                self.assertRaises(KeyboardInterrupt):
            audio.Cue(record).play('fixture')
        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=3)
        self.assertNotIn('cues', record)


class Restoration(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.enterContext(patch.object(audio, 'OWNED', self.root / 'owned.json'))
        self.enterContext(patch.object(audio, 'BOOT', self.root / 'boot'))
        audio.BOOT.write_text('same-boot')
        self.values = {name: 'off' if name.endswith('Switch') else '0' for name in audio.CONTROLS}
        self.enterContext(patch.object(audio, 'card'))
        self.enterContext(patch.object(audio, 'idle', return_value={'Speaker Amp DRV': 'Off', 'Headphone Amp': 'Off'}))
        self.enterContext(patch.object(audio, 'control', side_effect=lambda n: self.values[n]))
        self.enterContext(patch.object(audio, 'set_control', side_effect=lambda n, v: self.values.__setitem__(n, v)))

    def test_normal_and_failed_sessions_restore_original_controls(self):
        original = self.values.copy()
        for failed in (False, True):
            record = {}
            try:
                with audio.session(record):
                    self.assertEqual(self.values, audio.CONTROLS)
                    if failed:
                        raise RuntimeError('cue failed')
            except RuntimeError:
                self.assertTrue(failed)
            self.assertEqual(self.values, original)
            self.assertTrue(record['restored'])
            self.assertFalse(audio.OWNED.exists())

    def test_other_boot_or_missing_controls_do_not_restore(self):
        for saved in (dict(boot_id='other', controls=self.values), dict(boot_id='same-boot', controls={})):
            audio.OWNED.write_text(json.dumps(saved))
            with self.assertRaises(ValueError):
                audio.restore()
            self.assertTrue(audio.OWNED.exists())

    def test_failed_restore_preserves_owner_and_pm_cleanup_still_runs(self):
        audio.OWNED.write_text(json.dumps(dict(boot_id='same-boot', controls=self.values)))
        with patch.object(audio, 'set_control', side_effect=OSError('mixer failure')):
            with self.assertRaises(OSError):
                audio.restore()
        self.assertTrue(audio.OWNED.exists())
        with patch.object(sys, 'argv', ['pm', '--restore']), patch('keypad_pm.restore_trace'), \
                patch.object(pm, 'STATE', self.root/'pm-owned.json'), \
                patch('keypad_pm.restore_persistence'), patch('keypad_input.restore_console') as console, \
                patch.object(audio, 'restore', side_effect=OSError('audio cleanup failed')), \
                patch.object(pm, 'restore') as power, self.assertRaises(OSError):
            pm.main()
        console.assert_called_once_with()
        power.assert_called_once_with()

    def test_screen_warning_restores_mixer_before_observer_lead_in(self):
        original = self.values.copy()
        def lead_in(seconds):
            self.assertEqual(seconds, 1)
            self.assertEqual(self.values, original)
            self.assertFalse(audio.OWNED.exists())
        record = {}
        with patch.object(audio.Cue, 'play') as play, patch.object(audio.time, 'sleep', side_effect=lead_in):
            audio.warn_screen(record, owner='a'*32)
        play.assert_called_once_with('screen-blank')
        self.assertTrue(record['passed'])
        self.assertTrue(record['restored'])

    def test_failed_warning_restores_mixer_and_does_not_report_pass(self):
        record = {}
        original = self.values.copy()
        with patch.object(audio.Cue, 'play', side_effect=RuntimeError('playback')), \
                patch.object(audio.time, 'sleep') as wait, self.assertRaisesRegex(RuntimeError, 'playback'):
            audio.warn_screen(record)
        self.assertEqual(self.values, original)
        self.assertFalse(record['passed'])
        wait.assert_not_called()

    def test_warning_ownership_survives_failed_restore(self):
        record = {}
        with patch.object(audio.Cue, 'play'), patch.object(audio, 'restore', side_effect=OSError('restore')), \
                self.assertRaises(OSError):
            audio.warn_screen(record, owner='a'*32)
        self.assertEqual(json.loads(audio.OWNED.read_text())['notice_owner'], 'a'*32)
        self.assertFalse(record['passed'])

    def test_warning_cleanup_cannot_restore_another_owners_mixer(self):
        original = self.values.copy()
        audio.OWNED.write_text(json.dumps(dict(boot_id='same-boot', controls=original, notice_owner='a'*32)))
        with patch.object(audio, 'set_control') as write, self.assertRaisesRegex(ValueError, 'another owner'):
            audio.restore(owner='b'*32)
        write.assert_not_called()
        self.assertTrue(audio.OWNED.exists())
        audio.restore(owner='a'*32)
        self.assertFalse(audio.OWNED.exists())


class Gating(unittest.TestCase):
    def test_host_restore_survives_collected_unit_or_failed_stop(self):
        for outputs in ([b'not-found\n'], [b'loaded\n', RuntimeError('stop failed')]):
            with patch.object(audio_host, 'run', side_effect=outputs) as remote, \
                    patch.object(audio_host, 'inline') as restore:
                if len(outputs) == 1:
                    audio_host.restore('client')
                else:
                    with self.assertRaises(RuntimeError):
                        audio_host.restore('client')
                self.assertEqual(remote.call_count, len(outputs))
                restore.assert_called_once_with('client', '--restore')

    def test_audio_cannot_enable_nonphysical_or_unauthorized_pm(self):
        with self.assertRaises(ValueError):
            host.service_command('/tmp/gameshellneo-pm.test', 'devices', 'a'*32, True, None, False, True)
        with patch.object(pm, 'result_dir') as directory, self.assertRaises(ValueError):
            pm.test_stage({'experiments': {'suspend_diagnostics': True, 'keypad_supply_retention': True}},
                          'devices', 'a'*32, True, None, True, True)
        directory.assert_not_called()

    def test_input_cues_screen_warning_and_quiescence_are_required(self):
        labels = ['before-' + b for b in 'ABXY'] + ['hold-A', 'screen-blank'] + ['after-' + b for b in 'ABXY']
        off = {'Speaker Amp DRV': 'Off', 'Headphone Amp': 'Off'}
        record = dict(restored=True, idle_before_pm=off,
                      cues=[dict(label=label, amplifiers_after=off) for label in labels])
        host.validate_audio_result(record)
        record['cues'].pop()
        with self.assertRaises(ValueError):
            host.validate_audio_result(record)


class RebootWarning(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.capture = Path(self.directory.name)
        self.before = dict(boot_id='boot', controls='original')
        self.result = dict(run_id='a'*32, passed=True, restored=True,
                           before=self.before.copy(), after=self.before.copy(), cues=[{}, {}, {}])
        self.enterContext(patch.object(audio_host, 'device', return_value=nullcontext('client')))

    def request(self):
        audio_host.request_reboot({}, 'wifi', self.capture, 'a'*32, self.before, self.result)

    def test_only_verified_audio_can_queue_one_reboot(self):
        with patch.object(audio_host, 'run', side_effect=[b'boot\n', b'']) as run:
            self.request()
        self.assertEqual(run.call_count, 2)
        command = run.call_args_list[-1].args[1]
        self.assertIn('--on-active=2s', command)
        self.assertIn('/usr/bin/systemctl reboot', command)
        self.assertTrue(json.loads((self.capture/'reboot.json').read_text())['accepted'])

    def test_playback_restore_identity_and_boot_failures_never_reboot(self):
        for key, bad in [('passed', False), ('restored', False), ('run_id', 'b'*32), ('cues', [])]:
            original = self.result[key]
            self.result[key] = bad
            with patch.object(audio_host, 'run') as run, self.assertRaises(ValueError):
                self.request()
            run.assert_not_called()
            self.result[key] = original
        with patch.object(audio_host, 'run', return_value=b'other-boot\n') as run, self.assertRaises(ValueError):
            self.request()
        self.assertEqual(run.call_count, 1)

    def test_uncertain_submission_is_recorded_and_never_retried(self):
        with patch.object(audio_host, 'run', side_effect=[b'boot\n', OSError('transport')]) as run, \
                self.assertRaisesRegex(RuntimeError, 'uncertain'):
            self.request()
        self.assertEqual(run.call_count, 2)
        record = json.loads((self.capture/'reboot.json').read_text())
        self.assertTrue(record['submission_attempted'])
        self.assertFalse(record['accepted'])


class PMWarning(unittest.TestCase):
    def test_failed_notice_prevents_device_suspend_but_freezer_needs_no_notice(self):
        @contextmanager
        def observe(*args, **kwargs):
            yield 10
        for stage, failure in [('devices', True), ('devices', False), ('freezer', False)]:
            with tempfile.TemporaryDirectory() as temporary, \
                    patch.object(pm, 'result_dir', return_value=Path(temporary)/'run'), \
                    patch.object(pm, 'STATE', Path(temporary)/'pm-owned.json'), \
                    patch.object(pm, 'snapshot', return_value={}), patch.object(pm, 'validate'), \
                    patch.object(pm, 'command', return_value=''), patch('keypad_pm.observe', observe), \
                    patch.object(pm, 'stage_controls', return_value=nullcontext()), patch.object(pm.os, 'sync'), \
                    patch.object(audio, 'warn_screen', side_effect=ValueError('notice') if failure else None) as warning, \
                    patch.object(pm, 'enter_stage', side_effect=RuntimeError('entered')) as enter:
                with self.assertRaisesRegex(ValueError if failure else RuntimeError, 'notice' if failure else 'entered'):
                    pm.test_stage({}, stage, 'a'*32)
                self.assertEqual(enter.call_count, 0 if failure else 1)
                self.assertEqual(warning.call_count, 0 if stage == 'freezer' else 1)


if __name__ == '__main__':
    unittest.main()
