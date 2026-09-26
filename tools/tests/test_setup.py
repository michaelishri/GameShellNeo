"""Setup must preserve secrets and refuse an unpinned or incorrect builder."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

source = Path(__file__).resolve().parents[1] / 'setup.py'
spec = importlib.util.spec_from_file_location('neo_setup', source)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def test_workspace_preserves_existing_secrets_on_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env.example').write_text('PASSWORD=\n')
            setup.prepare_workspace(root)
            env = root / '.env'
            self.assertEqual(env.read_text(), 'PASSWORD=\n')
            env.write_text('PASSWORD="existing # secret"\n')
            setup.prepare_workspace(root)
            self.assertEqual(env.read_text(), 'PASSWORD="existing # secret"\n')
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / '.local').stat().st_mode & 0o777, 0o700)

    def test_refuses_mutable_tags_and_wrong_downloaded_image(self):
        builder = {'image': 'example/builder@sha256:' + 'a' * 64, 'platform': 'linux/amd64'}
        setup.locked_builder({'builder': builder})
        image = {'Os': 'linux', 'Architecture': 'amd64', 'RepoDigests': [builder['image']]}
        setup.validate_image(builder, image)
        for change in ({'image': 'example/builder:latest'}, {'platform': 'linux/arm64'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                setup.locked_builder({'builder': dict(builder, **change)})
        for change in ({'RepoDigests': []}, {'Architecture': 'arm64'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                setup.validate_image(builder, dict(image, **change))


if __name__ == '__main__':
    unittest.main()
