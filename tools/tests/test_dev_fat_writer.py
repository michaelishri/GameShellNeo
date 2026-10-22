"""Admission for the separate, opt-in unchanged FAT-writer fixture."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('dev_fat_writer_fixture', ROOT / 'tools/check-dev-fat-writer.py')
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


class FatWriterAdmission(unittest.TestCase):
    def test_changed_cached_source_is_rejected_without_download_or_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            source = cache / 'source.c'
            data = b'unchanged upstream bytes'
            expected = hashlib.sha256(data).hexdigest()
            source.write_bytes(data)
            with patch.object(fixture, 'SOURCES', {'source.c': expected}):
                self.assertTrue(fixture.sources(cache)['unchanged'])
                source.write_bytes(b'preserve unexpected owner data')
                with patch.object(fixture.urllib.request, 'urlopen') as fetch, self.assertRaises(ValueError):
                    fixture.sources(cache, fetch=True)
                fetch.assert_not_called()
                self.assertEqual(source.read_bytes(), b'preserve unexpected owner data')

    def test_source_symlink_cannot_redirect_the_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            outside = cache / 'outside'
            outside.write_bytes(b'original')
            (cache / 'source.c').symlink_to(outside)
            with patch.object(fixture, 'SOURCES', {'source.c': hashlib.sha256(b'original').hexdigest()}):
                with self.assertRaises(ValueError):
                    fixture.sources(cache)

    def test_invalid_volume_rejects_before_it_can_be_used_as_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'not-fat16'
            for data in (b'', b'not a FAT volume', b'\0' * 510 + b'\x55\xaa'):
                path.write_bytes(data)
                with self.subTest(bytes=len(data)), self.assertRaises(ValueError):
                    fixture.audit(path)


if __name__ == '__main__':
    unittest.main()
