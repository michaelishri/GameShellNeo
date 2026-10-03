"""Prevent incomplete, duplicated or warning-bearing kernel runs passing admission."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extcon_kunit_results import CASES, COUNTS, PROVIDER_CASES, checked_cases

spec = importlib.util.spec_from_file_location('extcon_kunit_runner',
                                             Path(__file__).resolve().parents[1] / 'check-extcon-kunit.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class KUnitEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.suite = dict(name='extcon-notifier-lifetime', arch='um', misc=dict(COUNTS),
                          sub_groups=[], test_cases=[dict(name=name, status='PASS') for name in CASES])
        self.report = dict(name='KUnit Test Group', arch='um', misc=dict(COUNTS),
                           test_cases=[], sub_groups=[self.suite])
        self.log = '\n'.join(['extcon-notifier-lifetime', *CASES])

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

    def test_provider_requires_its_own_exact_suite_and_cases(self):
        report = deepcopy(self.report)
        suite = report['sub_groups'][0]
        suite['name'] = 'extcon-provider-lifetime'
        suite['test_cases'] = [dict(name=name, status='PASS') for name in PROVIDER_CASES]
        suite['misc'] = dict(COUNTS, tests=len(PROVIDER_CASES), passed=len(PROVIDER_CASES))
        report['misc'] = dict(suite['misc'])
        log = '\n'.join(['Kernel command line: fw_devlink=off', suite['name'], *PROVIDER_CASES])
        self.assertEqual(checked_cases(report, log, 'provider'), suite['test_cases'])
        for wrong_report, wrong_log, kind in (
            (report, log, 'notifier'), (self.report, self.log, 'provider'),
            (report, log, 'foreign'), (report, self.log, 'provider'),
        ):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                checked_cases(wrong_report, wrong_log, kind)
        for error in ('WARNING:', 'BUG:', 'not ok '):
            with self.subTest(error=error), self.assertRaises(ValueError):
                checked_cases(report, log + error, 'provider')
        for replacement in ('', 'fw_devlink=on', 'fw_devlink=off fw_devlink=on',
                            'fw_devlink=off fw_devlink=off'):
            with self.subTest(bootargs=replacement), self.assertRaises(ValueError):
                checked_cases(report, log.replace('fw_devlink=off', replacement), 'provider')
        suite['test_cases'][-1] = dict(suite['test_cases'][0])
        with self.assertRaises(ValueError):
            checked_cases(report, log, 'provider')


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
