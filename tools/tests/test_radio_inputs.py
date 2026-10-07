"""Public firmware pinning and preservation of private board calibration."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

spec = importlib.util.spec_from_file_location('prepare_build', Path(__file__).resolve().parents[1] / 'prepare-build.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class RadioInputTests(unittest.TestCase):
    def test_download_and_cache_are_verified_and_nvram_stays_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference, inputs, cache = (root / part for part in ('reference', 'inputs', 'cache'))
            reference.mkdir(); inputs.mkdir()
            (reference / 'board.txt').write_bytes(b'private board settings')
            radio = {
                'firmware': dict(filename='firmware.bin', sha256=hashlib.sha256(b'firmware').hexdigest(), url='https://example.invalid/pinned'),
                'nvram': dict(filename='board.txt', sha256=hashlib.sha256(b'private board settings').hexdigest()),
                'license': dict(filename='license', sha256=hashlib.sha256(b'license').hexdigest(), url='https://example.invalid/license'),
            }
            with patch.object(prepare.urllib.request, 'urlopen', side_effect=[io.BytesIO(b'firmware'), io.BytesIO(b'license')]) as download:
                prepare.stage_radio(radio, reference, inputs, cache)
                prepare.stage_radio(radio, reference, inputs, cache)
                self.assertEqual(download.call_count, 2)
            self.assertEqual((inputs / 'board.txt').read_bytes(), (reference / 'board.txt').read_bytes())
            self.assertEqual((inputs / 'license').read_bytes(), b'license')
            (cache / radio['firmware']['sha256']).write_bytes(b'corrupt')
            with self.assertRaises(SystemExit):
                prepare.stage_radio(radio, reference, inputs, cache)
            self.assertEqual((inputs / 'firmware.bin').read_bytes(), b'firmware')

    def test_bad_download_preserves_existing_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'firmware.bin').write_bytes(b'original')
            radio = {'firmware': dict(filename='firmware.bin', sha256='0' * 64, url='https://example.invalid/pinned')}
            with patch.object(prepare.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong')), self.assertRaises(ValueError):
                prepare.stage_radio(radio, root, root, root / 'cache')
            self.assertEqual((root / 'firmware.bin').read_bytes(), b'original')
            self.assertEqual(list((root / 'cache').iterdir()), [])
