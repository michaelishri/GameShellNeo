"""Shared diagnostic caller tests using actual driver and RAM helper bodies."""
import re

from kernel_checks import ROOT
from kernel_sources import atomic_json

HARNESS = ROOT / 'kernel/tests/brcmfmac_shared_test.c'
CASES = [('success', str(i)) for i in range(8)] + [
    (group, str(i)) for group, count in (
        ('wake_failure', 12), ('admission', 16), ('ram_failure', 24),
        ('metadata', 6), ('allocation', 16), ('callers', 12),
        ('later_admission', 28), ('later_failure', 56), ('startup', 16)) for i in range(count)]


def extract_sources(source, attempt, shared):
    base = source / 'drivers/net/wireless/broadcom/brcm80211/brcmfmac'
    sdio = (base / 'sdio.c').read_text()
    structs = ''.join(shared.declarations(sdio, 'struct ' + name + ' {')
                      for name in ('sdpcm_shared', 'sdpcm_shared_le', 'brcmf_trap_info'))
    constants = []
    for name in ('SDPCM_SHARED_VERSION', 'SDPCM_SHARED_VERSION_MASK', 'SDPCM_SHARED_ASSERT_BUILT',
                 'SDPCM_SHARED_ASSERT', 'SDPCM_SHARED_TRAP', 'CONSOLE_BUFFER_MAX'):
        found = re.findall(r'^#define\s+' + name + r'\s+[^\n]+$', sdio, re.M)
        if len(found) != 1:
            raise ValueError('Missing diagnostic constant: ' + name)
        constants += found
    (attempt / 'brcmfmac_shared_types.h').write_text('\n'.join(constants) + '\n' + structs)
    function = shared.helpers.extract.function
    # Reproduce the prototype/definition shape that previously extracted the
    # wrong body. Failure here must stop qualification before compiling tests.
    sample = 'static int example(int n);\nstatic int other(void)\n{\n}\nstatic int example(int n)\n{\n return n;\n}\n'
    if function(sample, 'static int example(') != 'static int example(int n)\n{\n return n;\n}\n':
        raise ValueError('Function extraction included a prototype or unrelated body')
    body = function(sdio, 'static inline bool brcmf_sdio_valid_shared_address(')
    if 'static int brcmf_sdio_diag_read(' in sdio:
        body += function(sdio, 'static int brcmf_sdio_diag_read(')
    for name in ('readshared', 'get_console_addr', 'trap_info', 'assert_info', 'dump_console',
                 'checkdied', 'died_dump'):
        prefix = 'static ' + ('void' if name == 'get_console_addr' and
                 'static void brcmf_sdio_get_console_addr(' in sdio else 'int')
        body += function(sdio, prefix + ' brcmf_sdio_' + name + '(')
    if 'static int brcmf_sdio_get_console_addr(' in sdio:
        body = '#define NEO_SHARED_RETURNS_STATUS 1\n' + body
    (attempt / 'brcmfmac_shared_functions.h').write_text(body)


def run_cases(attempt, shared, arm=False, sanitizer=False):
    label = 'arm' if arm else 'sanitizer' if sanitizer else 'native'
    binary = shared.compile_test(attempt, HARNESS, label + '-shared', arm, sanitizer,
                                 ['-DDEBUG', '-DNEO_CLOCK_DEADLINE', '-DNEO_SHARED_DIAGNOSTICS'])
    results = {}
    for group, index in CASES:
        result = shared.execute(binary, (group, index), arm)
        key = group + '-' + index
        results[key] = dict(returncode=result.returncode, output=result.stdout, error=result.stderr)
        (attempt / (label + '-shared-' + key + '.log')).write_text(result.stdout + result.stderr)
    atomic_json(attempt / (label + '-shared-results.json'), results)
    failed = [key for key, r in results.items() if r['returncode'] or
              r['output'].strip() != key.replace('-', ' ') + ' passed']
    print(f'{label} shared diagnostics: {len(results)-len(failed)}/{len(results)} pass', flush=True)
    if failed:
        raise RuntimeError('Shared diagnostic cases failed: ' + ', '.join(failed))


