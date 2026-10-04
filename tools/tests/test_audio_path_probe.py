"""Active audio observations must stay bounded and must not claim audibility."""
from contextlib import contextmanager
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import wave

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import audio_path_probe as probe
import speaker_audio as audio

spec = importlib.util.spec_from_file_location('audio_path_host', TOOLS / 'check-audio.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class Waveform(unittest.TestCase):
    def test_long_cue_preserves_amplitude_stereo_rate_and_fades(self):
        for duration, frames in ((80, 3840), (1000, 48000)):
            with wave.open(io.BytesIO(audio.waveform(duration))) as source:
                self.assertEqual((source.getnchannels(), source.getsampwidth(),
                                  source.getframerate(), source.getnframes()), (2, 2, 48000, frames))
                values = list(struct.iter_unpack('<hh', source.readframes(frames)))
            self.assertTrue(all(left == right for left, right in values))
            self.assertEqual(values[0], (0, 0))
            self.assertEqual(values[-1], (0, 0))
            self.assertLessEqual(max(abs(left) for left, _ in values), 3276)
        self.assertEqual(audio.waveform(), audio.waveform(80))

    def test_unsupported_durations_cannot_touch_pcm_or_mixer(self):
        for duration in (0, -1, 81, 1001, True, 80.0, '1000', None):
            with patch.object(audio.subprocess, 'Popen') as start, \
                    patch.object(audio, 'set_control') as change, self.assertRaises(ValueError):
                audio.Cue({}).play('invalid', duration_ms=duration)
            start.assert_not_called()
            change.assert_not_called()


class Observer(unittest.TestCase):
    def test_count_and_time_limits_and_read_errors_are_recorded(self):
        for count, window, failure in ((3, 8, None), (400, 0, None), (400, 8, OSError('read failed'))):
            record = dict(samples=[])
            with patch.object(probe, 'MAX_SAMPLES', count), \
                    patch.object(probe, 'WINDOW_SECONDS', window), \
                    patch.object(probe, 'INTERVAL_SECONDS', 0):
                probe.observe(Mock(return_value={}, side_effect=failure), record, threading.Event())
            self.assertIn('error', record)
            self.assertEqual(len(record['samples']), 3 if count == 3 else 0)

    def test_playback_failure_stops_observer_and_preserves_samples(self):
        record = {}
        sample = dict(pcm_status='state: RUNNING\n', amplifiers={'speaker': 'On', 'headphone': 'On'})
        with patch.object(probe, 'reader', return_value=lambda: sample), \
                self.assertRaisesRegex(RuntimeError, 'playback failed'):
            with probe.capture_path(record):
                raise RuntimeError('playback failed')
        self.assertNotIn('error', record)
        self.assertTrue(record['summary']['pcm_running_observed'])
        self.assertNotIn('audible', record['summary'])
        self.assertGreater(len(record['samples']), 0)

    def test_reader_keeps_pcm_amplifier_gpio_evidence_with_bounding_timestamps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pcm = root / 'pcm0p/sub0'
            pcm.mkdir(parents=True)
            (pcm / 'status').write_text('state: RUNNING\n')
            (pcm / 'hw_params').write_text('rate: 48000\n')
            for name in ('Speaker Amp DRV', 'Headphone Amp'):
                (root / name).write_text(name + ': On\n')
            gpio = root / 'gpio'
            gpio.write_text('gpio-355 (PL3 |enable) out hi\n')
            with patch.object(audio, 'card', return_value=root), patch.object(audio, 'ASOC', root), \
                    patch.object(probe, 'GPIO', gpio):
                record = probe.reader()()
            self.assertIn('PL3', record['gpio'])
            self.assertTrue(probe.summarize([record])['both_amplifiers_on_observed'])
            self.assertLessEqual(record['started_seconds'], record['completed_seconds'])


class Result(unittest.TestCase):
    def test_probe_failure_restores_and_saves_original_failure(self):
        @contextmanager
        def session(record, owner):
            try:
                yield Mock()
            finally:
                record['restored'] = True
        with tempfile.TemporaryDirectory() as temporary, patch.object(probe, 'RESULTS', Path(temporary)), \
                patch.object(audio, 'inspect', return_value={}), patch.object(audio, 'session', session), \
                patch.object(audio, 'control', return_value='0'), patch.object(probe.time, 'sleep'), \
                patch.object(probe, 'reader', side_effect=OSError('observer failed')), \
                self.assertRaisesRegex(OSError, 'observer failed'):
            try:
                probe.test('a'*32)
            finally:
                saved = json.loads((Path(temporary) / ('a'*32) / 'result.json').read_text())
                self.assertTrue(saved['restored'])
                self.assertFalse(saved['passed'])
                self.assertIn('observer failed', saved['error'])

    def test_host_requires_complete_comparison_and_same_boot_restoration(self):
        before = dict(boot_id='boot', controls='quiet')
        record = dict(run_id='a'*32, passed=True, restored=True, kind='audio-path',
                      before=before.copy(), after=before.copy(),
                      cues=[dict(level=3, duration_ms=x) for x in (80, 1000)],
                      paths=[dict(duration_ms=x, samples=[{}]) for x in (80, 1000)])
        host.validate(record, before, 'a'*32, True)
        for key, bad in (('cues', [{}]), ('paths', []), ('restored', False),
                         ('after', dict(boot_id='new-boot', controls='quiet')),
                         ('after', dict(boot_id='boot', controls='loud'))):
            with self.assertRaises(ValueError):
                host.validate(record | {key: bad}, before, 'a'*32, True)


if __name__ == '__main__':
    unittest.main()
