"""Reject expensive build work early without choosing replacement inputs."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import build_preflight as preflight


class BuildPreflight(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root/'build').mkdir()
        self.boot = self.root/'explicit bootloader.bin'; self.boot.write_bytes(b'boot')
        self.radio = self.root/'explicit radio'; self.radio.mkdir()
        (self.radio/'nvram.txt').write_bytes(b'private calibration')
        self.lock = dict(linux={'tag':'v6.18.54'}, bootloader=self.asset('boot.bin', b'boot'),
                         radio={'nvram':self.asset('nvram.txt', b'private calibration'),
                                'firmware':dict(self.asset('fw.bin', b'firmware'), url='https://example.invalid/pinned')})
        self.lock['bootloader']['size_bytes'] = 4
        self.save_lock()

    def asset(self, name, data):
        return dict(filename=name, sha256=hashlib.sha256(data).hexdigest())

    def save_lock(self):
        (self.root/'build/sources.lock.json').write_text(json.dumps(self.lock))

    def check(self, scope='full'):
        return preflight.preflight(self.root, scope, self.boot, self.radio)

    def test_read_only_explicit_inputs_and_uncached_public_download(self):
        before = sorted(str(p) for p in self.root.rglob('*'))
        with patch.object(preflight, 'filesystem', return_value=(1, 20*preflight.GIB, '/storage')):
            result = self.check()
        self.assertTrue(result['passed'])
        self.assertEqual(result['inputs'][-1]['kind'], 'nvram')
        self.assertEqual(result['inputs'][1]['status'], 'download-required')
        self.assertNotIn('private calibration', json.dumps(result))
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))

    def test_missing_selected_input_does_not_use_staged_copy(self):
        inputs = self.root/'.local/inputs'; inputs.mkdir(parents=True)
        (inputs/'boot.bin').write_bytes(b'boot'); self.boot.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing input'):
            self.check('inputs')
        self.boot.write_bytes(b'boot'); (self.radio/'nvram.txt').unlink()
        (inputs/'nvram.txt').write_bytes(b'private calibration')
        with self.assertRaisesRegex(ValueError, 'Missing input'):
            self.check('inputs')

    def test_prepare_rejects_bad_inputs_before_clone_or_directory_creation(self):
        spec=importlib.util.spec_from_file_location('preflight_prepare',TOOLS/'prepare-build.py')
        prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)
        self.boot.unlink()
        with patch.object(prepare,'LOCK',self.lock), patch.object(prepare,'LOCAL',self.root/'.local'), \
                patch.object(prepare,'run') as run, patch.object(sys,'argv',[
                    'prepare-build.py','--bootloader',str(self.boot),'--radio-directory',str(self.radio)]):
            with self.assertRaisesRegex(ValueError,'Missing input'):
                prepare.main()
        run.assert_not_called()
        self.assertFalse((self.root/'.local').exists())

    def test_size_hash_and_nonregular_inputs_fail(self):
        self.boot.write_bytes(b'wrong size')
        with self.assertRaisesRegex(ValueError, 'size differs'):
            self.check('inputs')
        self.boot.write_bytes(b'bad!')
        with self.assertRaisesRegex(ValueError, 'checksum differs'):
            self.check('inputs')
        self.boot.unlink(); self.boot.mkdir()
        with self.assertRaisesRegex(ValueError, 'regular file'):
            self.check('inputs')

    def test_cached_public_blob_is_checked_without_reference_fallback(self):
        cache=self.root/'.local/downloads/radio'; cache.mkdir(parents=True)
        cached=cache/self.lock['radio']['firmware']['sha256']; cached.write_bytes(b'corrupt')
        (self.radio/'fw.bin').write_bytes(b'firmware')
        with self.assertRaisesRegex(ValueError, 'checksum differs'):
            self.check('inputs')
        cached.write_bytes(b'firmware')
        self.assertEqual(self.check('inputs')['inputs'][1]['status'], 'verified')

    def test_full_shared_filesystem_adds_roles_once_and_checks_boundary(self):
        with patch.object(preflight, 'filesystem', return_value=(1, 16*preflight.GIB-1, '/storage')):
            with self.assertRaisesRegex(ValueError, '16 GiB required'):
                self.check()
        with patch.object(preflight, 'filesystem', return_value=(1, 16*preflight.GIB, '/storage')):
            records=self.check()['storage']
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['required_bytes'],16*preflight.GIB)

    def test_split_filesystems_are_independently_checked(self):
        def storage(path):
            if 'downloads' in path.parts:
                return 2, 6*preflight.GIB-1, '/download-storage'
            return 1, 20*preflight.GIB, '/other-storage'
        with patch.object(preflight,'filesystem',side_effect=storage):
            with self.assertRaisesRegex(ValueError,'6 GiB required'):
                self.check()

    def test_kernel_only_does_not_require_image_inputs(self):
        self.boot.unlink()
        with patch.object(preflight, 'filesystem', return_value=(1, 6*preflight.GIB, '/storage')):
            result=self.check('kernel')
        self.assertEqual(result['inputs'],[])
        self.assertEqual(result['storage'][0]['required_bytes'],6*preflight.GIB)
        with self.assertRaises(ValueError):
            self.check('unknown')

    def test_filesystem_follows_symlinks_and_uses_existing_ancestor(self):
        target=self.root/'storage'; target.mkdir()
        link=self.root/'alias';link.symlink_to(target,target_is_directory=True)
        device,free,existing=preflight.filesystem(link/'not-created/yet')
        self.assertEqual(existing,str(target))
        self.assertEqual(device,target.stat().st_dev)
        self.assertGreaterEqual(free,0)
        self.assertFalse((target/'not-created').exists())

    def test_bad_radio_path_or_url_rejected(self):
        for field,value in [('filename','../escape'),('url','http://example.invalid'),('sha256','../escape')]:
            with self.subTest(field=field):
                original=self.lock['radio']['firmware'][field]
                self.lock['radio']['firmware'][field]=value;self.save_lock()
                with self.assertRaises(ValueError):self.check('inputs')
                self.lock['radio']['firmware'][field]=original;self.save_lock()

    def test_build_shell_wrappers_stop_before_expensive_actions(self):
        tools=self.root/'tools';tools.mkdir()
        (tools/'build_preflight.py').write_text('raise SystemExit(7)\n')
        provision=self.root/'.local/provisioning/device';provision.mkdir(parents=True)
        (provision/'identity.json').write_text('{}')
        for name in ('build-kernel.sh','build-image.sh'):
            with self.subTest(wrapper=name):
                path=tools/name;shutil.copyfile(TOOLS/name,path)
                result=subprocess.run(['bash',str(path)],capture_output=True,text=True)
                self.assertEqual(result.returncode,7,result.stderr)
                self.assertFalse((self.root/'.local/build/kernel').exists())
                self.assertFalse((self.root/'.local/downloads').exists())

    @unittest.skipUnless(shutil.which('task'), 'Go Task required for workflow dry run')
    def test_full_workflow_prepares_before_kernel_even_with_scope_override(self):
        result=subprocess.run(['task','--dry','--verbose','build','SCOPE=kernel'],cwd=TOOLS.parent,
                              capture_output=True,text=True,check=True)
        output=result.stdout+result.stderr
        self.assertLess(output.index('build_preflight.py --scope full'),output.index('prepare-build.py'))
        self.assertLess(output.index('prepare-build.py'),output.index('tools/build-kernel.sh'))


if __name__ == '__main__':
    unittest.main()
