#!/usr/bin/env python3
"""Exercise actual RX packet callers with tracked buffers and scripted transfers."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import uuid

import brcmfmac_irq_checks as irq
from kernel_checks import ROOT, archive_for, build_objects, sha256
from kernel_sources import atomic_json, ensure_source, locked

BASE = 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/'
WORK = ROOT / '.local/build/brcmfmac-rx-callers'
HARNESS = ROOT / 'kernel/tests/brcmfmac_rx_callers_test.c'
CASES = [(group, str(index)) for group, count in (
    ('data', 16), ('control', 4), ('glom', 6), ('success', 3), ('glom_success', 2),
    ('glom_header', 12), ('glom_pair', 2), ('glom_pair_success', 1),
    ('descriptor', 6), ('prior_error', 1))
    for index in range(count)]
CONTROL_CASES = [(group, str(index)) for group, count in (
    ('ctl_oom', 40), ('ctl_body', 12), ('ctl_success', 8), ('ctl_retries', 2))
    for index in range(count)]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


helpers = module('rx_recovery_helpers', 'check-brcmfmac-rx-recovery.py')


def declarations(source, prefix):
    start = source.index(prefix)
    return source[start:source.index('\n};', start) + 4]


def extract_sources(source, output):
    sdio, header, bcmsdh = ((source / BASE / n).read_text() for n in ('sdio.c', 'sdio.h', 'bcmsdh.c'))
    types = helpers.constants(sdio, header, (source / 'include/linux/mmc/sdio.h').read_text())
    for prefix in ('struct brcmf_sdio_hdrinfo {', 'struct brcmf_sdio_count {', 'enum brcmf_sdio_frmtype {'):
        types += declarations(sdio, prefix)
    for line in sdio.splitlines(True):
        match = re.match(r'#define\s+(\w+)', line)
        if match and (match[1].startswith('SDPCM_') and match[1] != 'SDPCM_PROT_VERSION' or
                      match[1] in ('BRCMF_FIRSTREAD', 'MAX_RX_DATASZ', 'RETRYCHAN')):
            if line.endswith('\\\n'):
                raise ValueError('Unexpected multiline RX macro')
            types += line
    text = helpers.functions(sdio, bcmsdh)
    for decl in ('static uint brcmf_sdio_glom_len(', 'static void brcmf_sdio_free_glom(',
                 'static inline u8 brcmf_sdio_getdatoffset(', 'static inline bool brcmf_sdio_fromevntchan(',
                 'static int brcmf_sdio_hdparse(', 'static u8 brcmf_sdio_rxglom(',
                 'static void\nbrcmf_sdio_read_control(', 'static void brcmf_sdio_pad(',
                 'static uint brcmf_sdio_readframes('):
        text += helpers.extract.function(sdio, decl)
    (output / 'brcmfmac_rx_caller_types.h').write_text(types)
    (output / 'brcmfmac_rx_caller_functions.h').write_text(text)


def compile_test(attempt, harness, name, arm=False, sanitizer=False, defines=()):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    binary = attempt / (name + '.bin')
    command = ['arm-linux-gnueabihf-gcc' if arm else 'cc', '-std=gnu11', '-O1', '-g',
        '-Wall', '-Wextra', '-Werror', '-Wno-trigraphs', '-ftrivial-auto-var-init=pattern',
        *defines, '-I', str(attempt), str(harness), '-o', str(binary)]
    if arm:
        command.append('-static')
    if sanitizer:
        command += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    (attempt / (name + '-compile.log')).write_text(result.stdout + result.stderr)
    result.check_returncode()
    return binary


def execute(binary, arguments=(), arm=False):
    return subprocess.run([*(['qemu-arm'] if arm else []), str(binary), *arguments],
                          capture_output=True, text=True, timeout=30)


def run_cases(attempt, arm=False, sanitizer=False, control=False):
    label = 'arm' if arm else 'sanitizer' if sanitizer else 'native'
    binary = compile_test(attempt, HARNESS, label, arm, sanitizer)
    results = {}
    cases = CASES + (CONTROL_CASES if control else [])
    for group, index in cases:
        result = execute(binary, (group, index), arm)
        name = group + '-' + index
        results[name] = dict(returncode=result.returncode, output=result.stdout, error=result.stderr)
        (attempt / (label + '-' + name + '.log')).write_text(result.stdout + result.stderr)
    atomic_json(attempt / (label + '-results.json'), results)
    failures = [name for name, value in results.items() if value['returncode'] or
                value['output'].strip() != name.replace('-', ' ') + ' passed']
    print(label + f' RX callers: {len(cases)-len(failures)}/{len(cases)} pass', flush=True)
    if failures:
        raise RuntimeError('RX caller cases failed: ' + ', '.join(failures))


def packet_negatives(attempt):
    generated = attempt / 'brcmfmac_rx_caller_functions.h'
    good = generated.read_text()
    change = helpers.extract.mutate_once
    glom = helpers.extract.function(good, 'static u8 brcmf_sdio_rxglom(')
    read = helpers.extract.function(good, 'static uint brcmf_sdio_readframes(')
    cases = [
        ('lost_packet_free', read,
         '\t\t\t\tbrcmu_pkt_buf_free_skb(pkt);\n\t\t\t}\n\t\t\t/* prepare',
         '\t\t\t}\n\t\t\t/* prepare', ('data', '14')),
        ('lost_superframe_gate', glom,
         'if (!errcode) {\n\t\t\tbus->cur_read.len',
         'if (true) {\n\t\t\tbus->cur_read.len', ('glom', '2')),
        ('lost_receive_error_gate', read, '!READ_ONCE(bus->sdiodev->io_error) &&',
         '', ('data', '1')),
        ('lost_next_frame_clear', read, '\t\trd->len_nxtfrm = 0;\n\t}',
         '\t}', ('prior_error', '0')),
    ]
    results = {}
    try:
        for name, body, before, after, case in cases:
            broken = change(good, body, change(body, before, after))
            generated.write_text(broken)
            (attempt / (name + '.h')).write_text(broken)
            binary = compile_test(attempt, HARNESS, name)
            result = execute(binary, case)
            (attempt / (name + '.log')).write_text(result.stdout + result.stderr)
            if not result.returncode or 'Assertion' not in result.stderr:
                raise ValueError('Packet negative control did not fail an assertion: ' + name)
            results[name] = dict(returncode=result.returncode, case=case, error=result.stderr)
    finally:
        generated.write_text(good)
    atomic_json(attempt / 'packet-negatives.json', results)
    print(f'{len(results)} packet negative controls rejected', flush=True)


def control_negatives(attempt):
    generated = attempt / 'brcmfmac_rx_caller_functions.h'
    good = generated.read_text()
    change = helpers.extract.mutate_once
    control = helpers.extract.function(good, 'static void\nbrcmf_sdio_read_control(')
    read = helpers.extract.function(good, 'static uint brcmf_sdio_readframes(')
    cases = [
        ('lost_allocation_recovery', control, 'brcmf_sdio_rxfail(bus, false, true);',
         '', ('ctl_oom', '0')),
        ('lost_retry_header_clear', read, 'rd->len = bus->rxskip ? 0 : rd->len_nxtfrm << 4;',
         'rd->len = rd->len_nxtfrm << 4;', ('ctl_body', '0')),
        ('lost_successful_hint', read, 'rd->len = bus->rxskip ? 0 : rd->len_nxtfrm << 4;',
         'rd->len = 0;', ('ctl_success', '4')),
        ('lost_pending_response', control, 'brcmf_sdio_rxfail(bus, false, true);',
         'bus->rxctl = NULL; bus->rxlen = 0; brcmf_sdio_rxfail(bus, false, true);', ('ctl_oom', '2')),
        ('lost_allocation_error_count', control,
         '\t\tbus->sdcnt.rxc_errors++;\n\t\tbrcmf_sdio_rxfail(bus, false, true);',
         '\t\tbrcmf_sdio_rxfail(bus, false, true);', ('ctl_oom', '0')),
    ]
    results = {}
    try:
        for name, body, before, after, case in cases:
            broken = change(good, body, change(body, before, after))
            generated.write_text(broken)
            (attempt / (name + '.h')).write_text(broken)
            binary = compile_test(attempt, HARNESS, name)
            result = execute(binary, case)
            (attempt / (name + '.log')).write_text(result.stdout + result.stderr)
            if not result.returncode or 'Assertion' not in result.stderr:
                raise ValueError('Control negative did not fail an assertion: ' + name)
            results[name] = dict(returncode=result.returncode, case=case, error=result.stderr)
    finally:
        generated.write_text(good)
    atomic_json(attempt / 'control-negatives.json', results)
    print(f'{len(results)} control FIFO negative controls rejected', flush=True)


def run_dpc(attempt, mailbox, arm=False, sanitizer=False, negatives=False):
    generated = attempt / 'brcmfmac_freezer_functions.h'
    good = generated.read_text()
    extract = helpers.extract
    if negatives:
        variants = irq.variants(good, extract.function, extract.mutate_once,
                                hardened=True, mailbox=mailbox)
        if mailbox:
            variants = module('rx_mailbox_checks', 'check-brcmfmac-mailbox.py').variants(good)
        dpc = extract.function(good, 'static void brcmf_sdio_dpc(')
        for name, before, after in (
            ('lost_rx_worker_exit', 'err = READ_ONCE(sdiod->io_error);\n\t\tif (err)',
             'err = READ_ONCE(sdiod->io_error);\n\t\tif (false && err)'),
            ('lost_rx_worker_host', 'if (err) {\n\t\t\tsdio_claim_host(sdiod->func1);\n\t\t\tgoto failed;',
             'if (err) {\n\t\t\tgoto failed;'),
        ):
            variants[name] = extract.mutate_once(good, dpc, extract.mutate_once(dpc, before, after))
    else:
        variants = {'candidate': good}
    variants['candidate_debug'] = good
    label = 'arm' if arm else 'sanitizer' if sanitizer else 'native'
    results = {}
    try:
        for name, body in variants.items():
            generated.write_text(body)
            (attempt / ('dpc-' + name + '.h')).write_text(body)
            defines = ['-DNEO_WORKER_ERRORS', '-DNEO_RX_RECOVERY']
            if mailbox:
                defines.append('-DNEO_MAILBOX_ERRORS')
            if name == 'candidate_debug':
                defines.append('-DDEBUG')
            prefix = f'dpc-{label}-{name}'
            binary = compile_test(attempt, ROOT / 'kernel/tests/brcmfmac_irq_test.c',
                                  prefix, arm, sanitizer, defines)
            result = execute(binary, arm=arm)
            (attempt / (prefix + '.log')).write_text(result.stdout + result.stderr)
            if name in ('candidate', 'candidate_debug'):
                result.check_returncode()
                count = (147 if mailbox else 65) + 2 * (name == 'candidate_debug')
                if result.stdout.strip() != f'{count} IRQ service scenarios passed (0 characterize existing error limitations)':
                    raise ValueError('Unexpected DPC scenario coverage: ' + result.stdout)
            elif not result.returncode or 'Assertion' not in result.stderr:
                raise ValueError('DPC negative control did not fail an assertion: ' + name)
            results[name] = dict(returncode=result.returncode, output=result.stdout, error=result.stderr)
    finally:
        generated.write_text(good)
    atomic_json(attempt / ('dpc-' + label + '-results.json'), results)
    print(label + f' DPC checks: normal/debug passed; {len(results)-2} negative controls rejected', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-only', action='store_true')
    parser.add_argument('--packet-fixes', action='store_true')
    parser.add_argument('--mailbox', action='store_true')
    parser.add_argument('--compile-drivers', action='store_true')
    parser.add_argument('--control-cases', action='store_true',
                        help='Include byte-position control FIFO scenarios; also allows baseline reproduction')
    parser.add_argument('--control-fixes', action='store_true',
                        help='Add candidate 0048 and its control FIFO qualification')
    parser.add_argument('--arm-attempt', help=argparse.SUPPRESS)
    args = parser.parse_args()
    control = args.control_cases or args.control_fixes
    if args.control_fixes and not args.packet_fixes:
        parser.error('--control-fixes requires --packet-fixes')
    if args.arm_attempt:
        run_cases(ROOT / args.arm_attempt, arm=True, control=control)
        run_dpc(ROOT / args.arm_attempt, args.mailbox, arm=True)
        return
    os.umask(0o077)
    WORK.mkdir(parents=True, exist_ok=True)
    with locked(WORK / '.lock'):
        attempt = WORK / 'attempts' / uuid.uuid4().hex
        attempt.mkdir(parents=True)
        print('RX caller evidence:', attempt, flush=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        queue = list(helpers.module('rx_caller_kernel_inputs', 'kernel-inputs.py').patches())
        patches = [ROOT / 'kernel/candidates/0046-brcmfmac-rx-recovery.patch']
        if args.packet_fixes:
            patches.append(ROOT / 'kernel/candidates/0047-brcmfmac-rx-packet-errors.patch')
        if args.mailbox:
            patches.append(ROOT / 'kernel/candidates/0039-brcmfmac-mailbox-errors.patch')
        if args.control_fixes:
            patches.append(ROOT / 'kernel/candidates/0048-brcmfmac-control-rx-retry.patch')
        for path in patches:
            if path.name in {name for name, _ in queue}:
                raise ValueError('Caller candidate unexpectedly entered image queue')
            queue.append((path.name, path.read_bytes()))
        manifest = [dict(name=n, sha256=hashlib.sha256(b).hexdigest()) for n, b in queue]
        paths = [*patches, HARNESS, Path(__file__), ROOT / 'build/sources.lock.json',
                 ROOT / 'tools/check-brcmfmac-rx-recovery.py', ROOT / 'tools/check-brcmfmac-pm.py',
                 ROOT / 'tools/brcmfmac_irq_checks.py', ROOT / 'tools/kernel-inputs.py',
                 ROOT / 'tools/kernel_sources.py', ROOT / 'tools/kernel_checks.py',
                 ROOT / 'tools/check-brcmfmac-mailbox.py', ROOT / 'kernel/tests/brcmfmac_irq_test.c',
                 ROOT / 'kernel/gameshellneo.config']
        hashes = {str(p.relative_to(ROOT)): sha256(p) for p in paths}
        atomic_json(attempt / 'inputs.json', hashes)
        with locked(WORK / '.source-lock'):
            source, _, metadata = ensure_source(ROOT, WORK, archive, lock, manifest, recorded_patches=queue)
        atomic_json(attempt / 'source.json', metadata)
        extract_sources(source, attempt)
        sdio, header, bcmsdh = ((source / BASE / n).read_text() for n in ('sdio.c', 'sdio.h', 'bcmsdh.c'))
        (attempt / 'brcmfmac_irq_types.h').write_text(irq.definitions(sdio, header))
        (attempt / 'brcmfmac_freezer_functions.h').write_text(irq.extracted(
            sdio, header, helpers.extract.function, bcmsdh, hardened=True, mailbox=args.mailbox))
        run_cases(attempt, control=control)
        run_cases(attempt, sanitizer=True, control=control)
        if args.packet_fixes:
            packet_negatives(attempt)
        if args.control_fixes:
            control_negatives(attempt)
        run_dpc(attempt, args.mailbox, negatives=True)
        run_dpc(attempt, args.mailbox, sanitizer=True)
        if not args.native_only:
            command = ['docker', 'run', '--rm', '--network=none', '--pull=never',
                '--user', f'{os.getuid()}:{os.getgid()}', '--platform', lock['builder']['platform'],
                '--entrypoint=python3', '-v', f'{ROOT}:/project', '-w', '/project',
                lock['builder']['image'], 'tools/check-brcmfmac-rx-callers.py',
                '--arm-attempt', str(attempt.relative_to(ROOT)), *(['--mailbox'] if args.mailbox else []),
                *(['--control-cases'] if control else [])]
            subprocess.run(command, check=True, timeout=180)
        builds = {}
        if args.compile_drivers:
            for name, extra in dict(board=(), debug=('CONFIG_BRCMDBG=y',)).items():
                identity = hashlib.sha256(json.dumps([manifest, extra, hashes], sort_keys=True).encode()).hexdigest()[:16]
                scratch = WORK / ('kernel-' + identity)
                scratch.mkdir(exist_ok=True)
                (scratch / 'extra.config').write_text(''.join(x + '\n' for x in extra))
                builds[name] = build_objects(source, scratch, lock, [BASE + 'brcmfmac.o'],
                                            extra, True, metadata, offline=True)
        if hashes != {str(p.relative_to(ROOT)): sha256(p) for p in paths}:
            raise ValueError('RX caller test inputs changed during execution')
        record = dict(schema=1, native_complete=True, arm_complete=not args.native_only,
            packet_fixes=args.packet_fixes, mailbox=args.mailbox, inputs=hashes, source=metadata,
            control_cases=control, control_fixes=args.control_fixes,
            arm_build=builds, native_sanitizers=True, dpc_complete=True,
            cases=CASES + (CONTROL_CASES if control else []), artifact_dir=str(attempt.relative_to(ROOT)),
            artifacts={p.name: sha256(p) for p in attempt.iterdir() if p.is_file()},
            limits='Actual RX functions; userspace packet allocation/list and synchronous SDIO seams. '
                   'Actual DPC/IRQ/worker bodies have a scripted readframes boundary; packet tests '
                   'exercise actual readframes/parser/recovery with synchronous SDIO and tracked '
                   'userspace packet/list seams. No complete-kernel scheduler or hardware qualification.')
        atomic_json(attempt / 'evidence.json', record)
        atomic_json(WORK / 'evidence.json', record)


if __name__ == '__main__':
    main()
