"""Camera observations stay bounded and cannot import arbitrary Mac files."""
import importlib.util
from contextlib import redirect_stderr
from io import BytesIO, StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('mac_camera',
    Path(__file__).resolve().parents[1] / 'mac-camera.py')
camera = importlib.util.module_from_spec(spec)
spec.loader.exec_module(camera)


def result(**changes):
    data = dict(schema=1, action='capture', success=True, authorization='authorized',
                camera_name=camera.CAMERA,
                camera_stopped=True, frames=[dict(file='frame-000001.jpg', width=1280, height=720)])
    data.update(changes)
    return data


class CameraTests(unittest.TestCase):
    def test_only_known_exit_wait_race_with_saved_result_is_collectable(self):
        race = b'Unable to block on applications (initial call to kevent() failed: No such process)'
        for message, saved, expected in ((race, True, 0), (race, False, 1),
                                         (b'Application failed to launch', True, 1)):
            with self.subTest(message=message, saved=saved), TemporaryDirectory() as directory:
                if saved:
                    Path(directory, 'result.json').write_text('{}')
                source = camera.launch_source('/Camera.app', directory, 'status', 0, 2, directory)
                child = Mock(returncode=1, stdout=BytesIO(message))
                child.poll.return_value = 1
                output = Mock(buffer=BytesIO())
                with patch('subprocess.Popen', return_value=child), patch('sys.stdout', output):
                    with self.assertRaises(SystemExit) as exit:
                        exec(compile(source, '<camera-runner>', 'exec'), {})
                self.assertEqual(exit.exception.code, expected)

    def test_camera_selection_uses_private_preference_and_explicit_override(self):
        self.assertEqual(camera.selected_camera(camera.options(['capture']), {}), camera.CAMERA)
        self.assertEqual(camera.selected_camera(camera.options(['capture']),
                         {'NEO_CAMERA_NAME': 'Razer Kiyo'}), 'Razer Kiyo')
        self.assertEqual(camera.selected_camera(camera.options(['capture', '--camera', 'External']),
                         {'NEO_CAMERA_NAME': 'Razer Kiyo'}), 'External')
        for name in ('', ' ', 'Razer\nKiyo', 'Razer\x00Kiyo'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                camera.selected_camera(camera.options(['capture']), {'NEO_CAMERA_NAME': name})

    def test_camera_mismatch_cannot_be_accepted_as_observation(self):
        with self.assertRaises(ValueError):
            camera.validate_result(result(), 'capture', 'Razer Kiyo')
        self.assertEqual(camera.validate_result(result(camera_name='Razer Kiyo'), 'capture',
                         'Razer Kiyo'), ['frame-000001.jpg'])

    def test_frame_paths_cannot_escape_capture_directory(self):
        for name in ('../secret.jpg', '/etc/passwd', 'frame-000001.jpg/../../secret'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                camera.validate_result(result(frames=[dict(file=name, width=1280, height=720)]), 'capture')

    def test_failed_permission_is_not_a_successful_capture(self):
        for changes in (dict(authorization='denied'), dict(camera_stopped=False), dict(frames=[])):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                camera.validate_result(result(**changes), 'capture')

    def test_duplicate_frames_are_rejected(self):
        with self.assertRaises(ValueError):
            camera.validate_result(result(frames=result()['frames'] * 2), 'capture')

    def test_status_can_report_missing_permission_without_frames(self):
        self.assertEqual(camera.validate_result(result(action='status', authorization='notDetermined', frames=[]), 'status'), [])

    def test_duration_and_rate_limits_apply_before_remote_work(self):
        for args in (['capture', '--seconds', '-1'], ['capture', '--seconds', '301'],
                     ['capture', '--fps', '0'], ['capture', '--fps', '6'], ['status', '--seconds', '1']):
            with self.subTest(args=args), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                camera.options(args)

    def test_launch_source_remains_literal_with_shell_metacharacters(self):
        source = camera.launch_source("/private/it's $(false)/Camera.app", '/private/test', 'capture', 10, 2, '/private/test')
        compile(source, '<camera-runner>', 'exec')
        self.assertIn("'FaceTime HD Camera', 'video-only'", source)
        self.assertNotIn('shell=True', source)
        external = camera.launch_source('/private/Camera.app', '/private/test', 'capture', 0, 2,
                                        '/private/test', 'Camera $(false); camera')
        compile(external, '<camera-runner>', 'exec')
        self.assertIn("'Camera $(false); camera', 'video-only'", external)
        self.assertNotIn('shell=True', external)


if __name__ == '__main__':
    unittest.main()
