"""Actual-source watchdog qualification shared by the saved offline runner."""
import re

from kernel_checks import ROOT
from kernel_sources import atomic_json

HARNESS = ROOT / 'kernel/tests/brcmfmac_watchdog_test.c'


def cases(debug, clock=False):
    groups = [('poll_failure', 9), ('poll_success', 8), ('retire_after_poll', 3), ('quiet', 5),
              ('idle_failure', 12 if debug else 6), ('idle_success', 7),
              ('admission', 12 if debug else 8), ('between', 8 if debug else 4)]
    if debug:
        groups += [('console_failure', 27), ('console_queued_failure', 27),
                   ('console_local', 4), ('console_success', 9),
                   ('console_ram_allocation', 8), ('console_window_failure', 6),
                   ('console_transfer_allocation', 4), ('ram_helper', 8)]
    if clock:
        groups += [('clock_request', 12), ('clock_watchdog', 24), ('clock_admission', 8),
                   ('clock_retirement', 1)]
    return [(group, str(index)) for group, count in groups for index in range(count)]


def extract_sources(source, attempt, shared, clock=False):
    base = source / 'drivers/net/wireless/broadcom/brcm80211/brcmfmac'
    sdio, header, registers = ((base / 'sdio.c').read_text(), (base / 'sdio.h').read_text(),
                               (source / 'include/linux/mmc/sdio.h').read_text())
    bcmsdh = (base / 'bcmsdh.c').read_text()
    types = ''.join(shared.declarations(sdio, 'struct ' + name + ' {')
                    for name in ('rte_log_le', 'rte_console', 'brcmf_console', 'brcmf_sdio_count'))
    constants = []
    for name in ('CBUF_LEN', 'CONSOLE_LINE_MAX', 'BRCMF_WD_POLL', 'INTR_STATUS_FUNC1',
                 'INTR_STATUS_FUNC2', 'SDIO_CCCR_INTx', 'SBSDIO_SB_OFT_ADDR_LIMIT',
                 'SBSDIO_SB_OFT_ADDR_MASK', 'SBSDIO_SBWINDOW_MASK', 'SBSDIO_SB_ACCESS_2_4B_FLAG'):
        match = re.findall(r'^#define\s+' + name + r'\s+[^\n]+$', sdio + '\n' + header + '\n' + registers, re.M)
        if len(match) != 1:
            raise ValueError('Missing/ambiguous watchdog constant: ' + name)
        constants += match
    (attempt / 'brcmfmac_watchdog_types.h').write_text('\n'.join(constants) + '\n' + types)
    function = shared.helpers.extract.function
    body = function(header, 'static inline bool brcmf_sdiod_io_blocked(')
    if clock:
        sleep = shared.module('clock_sleep_checks', 'check-brcmfmac-sleep.py')
        includes = source / 'drivers/net/wireless/broadcom/brcm80211/include'
        (attempt / 'brcmfmac_clock_constants.h').write_text(sleep.constants(
            [header, (includes / 'chipcommon.h').read_text(), (includes / 'brcm_hw_ids.h').read_text(), sdio]))
        (attempt / 'brcmfmac_sleep_constants.h').write_text((attempt / 'brcmfmac_clock_constants.h').read_text())
        (attempt / 'brcmfmac_sleep_functions.h').write_text(sleep.functions(sdio))
        body += function(sdio, 'static int brcmf_sdio_htclk(')
    for prefix in ('void brcmf_sdio_wd_timer(', 'static void brcmf_sdio_dpc_failed('):
        body += function(sdio, prefix)
    body += '#ifdef DEBUG\n' + function(bcmsdh, 'int\nbrcmf_sdiod_ramrw(')
    body += function(sdio, 'static int brcmf_sdio_readconsole(') + '#endif\n'
    body += function(sdio, 'static void brcmf_sdio_bus_watchdog(')
    (attempt / 'brcmfmac_watchdog_functions.h').write_text(body)


def run_cases(attempt, shared, arm=False, sanitizer=False, clock=False):
    label = 'arm' if arm else 'sanitizer' if sanitizer else 'native'
    failures = []
    for debug in (False, True):
        kind = 'debug' if debug else 'normal'
        name = label + '-' + kind
        defines = (['-DDEBUG'] if debug else []) + (['-DNEO_CLOCK_DEADLINE'] if clock else [])
        binary = shared.compile_test(attempt, HARNESS, name, arm, sanitizer, defines)
        results = {}
        for group, index in cases(debug, clock):
            result = shared.execute(binary, (group, index), arm)
            key = group + '-' + index
            results[key] = dict(returncode=result.returncode, output=result.stdout, error=result.stderr)
            (attempt / (name + '-' + key + '.log')).write_text(result.stdout + result.stderr)
        atomic_json(attempt / (name + '-results.json'), results)
        failed = [key for key, value in results.items() if value['returncode'] or
                  value['output'].strip() != key.replace('-', ' ') + ' passed']
        print(f'{name} watchdog: {len(results)-len(failed)}/{len(results)} pass', flush=True)
        failures.extend(name + ':' + key for key in failed)
    if failures:
        raise RuntimeError('Watchdog scenarios failed: ' + ', '.join(failures))


