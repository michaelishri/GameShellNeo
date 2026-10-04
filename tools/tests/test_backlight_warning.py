"""Execute the saved shell sequence against a fake backlight and a real PTY."""
import os
from pathlib import Path
import pty
import subprocess
import tempfile
import unittest


class BacklightWarning(unittest.TestCase):
    def test_each_dark_interval_requires_a_completed_warning(self):
        source = (Path(__file__).resolve().parents[1]/'check-backlight.sh').read_text()
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                panel = root/'panel'; panel.mkdir()
                for name, value in dict(brightness='1', max_brightness='31', bl_power='0').items():
                    (panel/name).write_text(value)
                (panel/'actual_brightness').symlink_to(panel/'brightness')
                binary = root/'bin'; binary.mkdir()
                (binary/'sleep').write_text('#!/bin/sh\nexit 0\n')
                (binary/'sleep').chmod(0o700)
                (root/'speaker_audio.py').write_text(
                    'from pathlib import Path\n'
                    'p=Path(__file__).parent\n'
                    'with (p/"warnings").open("a") as f: f.write((p/"panel/brightness").read_text().strip()+"\\n")\n'
                    'raise SystemExit('+str(int(failure))+')\n')
                master, slave = pty.openpty()
                try:
                    script = root/'check-backlight.sh'
                    script.write_text(source.replace('/sys/class/backlight/ocp8178', str(panel))
                                      .replace('/dev/tty1', os.ttyname(slave)))
                    result = subprocess.run(['/bin/sh', str(script)], capture_output=True, text=True, timeout=10,
                                            env=os.environ | {'PATH':str(binary)+':'+os.environ['PATH']})
                finally:
                    os.close(slave); os.close(master)
                self.assertEqual((panel/'brightness').read_text().strip(), '1')
                warnings = (root/'warnings').read_text().splitlines()
                if failure:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(warnings, ['31'])
                    self.assertNotIn('requested=0', result.stdout)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(warnings, ['31']*3)
                    self.assertEqual(result.stdout.count('requested=0 actual=0'), 3)
