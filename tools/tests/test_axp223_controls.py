"""Reject incomplete or unhealthy kernel evidence for the control diagnostic."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import kernel_checks
SPEC = importlib.util.spec_from_file_location('axp_controls_check', ROOT / 'tools/check-axp223-controls.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class ControlResultsTests(unittest.TestCase):
    def setUp(self):
        counts = dict(tests=7, passed=7, failed=0, crashed=0, skipped=0, errors=0)
        suite = dict(name='axp223-controls', arch='um', misc=counts,
                     test_cases=[dict(name=n, status='PASS') for n in CHECK.CASES], sub_groups=[])
        self.report = dict(name='KUnit Test Group', arch='um', misc=counts.copy(),
                           test_cases=[], sub_groups=[suite])
        self.log = 'axp223-controls\n' + '\n'.join(CHECK.CASES)

    def test_complete_clean_result(self):
        self.assertEqual(len(CHECK.results_checked(self.report, self.log)), 7)

    def test_incomplete_duplicate_or_failed_cases(self):
        for mode in ('missing', 'duplicate', 'failed', 'skipped'):
            with self.subTest(mode=mode):
                report = copy.deepcopy(self.report)
                cases = report['sub_groups'][0]['test_cases']
                if mode == 'missing':
                    cases.pop()
                elif mode == 'duplicate':
                    cases[-1] = cases[0].copy()
                else:
                    cases[-1]['status'] = mode.upper()
                with self.assertRaises(ValueError):
                    CHECK.results_checked(report, self.log)

    def test_wrong_scope_or_counts(self):
        for location in ('group', 'suite'):
            for key, value in (('arch', 'arm'), ('name', 'unrelated'), ('misc', {})):
                with self.subTest(location=location, key=key):
                    report = copy.deepcopy(self.report)
                    target = report if location == 'group' else report['sub_groups'][0]
                    target[key] = value
                    with self.assertRaises(ValueError):
                        CHECK.results_checked(report, self.log)

    def test_kernel_diagnostics_or_incomplete_log(self):
        for text in ('WARNING:', 'BUG:', 'possible circular locking', 'Kernel panic',
                     'sleeping function called', 'not ok 1',
                     'INFO: task test blocked for more than 120 seconds'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                CHECK.results_checked(self.report, self.log + '\n' + text)
        with self.assertRaises(ValueError):
            CHECK.results_checked(self.report, self.log.replace(CHECK.CASES[-1], ''))

    def test_offline_arm_container_has_no_network_or_pull(self):
        lock = dict(builder=dict(image='locked-test-image', platform='linux/amd64',
                                 cross_compile='arm-linux-gnueabihf-'),
                    linux=dict(localversion='-test'))
        scratch = ROOT / '.local/test-arm-command'
        for offline in (False, True):
            with self.subTest(offline=offline), patch.object(kernel_checks, 'run') as run, \
                    patch.object(kernel_checks, 'check_overrides'), \
                    patch.object(kernel_checks, 'sha256', return_value='unused'):
                kernel_checks.build_objects(ROOT / '.local/test-source', scratch, lock,
                    ['drivers/mfd/axp20x-rsb.o'], (), True, {}, offline=offline)
                command = run.call_args.args[0]
                if offline:
                    self.assertEqual(command[command.index('--network') + 1], 'none')
                    self.assertEqual(command[command.index('--pull') + 1], 'never')
                else:
                    self.assertNotIn('--network', command)
                    self.assertNotIn('--pull', command)


if __name__ == '__main__':
    unittest.main()
