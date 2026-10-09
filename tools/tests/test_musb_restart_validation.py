"""Reject incomplete MUSB evidence and ambiguous test-hook extraction."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from musb_restart_kunit import CASES, checked_cases, replace_once
from musb_irq_kunit import CASES as IRQ_CASES, checked_cases as irq_checked_cases
from musb_work_kunit import CASES as WORK_CASES, checked_cases as work_checked_cases
from musb_pm_kunit import CASES as PM_CASES, checked_cases as pm_checked_cases

spec = importlib.util.spec_from_file_location('request_resume_checks', TOOLS / 'check-musb-request-resume.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class RestartEvidenceTests(unittest.TestCase):
    def setUp(self):
        counts = dict(tests=len(CASES), passed=len(CASES), failed=0, crashed=0, skipped=0, errors=0)
        suite = dict(name='musb-restart', arch='um', misc=counts, sub_groups=[],
                     test_cases=[dict(name=name, status='PASS') for name in CASES])
        self.report = dict(name='KUnit Test Group', arch='um', misc=counts,
                           test_cases=[], sub_groups=[suite])
        self.log = 'musb-restart\n' + '\n'.join(CASES)

    def test_complete_kernel_result(self):
        self.assertEqual(len(checked_cases(self.report, self.log)), len(CASES))

    def test_missing_duplicate_failed_or_skipped_case(self):
        for mode in ('missing', 'duplicate', 'FAIL', 'SKIP'):
            report = copy.deepcopy(self.report)
            cases = report['sub_groups'][0]['test_cases']
            if mode == 'missing':
                cases.pop()
            elif mode == 'duplicate':
                cases[-1] = cases[0]
            else:
                cases[0]['status'] = mode
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                checked_cases(report, self.log)

    def test_extra_suite_and_kernel_diagnostics(self):
        extra = copy.deepcopy(self.report)
        extra['sub_groups'].append(extra['sub_groups'][0])
        with self.assertRaises(ValueError):
            checked_cases(extra, self.log)
        for diagnostic in ('WARNING:', 'BUG:', 'not ok ', 'sleeping function called'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                checked_cases(self.report, self.log + diagnostic)
        with self.assertRaises(ValueError):
            checked_cases(self.report, 'musb-restart')

    def test_native_count_cannot_be_doubled_or_truncated(self):
        self.assertEqual(host.scenario_count('MUSB deferred-request audit: 48 source scenarios pass (24 per direction)\n'),
                         dict(total=48, per_direction=24))
        for text in ('', 'MUSB deferred-request audit: 36 source scenarios pass (18 per direction)',
                     'MUSB deferred-request audit: 72 source scenarios pass (36 per direction)',
                     'MUSB deferred-request audit: 48 source scenarios pass (24 per direction)\nextra'):
            with self.assertRaises(ValueError):
                host.scenario_count(text)

    def test_definition_extraction_skips_forward_declaration(self):
        source = 'static int work(int x);\nstatic void other(void) { }\nstatic int work(int x)\n{\n return x;\n}\n'
        self.assertEqual(host.function(source, 'work'), 'static int work(int x)\n{\n return x;\n}\n')

    def test_hook_rejects_missing_and_duplicate_anchor(self):
        self.assertEqual(replace_once('start marker end', 'marker', 'hook'), 'start hook end')
        for text in ('', 'marker marker'):
            with self.assertRaises(ValueError):
                replace_once(text, 'marker', 'hook')


class IrqEvidenceTests(unittest.TestCase):
    suite_name = 'musb-irq'
    cases = IRQ_CASES
    validate = staticmethod(irq_checked_cases)

    def setUp(self):
        counts = dict(tests=len(self.cases), passed=len(self.cases), failed=0, crashed=0, skipped=0, errors=0)
        self.report = dict(name='KUnit Test Group', arch='um', misc=counts, test_cases=[],
            sub_groups=[dict(name=self.suite_name, arch='um', misc=counts, sub_groups=[],
                             test_cases=[dict(name=name, status='PASS') for name in self.cases])])
        self.log = self.suite_name + '\n' + '\n'.join(self.cases)

    def test_complete_irq_suite_is_not_a_restart_result(self):
        self.assertEqual(len(self.validate(self.report, self.log)), len(self.cases))
        with self.assertRaises(ValueError):
            checked_cases(self.report, self.log)
        restart = RestartEvidenceTests()
        restart.setUp()
        with self.assertRaises(ValueError):
            self.validate(restart.report, restart.log)

    def test_missing_duplicate_failed_or_skipped_irq_case(self):
        for mode in ('missing', 'duplicate', 'FAIL', 'SKIP'):
            report = copy.deepcopy(self.report)
            cases = report['sub_groups'][0]['test_cases']
            if mode == 'missing':
                cases.pop()
            elif mode == 'duplicate':
                cases[-1] = cases[0]
            else:
                cases[0]['status'] = mode
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.validate(report, self.log)

    def test_rejects_kernel_diagnostics_and_extra_suites(self):
        for diagnostic in ('WARNING:', 'BUG:', 'possible circular locking', 'Kernel panic'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(ValueError):
                self.validate(self.report, self.log + diagnostic)
        self.report['sub_groups'].append(copy.deepcopy(self.report['sub_groups'][0]))
        with self.assertRaises(ValueError):
            self.validate(self.report, self.log)


class WorkEvidenceTests(IrqEvidenceTests):
    suite_name = 'musb-work'
    cases = WORK_CASES
    validate = staticmethod(work_checked_cases)

    def test_rejects_the_other_core_suite(self):
        irq = IrqEvidenceTests()
        irq.setUp()
        with self.assertRaises(ValueError):
            self.validate(irq.report, irq.log)
        with self.assertRaises(ValueError):
            irq.validate(self.report, self.log)


class PmEvidenceTests(WorkEvidenceTests):
    suite_name = 'musb-pm'
    cases = PM_CASES
    validate = staticmethod(pm_checked_cases)

    def test_rejects_work_suite(self):
        work = WorkEvidenceTests()
        work.setUp()
        with self.assertRaises(ValueError):
            self.validate(work.report, work.log)
        with self.assertRaises(ValueError):
            work.validate(self.report, self.log)
