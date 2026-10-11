"""Actual diagnostic output with controlled firmware metadata and bounded sinks."""
from kernel_checks import ROOT
from kernel_sources import atomic_json

HARNESS = ROOT / 'kernel/tests/brcmfmac_output_test.c'
FIXTURE = ROOT / 'kernel/tests/brcmfmac_output_fixture.h'
DEFINES = ['-DDEBUG', '-DNEO_CLOCK_DEADLINE', '-DNEO_SHARED_DIAGNOSTICS', '-DNEO_DIAGNOSTIC_BOUNDS']
CASES = [(group, str(i)) for group, count in (
    ('console_valid', 12), ('console_invalid', 9), ('console_allocation', 5),
    ('console_output_failure', 4), ('console_transport', 24), ('console_admission', 16),
    ('assertion_strings', 16), ('assertion_flags', 3), ('assertion_failure', 16),
    ('caller_output', 4)) for i in range(count)]


def run_cases(attempt, shared, arm=False, sanitizer=False, baseline=False):
    label = 'arm' if arm else 'sanitizer' if sanitizer else 'native'
    binary = shared.compile_test(attempt, HARNESS, label + '-output', arm, sanitizer, DEFINES)
    results = {}
    for group, index in CASES:
        result = shared.execute(binary, (group, index), arm)
        key = group + '-' + index
        results[key] = dict(returncode=result.returncode, output=result.stdout, error=result.stderr)
        (attempt / (label + '-output-' + key + '.log')).write_text(result.stdout + result.stderr)
    atomic_json(attempt / (label + '-output-results.json'), results)
    failed = [key for key, value in results.items() if value['returncode'] or
              value['output'].strip() != key.replace('-', ' ') + ' passed']
    print(f'{label} diagnostic output: {len(results)-len(failed)}/{len(results)} pass', flush=True)
    if failed and not baseline:
        raise RuntimeError('Diagnostic output cases failed: ' + ', '.join(failed))
    return failed


def negatives(attempt, shared):
    path = attempt / 'brcmfmac_shared_functions.h'
    good = path.read_text()
    extract = shared.helpers.extract
    console = extract.function(good, 'static int brcmf_sdio_dump_console(')
    assertion = extract.function(good, 'static int brcmf_sdio_assert_info(')
    variants = []

    def add(name, body, replacements, case, sanitizer=False):
        broken = body
        for before, after in replacements:
            broken = extract.mutate_once(broken, before, after)
        variants.append((name, extract.mutate_once(good, body, broken), case, sanitizer))

    for name, before, after, case in (
        ('lost_index_bound', 'console_index > console_size', 'false', ('console_invalid', '2')),
        ('lost_size_bound', 'console_size > CONSOLE_BUFFER_MAX', 'false', ('console_invalid', '4')),
        ('rejected_end_cursor', 'console_index > console_size', 'console_index >= console_size', ('console_valid', '7')),
        ('metadata_as_allocation', 'return -EINVAL;', 'return -ENOMEM;', ('console_invalid', '2')),
        ('lost_empty_fastpath', 'if (!console_size)', 'if (false)', ('console_valid', '0')),
        ('changed_ring_prefix', 'console_index - 1', 'console_index', ('console_valid', '5')),
        ('lost_output_error', 'if (rv < 0)\n\t\tgoto done;\n\n\tif (console_index > 0)',
         'if (false && rv < 0)\n\t\tgoto done;\n\n\tif (console_index > 0)', ('console_output_failure', '0')),
        ('lost_payload_error', 'console_size);\n\tif (rv < 0)',
         'console_size);\n\tif (false && rv < 0)', ('console_transport', '3')),
        ('lost_buffer_cleanup', 'vfree(conbuf);', 'if (false) vfree(conbuf);', ('console_output_failure', '1')),
    ):
        add(name, console, [(before, after)], case)
    for name, case in (('file', ('assertion_strings', '9')), ('expr', ('assertion_strings', '10'))):
        # Restore the original defect: all 80 array bytes can be overwritten.
        # A sanitizer report, rather than a compile failure, is required here.
        add('lost_' + name + '_terminator', assertion,
            [(name + '[80 + 1]', name + '[80]'),
             ('sizeof(' + name + ') - 1', 'sizeof(' + name + ')')], case, True)
        add('shortened_' + name + '_text', assertion,
            [('sizeof(' + name + ') - 1', 'sizeof(' + name + ') - 2')], case)
    results = {}
    try:
        for name, body, case, sanitizer in variants:
            path.write_text(body)
            (attempt / ('output-' + name + '.h')).write_text(body)
            binary = shared.compile_test(attempt, HARNESS, 'output-' + name,
                                         sanitizer=sanitizer, defines=DEFINES)
            result = shared.execute(binary, case)
            (attempt / ('output-' + name + '.log')).write_text(result.stdout + result.stderr)
            signal = 'ERROR: AddressSanitizer: stack-buffer-overflow' if sanitizer else 'Assertion'
            if not result.returncode or signal not in result.stderr:
                raise ValueError('Output mutation did not expose the expected failure: ' + name)
            results[name] = dict(case=case, sanitizer=sanitizer,
                                 returncode=result.returncode, error=result.stderr)
    finally:
        path.write_text(good)
    atomic_json(attempt / 'output-negatives.json', results)
    print(f'{len(results)} diagnostic output mutations rejected', flush=True)
