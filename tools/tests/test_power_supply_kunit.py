"""Prevent incomplete, duplicated or warning-bearing kernel runs passing admission."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from power_supply_kunit_results import CASES, checked_cases
from power_supply_kunit_source import instrument

COUNTS = dict(tests=len(CASES), passed=len(CASES), failed=0, crashed=0, skipped=0, errors=0)

spec = importlib.util.spec_from_file_location('power_supply_kunit_runner',
                                             Path(__file__).resolve().parents[1] / 'check-power-supply-kunit.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class HookTests(unittest.TestCase):
    def test_invalid_variant_environment_rejects_before_build(self):
        with patch.dict(os.environ, {'NEO_POWER_SUPPLY_KUNIT_VARIANT': 'original;false'}), \
                patch.object(sys, 'argv', ['check-power-supply-kunit.py']), \
                patch.object(runner, 'archive_for') as archive, \
                patch.object(runner, 'run') as run, self.assertRaises(SystemExit):
            runner.main()
        archive.assert_not_called()
        run.assert_not_called()

    def test_gates_preserve_both_original_cancellation_orders(self):
        prefix = ('#include "samsung-sdi-battery.h"\n'
                  '\t\t\t\t\t\tchanged_work);\n'
                  '\t\t\t\t\t\tdeferred_register_work.work);\n'
                  '\t\twhile (!device_trylock(psy->dev.parent)) {\n'
                  '\tpower_supply_changed(psy);\n\n\tif (psy->dev.parent)\n')
        cancels = ['\tcancel_work_sync(&psy->changed_work);\n',
                   '\tcancel_delayed_work_sync(&psy->deferred_register_work);\n']
        for order in (cancels, list(reversed(cancels))):
            with self.subTest(order=order):
                source = prefix + ''.join(order)
                gated = instrument(source)
                self.assertLess(gated.index(order[0].strip()), gated.index(order[1].strip()))
                for point in ('CHANGED_ENTER', 'DEFER_ENTER', 'PARENT_BLOCKED',
                              'DEFER_NOTIFY', 'DEFER_QUEUED', 'CANCEL_DEFER_BEGIN',
                              'CANCEL_CHANGED_BEGIN', 'CANCEL_CHANGED_DONE'):
                    self.assertEqual(gated.count('psy_lifetime_hook(psy, PSY_' + point + ')'), 1)
                with self.assertRaises(ValueError):
                    instrument(source.replace(order[0], ''))
                with self.assertRaises(ValueError):
                    instrument(source + order[0])


class KUnitEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.suite = dict(name='power-supply-lifetime', arch='um', misc=dict(COUNTS),
                          sub_groups=[], test_cases=[dict(name=name, status='PASS') for name in CASES])
        self.report = dict(name='KUnit Test Group', arch='um', misc=dict(COUNTS),
                           test_cases=[], sub_groups=[self.suite])
        self.log = '\n'.join(['power-supply-lifetime', *CASES])

    def test_complete_evidence_is_accepted_without_mutation(self):
        original = deepcopy(self.report)
        self.assertEqual(checked_cases(self.report, self.log), self.suite['test_cases'])
        self.assertEqual(self.report, original)

    def test_missing_duplicate_extra_and_nonpassing_cases(self):
        for mode in ('missing', 'duplicate', 'extra', 'SKIP', 'FAIL', 'ERROR'):
            with self.subTest(mode=mode):
                report = deepcopy(self.report)
                cases = report['sub_groups'][0]['test_cases']
                if mode == 'missing':
                    cases.pop()
                elif mode == 'duplicate':
                    cases[-1] = dict(cases[0])
                elif mode == 'extra':
                    cases.append(dict(name='foreign', status='PASS'))
                else:
                    cases[0]['status'] = mode
                with self.assertRaises(ValueError):
                    checked_cases(report, self.log)

    def test_other_architecture_suite_counts_or_nested_structure(self):
        for level in ('root', 'suite'):
            for field, value in (('arch', 'arm'), ('name', 'foreign'),
                                 ('misc', dict(COUNTS, errors=1)),
                                 ('sub_groups', [] if level == 'root' else [{}])):
                with self.subTest(level=level, field=field):
                    report = deepcopy(self.report)
                    target = report if level == 'root' else report['sub_groups'][0]
                    target[field] = value
                    with self.assertRaises(ValueError):
                        checked_cases(report, self.log)

    def test_warning_and_incomplete_log_are_rejected(self):
        for error in ('WARNING:', 'BUG:', 'possible circular locking', 'suspicious RCU',
                      'sleeping function called', 'Kernel panic', 'not ok ',
                      'rcu: INFO: rcu_preempt detected expedited stalls',
                      'INFO: task extcon-remove blocked for more than 120 seconds'):
            with self.subTest(error=error), self.assertRaises(ValueError):
                checked_cases(self.report, self.log + '\n' + error)
        with self.assertRaises(ValueError):
            checked_cases(self.report, self.log.replace(CASES[-1], ''))

    def test_malformed_groups_are_rejected(self):
        for value in (None, [], {}, dict(self.report, sub_groups=None),
                      dict(self.report, sub_groups=[None]),
                      dict(self.report, sub_groups=[self.suite, self.suite])):
            with self.subTest(value=value), self.assertRaises(ValueError):
                checked_cases(value, self.log)
        for value in (None, [], {}, {'name': [], 'status': 'PASS'}):
            with self.subTest(case=value):
                report = deepcopy(self.report)
                report['sub_groups'][0]['test_cases'][0] = value
                with self.assertRaises(ValueError):
                    checked_cases(report, self.log)



class ArtifactTests(unittest.TestCase):
    def test_later_runs_cannot_overwrite_retained_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch = root / 'kernel'
            (scratch / 'output').mkdir(parents=True)
            names = {'output/linux': 'linux', 'output/.config': 'config',
                     'output/test.log': 'test.log', 'results.json': 'results.json'}
            for source in names:
                (scratch / source).write_bytes(b'first ' + source.encode())
            with patch.object(runner, 'ROOT', root):
                first = runner.retain_run(scratch)
                for source in names:
                    (scratch / source).write_bytes(b'second ' + source.encode())
                second = runner.retain_run(scratch)
            self.assertNotEqual(first['artifact_dir'], second['artifact_dir'])
            for source, name in names.items():
                self.assertEqual((root / first['artifact_dir'] / name).read_bytes(),
                                 b'first ' + source.encode())
                self.assertEqual((root / second['artifact_dir'] / name).read_bytes(),
                                 b'second ' + source.encode())

    def test_partial_copy_cannot_publish_an_acceptance_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch = root / 'kernel'
            (scratch / 'output').mkdir(parents=True)
            (scratch / 'output/linux').write_bytes(b'kernel')
            with patch.object(runner, 'ROOT', root), self.assertRaises(FileNotFoundError):
                runner.retain_run(scratch)
            self.assertFalse(list(scratch.rglob('evidence.json')))


if __name__ == '__main__':
    unittest.main()
