"""Camera observations stay bounded and cannot import arbitrary Mac files."""
import importlib.util
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('mac_camera',
    Path(__file__).resolve().parents[1] / 'mac-camera.py')
camera = importlib.util.module_from_spec(spec)
spec.loader.exec_module(camera)


def result(**changes):
    data = dict(schema=1, action='capture', success=True, authorization='authorized',
                camera_stopped=True, frames=[dict(file='frame-000001.jpg', width=1280, height=720)])
    data.update(changes)
    return data


class CameraTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
