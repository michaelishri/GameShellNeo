"""Check overlapping patch validation leaves source intact on failure."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('kernel_inputs', Path(__file__).resolve().parents[1] / 'kernel-inputs.py')
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


def change(before, after):
    return f'--- a/example\n+++ b/example\n@@ -1 +1 @@\n-{before}\n+{after}\n'.encode()


class KernelQueueTests(unittest.TestCase):
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