def run_sleep(attempt, shared, arm=False, sanitizer=False):
    label = 'arm' if arm else 'sanitizer' if sanitizer else 'native'
    results = {}
    for debug in (False, True):
        name = label + '-sleep-' + ('debug' if debug else 'normal')
        binary = shared.compile_test(attempt, ROOT / 'kernel/tests/brcmfmac_sleep_test.c',
                                     name, arm, sanitizer, ['-DDEBUG'] if debug else [])
        result = shared.execute(binary, arm=arm)
        (attempt / (name + '.log')).write_text(result.stdout + result.stderr)
        result.check_returncode()
        lines = result.stdout.strip().splitlines()
        if (len(lines) != 3 or
                lines[0] != 'happy: 43 scenarios, transfer/delay/state transcript a2658cef' or
                lines[-1] != 'with recovery: 95 scenarios passed'):
            raise ValueError('Sleep regression coverage/transcript changed: ' + result.stdout)
        results[name] = dict(returncode=result.returncode, output=result.stdout, error=result.stderr)
    atomic_json(attempt / (label + '-sleep-results.json'), results)
    print(f'{label} sleep: 95 normal/debug cases and original happy transcript pass', flush=True)


def negatives(attempt, shared, clock=False):
    path = attempt / 'brcmfmac_watchdog_functions.h'
    good = path.read_text(); extract = shared.helpers.extract
    watchdog = extract.function(good, 'static void brcmf_sdio_bus_watchdog(')
    console = extract.function(good, 'static int brcmf_sdio_readconsole(')
    ram = extract.function(good, 'int\nbrcmf_sdiod_ramrw(')
    variants = []

    def add(name, body, before, after, group, index, debug=False):
        broken = extract.mutate_once(good, body, extract.mutate_once(body, before, after))
        variants.append((name, broken, (group, str(index)), debug))

    add('lost_entry_gate', watchdog, 'if (brcmf_sdiod_io_blocked(sdiod))\n\t\treturn;',
        'if (false)\n\t\treturn;', 'poll_failure', 0)
    admissions = list(re.finditer(r'if \(brcmf_sdiod_io_blocked\(sdiod\)\)\n\s*goto release;', watchdog))
    if len(admissions) != (4 if clock else 3):
        raise ValueError('Unexpected watchdog admission gates')
    for index, gate in enumerate(admissions):
        broken = watchdog[:gate.start()] + gate[0].replace('if (brcmf_sdiod_io_blocked(sdiod))', 'if (false)') + watchdog[gate.end():]
        target = ('clock_admission', '0') if clock and not index else ('admission', str((index - int(clock)) * 4))
        variants.append(('lost_claim_gate_' + str(index), extract.mutate_once(good, watchdog, broken), target, True))
    errors = list(re.finditer(r'if \(err\)\n\s*goto failed;', watchdog))
    if len(errors) != 4:
        raise ValueError('Unexpected watchdog failure gates')
    targets = [('poll_failure', '0'), ('console_failure', '0'), ('console_failure', '9'), ('idle_failure', '1')]
    for index, gate in enumerate(errors):
        broken = watchdog[:gate.start()] + gate[0].replace('if (err)', 'if (false && err)') + watchdog[gate.end():]
        variants.append(('lost_failure_gate_' + str(index), extract.mutate_once(good, watchdog, broken), targets[index], True))
    reports = list(re.finditer(r'\*ioerr = rv == -ENOMEM \? 0 : rv;', console))
    if len(reports) != 2:
        raise ValueError('Unexpected console transport-error reports')
    for index, report in enumerate(reports):
        broken = console[:report.start()] + '*ioerr = 0;' + console[report.end():]
        variants.append(('lost_console_ioerr_' + str(index), extract.mutate_once(good, console, broken),
                         ('console_failure', str(9 * (index + 1))), True))
        broken = console[:report.start()] + '*ioerr = rv;' + console[report.end():]
        variants.append(('local_ram_as_transport_' + str(index), extract.mutate_once(good, console, broken),
                         ('console_ram_allocation', str(index)), True))
    add('ram_allocation_wrong_errno', ram, 'return -ENOMEM;', 'return -EIO;', 'ram_helper', 0, True)
    add('local_allocation_as_transport', console, 'return -ENOMEM;', 'return *ioerr = -ENOMEM;', 'console_local', 0, True)
    add('local_index_as_transport', console, 'return -EBADE;', 'return *ioerr = -EBADE;', 'console_local', 1, True)
    add('lost_poll_notification', watchdog, 'if (intstatus)', 'if (false && intstatus)', 'poll_success', 2)
    publication = ('\t\t\t\tif (intstatus) {\n'
                   '\t\t\t\t\tbus->sdcnt.pollcnt++;\n'
                   '\t\t\t\t\tatomic_set(&bus->ipend, 1);\n'
                   '\t\t\t\t\tbus->dpc_triggered = true;\n'
                   '\t\t\t\t\tqueue_work(bus->brcmf_wq, &bus->datawork);\n'
                   '\t\t\t\t}\n')
    release = '\t\t\t\tsdio_release_host(sdiod->func1);\n'
    add('late_poll_publication', watchdog, publication + release,
        release + publication, 'retire_after_poll', 0)
    add('lost_idle_timer_stop', watchdog, 'brcmf_sdio_wd_timer(bus, false);', '(void)bus;', 'idle_success', 0)
    add('lost_quarantine', watchdog, 'brcmf_sdio_dpc_failed(bus, err);', '(void)err;', 'poll_failure', 0)
    add('unclaimed_quarantine', watchdog, 'brcmf_sdio_dpc_failed(bus, err);',
        'sdio_release_host(sdiod->func1);\n\tbrcmf_sdio_dpc_failed(bus, err);', 'poll_failure', 0)
    if clock:
        request = extract.function(good, 'static int brcmf_sdio_htclk(')
        add('missing_clock_budget', request, 'bus->clk_pending_deadline = timeout;',
            '(void)timeout;', 'clock_request', 0)
        add('renewed_clock_budget', request,
            'bus->clkstate == CLK_PENDING ? bus->clk_pending_deadline :',
            'false ? bus->clk_pending_deadline :', 'clock_request', 1)
        add('missing_watchdog_clock_notification', watchdog,
            'time_after_eq(jiffies, READ_ONCE(bus->clk_pending_deadline))',
            '(false && time_after_eq(jiffies, READ_ONCE(bus->clk_pending_deadline)))', 'clock_watchdog', 1)
        add('early_watchdog_clock_notification', watchdog,
            'time_after_eq(jiffies, READ_ONCE(bus->clk_pending_deadline))',
            '(true || time_after_eq(jiffies, READ_ONCE(bus->clk_pending_deadline)))', 'clock_watchdog', 0)
        add('lost_clock_deadline_recheck', watchdog,
            'time_after_eq(jiffies, bus->clk_pending_deadline) &&', 'true &&', 'clock_admission', 6)
        publication = ('\t\t\tatomic_set(&bus->ipend, 1);\n'
                       '\t\t\tbus->dpc_triggered = true;\n'
                       '\t\t\tqueue_work(bus->brcmf_wq, &bus->datawork);\n')
        add('lost_clock_pending_status', watchdog, publication,
            publication.replace('atomic_set(&bus->ipend, 1);', 'atomic_set(&bus->ipend, 0);'),
            'clock_watchdog', 1)
        add('late_clock_publication', watchdog, publication,
            '\t\t\tsdio_release_host(sdiod->func1);\n' + publication +
            '\t\t\tsdio_claim_host(sdiod->func1);\n', 'clock_retirement', 0)
    results = {}
    try:
        for name, body, case, debug in variants:
            path.write_text(body); (attempt / (name + '.h')).write_text(body)
            defines = (['-DDEBUG'] if debug else []) + (['-DNEO_CLOCK_DEADLINE'] if clock else [])
            binary = shared.compile_test(attempt, HARNESS, name, defines=defines)
            result = shared.execute(binary, case)
            (attempt / (name + '.log')).write_text(result.stdout + result.stderr)
            if not result.returncode or 'Assertion' not in result.stderr:
                raise ValueError('Watchdog mutation did not fail assertion: ' + name)
            results[name] = dict(case=case, debug=debug, returncode=result.returncode, error=result.stderr)
    finally:
        path.write_text(good)
    atomic_json(attempt / 'negatives.json', results)
    print(f'{len(results)} watchdog mutations rejected', flush=True)
