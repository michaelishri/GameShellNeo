"""Boundary checks for secrets, image transfers and command argument handling."""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from private_config import load_env

spec = importlib.util.spec_from_file_location('pack_image', TOOLS / 'pack-image.py')
pack_image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pack_image)


class WorkflowTests(unittest.TestCase):
    def test_dotenv_treats_shell_syntax_as_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            value = 'literal $(touch never) `command` # password'
            path.write_text('export M2_MACBOOK_AIR_PASSWORD=' + shlex.quote(value) + '\nGAMESHELL_IP=example # comment\n')
            with patch.dict(os.environ, {}, clear=True):
                values = load_env(path)
            self.assertEqual(values['M2_MACBOOK_AIR_PASSWORD'], value)
            self.assertEqual(values['GAMESHELL_IP'], 'example')

    def test_pack_and_failed_hash_preserve_existing_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'sample.img'
            source.write_bytes(bytes(range(256)) * 100)
            report = {'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'bytes': source.stat().st_size}
            output = root / 'transfer'
            record = pack_image.pack(source, report, output)
            self.assertEqual(gzip.decompress((output / record['compressed_file']).read_bytes()), source.read_bytes())
            previous = (output / 'transfer.json').read_bytes()
            source.write_bytes(b'incorrect image')
            with self.assertRaises(ValueError):
                pack_image.pack(source, report, output)
            self.assertEqual((output / 'transfer.json').read_bytes(), previous)
            self.assertFalse(list(output.glob('*.part')))

    def test_explicit_verification_does_not_require_a_current_bundle(self):
        with patch.object(sys, 'argv', ['pack-image.py', 'verify']), \
             patch.dict(os.environ, {'NEO_IMAGE': '/private/selected.img'}), \
             patch.object(pack_image, 'current_image') as current, \
             patch.object(pack_image.subprocess, 'run') as run:
            pack_image.main()
        current.assert_not_called()
        run.assert_called_once_with([str(TOOLS / 'verify-image.sh'), '/private/selected.img'], check=True)

    @unittest.skipUnless(shutil.which('flock'), 'Linux build-stage lock requires flock')
    def test_build_logger_preserves_failure_and_handles_spaced_paths(self):
        with tempfile.TemporaryDirectory(prefix='neo workflow ') as directory:
            root = Path(directory)
            (root / 'tools').mkdir()
            script = root / 'tools/run-logged.sh'
            shutil.copyfile(TOOLS / 'run-logged.sh', script)
            result = subprocess.run(['bash', str(script), 'failure-check', 'sh', '-c',
                                     'echo expected failure; exit 7'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 7)
            self.assertIn('expected failure', (root / '.local/build/failure-check.log').read_text())


if __name__ == '__main__':
    unittest.main()
