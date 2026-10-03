"""Version-only reuse must not admit changed rootfs dependencies or archives."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rootfs_cache', TOOLS / 'rootfs-cache.py')
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class CacheIdentity(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(cache, 'ROOT', self.root))
        self.enterContext(patch.object(cache, 'CACHE', self.root / 'cache'))
        self.enterContext(patch.object(cache, 'LEDGER', self.root / 'ledger.json'))
        for directory in ('build/armbian/extensions', 'build/armbian/config',
                          'build/armbian-patches', 'tools', 'cache'):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.lock = dict(image_version='diagnostic.17', board='cpi31', architecture='armhf',
                         linux={'tag': 'v6.18.54', 'localversion': '-neo17'},
                         builder={'image': 'pinned-builder'}, armbian={'commit': 'pinned-commit'},
                         debian={'snapshot': 'signed-snapshot'}, features={'speaker_audio': True})
        self.write_lock(self.lock)
        (self.root / 'tools/build-image.sh').write_text('build --minimal --trixie\n')
        (self.root / 'tools/image.py').write_text('def apt_sources(root):\n    return "snapshot"\n')
        (self.root / 'build/armbian/config/board.conf').write_text('board=cpi31\n')
        (self.root / 'build/armbian-patches/0001-cache.patch').write_text('cache policy\n')
        self.extension = self.root / 'build/armbian/extensions/gameshellneo.sh'
        self.extension.write_text('function extension_prepare_config__gameshellneo() {\n'
                                  '    add_packages_to_image python3\n}\n'
                                  'function custom_apt_repo__gameshellneo() {\n'
                                  '    set_apt_policy\n}\n'
                                  'function pre_umount_final_image__gameshellneo() {\n'
                                  '    finalize_image\n}\n')
        self.archive = cache.CACHE / 'rootfs-armhf-trixie-minimal_fixture.tar.zst'
        self.archive.write_bytes(b'fixture archive')

    def write_lock(self, value):
        (self.root / 'build/sources.lock.json').write_text(json.dumps(value, indent=2) + '\n')

    def command(self, action):
        output = StringIO()
        with patch.object(sys, 'argv', ['rootfs-cache.py', action]), redirect_stdout(output):
            cache.main()
        return output.getvalue().splitlines()

    def test_version_only_reuse_preserves_verified_archive_and_ledger(self):
        self.command('record')
        ledger = cache.LEDGER.read_bytes()
        changed = deepcopy(self.lock)
        changed['image_version'] = 'diagnostic.18'
        changed['linux']['localversion'] = '-neo18'
        self.write_lock(changed)
        self.assertEqual(self.command('check'), [self.archive.name, cache.sha(self.archive)])
        self.assertEqual(cache.LEDGER.read_bytes(), ledger)

    def test_all_other_lock_fields_including_future_fields_invalidate(self):
        self.command('record')
        changes = ({'architecture': 'arm64'}, {'board': 'other'},
                   {'linux': self.lock['linux'] | {'tag': 'v6.18.55'}},
                   {'builder': {'image': 'other'}}, {'armbian': {'commit': 'other'}},
                   {'debian': {'snapshot': 'other'}}, {'features': {'speaker_audio': False}},
                   {'unknown_future_dependency': 'new'},
                   {'linux': self.lock['linux'] | {'unknown_field': 'new'}})
        for change in changes:
            self.write_lock(self.lock | change)
            with self.subTest(change=change), self.assertRaises(SystemExit):
                self.command('check')

    def test_bootstrap_hooks_apt_and_wrapper_arguments_invalidate(self):
        self.command('record')
        for name in ('tools/build-image.sh', 'tools/image.py',
                     'build/armbian/config/board.conf', 'build/armbian-patches/0001-cache.patch',
                     'build/armbian/extensions/gameshellneo.sh'):
            path = self.root / name
            original = path.read_text()
            if name.endswith('image.py'):
                modified = original.replace('snapshot', 'other-snapshot')
            elif name.endswith('gameshellneo.sh'):
                modified = original.replace('python3', 'python3 extra-package')
            else:
                modified = original + '# changed dependency\n'
            path.write_text(modified)
            with self.subTest(name=name), self.assertRaises(SystemExit):
                self.command('check')
            path.write_text(original)
        self.assertEqual(self.command('check')[0], self.archive.name)

    def test_final_image_hook_and_lock_json_format_do_not_change_base(self):
        self.command('record')
        self.extension.write_text(self.extension.read_text().replace('finalize_image', 'new_finalization'))
        (self.root / 'build/sources.lock.json').write_text(json.dumps(self.lock, sort_keys=True))
        self.assertEqual(self.command('check')[0], self.archive.name)

    def test_legacy_ledger_and_changed_missing_archive_reject(self):
        self.command('record')
        saved = cache.LEDGER.read_text()
        legacy = json.loads(saved)
        legacy['inputs'].pop('base_rootfs_lock_v2')
        legacy['inputs']['build/sources.lock.json'] = cache.sha(self.root / 'build/sources.lock.json')
        cache.LEDGER.write_text(json.dumps(legacy))
        with self.assertRaises(SystemExit):
            self.command('check')
        cache.LEDGER.write_text(saved)
        self.archive.write_bytes(b'corrupt')
        with self.assertRaises(SystemExit):
            self.command('check')
        self.archive.unlink()
        with self.assertRaises(SystemExit):
            self.command('check')


if __name__ == '__main__':
    unittest.main()