def negatives(attempt, shared):
    path = attempt / 'brcmfmac_shared_functions.h'
    good = path.read_text()
    extract = shared.helpers.extract
    read = extract.function(good, 'static int brcmf_sdio_diag_read(')
    header = extract.function(good, 'static int brcmf_sdio_readshared(')
    console = extract.function(good, 'static int brcmf_sdio_get_console_addr(')
    died = extract.function(good, 'static int brcmf_sdio_checkdied(')
    variants = []

    def add(name, body, before, after, group, index):
        broken = extract.mutate_once(good, body, extract.mutate_once(body, before, after))
        variants.append((name, broken, (group, str(index))))

    add('lost_prior_error', read, 'if (ret)\n\t\tgoto out;',
        'if (false && ret)\n\t\tgoto out;', 'admission', 0)
    add('lost_pm_admission', read, 'if (READ_ONCE(sdiod->pm_failed))',
        'if (false && READ_ONCE(sdiod->pm_failed))', 'admission', 1)
    add('lost_media_admission', read, 'if (sdiod->state == BRCMF_SDIOD_NOMEDIUM)',
        'if (false && sdiod->state == BRCMF_SDIOD_NOMEDIUM)', 'admission', 3)
    add('lost_wake_error', read, 'if (ret)\n\t\tgoto failed;',
        'if (false && ret)\n\t\tgoto failed;', 'wake_failure', 0)
    add('lost_cleanup', read, 'brcmf_sdio_dpc_failed(bus, ret);',
        '(void)ret;', 'ram_failure', 0)
    add('unclaimed_cleanup', read, 'brcmf_sdio_dpc_failed(bus, ret);',
        'sdio_release_host(sdiod->func1);\n\tbrcmf_sdio_dpc_failed(bus, ret);', 'callers', 10)
    add('allocation_as_transport', read, 'ret && ret != -ENOMEM',
        'ret', 'allocation', 0)
    version = 'if ((le32_to_cpu(sh_le.flags) & SDPCM_SHARED_VERSION_MASK) > SDPCM_SHARED_VERSION)'
    add('lost_version_validation', header, version,
        version.replace('if (', 'if (false && ', 1), 'metadata', 4)
    add('premature_publication', header, version,
        'sh->flags = le32_to_cpu(sh_le.flags);\n\t' + version, 'metadata', 4)
    add('swallowed_console_error', console, 'return ret;', 'return 0;', 'wake_failure', 2)
    add('swallowed_trap_error', died, 'return brcmf_sdio_trap_info(NULL, bus, &sh);',
        '(void)brcmf_sdio_trap_info(NULL, bus, &sh);', 'callers', 6)
    for name, cases in (('trap_info', [0]), ('assert_info', [4, 4]),
                        ('dump_console', [12, 16, 20, 24])):
        body = extract.function(good, 'static int brcmf_sdio_' + name + '(')
        calls = list(re.finditer(r'brcmf_sdio_diag_read\(bus,', body))
        if len(calls) != len(cases):
            raise ValueError('Unexpected guarded diagnostic read count: ' + name)
        for index, (call, case) in enumerate(zip(calls, cases)):
            # Assertion reads share an outer claim. Removing the second guard
            # is checked by a transport failure on that read, rather than an
            # impossible competing host owner between its two transfers.
            broken = body[:call.start()] + 'brcmf_sdiod_ramrw(bus->sdiodev, false,' + body[call.end():]
            scenario = ('later_admission', str(case))
            if name == 'assert_info' and index == 1:
                scenario = ('later_failure', '1')
            variants.append(('unguarded_' + name + '_' + str(index),
                             extract.mutate_once(good, body, broken), scenario))
    results = {}
    try:
        for name, body, case in variants:
            path.write_text(body); (attempt / ('shared-' + name + '.h')).write_text(body)
            binary = shared.compile_test(attempt, HARNESS, 'shared-' + name,
                defines=['-DDEBUG', '-DNEO_CLOCK_DEADLINE', '-DNEO_SHARED_DIAGNOSTICS'])
            result = shared.execute(binary, case)
            (attempt / ('shared-' + name + '.log')).write_text(result.stdout + result.stderr)
            if not result.returncode or 'Assertion' not in result.stderr:
                raise ValueError('Shared mutation did not fail an assertion: ' + name)
            results[name] = dict(case=case, returncode=result.returncode, error=result.stderr)
    finally:
        path.write_text(good)
    atomic_json(attempt / 'shared-negatives.json', results)
    print(f'{len(results)} shared diagnostic mutations rejected', flush=True)
