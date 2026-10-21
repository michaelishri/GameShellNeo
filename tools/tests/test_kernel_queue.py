"""Check overlapping patch validation leaves source intact on failure."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('kernel_inputs', Path(__file__).resolve().parents[1] / 'kernel-inputs.py')
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


def change(before, after):
    return f'--- a/example\n+++ b/example\n@@ -1 +1 @@\n-{before}\n+{after}\n'.encode()


class KernelQueueTests(unittest.TestCase):
    def test_clock_recorder_requires_explicit_selector_and_one_canonical_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'build').mkdir()
            (root / 'kernel/patches').mkdir(parents=True)
            candidate = root / 'kernel/candidates/clock-provenance'
            candidate.mkdir(parents=True)
            (candidate / 'hooks.patch').write_bytes(change('one', 'two'))
            for name in ('neo-clock-diag.h', 'neo-clock-diag.c'):
                (candidate / name).write_text(name + '\n')
            lock = root / 'build/sources.lock.json'
            with patch.object(queue, 'ROOT', root):
                for value in (None, False, True):
                    lock.write_text(json.dumps({'experiments': {} if value is None else
                                                {'clock_provenance': value}}))
                    result = dict(queue.patches())
                    self.assertEqual(queue.CLOCK_PATCH in result, value is True)
                source = root / 'source'
                source.mkdir()
                (source / 'example').write_text('one\n')
                queue.apply_queue(source, [(queue.CLOCK_PATCH, result[queue.CLOCK_PATCH])])
                self.assertEqual((source / 'example').read_text(), 'two\n')
                for name in ('neo-clock-diag.h', 'neo-clock-diag.c'):
                    self.assertEqual((source / 'kernel/time' / name).read_bytes(),
                                     (candidate / name).read_bytes())
                (root / 'kernel/patches' / queue.CLOCK_PATCH).write_text('duplicate\n')
                with self.assertRaises(ValueError):
                    list(queue.patches())

    def test_clock_selector_rejects_truthy_non_booleans(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'build').mkdir()
            with patch.object(queue, 'ROOT', root):
                for value in ('true', 1, None, []):
                    (root / 'build/sources.lock.json').write_text(json.dumps(
                        {'experiments': {'clock_provenance': value}}))
                    with self.subTest(value=value), self.assertRaises(ValueError):
                        list(queue.patches())

    def test_later_patch_can_depend_on_earlier_patch(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / 'example').write_text('one\n')
            queue.apply_queue(source, [('first', change('one', 'two')), ('second', change('two', 'three'))])
            self.assertEqual((source / 'example').read_text(), 'three\n')

    def test_late_failure_does_not_modify_any_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / 'example').write_text('one\n')
            with self.assertRaises(RuntimeError):
                queue.apply_queue(source, [('first', change('one', 'two')), ('bad', change('wrong', 'three'))])
            self.assertEqual((source / 'example').read_text(), 'one\n')
            self.assertEqual([path.name for path in source.iterdir()], ['example'])
