#!/usr/bin/env python3
"""Exercise actual TX FIFO recovery and control/data callers without a device."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

from kernel_checks import ROOT, archive_for, build_objects, sha256
from kernel_sources import atomic_json, ensure_source, locked

BASE = 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/'
WORK = ROOT / '.local/build/brcmfmac-tx-recovery'
HARNESS = ROOT / 'kernel/tests/brcmfmac_tx_recovery_test.c'
POLL_STATUS = False
CLOCK_DEADLINE = False
CASES = [(group, str(index)) for group, count in (
    ('helper_failure', 24), ('helper_success', 3), ('helper_exhaustion', 1),
    ('helper_prior', 3), ('control_failure', 10), ('control_success', 32),
    ('control_prior', 3), ('data_failure', 20), ('data_success', 8), ('data_local', 3))
    for index in range(count)]
POLL_CASES = [(group, str(index)) for group, count in (
    ('poll_failure', 72), ('poll_success', 12), ('poll_prior', 6), ('poll_interrupt', 18))
    for index in range(count)]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


rx = module('tx_shared_caller_checks', 'check-brcmfmac-rx-callers.py')


def extract_sources(source, attempt):
    sdio, header, bcmsdh = ((source / BASE / name).read_text() for name in ('sdio.c', 'sdio.h', 'bcmsdh.c'))
    types = rx.helpers.constants(sdio, header, (source / 'include/linux/mmc/sdio.h').read_text())
    for prefix in ('struct brcmf_sdio_hdrinfo {', 'struct brcmf_sdio_count {'):
        types += rx.declarations(sdio, prefix)
    for name in ('SFC_WF_TERM', 'TXRETRIES', 'TXLOW', 'TXHI', 'TXQLEN', 'TXCTL_CREDITS', 'SDPCM_SEQ_WRAP',
                 'SDPCM_CONTROL_CHANNEL', 'SDPCM_DATA_CHANNEL'):
        matches = re.findall(r'^#define\s+' + name + r'\s+[^\n]+$', sdio, re.M)
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous TX constant: ' + name)
        types += matches[0] + '\n'
    text = rx.helpers.extract.function(bcmsdh, 'int brcmf_sdiod_abort(')
    for prefix in ('static bool data_ok(', 'static void brcmf_sdio_txfail(',
                   'static int brcmf_sdio_txpkt(', 'static uint brcmf_sdio_sendfromq(',
                   'static int brcmf_sdio_tx_ctrlframe('):
        text += rx.helpers.extract.function(sdio, prefix)
    (attempt / 'brcmfmac_tx_types.h').write_text(types)
    (attempt / 'brcmfmac_tx_functions.h').write_text(text)


def run_cases(attempt, arm=False, sanitizer=False):
    label = 'arm' if arm else 'sanitizer' if sanitizer else 'native'
    binary = rx.compile_test(attempt, HARNESS, label, arm, sanitizer)
    results = {}
    for group, index in CASES:
        result = rx.execute(binary, (group, index), arm)
        name = group + '-' + index
        results[name] = dict(returncode=result.returncode, output=result.stdout, error=result.stderr)
        (attempt / (label + '-' + name + '.log')).write_text(result.stdout + result.stderr)
    atomic_json(attempt / (label + '-results.json'), results)
    failed = [name for name, value in results.items() if value['returncode'] or
              value['output'].strip() != name.replace('-', ' ') + ' passed']
    print(f'{label} TX recovery: {len(CASES)-len(failed)}/{len(CASES)} pass', flush=True)
    if failed:
        raise RuntimeError('TX scenarios failed: ' + ', '.join(failed))


def negatives(attempt):
    path = attempt / 'brcmfmac_tx_functions.h'
    good = path.read_text()
    extract = rx.helpers.extract
    fail = extract.function(good, 'static void brcmf_sdio_txfail(')
    control = extract.function(good, 'static int brcmf_sdio_tx_ctrlframe(')
    packet = extract.function(good, 'static int brcmf_sdio_txpkt(')
    queue = extract.function(good, 'static uint brcmf_sdio_sendfromq(')
    cases = [
        ('lost_prior_error', fail, 'if (READ_ONCE(sdiodev->io_error))', 'if (false)', ('helper_prior', '0')),
        ('lost_error_latch', fail, 'WRITE_ONCE(sdiodev->io_error, err);', '', ('helper_failure', '0')),
        ('lost_exhaustion', fail, 'err = -ETIMEDOUT;', 'err = 0;', ('helper_exhaustion', '0')),
        ('shortened_flush_budget', fail, 'i < 3', 'i < 2', ('helper_success', '2')),
        ('lost_control_admission', control, 'if (ret)\n\t\treturn ret;',
         'if (false && ret)\n\t\treturn ret;', ('control_prior', '0')),
        ('lost_control_retry_gate', control, 'if (READ_ONCE(bus->sdiodev->io_error))',
         'if (false)', ('control_failure', '0')),
        ('lost_control_success_sequence', control, 'bus->tx_seq = (bus->tx_seq + 1) % SDPCM_SEQ_WRAP;',
         'bus->tx_seq = bus->tx_seq;', ('control_success', '0')),
        ('lost_packet_admission', packet, 'if (ret)\n\t\tgoto release;',
         'if (false && ret)\n\t\tgoto release;', ('data_local', '2')),
        ('lost_postprocessing', packet, 'brcmf_sdio_txpkt_postp(bus, pktq);',
         'if (false) brcmf_sdio_txpkt_postp(bus, pktq);', ('data_local', '0')),
        ('lost_completion', packet, 'brcmf_proto_bcdc_txcomplete(bus->sdiodev->dev, pkt_next,',
         'if (false) brcmf_proto_bcdc_txcomplete(bus->sdiodev->dev, pkt_next,', ('data_local', '0')),
        ('lost_queue_admission', queue, 'cnt < maxframes && !READ_ONCE(bus->sdiodev->io_error) &&',
         'cnt < maxframes &&', ('data_failure', '0')),
        ('lost_poll_gate', queue, 'if (READ_ONCE(bus->sdiodev->io_error))',
         'if (false)', ('data_failure', '1')),
        ('lost_deflow_gate', queue, 'if (!READ_ONCE(bus->sdiodev->io_error) &&',
         'if (true &&', ('data_failure', '0')),
    ]
    if POLL_STATUS:
        cases += [
            ('lost_poll_error_latch', queue, 'WRITE_ONCE(bus->sdiodev->io_error, ret);',
             '(void)ret;', ('poll_failure', '0')),
            ('lost_poll_admission', queue, 'ret = READ_ONCE(bus->sdiodev->io_error);',
             'ret = 0;', ('poll_prior', '0')),
            ('late_poll_latch', queue,
             '\t\t\t\tif (ret)\n\t\t\t\t\tWRITE_ONCE(bus->sdiodev->io_error, ret);\n'
             '\t\t\t}\n\t\t\tsdio_release_host(bus->sdiodev->func1);',
             '\t\t\t}\n\t\t\tsdio_release_host(bus->sdiodev->func1);\n'
             '\t\t\tif (ret)\n\t\t\t\tWRITE_ONCE(bus->sdiodev->io_error, ret);', ('poll_failure', '0')),
            ('lost_poll_status_gate', queue, 'if (ret != 0)', 'if (false)', ('poll_failure', '8')),
            ('lost_poll_notification', queue, 'if (intstatus & bus->hostintmask)',
             'if (false && (intstatus & bus->hostintmask))', ('poll_success', '4')),
            ('lost_poll_statistics', queue, 'bus->sdcnt.f2txdata++;', '', ('poll_success', '0')),
        ]
    gates = list(re.finditer(r'if \(err\)\n\s*goto failed;', fail))
    if len(gates) != 4:
        raise ValueError('Unexpected TX recovery error gates')
    variants = {name: (extract.mutate_once(good, body, extract.mutate_once(body, before, after)), case)
                for name, body, before, after, case in cases}
    for index, gate in enumerate(gates):
        broken = fail[:gate.start()] + gate[0].replace('if (err)', 'if (false && err)') + fail[gate.end():]
        variants['lost_recovery_gate_' + str(index)] = (extract.mutate_once(good, fail, broken), ('helper_failure', str(index * 6)))
    results = {}
    try:
        for name, (body, case) in variants.items():
            path.write_text(body); (attempt / (name + '.h')).write_text(body)
            binary = rx.compile_test(attempt, HARNESS, name)
            result = rx.execute(binary, case)
            (attempt / (name + '.log')).write_text(result.stdout + result.stderr)
            if not result.returncode or 'Assertion' not in result.stderr:
                raise ValueError('TX mutation did not fail an assertion: ' + name)
            results[name] = dict(case=case, returncode=result.returncode, error=result.stderr)
    finally:
        path.write_text(good)
    atomic_json(attempt / 'negatives.json', results)
    print(f'{len(results)} TX mutations rejected', flush=True)


def worker_variants(good):
    extract = rx.helpers.extract
    variants = module('tx_mailbox_checks', 'check-brcmfmac-mailbox.py').variants(good)
    dpc = extract.function(good, 'static void brcmf_sdio_dpc(')
    for name, before, after in (
        ('lost_rx_exit', '/* RX callers own packet cleanup; retire the worker before any TX. */\n'
         '\t\terr = READ_ONCE(sdiod->io_error);',
         '/* Broken RX handoff */\n\t\terr = 0;'),
        ('lost_rx_host', '\t\tif (err) {\n\t\t\tsdio_claim_host(sdiod->func1);\n'
         '\t\t\tgoto failed;\n\t\t}\n\t\tif (!bus->rxpending)',
         '\t\tif (err) {\n\t\t\tgoto failed;\n\t\t}\n\t\tif (!bus->rxpending)'),
        ('lost_control_exit', 'if (READ_ONCE(sdiod->io_error)) {', 'if (false) {'),
        ('lost_data_exit', 'brcmf_sdio_sendfromq(bus, framecnt);\n\t\terr = READ_ONCE(sdiod->io_error);',
         'brcmf_sdio_sendfromq(bus, framecnt);\n\t\terr = 0;'),
        ('lost_data_host', '\t\tbrcmf_sdio_sendfromq(bus, framecnt);\n\t\terr = READ_ONCE(sdiod->io_error);\n'
         '\t\tif (err) {\n\t\t\tsdio_claim_host(sdiod->func1);',
         '\t\tbrcmf_sdio_sendfromq(bus, framecnt);\n\t\terr = READ_ONCE(sdiod->io_error);\n\t\tif (err) {'),
    ):
        variants[name] = extract.mutate_once(good, dpc, extract.mutate_once(dpc, before, after))
    return variants


def run_worker(attempt, arm=False, sanitizer=False, negative=False):
    generated = attempt / 'brcmfmac_freezer_functions.h'; good = generated.read_text()
    variants = worker_variants(good) if negative else {'candidate': good}
    if negative and CLOCK_DEADLINE:
        extract = rx.helpers.extract
        dpc = extract.function(good, 'static void brcmf_sdio_dpc(')
        for name, replacement in (
                ('lost_clock_timeout', 'false && time_after_eq(jiffies, bus->clk_pending_deadline)'),
                ('early_clock_timeout', 'true || time_after_eq(jiffies, bus->clk_pending_deadline)')):
            variants[name] = extract.mutate_once(good, dpc, extract.mutate_once(dpc,
                'time_after_eq(jiffies, bus->clk_pending_deadline)', replacement))
    variants['candidate_debug'] = good
    label = 'arm' if arm else 'sanitizer' if sanitizer else 'native'
    results = {}
    try:
        for name, body in variants.items():
            generated.write_text(body); (attempt / (name + '.h')).write_text(body)
            defines = ['-DNEO_WORKER_ERRORS', '-DNEO_RX_RECOVERY', '-DNEO_MAILBOX_ERRORS', '-DNEO_TX_RECOVERY']
            if POLL_STATUS: defines.append('-DNEO_TX_POLL')
            if CLOCK_DEADLINE: defines.append('-DNEO_CLOCK_DEADLINE')
            if name == 'candidate_debug': defines.append('-DDEBUG')
            binary = rx.compile_test(attempt, ROOT / 'kernel/tests/brcmfmac_irq_test.c',
                                     label + '-' + name, arm, sanitizer, defines)
            result = rx.execute(binary, arm=arm)
            (attempt / (label + '-' + name + '.log')).write_text(result.stdout + result.stderr)
            if name in ('candidate', 'candidate_debug'):
                result.check_returncode()
                count = 179 + (32 if POLL_STATUS else 0) + (24 if CLOCK_DEADLINE else 0) + 2 * (name == 'candidate_debug')
                if result.stdout.strip() != f'{count} IRQ service scenarios passed (0 characterize existing error limitations)':
                    raise ValueError('Unexpected TX worker coverage: ' + result.stdout)
            elif not result.returncode or 'Assertion' not in result.stderr:
                raise ValueError('Worker mutation did not fail an assertion: ' + name)
            results[name] = dict(returncode=result.returncode, output=result.stdout, error=result.stderr)
    finally:
        generated.write_text(good)
    atomic_json(attempt / (label + '-results.json'), results)
    count = (211 if POLL_STATUS else 179) + (24 if CLOCK_DEADLINE else 0)
    print(f'{label} worker: {count}/{count+2} cases pass; {len(results)-2} mutations rejected', flush=True)


def main():
    global POLL_STATUS, CLOCK_DEADLINE, CASES, WORK
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--baseline', action='store_true', help='Reproduce uncorrected TX error ownership')
    mode.add_argument('--poll-status', action='store_true', help='Qualify queued-TX polling status errors')
    mode.add_argument('--poll-baseline', action='store_true', help='Reproduce discarded polling status errors')
    mode.add_argument('--watchdog-errors', action='store_true', help='Qualify watchdog errors and retirement')
    mode.add_argument('--watchdog-baseline', action='store_true', help='Reproduce ignored watchdog errors')
    mode.add_argument('--clock-deadline', action='store_true', help='Qualify bounded asynchronous clock readiness')
    mode.add_argument('--clock-baseline', action='store_true', help='Reproduce an unbounded pending clock')
    parser.add_argument('--native-only', action='store_true')
    parser.add_argument('--compile-drivers', action='store_true')
    parser.add_argument('--arm-attempt', help=argparse.SUPPRESS)
    args = parser.parse_args()
    CLOCK_DEADLINE = args.clock_deadline or args.clock_baseline
    watchdog_mode = args.watchdog_errors or args.watchdog_baseline or CLOCK_DEADLINE
    watchdog = module('watchdog_checks', 'brcmfmac_watchdog_checks.py') if watchdog_mode else None
    POLL_STATUS = args.poll_status or args.poll_baseline or watchdog_mode
    if POLL_STATUS:
        CASES = CASES + POLL_CASES
        WORK = ROOT / '.local/build/brcmfmac-tx-poll'
    if watchdog_mode:
        WORK = ROOT / '.local/build/brcmfmac-watchdog'
    if CLOCK_DEADLINE:
        WORK = ROOT / '.local/build/brcmfmac-clock-deadline'
    if args.arm_attempt:
        attempt = ROOT / args.arm_attempt
        if watchdog:
            watchdog.run_cases(attempt / 'watchdog', rx, arm=True, clock=CLOCK_DEADLINE)
            if CLOCK_DEADLINE:
                watchdog.run_sleep(attempt / 'watchdog', rx, arm=True)
        run_cases(attempt, arm=True)
        rx.run_cases(attempt / 'rx', arm=True, control=True)
        run_worker(attempt / 'worker', arm=True)
        return
    os.umask(0o077)
    WORK.mkdir(parents=True, exist_ok=True)
    with locked(WORK / '.lock'):
        attempt = WORK / 'attempts' / uuid.uuid4().hex
        attempt.mkdir(parents=True)
        print('TX recovery evidence:', attempt, flush=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        queue = list(rx.helpers.module('tx_kernel_inputs', 'kernel-inputs.py').patches())
        paths = [ROOT / 'kernel/candidates' / name for name in (
            '0046-brcmfmac-rx-recovery.patch', '0047-brcmfmac-rx-packet-errors.patch',
            '0039-brcmfmac-mailbox-errors.patch', '0048-brcmfmac-control-rx-retry.patch')]
        if not args.baseline:
            paths.append(ROOT / 'kernel/candidates/0049-brcmfmac-tx-recovery.patch')
        if args.poll_status or watchdog_mode:
            paths.append(ROOT / 'kernel/candidates/0050-brcmfmac-tx-poll-errors.patch')
        if args.watchdog_errors or CLOCK_DEADLINE:
            paths.append(ROOT / 'kernel/candidates/0051-brcmfmac-watchdog-errors.patch')
        if args.clock_deadline:
            paths.append(ROOT / 'kernel/candidates/0052-brcmfmac-clock-deadline.patch')
        for path in paths:
            if path.name in {name for name, _ in queue}:
                raise ValueError('TX test candidate unexpectedly entered image queue')
            queue.append((path.name, path.read_bytes()))
        manifest = [dict(name=name, sha256=hashlib.sha256(data).hexdigest()) for name, data in queue]
        paths += [HARNESS, Path(__file__), ROOT / 'build/sources.lock.json',
                  ROOT / 'tools/check-brcmfmac-rx-callers.py', ROOT / 'tools/check-brcmfmac-rx-recovery.py',
                  ROOT / 'tools/check-brcmfmac-pm.py', ROOT / 'tools/brcmfmac_irq_checks.py',
                  ROOT / 'tools/kernel-inputs.py', ROOT / 'tools/kernel_sources.py', ROOT / 'tools/kernel_checks.py',
                  ROOT / 'tools/check-brcmfmac-mailbox.py', ROOT / 'kernel/tests/brcmfmac_irq_test.c',
                  ROOT / 'kernel/tests/brcmfmac_rx_callers_test.c', ROOT / 'kernel/gameshellneo.config']
        if watchdog:
            paths += [watchdog.HARNESS, ROOT / 'tools/brcmfmac_watchdog_checks.py']
        if CLOCK_DEADLINE:
            paths += [ROOT / 'tools/check-brcmfmac-sleep.py', ROOT / 'kernel/tests/brcmfmac_sleep_test.c']
        hashes = {str(path.relative_to(ROOT)): sha256(path) for path in paths}
        atomic_json(attempt / 'inputs.json', hashes)
        with locked(WORK / '.source-lock'):
            source, _, metadata = ensure_source(ROOT, WORK, archive, lock, manifest, recorded_patches=queue)
        atomic_json(attempt / 'source.json', metadata)
        if watchdog:
            watch = attempt / 'watchdog'; watch.mkdir()
            watchdog.extract_sources(source, watch, rx, clock=CLOCK_DEADLINE)
            watchdog.run_cases(watch, rx, clock=CLOCK_DEADLINE)
            if args.watchdog_baseline:
                raise RuntimeError('Watchdog baseline unexpectedly passed; inspect before qualification')
            if args.clock_baseline:
                raise RuntimeError('Clock baseline unexpectedly passed; inspect before qualification')
            watchdog.run_cases(watch, rx, sanitizer=True, clock=CLOCK_DEADLINE)
            watchdog.negatives(watch, rx, clock=CLOCK_DEADLINE)
            if CLOCK_DEADLINE:
                watchdog.run_sleep(watch, rx)
                watchdog.run_sleep(watch, rx, sanitizer=True)
        extract_sources(source, attempt)
        run_cases(attempt)
        run_cases(attempt, sanitizer=True)
        if args.baseline or args.poll_baseline:
            raise RuntimeError('Baseline unexpectedly passed; inspect before qualification')
        negatives(attempt)
        receive = attempt / 'rx'; receive.mkdir()
        rx.extract_sources(source, receive)
        rx.run_cases(receive, control=True)
        rx.run_cases(receive, sanitizer=True, control=True)
        rx.packet_negatives(receive); rx.control_negatives(receive)
        worker = attempt / 'worker'; worker.mkdir()
        sdio, header, bcmsdh = ((source / BASE / name).read_text() for name in ('sdio.c', 'sdio.h', 'bcmsdh.c'))
        (worker / 'brcmfmac_irq_types.h').write_text(rx.irq.definitions(sdio, header))
        (worker / 'brcmfmac_freezer_functions.h').write_text(rx.irq.extracted(
            sdio, header, rx.helpers.extract.function, bcmsdh, hardened=True, mailbox=True))
        run_worker(worker, negative=True)
        run_worker(worker, sanitizer=True)
        if not args.native_only:
            subprocess.run(['docker', 'run', '--rm', '--network=none', '--pull=never',
                '--user', f'{os.getuid()}:{os.getgid()}', '--platform', lock['builder']['platform'],
                '--entrypoint=python3', '-v', f'{ROOT}:/project', '-w', '/project',
                lock['builder']['image'], 'tools/check-brcmfmac-tx-recovery.py',
                *(['--clock-deadline'] if CLOCK_DEADLINE else ['--watchdog-errors'] if watchdog_mode else ['--poll-status'] if POLL_STATUS else []),
                '--arm-attempt', str(attempt.relative_to(ROOT))], check=True, timeout=180)
        builds = {}
        if args.compile_drivers:
            for name, extra in dict(board=(), debug=('CONFIG_BRCMDBG=y',)).items():
                identity = hashlib.sha256(json.dumps([manifest, extra, hashes], sort_keys=True).encode()).hexdigest()[:16]
                scratch = WORK / ('kernel-' + identity); scratch.mkdir(exist_ok=True)
                (scratch / 'extra.config').write_text(''.join(value + '\n' for value in extra))
                builds[name] = build_objects(source, scratch, lock, [BASE + 'brcmfmac.o'],
                                            extra, True, metadata, offline=True)
        if hashes != {str(path.relative_to(ROOT)): sha256(path) for path in paths}:
            raise ValueError('TX test inputs changed during execution')
        atomic_json(attempt / 'evidence.json', dict(schema=1, baseline=args.baseline or args.poll_baseline,
            poll_status=POLL_STATUS,
            watchdog=watchdog_mode,
            clock_deadline=CLOCK_DEADLINE,
            native_complete=True, native_sanitizers=True, arm_complete=not args.native_only,
            inputs=hashes, source=metadata, cases=CASES, arm_build=builds,
            artifacts={str(path.relative_to(attempt)): sha256(path) for path in attempt.rglob('*') if path.is_file()},
            limits=('Actual HT clock and sleep bodies with scripted transfers and jiffies. '
                    'Watchdog queue and worker notification tested at separate controlled seams; '
                    'no wall-clock scheduling guarantee. ' if CLOCK_DEADLINE else '') +
                   ('Actual watchdog/console/timer/cleanup bodies; scripted transport, clock, IRQ and '
                    'timer operations plus deterministic host-boundary injections. ' if watchdog_mode else '') +
                   'Actual recovery/control/data callers; scripted synchronous SDIO, packet queues, '
                   'header packing and packet prep/postprocessing. Actual worker bodies use scripted '
                   'packet-call boundaries; no complete-kernel concurrency or hardware qualification.'))


if __name__ == '__main__':
    main()
