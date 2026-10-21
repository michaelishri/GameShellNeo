#!/usr/bin/env python3
"""Fault-test actual RX abort/flush helpers; caller/packet qualification is separate."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shlex
import subprocess
import uuid

import brcmfmac_irq_checks as irq
from kernel_checks import ROOT, archive_for, build_objects, run, sha256
from kernel_sources import atomic_json, ensure_source, locked

BASE = 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/'
WORK = ROOT / '.local/build/brcmfmac-rx-recovery'
PATCH = ROOT / 'kernel/candidates/0046-brcmfmac-rx-recovery.patch'
HARNESS = ROOT / 'kernel/tests/brcmfmac_rx_recovery_test.c'


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


extract = module('rx_pm_extract', 'check-brcmfmac-pm.py')


def functions(sdio, bcmsdh):
    return (extract.function(bcmsdh, 'int brcmf_sdiod_abort(') +
            extract.function(sdio, 'static void brcmf_sdio_rxfail('))


def variants(good):
    cases = {'candidate': good}
    abort = extract.function(good, 'int brcmf_sdiod_abort(')
    fail = extract.function(good, 'static void brcmf_sdio_rxfail(')
    for name, body, before, after in (
        ('lost_abort_errno', abort, 'return err;', 'return 0;'),
        ('lost_previous_error', fail, 'if (READ_ONCE(sdiod->io_error))', 'if (false)'),
        ('lost_failure_latch', fail, 'WRITE_ONCE(sdiod->io_error, err);', ''),
        ('lost_exhaustion', fail, 'if (!retries) {', 'if (false) {'),
        ('lost_partial_clear', fail, 'bus->cur_read.len = 0;', ''),
        ('lost_retransmission', fail, 'if (rtx) {', 'if (false && rtx) {'),
        ('lost_rxskip', fail, 'bus->rxskip = true;', ''),
        ('shortened_successful_budget', fail, 'lastrbc = retries = 0xffff',
         'lastrbc = retries = 0xfffe'),
    ):
        cases[name] = extract.mutate_once(good, body, extract.mutate_once(body, before, after))
    # Abort, terminate, high read, low read and NAK each have a distinct gate.
    gates = list(re.finditer(r'if \(err\)\n\s*goto failed;', fail))
    if len(gates) != 5:
        raise ValueError('Unexpected RX error gate inventory')
    for index, gate in enumerate(gates):
        broken = fail[:gate.start()] + gate[0].replace('if (err)', 'if (false && err)') + fail[gate.end():]
        cases[f'lost_error_gate_{index}'] = extract.mutate_once(good, fail, broken)
    return cases


def constants(sdio, header, mmc):
    result = irq.definitions(sdio, header)
    for name, source in (('SFC_RF_TERM', sdio), ('SMB_NAK', sdio), ('SDIO_CCCR_ABORT', mmc)):
        lines = re.findall(r'^#define\s+' + name + r'\s+[^\n]+$', source, re.M)
        if len(lines) != 1:
            raise ValueError('Missing or duplicate definition: ' + name)
        result += lines[0] + '\n'
    return result


def checked_output(output):
    if output.strip() != '44 RX recovery helper scenarios passed':
        raise ValueError('Unexpected helper coverage: ' + output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    WORK.mkdir(parents=True, exist_ok=True)
    with locked(WORK / '.lock'):
        attempt = WORK / 'attempts' / uuid.uuid4().hex
        attempt.mkdir(parents=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        queue = list(module('rx_kernel_inputs', 'kernel-inputs.py').patches())
        if PATCH.name in {name for name, _ in queue}:
            raise ValueError('RX candidate unexpectedly entered the image queue')
        queue.append((PATCH.name, PATCH.read_bytes()))
        manifest = [dict(name=n, sha256=hashlib.sha256(b).hexdigest()) for n, b in queue]
        paths = [PATCH, HARNESS, Path(__file__), ROOT / 'build/sources.lock.json',
                 ROOT / 'tools/brcmfmac_irq_checks.py', ROOT / 'tools/check-brcmfmac-pm.py',
                 ROOT / 'tools/kernel-inputs.py', ROOT / 'tools/kernel_sources.py',
                 ROOT / 'tools/kernel_checks.py', ROOT / 'kernel/gameshellneo.config']
        hashes = {str(p.relative_to(ROOT)): sha256(p) for p in paths}
        atomic_json(attempt / 'inputs.json', hashes)
        with locked(WORK / '.source-lock'):
            source, _, metadata = ensure_source(ROOT, WORK, archive, lock, manifest, recorded_patches=queue)
        sdio, header, bcmsdh = ((source / BASE / n).read_text() for n in ('sdio.c', 'sdio.h', 'bcmsdh.c'))
        good = functions(sdio, bcmsdh)
        types = constants(sdio, header, (source / 'include/linux/mmc/sdio.h').read_text())
        (attempt / 'brcmfmac_rx_constants.h').write_text(types)
        generated = attempt / 'brcmfmac_rx_functions.h'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-trigraphs',
                 '-I', str(attempt), str(HARNESS)]
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, text in variants(good).items():
                generated.write_text(text)
                binary = attempt / (name + '.bin')
                run(['cc', *flags, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
                (attempt / (name + '.log')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                    checked_output(result.stdout)
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise ValueError('Negative control did not fail an assertion: ' + name)
                results[name] = dict(returncode=result.returncode, output=result.stdout.strip(),
                                     error=result.stderr.strip())
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            generated.write_text(good)
        relative = attempt.relative_to(ROOT).as_posix()
        compile_command = ['arm-linux-gnueabihf-gcc', '-std=gnu11', '-O2', '-Wall', '-Wextra',
            '-Werror', '-Wno-trigraphs', '-static', '-I' + relative,
            str(HARNESS.relative_to(ROOT)), '-o', relative + '/arm.bin']
        arm = subprocess.check_output(['docker', 'run', '--rm', '--network=none', '--pull=never',
            '--user', f'{os.getuid()}:{os.getgid()}', '--platform', lock['builder']['platform'],
            '--entrypoint=sh', '-v', f'{ROOT}:/project', '-w', '/project', lock['builder']['image'],
            '-ec', shlex.join(compile_command) + '\n' + shlex.join(['qemu-arm', relative + '/arm.bin'])],
            text=True, timeout=120)
        checked_output(arm)
        print('ARM32: ' + arm.strip(), flush=True)
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
            raise ValueError('RX recovery inputs changed during execution')
        record = dict(schema=1, helper_checks_complete=True, caller_checks_complete=False,
            inputs=hashes, source=metadata, native=results, arm32=arm.strip(), arm_build=builds,
            artifact_dir=str(attempt.relative_to(ROOT)),
            artifacts={p.name: sha256(p) for p in attempt.iterdir() if p.is_file()},
            limits='Actual abort/RX recovery helper bodies with synchronous SDIO seams. '
                   'DPC/caller/packet lifetime tests, integration and hardware qualification pending.')
        atomic_json(attempt / 'evidence.json', record)
        atomic_json(WORK / 'helper-evidence.json', record)
        print('Saved helper-only evidence:', attempt / 'evidence.json', flush=True)


if __name__ == '__main__':
    main()
