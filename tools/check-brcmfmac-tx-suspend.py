#!/usr/bin/env python3
"""Exercise actual transmit admission/PM functions; no device access."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tarfile

from kernel_checks import archive_for, compile_objects, run, sha256

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/build/brcmfmac-tx-suspend-tests'
BASE = 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/'
FILES = tuple(BASE + name for name in ('core.c', 'core.h', 'cfg80211.c', 'cfg80211.h'))
PATCHES = tuple(ROOT / 'kernel/patches' / name for name in (
    '0020-brcmfmac-regulatory-suspend.patch', '0021-brcmfmac-tx-suspend.patch'))


def function(source, declaration):
    start = source.index(declaration)
    return source[start:source.index('\n}', start) + 2] + '\n'


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise ValueError('Missing/ambiguous negative control: ' + before)
    return source.replace(before, after, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-driver', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        evidence_path = WORK / ('compile-evidence.json' if args.compile_driver else 'evidence.json')
        evidence_path.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        directory = WORK / 'patched'
        with tarfile.open(archive, mode='r|xz') as source:
            prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
            remaining = set(FILES)
            for member in source:
                name = member.name.removeprefix(prefix)
                if name not in remaining:
                    continue
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(source.extractfile(member).read())
                remaining.remove(name)
                if not remaining:
                    break
            if remaining:
                raise ValueError('Missing locked sources: ' + repr(remaining))
        original = {name: sha256(directory / name) for name in FILES}
        for patch in PATCHES:
            run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=directory)
        core = (directory / FILES[0]).read_text()
        cfg = (directory / FILES[2]).read_text()
        header = (directory / FILES[1]).read_text()
        reasons = re.search(r'enum brcmf_netif_stop_reason \{.*?\n};', header, re.S)
        if not reasons:
            raise ValueError('Missing queue stop reasons')
        (WORK / 'brcmfmac_tx_reasons.h').write_text(reasons[0] + '\n')
        good = '\n'.join(function(core, declaration) for declaration in (
            'void brcmf_txflowblock_if(', 'void brcmf_net_setcarrier(', 'void brcmf_bus_change_state('))
        good += '\n'.join(function(cfg, declaration) for declaration in (
            'static void brcmf_cfg80211_suspend_tx(', 'static void brcmf_cfg80211_resume_tx(',
            'static s32 brcmf_cfg80211_resume(', 'static s32 brcmf_cfg80211_suspend('))
        mutations = {
            'lost_bus_release': ('BRCMF_NETIF_STOP_REASON_NONE, false);', 'BRCMF_NETIF_STOP_REASON_SUSPEND, true);'),
            'late_up_publication': ('\tbus->state = state;', ''),
            'lost_suspend_reason': ('BRCMF_NETIF_STOP_REASON_SUSPEND,\n\t\t\t\t     true);',
                                    'BRCMF_NETIF_STOP_REASON_FLOW,\n\t\t\t\t     true);'),
            'lost_transmit_drain': ('\t\tnetif_tx_disable(vif->ifp->ndev);', ''),
            'late_suspend_block': ('\tbrcmf_cfg80211_suspend_tx(cfg);', ''),
            'lost_resume_release': ('\tbrcmf_cfg80211_resume_tx(cfg, err);', ''),
            'early_resume_release': ('\tif (cfg->regulatory_pending) {',
                                     '\tbrcmf_cfg80211_resume_tx(cfg, 0);\n\tif (cfg->regulatory_pending) {'),
            'lost_replay_error': ('\t\terr = brcmf_cfg80211_apply_country(wiphy, cfg->regulatory_alpha2);',
                                  '\t\tbrcmf_cfg80211_apply_country(wiphy, cfg->regulatory_alpha2);'),
            'lost_failure_carrier': ('\t\tif (err || cfg->pub->bus_if->state != BRCMF_BUS_UP)\n\t\t\tbrcmf_net_setcarrier(vif->ifp, false);', ''),
            'lost_failed_transport_gate': ('err || cfg->pub->bus_if->state != BRCMF_BUS_UP', 'err'),
            'lost_other_stop_owners': ('ifp->netif_stop &= ~reason;', 'ifp->netif_stop = 0;'),
            'bypass_stop_owners': ('if (!ifp->netif_stop)\n\t\t\tnetif_wake_queue',
                                   'if (true)\n\t\t\tnetif_wake_queue'),
        }
        cases = {'candidate': good}
        for name, (before, after) in mutations.items():
            cases[name] = replace_once(good, before, after)
        harness = ROOT / 'kernel/tests/brcmfmac_tx_suspend_test.c'
        generated = WORK / 'brcmfmac_tx_functions.h'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread',
                 '-Wno-unused-variable', '-Wno-unused-function', '-Wno-unused-parameter',
                 '-I', str(WORK), str(harness)]
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, code in cases.items():
                generated.write_text(code)
                binary = WORK / name
                run(['cc', *flags, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise ValueError('Broken variant did not fail by assertion: ' + name)
                results[name] = dict(returncode=result.returncode, output=result.stdout.strip(), error=result.stderr.strip())
                print(name + ': ' + (result.stdout.strip() or 'expected assertion failure'), flush=True)
        finally:
            generated.write_text(good)
        relative = WORK.relative_to(ROOT).as_posix()
        builder = lock['builder']
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n'
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -pthread -static '
            '-Wno-unused-variable -Wno-unused-function -Wno-unused-parameter '
            f'-I{relative} kernel/tests/brcmfmac_tx_suspend_test.c -o {relative}/arm\n'
            f'qemu-arm {relative}/arm'], text=True, timeout=120).strip()
        if arm != results['candidate']['output']:
            raise ValueError('Native/ARM32 results differ')
        print('ARM32: ' + arm, flush=True)
        evidence = dict(original=original, patches={p.name: sha256(p) for p in PATCHES},
                        harness_sha256=sha256(harness), results=results, arm=arm,
                        limits='Actual queue/PM functions; pthread-modeled single-queue/flow locks and firmware outcomes. Not kernel lockdep, transport teardown or hardware qualification.')
        if args.compile_driver:
            evidence['compile'] = compile_objects(archive, lock, WORK,
                                                   (BASE + 'core.o', BASE + 'cfg80211.o'))
        evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    main()
