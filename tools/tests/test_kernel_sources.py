"""Protect legacy evidence, source identity, isolation and interrupted compaction."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import kernel_sources as sources

spec = importlib.util.spec_from_file_location('compact_sources', TOOLS / 'compact-driver-sources.py')
compact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compact)


class SourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.work = self.root / '.local/build/musb-sleep-tests'
        self.work.mkdir(parents=True)
        (self.work / '.lock').touch()
        (self.root / 'build').mkdir()
        (self.root / 'tools').mkdir()
        (self.root / 'tools/kernel-inputs.py').write_text('''import json, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'manifest.json').read_text())
path = Path(sys.argv[2])
if sys.argv[1] == '--export':
    (path / 'manifest.json').write_text(json.dumps(manifest))
else:
    (path / '.gameshellneo-patches.json').write_text(json.dumps(manifest))
''')
        self.manifest = [{'name': 'fixture.patch', 'sha256': 'a' * 64}]
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        original = self.root / 'original'
        original.mkdir()
        (original / 'Makefile').write_text('kernel fixture')
        (original / 'script').write_text('executable fixture')
        (original / 'script').chmod(0o755)
        (original / 'link').symlink_to('script')
        (original / 'empty').mkdir()
        self.archive = self.root / '.local/downloads/linux-fixture.tar.xz'
        self.archive.parent.mkdir()
        with tarfile.open(self.archive, 'w:xz') as archive:
            archive.add(original, arcname='linux-fixture')
        self.lock = {'linux': {'tag': 'vfixture', 'tarball_sha256': sources.sha256(self.archive),
                               'defconfig_sha256': 'b' * 64}}
        (self.root / 'build/sources.lock.json').write_text(json.dumps(self.lock))
        self.builds = []
        self.evidence = {}
        for index, char in enumerate('ab'):
            scratch = self.work / ('kernel-' + char * 16)
            shutil.copytree(original, scratch / 'source', symlinks=True)
            (scratch / 'source/.gameshellneo-patches.json').write_text(json.dumps(self.manifest))
            (scratch / 'output/drivers').mkdir(parents=True)
            obj = scratch / 'output/drivers/test.o'
            obj.write_text('object' + char)
            config = scratch / 'output/.config'
            config.write_text('config' + char)
            self.evidence[str(index)] = dict(scratch=str(scratch.relative_to(self.root)),
                objects={'drivers/test.o': sources.sha256(obj)}, config_sha256=sources.sha256(config))
            self.builds.append(scratch)
        self.save_evidence()

    def save_evidence(self):
        (self.work / 'matrix-evidence.json').write_text(json.dumps(self.evidence))

    def ensure(self, manifest=None):
        with sources.locked(self.work / '.source-lock'):
            return sources.ensure_source(self.root, self.work, self.archive, self.lock,
                                         manifest or self.manifest)

    def run_compact(self, apply=True):
        return compact.compact(self.root, self.work.name, apply=apply)

    def test_preview_apply_idempotence_and_evidence_preservation(self):
        saved = (self.work / 'matrix-evidence.json').read_bytes()
        result = self.run_compact(False)
        self.assertEqual(set(result['selection'].values()), {'replace'})
        self.assertTrue(all(not (p / 'source').is_symlink() for p in self.builds))
        self.assertFalse(list(self.work.glob('compact-*.json')))
        result = self.run_compact()
        self.assertTrue(result['verified'])
        self.assertEqual(len(list((self.work / '.sources').glob('source-*'))), 1)
        self.assertTrue(all((p / 'source').is_symlink() for p in self.builds))
        self.assertEqual((self.work / 'matrix-evidence.json').read_bytes(), saved)
        self.assertEqual(set(self.run_compact()['selection'].values()), {'shared'})

    def test_patch_identity_changes_but_builder_and_config_do_not(self):
        source, _, _ = self.ensure()
        self.lock.update(builder={'image': 'different'}, image_version='different')
        self.lock['linux']['localversion'] = 'different'
        self.assertEqual(self.ensure()[0], source)
        self.manifest[0]['sha256'] = 'c' * 64
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        self.assertNotEqual(self.ensure()[0], source)
        spec = sources.source_spec(self.lock, self.manifest)
        self.lock['linux']['tarball_sha256'] = 'd' * 64
        self.assertNotEqual(sources.digest(spec), sources.digest(sources.source_spec(self.lock, self.manifest)))

    def test_tampered_cache_and_legacy_rejected(self):
        source, _, _ = self.ensure()
        (source / 'Makefile').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            self.run_compact()
        self.assertTrue(all(not (p / 'source').is_symlink() for p in self.builds))

    def test_umask_differences_do_not_change_source_identity(self):
        (self.builds[1] / 'source/script').chmod(0o700)
        self.assertTrue(self.run_compact()['verified'])

    def test_any_legacy_mismatch_prevents_all_replacements(self):
        for mutation in ('content', 'mode', 'link', 'extra'):
            with self.subTest(mutation=mutation):
                source = self.builds[1] / 'source'
                if mutation == 'content':
                    (source / 'Makefile').write_text('different')
                elif mutation == 'mode':
                    (source / 'script').chmod(0o644)
                elif mutation == 'link':
                    (source / 'link').unlink()
                    (source / 'link').symlink_to('/outside')
                else:
                    (source / 'unexpected').touch()
                with self.assertRaises(ValueError):
                    self.run_compact()
                self.assertFalse((self.builds[0] / 'source').is_symlink())
                shutil.rmtree(source)
                shutil.copytree(self.builds[0] / 'source', source, symlinks=True)

    def test_bad_object_or_config_prevents_source_deletion(self):
        for name in ('drivers/test.o', '.config'):
            path = self.builds[1] / 'output' / name
            saved = path.read_bytes()
            path.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'evidence mismatch'):
                self.run_compact()
            self.assertFalse((self.builds[0] / 'source').is_symlink())
            path.write_bytes(saved)

    def test_busy_suite_and_source_locks(self):
        for name in ('.lock', '.source-lock'):
            with sources.locked(self.work / name):
                with self.assertRaises(BlockingIOError):
                    self.run_compact()

    def test_escaping_evidence_and_symlink_output(self):
        saved = self.evidence['0']['scratch']
        self.evidence['0']['scratch'] = '../../outside'
        self.save_evidence()
        with self.assertRaises(ValueError):
            self.run_compact()
        self.evidence['0']['scratch'] = saved
        self.save_evidence()
        (self.builds[0] / 'output').rename(self.root / 'outside')
        (self.builds[0] / 'output').symlink_to(self.root / 'outside')
        with self.assertRaises(ValueError):
            self.run_compact()
        self.assertTrue((self.root / 'outside/drivers/test.o').is_file())

    def test_unknown_contents_and_unrecorded_backup_rejected(self):
        for name in ('unknown', '.source-retired'):
            path = self.builds[1] / name
            path.mkdir()
            with self.assertRaises(ValueError):
                self.run_compact()
            self.assertFalse((self.builds[0] / 'source').is_symlink())
            path.rmdir()

    def test_symlink_store_and_source_rejected(self):
        (self.root / 'outside').mkdir()
        (self.work / '.sources').symlink_to(self.root / 'outside')
        with self.assertRaises(ValueError):
            self.run_compact()
        (self.work / '.sources').unlink()
        shutil.rmtree(self.builds[1] / 'source')
        (self.builds[1] / 'source').symlink_to(self.builds[0] / 'source')
        with self.assertRaises(ValueError):
            self.run_compact()

    def test_interrupt_after_retirement_resumes_without_reextracting(self):
        source, entries, metadata = self.ensure()
        scratch = self.builds[0]
        marker = dict(schema=1, source=str(source.relative_to(self.work)), tree_sha256=metadata['tree_sha256'])
        sources.atomic_json(scratch / '.source-migration.json', marker)
        (scratch / 'source').rename(scratch / '.source-retired')
        with self.assertRaisesRegex(ValueError, 'Interrupted'):
            sources.attach_source(scratch, source, entries)
        self.assertTrue(self.run_compact()['verified'])
        self.assertFalse((scratch / '.source-retired').exists())

    def test_partial_removal_can_resume_but_not_if_remaining_file_changed(self):
        source, _, metadata = self.ensure()
        scratch = self.builds[0]
        marker = dict(schema=1, source=str(source.relative_to(self.work)), tree_sha256=metadata['tree_sha256'])
        sources.atomic_json(scratch / '.source-migration.json', marker)
        (scratch / 'source').rename(scratch / '.source-retired')
        (scratch / 'source').symlink_to(sources.source_link(scratch, source))
        retired = scratch / '.source-retired'
        (retired / 'script').unlink()
        original = (retired / 'Makefile').read_bytes()
        (retired / 'Makefile').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Retired source changed'):
            self.run_compact()
        self.assertTrue(retired.exists())
        (retired / 'Makefile').write_bytes(original)
        self.assertTrue(self.run_compact()['verified'])

    def test_removal_failure_retains_journal_and_evidence(self):
        self.ensure()
        real_remove = shutil.rmtree
        def fail_retired(path, *args, **kwargs):
            if Path(path).name == '.source-retired':
                (Path(path) / 'script').unlink()
                raise OSError('simulated interrupted deletion')
            return real_remove(path, *args, **kwargs)
        with patch.object(compact.shutil, 'rmtree', side_effect=fail_retired):
            with self.assertRaises(OSError):
                self.run_compact()
        self.assertTrue((self.builds[0] / '.source-migration.json').is_file())
        self.assertTrue(self.run_compact()['verified'])

    def test_archive_mismatch_rejected(self):
        self.archive.write_bytes(b'bad archive')
        with self.assertRaisesRegex(ValueError, 'archive hash mismatch'):
            self.run_compact()

    def test_changed_patch_queue_during_preparation_publishes_no_cache(self):
        expected = [{'name': 'fixture.patch', 'sha256': 'd' * 64}]
        with self.assertRaisesRegex(ValueError, 'Patch queue changed'):
            self.ensure(expected)
        self.assertFalse(list((self.work / '.sources').iterdir()))

    def test_evidence_symlink_is_rejected(self):
        path = self.work / 'matrix-evidence.json'
        path.rename(self.root / 'saved.json')
        path.symlink_to(self.root / 'saved.json')
        with self.assertRaises(ValueError):
            self.run_compact()

    def test_retired_source_symlink_cannot_delete_external_files(self):
        source, _, metadata = self.ensure()
        scratch = self.builds[0]
        marker = dict(schema=1, source=str(source.relative_to(self.work)), tree_sha256=metadata['tree_sha256'])
        sources.atomic_json(scratch / '.source-migration.json', marker)
        (scratch / 'source').rename(self.root / 'external')
        (scratch / 'source').symlink_to(sources.source_link(scratch, source))
        (scratch / '.source-retired').symlink_to(self.root / 'external')
        with self.assertRaises(ValueError):
            self.run_compact()
        self.assertTrue((self.root / 'external/Makefile').is_file())

    def test_attach_source_uses_link_and_rejects_wrong_link(self):
        source, entries, _ = self.ensure()
        scratch = self.work / 'new'
        scratch.mkdir()
        sources.attach_source(scratch, source, entries)
        self.assertEqual((scratch / 'source').resolve(), source)
        (scratch / 'source').unlink()
        (scratch / 'source').symlink_to('/outside')
        with self.assertRaises(ValueError):
            sources.attach_source(scratch, source, entries)

    def test_missing_evidence_and_invalid_suite_rejected(self):
        (self.work / 'matrix-evidence.json').unlink()
        with self.assertRaisesRegex(ValueError, 'No completed'):
            self.run_compact()
        with self.assertRaisesRegex(ValueError, 'Unsupported suite'):
            compact.compact(self.root, '../outside', apply=True)

    def test_target_rejects_unrelated_repository_alias_and_nested_path(self):
        subprocess.run(['git', 'init', '--quiet', str(self.root)], check=True)
        with self.assertRaisesRegex(ValueError, 'this repository'):
            compact.target_root(str(self.root))
        alias = self.root / 'alias'
        alias.symlink_to(compact.ROOT, target_is_directory=True)
        with self.assertRaises(ValueError):
            compact.target_root(str(alias))
        with self.assertRaisesRegex(ValueError, 'worktree root'):
            compact.target_root(str(compact.ROOT / 'tools'))
