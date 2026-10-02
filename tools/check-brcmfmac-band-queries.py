#!/usr/bin/env python3
"""Check actual band-query functions with transport and firmware rejections."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import resource
import subprocess
import tarfile

from kernel_checks import archive_for, compile_objects, run, sha256

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/build/brcmfmac-band-query-tests'
SOURCE = 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/cfg80211.c'
PATCH = ROOT / 'kernel/patches/0022-brcmfmac-band-query-errors.patch'


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
        path = directory / SOURCE
        path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, mode='r|xz') as source:
            wanted = 'linux-' + lock['linux']['tag'][1:] + '/' + SOURCE
            for member in source:
                if member.name == wanted:
                    path.write_bytes(source.extractfile(member).read())
                    break
            else:
                raise ValueError('Missing locked cfg80211 source')
        original = sha256(path)
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCH)], cwd=directory)
        source = path.read_text()
        good = function(source, 'static int brcmf_get_bwcap(') + function(source, 'static int brcmf_setup_wiphybands(')
        mutations = {
            'lost_nmode_error': ('bphy_err(drvr, "nmode error (%d)\\n", err);\n\t\treturn err;',
                                'nmode = 0;'),
            'lost_vht_transport_error': ('err = brcmf_fil_iovar_int_get(ifp, "vhtmode", &vhtmode);\n\tif (err && err != -EBADE)\n\t\treturn err;',
                                        'err = brcmf_fil_iovar_int_get(ifp, "vhtmode", &vhtmode);'),
            'lost_rxchain_transport_error': ('bphy_err(drvr, "rxchain error (%d)\\n", err);\n\t\t\treturn err;', ''),
            'lost_bw_transport_error': ('\tif (err != -EBADE)\n\t\treturn err;\n\tbrcmf_dbg', '\tbrcmf_dbg'),
            'lost_second_band_error': ('return err == -EBADE ? 0 : err;', 'return 0;'),
            'lost_legacy_transport_error': ('\t\tif (err != -EBADE)\n\t\t\treturn err;\n\t\t/* Preserve', '\t\t/* Preserve'),
            'lost_legacy_validation': ('\t\treturn -EINVAL;\n\t}\n\treturn 0;', '\t\treturn 0;\n\t}\n\treturn 0;'),
            'lost_bw_propagation': ('err = brcmf_get_bwcap(ifp, bw_cap);\n\tif (err)\n\t\treturn err;',
                                    'err = brcmf_get_bwcap(ifp, bw_cap);'),
            'lost_chain_bound': ('\tif (nchain > 8)\n\t\treturn -EINVAL;', ''),
        }
        cases = {'candidate': good}
        for name, (before, after) in mutations.items():
            cases[name] = replace_once(good, before, after)
        block = ('\terr = brcmf_construct_chaninfo(cfg, bw_cap);\n\tif (err) {\n'
                 '\t\tbphy_err(drvr, "brcmf_construct_chaninfo failed (%d)\\n", err);\n'
                 '\t\treturn err;\n\t}\n\n')
        early = replace_once(good, block, '')
        cases['early_channel_mutation'] = replace_once(early, '\tif (vhtmode) {', block + '\tif (vhtmode) {')
        harness = ROOT / 'kernel/tests/brcmfmac_band_query_test.c'
        generated = WORK / 'brcmfmac_band_functions.h'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-variable',
                 '-Wno-sign-compare', '-I', str(WORK), str(harness)]
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
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
            '-Wno-unused-variable -Wno-sign-compare '
            f'-I{relative} kernel/tests/brcmfmac_band_query_test.c -o {relative}/arm\n'
            f'qemu-arm {relative}/arm'], text=True, timeout=120).strip()
        if arm != results['candidate']['output']:
            raise ValueError('Native/ARM32 results differ')
        print('ARM32: ' + arm, flush=True)
        evidence = dict(original_sha256=original, patch_sha256=sha256(PATCH),
                        harness_sha256=sha256(harness), results=results, arm=arm,
                        limits='Actual bandwidth/setup functions; modeled firmware and channel/capability consumers. Not firmware support, full channel transaction or hardware proof.')
        if args.compile_driver:
            evidence['compile'] = compile_objects(archive, lock, WORK, (SOURCE.removesuffix('.c') + '.o',))
        evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    main()
