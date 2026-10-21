"""Preserve original inspection provenance and failures during awake diagnosis."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, TOOLS / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


host = load('clock_inspection_host', 'check-clock-paths.py')
pm = load('clock_inspection_pm', 'check-pm-stages.py')
REVISION = '1' * 40


class Inspection(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'tools').mkdir()
        self.sources = {name: '# Original source: ' + name + '\n' for name in pm.INLINE_FILES}
        for name, source in self.sources.items():
            (self.root / 'tools' / name).write_text(source)
        self.enterContext(patch.object(host, 'ROOT', self.root))

    def git(self, args, **kwargs):
        self.assertEqual(args[:3], ['git', '-C', str(self.root)])
        self.assertEqual(kwargs, dict(check=True, capture_output=True, timeout=10))
        operation = args[3:]
        if operation == ['rev-parse', '--verify', REVISION + '^{commit}']:
            return SimpleNamespace(stdout=(REVISION + '\n').encode())
        if operation == ['merge-base', '--is-ancestor', REVISION, 'HEAD']:
            return SimpleNamespace(stdout=b'')
        self.assertEqual(operation[0], 'show')
        self.assertTrue(operation[1].startswith(REVISION + ':tools/'))
        return SimpleNamespace(stdout=self.sources[operation[1].split('/')[-1]].encode())

    def test_explicit_revision_uses_all_original_bytes_and_real_source_hashes(self):
        (self.root / 'tools/test-pm-stages.py').write_text('# Different working source\n')
        with patch.object(host.subprocess, 'run', side_effect=self.git) as git:
            program = host.inspection_program(pm, REVISION, self.root)
        self.assertEqual(git.call_count, len(pm.INLINE_FILES) + 2)
        self.assertEqual(program, pm.inline_program(self.sources))
        receipt = json.loads((self.root / 'inspection-sources.json').read_text())
        self.assertEqual(receipt, dict(revision=REVISION, operation='inspect-only', files={
            name: hashlib.sha256(source.encode()).hexdigest() for name, source in self.sources.items()}))
        program += '\nimport kernel_evidence\nprint(__source_sha256__)\nprint(kernel_evidence.__source_sha256__)\n'
        # Execute the generated bundle to check the identities it actually supplies.
        result = subprocess.run([sys.executable, '-B', '-'], input=program.encode(), capture_output=True, check=True)
        self.assertEqual(result.stdout.decode().splitlines(),
                         [receipt['files'][name] for name in ('test-pm-stages.py', 'kernel_evidence.py')])

    def test_current_sources_are_default_without_git_or_fallback(self):
        with patch.object(host.subprocess, 'run') as git:
            self.assertEqual(host.inspection_program(pm, '', self.root), pm.inline_program(self.sources))
        git.assert_not_called()
        self.assertIsNone(json.loads((self.root / 'inspection-sources.json').read_text())['revision'])

    def test_bad_revision_and_unrelated_commit_fail_without_source_or_device_execution(self):
        with patch.object(host.subprocess, 'run') as git:
            for revision in ('HEAD', 'be6c719', '../file', '1' * 39, '1' * 41):
                with self.subTest(revision=revision), self.assertRaises(ValueError):
                    host.inspection_program(pm, revision, self.root)
            git.assert_not_called()
        failure = subprocess.CalledProcessError(1, ['git', 'merge-base'])
        with patch.object(host.subprocess, 'run', side_effect=[SimpleNamespace(stdout=REVISION.encode()), failure]) as git:
            with self.assertRaises(subprocess.CalledProcessError):
                host.inspection_program(pm, REVISION, self.root)
        self.assertEqual(git.call_count, 2)
        self.assertFalse((self.root / 'inspection-source.py').exists())

    def test_changed_collector_or_incomplete_sources_cannot_relabel_checkpoint(self):
        (self.root / 'tools/kernel_evidence.py').write_text('# Changed collector\n')
        with patch.object(host.subprocess, 'run', side_effect=self.git), self.assertRaisesRegex(ValueError, 'collector'):
            host.inspection_program(pm, REVISION, self.root)
        self.assertFalse((self.root / 'inspection-sources.json').exists())
        sources = self.sources.copy(); del sources['battery_sample.py']
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            pm.inline_program(sources)

    def test_failed_inspection_saves_output_and_does_not_submit_measurement(self):
        error = b'Traceback: original checkpoint mismatch\n'
        def failed(client, **kwargs):
            self.assertEqual(kwargs['command'], 'sudo -n python3 -B - --inspect')
            self.assertEqual(kwargs['input_data'], b'original inspection')
            kwargs['output'].write(error)
            raise RuntimeError('Remote command failed (exit 1)')
        with patch.object(host, 'run', side_effect=failed) as runner:
            with self.assertRaises(RuntimeError):
                host.inspect(None, 'original inspection', self.root, 'before')
        runner.assert_called_once()
        self.assertEqual((self.root / 'before-output.txt').read_bytes(), error)
        self.assertFalse((self.root / 'before.json').exists())

        (self.root / 'build').mkdir()
        (self.root / 'build/sources.lock.json').write_text('{}')
        with patch.object(sys, 'argv', ['clock-paths']), patch.object(host, 'LOCAL', self.root), \
                patch.object(host, 'evidence_directory', return_value=self.root), \
                patch.object(host, 'source_receipt', return_value={}), patch.object(host, 'load_env'), \
                patch.object(host, 'device', return_value=MagicMock()), patch.object(host, 'load', return_value=Mock()), \
                patch.object(host, 'inspection_program', return_value='original inspection'), \
                patch.object(host, 'inspect', side_effect=RuntimeError('preflight rejected')) as inspect, \
                patch.object(host, 'run') as runner, self.assertRaisesRegex(RuntimeError, 'preflight rejected'):
            host.main()
        runner.assert_not_called()
        inspect.assert_called_once()
        self.assertFalse((self.root / 'comparison.json').exists())
        self.assertFalse((self.root / 'summary.json').exists())


if __name__ == '__main__':
    unittest.main()
