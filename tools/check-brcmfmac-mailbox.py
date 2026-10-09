#!/usr/bin/env python3
"""Test the isolated mailbox candidate against the complete locked source queue."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess

import brcmfmac_irq_checks as irq
from kernel_checks import ROOT, archive_for, build_objects, run, sha256
from kernel_sources import ensure_source, locked

WORK = ROOT / '.local/build/brcmfmac-mailbox-tests'
PATCH = ROOT / 'kernel/candidates/0039-brcmfmac-mailbox-errors.patch'
HARNESS = ROOT / 'kernel/tests/brcmfmac_irq_test.c'
BASE = 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/'


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


pm = module('mailbox_pm_extract', 'check-brcmfmac-pm.py')
function, mutate_once = pm.function, pm.mutate_once


def variants(good):
    cases = irq.variants(good, function, mutate_once, hardened=True, mailbox=True)
    mail = function(good, 'static int brcmf_sdio_hostmail(')
    dpc = function(good, 'static void brcmf_sdio_dpc(')
    read_gate = '\tbus->sdcnt.f1regdata++;\n\tif (ret)\n\t\treturn ret;'
    if mail.count(read_gate) != 2:
        raise ValueError('Expected read and ACK error gates')
    for name, index in [('lost_mailbox_read_error', 0), ('lost_mailbox_ack_error', 1)]:
        parts = mail.split(read_gate)
        replacement = '\tbus->sdcnt.f1regdata++;\n\tif (false && ret)\n\t\treturn ret;'
        text = parts[0] + (replacement if index == 0 else read_gate) + parts[1]
        text += (replacement if index == 1 else read_gate) + parts[2]
        cases[name] = mutate_once(good, mail, text)
    for name, body, before, after in (
        ('lost_mailbox_output_init', mail, '*status = 0;', ''),
        ('lost_mailbox_frame_output', mail, '*status = intstatus;', '*status = 0 * intstatus;'),
        ('lost_mailbox_dpc_exit', dpc,
         'err = brcmf_sdio_hostmail(bus, &mailbox_status);\n\t\tif (err)',
         'err = brcmf_sdio_hostmail(bus, &mailbox_status);\n\t\tif (false && err)'),
        ('lost_mailbox_dpc_status', dpc, 'intstatus |= mailbox_status;',
         'intstatus |= 0 * mailbox_status;'),
        ('lost_valid_firmware_halt', mail, 'if (hmb_data & HMB_DATA_FWHALT)',
         'if (false && (hmb_data & HMB_DATA_FWHALT))'),
        ('lost_nak_clear', mail, 'bus->rxskip = false;', ''),
        ('lost_flow_state', mail, 'bus->flowcontrol = fcbits;', ''),
        ('lost_mailbox_read_count', mail, read_gate + '\n\n\tbrcmf_sdiod_writel(',
         '\tif (ret)\n\t\treturn ret;\n\n\tbrcmf_sdiod_writel('),
    ):
        cases[name] = mutate_once(good, body, mutate_once(body, before, after))
    # Decode first but still return the exact ACK error: error-return assertions
    # alone are insufficient; the side-effect and publication checks must fail.
    start = mail.index('\tbrcmf_sdiod_writel(')
    end = mail.index('\n\n\t/* dongle indicates', start)
    ack = mail[start:end]
    reordered = mutate_once(mail, ack + '\n\n', '')
    reordered = mutate_once(reordered, '\treturn 0;', ack + '\n\treturn 0;')
    cases['decodes_before_ack'] = mutate_once(good, mail, reordered)
    cases['loses_mailbox_errno'] = mutate_once(good, mail, mail.replace('return ret;', 'return -EIO;'))
    return cases


def check_output(output, debug=False):
    count = 133 if debug else 131
    expected = f'{count} IRQ service scenarios passed (0 characterize existing error limitations)'
    if output.strip() != expected:
        raise ValueError('Unexpected scenario output: ' + output)


def compile_drivers(source, lock, manifest, metadata):
    result = {}
    for name, extra in dict(board=(), debug=('CONFIG_BRCMDBG=y',)).items():
        identity = hashlib.sha256(json.dumps([manifest, extra, lock,
            sha256(ROOT / 'kernel/gameshellneo.config')], sort_keys=True).encode()).hexdigest()[:16]
        scratch = WORK / ('kernel-' + identity)
        scratch.mkdir(exist_ok=True)
        (scratch / 'extra.config').write_text(''.join(x + '\n' for x in extra))
        result[name] = build_objects(source, scratch, lock, [BASE + 'brcmfmac.o'],
                                    extra, True, metadata)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-drivers', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = WORK / ('compile-evidence.json' if args.compile_drivers else 'evidence.json')
        output.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        queue = list(module('mailbox_kernel_inputs', 'kernel-inputs.py').patches())
        if PATCH.name in {name for name, _ in queue}:
            raise ValueError('Candidate unexpectedly entered active image queue')
        queue.append((PATCH.name, PATCH.read_bytes()))
        manifest = [dict(name=n, sha256=hashlib.sha256(b).hexdigest()) for n, b in queue]
        with locked(WORK / '.source-lock'):
            source, _, metadata = ensure_source(ROOT, WORK, archive, lock, manifest, recorded_patches=queue)
            sdio, header, bcmsdh = ((source / BASE / n).read_text() for n in ('sdio.c', 'sdio.h', 'bcmsdh.c'))
            good = irq.extracted(sdio, header, function, bcmsdh, hardened=True, mailbox=True)
            (WORK / 'brcmfmac_irq_types.h').write_text(irq.definitions(sdio, header))
            extracted = WORK / 'brcmfmac_freezer_functions.h'
            flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-trigraphs',
                     '-pthread', '-DNEO_WORKER_ERRORS', '-DNEO_MAILBOX_ERRORS',
                     '-I', str(WORK), str(HARNESS)]
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            results = {}
            try:
                cases = variants(good)
                cases['candidate_debug'] = good
                for name, text in cases.items():
                    if name not in {'candidate', 'candidate_debug'} and text == good:
                        raise ValueError('Ineffective negative control: ' + name)
                    extracted.write_text(text)
                    binary = WORK / (name + '.bin')
                    run(['cc', *flags, *(['-DDEBUG'] if name == 'candidate_debug' else []),
                         '-o', str(binary)])
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                    (WORK / (name + '.log')).write_text(result.stdout + result.stderr)
                    if name in {'candidate', 'candidate_debug'}:
                        result.check_returncode()
                        check_output(result.stdout, name == 'candidate_debug')
                    elif result.returncode == 0 or 'Assertion' not in result.stderr:
                        raise ValueError('Negative control did not fail an assertion: ' + name)
                    results[name] = dict(returncode=result.returncode, output=result.stdout.strip(),
                                         error=result.stderr.strip())
                    print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
            finally:
                extracted.write_text(good)
            arm = {}
            builder = lock['builder']
            relative = WORK.relative_to(ROOT).as_posix()
            for debug in (False, True):
                value = subprocess.check_output(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
                    '--platform', builder['platform'], '--entrypoint', 'bash', '-v', f'{ROOT}:/project',
                    '-w', '/project', builder['image'], '-c',
                    'set -euo pipefail\narm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror '
                    '-Wno-trigraphs -pthread -static -DNEO_WORKER_ERRORS -DNEO_MAILBOX_ERRORS '
                    + ('-DDEBUG ' if debug else '') + f'-I{relative} kernel/tests/brcmfmac_irq_test.c '
                    f'-o {relative}/arm{"-debug" if debug else ""}.bin\n'
                    f'qemu-arm {relative}/arm{"-debug" if debug else ""}.bin'], text=True, timeout=120)
                check_output(value, debug)
                arm['debug' if debug else 'normal'] = value.strip()
                print('ARM32: ' + value.strip(), flush=True)
            inputs = [PATCH, HARNESS, Path(__file__), ROOT / 'tools/brcmfmac_irq_checks.py',
                      ROOT / 'tools/check-brcmfmac-pm.py', ROOT / 'tools/kernel_checks.py',
                      ROOT / 'tools/kernel_sources.py', ROOT / 'tools/kernel-inputs.py',
                      ROOT / 'tools/check-kernel-config.py', ROOT / 'kernel/gameshellneo.config',
                      ROOT / 'build/sources.lock.json']
            evidence = dict(archive_sha256=sha256(archive), patches=manifest, shared_source=metadata,
                inputs={str(p.relative_to(ROOT)): sha256(p) for p in inputs},
                driver_sources={n: sha256(source / BASE / n) for n in ('sdio.c', 'sdio.h', 'bcmsdh.c')},
                generated_sha256=sha256(extracted), types_sha256=sha256(WORK / 'brcmfmac_irq_types.h'),
                native=results, arm32=arm, builder=builder,
                limits='Actual mailbox/ISR/status/DPC/worker/IRQ-quiesce bodies with scripted SDIO, '
                       'packet, firmware-crash, console-read and workqueue boundaries. No hardware, '
                       'RF, automatic recovery, performance or power qualification. Candidate outside image queue.')
            if args.compile_drivers:
                evidence['arm_build'] = compile_drivers(source, lock, manifest, metadata)
            output.write_text(json.dumps(evidence, indent=2) + '\n')
            print('Saved', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
