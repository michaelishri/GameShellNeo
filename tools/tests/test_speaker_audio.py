"""Bounded waveform, mixer ownership and PM isolation for physical speaker cues."""
import importlib.util
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
        for level in (0, 4, True, '3', -1):
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
                patch('keypad_pm.restore_persistence'), patch('keypad_input.restore_console') as console, \
                patch.object(audio, 'restore', side_effect=OSError('audio cleanup failed')), \
                patch.object(pm, 'restore') as power, self.assertRaises(OSError):
            pm.main()
        console.assert_called_once_with()
        power.assert_called_once_with()


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

    def test_all_nine_cues_and_quiescence_are_required(self):
        labels = ['before-' + b for b in 'ABXY'] + ['hold-A'] + ['after-' + b for b in 'ABXY']
        off = {'Speaker Amp DRV': 'Off', 'Headphone Amp': 'Off'}
        record = dict(restored=True, idle_before_pm=off,
                      cues=[dict(label=label, amplifiers_after=off) for label in labels])
        host.validate_audio_result(record)
        record['cues'].pop()
        with self.assertRaises(ValueError):
            host.validate_audio_result(record)


if __name__ == '__main__':
    unittest.main()
