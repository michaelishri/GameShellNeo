"""Reuse an existing identity without allowing a writable container input mount."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import image_provisioning


class ImageProvisioning(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.provision = self.root / '.local/provisioning/device'
        self.populate(self.provision)

    def populate(self, path):
        path.mkdir(parents=True)
        for name in image_provisioning.FILES:
            (path / name).write_text('private fixture\n')

    def test_default_and_explicit_directory_do_not_write_or_copy(self):
        selected = self.root / 'existing identity with spaces'
        self.populate(selected)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(image_provisioning.directory(self.root, {}), self.provision)
        self.assertEqual(image_provisioning.directory(self.root, {
            'NEO_IMAGE_PROVISIONING_DIRECTORY': str(selected)}), selected)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in self.root.rglob('*') if p.is_file()})

    def test_missing_nonregular_or_symlink_input_fails(self):
        source = self.provision / 'ssh_host_ed25519_key'
        source.unlink()
        for kind in ('missing', 'directory', 'symlink'):
            if kind == 'directory':
                source.mkdir()
            elif kind == 'symlink':
                source.rmdir()
                source.symlink_to(self.provision / 'identity.json')
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'regular'):
                image_provisioning.directory(self.root, {})

    def test_invalid_or_nonexistent_explicit_directory_fails(self):
        for value in ('relative/path', '/missing-neo-provisioning', '/tmp/has:separator',
                      '/tmp/has\nnewline', '/tmp/has\rcarriage', '/tmp/has\0nul'):
            with self.subTest(value=value), self.assertRaises((OSError, ValueError)):
                image_provisioning.directory(self.root, {
                    'NEO_IMAGE_PROVISIONING_DIRECTORY': value})

    def test_build_and_verification_bind_selected_input_read_only_as_data(self):
        selected = self.root / "existing identity ' $(false)"
        self.populate(selected)
        tools = self.root / 'tools'
        tools.mkdir()
        for name in ('image_provisioning.py', 'build-image.sh', 'verify-image.sh'):
            shutil.copyfile(TOOLS / name, tools / name)
        for name in ('build_preflight.py', 'kernel-artifacts.py', 'bundle-image.py', 'image.py'):
            (tools / name).write_text('')
        (tools / 'rootfs-cache.py').write_text(
            'import sys\nraise SystemExit(1 if sys.argv[1] == "check" else 0)\n')
        (self.root / 'build').mkdir()
        (self.root / 'build/sources.lock.json').write_text(json.dumps({
            'builder': {'image': 'locked-builder'},
            'debian': {'snapshot': 'snapshot', 'security_snapshot': 'security'}}))
        kernel = self.root / '.local/build/kernel/arch/arm/boot'
        kernel.mkdir(parents=True)
        (kernel / 'zImage').write_bytes(b'fixture')
        image = self.root / 'regular image.img'
        image.write_bytes(b'fixture')
        binary = self.root / 'bin'
        binary.mkdir()
        docker = binary / 'docker'
        docker.write_text('#!' + sys.executable + '\nimport json, os, sys\n'
                          'open(os.environ["CAPTURE"], "w").write(json.dumps(sys.argv[1:]))\n')
        docker.chmod(0o700)
        capture = self.root / 'arguments.json'
        for directory in (self.provision, selected):
            environment = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'],
                               NEO_IMAGE_PROVISIONING_DIRECTORY=str(directory), CAPTURE=str(capture))
            for name, arguments in (('build-image.sh', []), ('verify-image.sh', [str(image)])):
                with self.subTest(wrapper=name, directory=directory):
                    subprocess.run(['bash', str(tools / name), *arguments], env=environment,
                                   check=True, capture_output=True, text=True)
                    actual = json.loads(capture.read_text())
                    self.assertIn(str(directory) + ':/project/.local/provisioning/device:ro', actual)
                    self.assertNotIn(str(directory) + ':/project/.local/provisioning/device', actual)
                    self.assertFalse((self.root / 'pwned').exists())


if __name__ == '__main__':
    unittest.main()
