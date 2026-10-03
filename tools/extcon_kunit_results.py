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
PROVIDER_CASES = (
    'extcon_provider_bound_test',
    'extcon_provider_existing_link_test',
    'extcon_provider_missing_test',
    'extcon_provider_invalid_test',
    'extcon_provider_probe_failure_test',
    'extcon_provider_still_probing_test',
    'extcon_provider_failed_supplier_test',
    'extcon_provider_unbinding_test',
    'extcon_provider_waits_probe_test',
    'extcon_provider_waits_callback_test',
)
COUNTS = dict(tests=len(CASES), passed=len(CASES), failed=0, crashed=0, skipped=0, errors=0)


def checked_cases(report, log, kind='notifier'):
    if kind not in ('notifier', 'provider'):
        raise ValueError('Unknown extcon suite')
    expected = CASES if kind == 'notifier' else PROVIDER_CASES
    suite_name = 'extcon-' + kind + '-lifetime'
    counts = dict(tests=len(expected), passed=len(expected), failed=0, crashed=0, skipped=0, errors=0)
    if kind == 'provider':
        commands = re.findall(r'^Kernel command line: (.+)$', log, re.M)
        if (len(commands) != 1 or
                [arg for arg in commands[0].split() if arg.startswith('fw_devlink=')] !=
                ['fw_devlink=off']):
            raise ValueError('Provider qualification requires exactly fw_devlink=off')
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
        raise ValueError('Incomplete or different extcon suite')
    cases = suite['test_cases']
    if (len(cases) != len(expected) or any(not isinstance(case, dict) for case in cases) or
            any(not isinstance(case.get('name'), str) for case in cases) or
            {case.get('name') for case in cases} != set(expected) or
            any(case.get('status') != 'PASS' for case in cases)):
        raise ValueError('Expected each extcon case exactly once, all passing')
    if suite_name not in log or any(name not in log for name in expected):
        raise ValueError('Kernel log is missing the requested test output')
    return cases
