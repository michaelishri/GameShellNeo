"""Fail-closed acceptance of the exact extcon lifetime KUnit suite."""
import re

CASES = (
    'extcon_sync_active_test',
    'extcon_sync_selected_next_test',
    'extcon_sync_all_chain_test',
    'extcon_async_active_test',
    'extcon_async_selected_next_test',
    'extcon_async_all_chain_test',
    'extcon_nested_process_test',
    'extcon_nested_softirq_test',
    'extcon_unregistered_allocation_test',
)
COUNTS = dict(tests=len(CASES), passed=len(CASES), failed=0, crashed=0, skipped=0, errors=0)


def checked_cases(report, log):
    if re.search(r'WARNING:|BUG:|possible circular locking|suspicious RCU|'
                 r'sleeping function called|Kernel panic|not ok |'
                 r'rcu:.*detected .*stalls|INFO: task .*blocked for more than', log):
        raise ValueError('Kernel diagnostic or failing TAP entry')
    if (not isinstance(report, dict) or report.get('name') != 'KUnit Test Group' or
            report.get('arch') != 'um' or report.get('misc') != COUNTS or
            report.get('test_cases') != [] or not isinstance(report.get('sub_groups'), list) or
            len(report['sub_groups']) != 1):
        raise ValueError('Expected exactly the requested UML KUnit group')
    suite = report['sub_groups'][0]
    if (not isinstance(suite, dict) or suite.get('name') != 'extcon-notifier-lifetime' or
            suite.get('arch') != 'um' or suite.get('misc') != COUNTS or
            suite.get('sub_groups') != [] or not isinstance(suite.get('test_cases'), list)):
        raise ValueError('Incomplete or different notifier suite')
    cases = suite['test_cases']
    if (len(cases) != len(CASES) or any(not isinstance(case, dict) for case in cases) or
            any(not isinstance(case.get('name'), str) for case in cases) or
            {case.get('name') for case in cases} != set(CASES) or
            any(case.get('status') != 'PASS' for case in cases)):
        raise ValueError('Expected each notifier case exactly once, all passing')
    if 'extcon-notifier-lifetime' not in log or any(name not in log for name in CASES):
        raise ValueError('Kernel log is missing the requested test output')
    return cases
