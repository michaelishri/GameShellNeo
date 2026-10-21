"""Software timing boundaries with fake playback; never opens an audio device."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import speaker_audio as audio

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('audio_timing_report', TOOLS/'report-audio-timing.py')
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)
OFF = {'Headphone Amp': 'Off', 'Speaker Amp DRV': 'Off'}


def cue():
    points = [100, 100.04, 100.046, 100.116, 100.119, 101.819, 101.820]
    return dict(label='fixture', started_seconds=points[3], completed_seconds=points[-1],
                timing=dict(schema=1, clock='monotonic', **dict(zip(reporter.POINTS, points))))


class Playback(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.enterContext(patch.object(audio.time, 'monotonic', side_effect=lambda: self.now))
        self.wait = self.enterContext(patch.object(audio.time, 'sleep', side_effect=self.advance))
        self.payload = audio.waveform(1000)
        self.wave = self.enterContext(patch.object(audio, 'waveform', side_effect=self.waveform))
        self.mixer = self.enterContext(patch.object(audio, 'set_control', side_effect=lambda *a: self.advance(.07)))
        self.idle_count = 0
        self.idle = self.enterContext(patch.object(audio, 'idle', side_effect=self.check_idle))
        self.process = Mock(returncode=0)
        self.process.poll.return_value = 0
        self.process.communicate.side_effect = self.communicate
        self.start = self.enterContext(patch.object(audio.subprocess, 'Popen', side_effect=self.create))

    def advance(self, seconds):
        self.now += seconds

    def waveform(self, duration_ms):
        self.advance(.04)
        return self.payload

    def check_idle(self):
        self.idle_count += 1
        self.advance(.006 if self.idle_count == 1 else .001)
        return OFF.copy()

    def create(self, *args, **kwargs):
        self.advance(.003)
        return self.process

    def communicate(self, payload, timeout):
        self.advance(1.7)
        return b'', b''

    def test_phases_cover_preparation_without_changing_original_interval_or_playback(self):
        record = {}
        audio.Cue(record).play('fixture')
        saved = record['cues'][0]
        result = reporter.cue_summary(saved)
        self.assertEqual(result['phase_ms'], dict(zip(reporter.PHASES, [40, 6, 70, 3, 1700, 1])))
        self.assertEqual(result['playback_request_to_idle_ms'], 1704)
        self.assertEqual(result['call_to_idle_ms'], 1820)
        self.assertEqual(result['waveform_duration_ms'], 1000)
        self.assertEqual(saved['amplifiers_after'], OFF)
        self.assertEqual(saved['duration_ms'], 1000)
        self.assertEqual(saved['level'], audio.WARNING_LEVEL)
        self.process.communicate.assert_called_once_with(self.payload, timeout=5)
        self.start.assert_called_once_with(['aplay', '-q', '-D', 'hw:CARD=GameShellNeo,DEV=0', '-t', 'wav'],
            stdin=audio.subprocess.PIPE, stdout=audio.subprocess.PIPE, stderr=audio.subprocess.PIPE)
        self.wave.assert_called_once_with(1000)
        self.mixer.assert_called_once_with('Headphone Playback Volume', str(audio.LEVELS[audio.WARNING_LEVEL]))
        self.process.kill.assert_not_called()
        self.wait.assert_not_called()
        self.assertEqual(self.idle_count, 2)

    def test_final_idle_retry_is_measured_separately_from_playback(self):
        self.idle.side_effect = [OFF, ValueError('still on'), OFF]
        record = {}
        audio.Cue(record).play('fixture')
        result = reporter.cue_summary(record['cues'][0])
        self.assertEqual(result['phase_ms']['post_playback_idle_check'], 100)
        self.assertEqual(result['phase_ms']['playback_process'], 1700)
        self.wait.assert_called_once_with(.1)

    def test_idle_timeout_preserves_failure_without_successful_timing(self):
        self.idle.side_effect = lambda: OFF if self.now < 101 else (_ for _ in ()).throw(ValueError('still on'))
        record = {}
        with self.assertRaisesRegex(ValueError, 'still on'):
            audio.Cue(record).play('fixture')
        self.assertNotIn('cues', record)
        self.assertGreaterEqual(self.now, 107)

    def test_nonzero_playback_never_publishes_timing_as_a_completed_cue(self):
        self.process.returncode = 1
        record = {}
        with self.assertRaisesRegex(RuntimeError, 'playback failed'):
            audio.Cue(record).play('fixture')
        self.assertNotIn('cues', record)
        self.assertEqual(self.idle.call_count, 1)


class Reports(unittest.TestCase):
    def test_legacy_timings_are_kept_without_invented_phases(self):
        old = cue()
        old.pop('timing')
        value = reporter.cue_summary(old)
        self.assertEqual(value['playback_request_to_idle_ms'], 1704)
        self.assertIsNone(value['phase_ms'])
        self.assertIsNone(value['call_to_idle_ms'])
        self.assertIsNone(value['waveform_duration_ms'])

    def test_bad_clocks_schemas_endpoints_and_order_cannot_fall_back_to_legacy(self):
        mutations = [lambda c: c.update(timing=None),
            lambda c: c['timing'].update(clock='realtime'),
            lambda c: c['timing'].update(schema=True),
            lambda c: c['timing'].update(schema=2),
            lambda c: c['timing'].pop('call_seconds'),
            lambda c: c['timing'].update(call_seconds=101),
            lambda c: c['timing'].update(idle_after_seconds=102),
            lambda c: c.update(started_seconds=100),
            lambda c: c['timing'].update(process_created_seconds=float('nan')),
            lambda c: c['timing'].update(waveform_ready_seconds=float('inf')),
            lambda c: c.update(completed_seconds=True),
            lambda c: c.update(duration_ms=True),
            lambda c: c.update(duration_ms=500),
            lambda c: c['timing'].update(call_seconds=-1)]
        for mutate in mutations:
            value = cue()
            mutate(value)
            with self.assertRaises((ValueError, KeyError)):
                reporter.cue_summary(value)

    def test_only_current_result_containers_are_reported_and_failure_is_preserved(self):
        value = dict(passed=False, speaker_audio={'cues': [cue()]}, screen_warning={'cues': [cue()]},
                     qualification={'cues': [cue()]*5}, before={'cues': [cue()]*5})
        result = reporter.summarize(value)
        self.assertFalse(result['original_result_passed'])
        self.assertEqual([c['scope'] for c in result['cues']], ['speaker_audio', 'screen_warning'])
        self.assertIn('no acoustic-onset', result['limits'])

    def test_report_does_not_print_labels_or_other_arbitrary_capture_fields(self):
        value = cue()
        value['label'] = 'private-fixture-identity'
        result = reporter.summarize(dict(cues=[value], secrets='private-fixture-identity'))
        self.assertNotIn('private-fixture-identity', json.dumps(result))

    def test_missing_empty_malformed_and_oversized_cue_lists_reject(self):
        for value in [[], {}, {'cues': []}, {'cues': {}}, {'cues': [cue()]*(reporter.MAX_CUES+1)},
                      {'speaker_audio': 'bad'}, {'cues': [cue()], 'passed': 1}]:
            with self.assertRaises(ValueError):
                reporter.summarize(value)

    def test_private_saved_input_is_hashed_and_never_modified(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'result.json'
            raw = json.dumps(dict(passed=True, cues=[cue()])).encode()
            path.write_bytes(raw)
            result = reporter.report(path)
            self.assertEqual(result['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(result['capture_bytes'], len(raw))
            self.assertEqual(path.read_bytes(), raw)
            self.assertTrue(result['original_result_passed'])

    def test_capture_bounds_and_invalid_json_do_not_echo_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'result.json'
            path.write_text('private-fixture-identity')
            with self.assertRaisesRegex(ValueError, '^Invalid audio timing evidence; contents withheld$'):
                reporter.report(path)
            with patch.object(reporter, 'MAX_CAPTURE', 4), self.assertRaisesRegex(ValueError, 'exceeds'):
                reporter.report(path)


if __name__ == '__main__':
    unittest.main()
