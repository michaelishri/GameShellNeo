"""Require the complete power-supply kernel suite without diagnostics."""
import re

CASES = (
    'psy_lifetime_overlap_test',
    'psy_lifetime_parent_locked_test',
    'psy_lifetime_completed_test',
    'psy_lifetime_active_notification_test',
)


def checked_cases(report, log):
    expected = CASES
    suite_name = 'power-supply-lifetime'
    counts = dict(tests=len(expected), passed=len(expected), failed=0, crashed=0, skipped=0, errors=0)
    if re.search(r'WARNING:|BUG:|possible circular locking|suspicious RCU|'
                 r'sleeping function called|Kernel panic|not ok |'
                 r'rcu:.*detected .*stalls|INFO: task .*blocked for more than', log):
        raise ValueError('Kernel diagnostic or failing TAP entry')
    if (not isinstance(report, dict) or report.get('name') != 'KUnit Test Group' or
            report.get('arch') != 'um' or report.get('misc') != counts or
            report.get('test_cases') != [] or not isinstance(report.get('sub_groups'), list) or
            len(report['sub_groups']) != 1):
        raise ValueError('Expected exactly the requested UML KUnit group')
    suite = report['sub_groups'][0]
    if (not isinstance(suite, dict) or suite.get('name') != suite_name or
            suite.get('arch') != 'um' or suite.get('misc') != counts or
            suite.get('sub_groups') != [] or not isinstance(suite.get('test_cases'), list)):
        raise ValueError('Incomplete or different power-supply suite')
    cases = suite['test_cases']
    if (len(cases) != len(expected) or any(not isinstance(case, dict) for case in cases) or
            any(not isinstance(case.get('name'), str) for case in cases) or
            {case.get('name') for case in cases} != set(expected) or
            any(case.get('status') != 'PASS' for case in cases)):
        raise ValueError('Expected each power-supply case exactly once, all passing')
    if suite_name not in log or any(name not in log for name in expected):
        raise ValueError('Kernel log is missing the requested test output')
    return cases
