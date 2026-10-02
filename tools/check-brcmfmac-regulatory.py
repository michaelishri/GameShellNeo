#!/usr/bin/env python3
"""Test actual country/PM callbacks from the locked archive; no device access."""
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
WORK = ROOT / '.local/build/brcmfmac-regulatory-tests'
BASE = 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/'
FILES = (BASE + 'cfg80211.c', BASE + 'cfg80211.h',
         'net/wireless/sysfs.c', 'net/wireless/reg.c')
PATCH = ROOT / 'kernel/patches/0020-brcmfmac-regulatory-suspend.patch'


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
        output = WORK / ('compile-evidence.json' if args.compile_driver else 'evidence.json')
        output.unlink(missing_ok=True)
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
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCH)], cwd=directory)
        source = (directory / FILES[0]).read_text()
        header = (directory / FILES[1]).read_text()
        declarations = ('static bool brmcf_use_iso3166_ccode_fallback(',
                        'static s32 brcmf_translate_country_code(',
                        'static int brcmf_cfg80211_apply_country(struct wiphy *wiphy, char alpha2[2])\n',
                        'static s32 brcmf_cfg80211_resume(',
                        'static s32 brcmf_cfg80211_suspend(',
                        'static void brcmf_cfg80211_reg_notifier(')
        good = '\n'.join(function(source, name) for name in declarations)
        fields = re.search(r'\tbool regulatory_suspended;\n\tbool regulatory_pending;\n\tchar regulatory_alpha2\[2\];', header)
        if not fields:
            raise ValueError('Missing driver regulatory state declarations')
        (WORK / 'brcmfmac_regulatory_fields.h').write_text(fields[0] + '\n')
        mutations = {
            'lost_suspend_gate': ('cfg->regulatory_suspended = true;', ''),
            'lost_deferral': ('if (cfg->regulatory_suspended) {', 'if (false) {'),
            'lost_latest_request': ('memcpy(cfg->regulatory_alpha2, req->alpha2,', 'if (!cfg->regulatory_pending) memcpy(cfg->regulatory_alpha2, req->alpha2,'),
            'lost_pending': ('cfg->regulatory_pending = true;', ''),
            'lost_resume_open': ('cfg->regulatory_suspended = false;', ''),
            'lost_consumption': ('cfg->regulatory_pending = false;', ''),
            'lost_replay_error': ('return brcmf_cfg80211_apply_country(wiphy, cfg->regulatory_alpha2);', 'brcmf_cfg80211_apply_country(wiphy, cfg->regulatory_alpha2); return 0;'),
            'unchanged_is_error': ('return err == -EAGAIN ? 0 : err;', 'return err;'),
            'lost_band_error': ('return brcmf_setup_wiphybands(cfg);', 'brcmf_setup_wiphybands(cfg); return 0;'),
        }
        cases = {'candidate': good}
        for name, (before, after) in mutations.items():
            cases[name] = replace_once(good, before, after)
        generated = WORK / 'brcmfmac_regulatory_functions.h'
        harness = ROOT / 'kernel/tests/brcmfmac_regulatory_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                 '-Wno-unused-variable', '-I', str(WORK), str(harness)]
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
        builder = lock['builder']
        relative = WORK.relative_to(ROOT).as_posix()
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n'
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -Wno-unused-variable -static '
            f'-I{relative} kernel/tests/brcmfmac_regulatory_test.c -o {relative}/arm\n'
            f'qemu-arm {relative}/arm'], text=True, timeout=120).strip()
        if arm != results['candidate']['output']:
            raise ValueError('Native/ARM32 results differ')
        print('ARM32: ' + arm, flush=True)
        evidence = dict(original=original, patch_sha256=sha256(PATCH),
                        harness_sha256=sha256(harness), results=results, arm=arm,
                        limits='Actual callback source with modeled RTNL/firmware/PM ordering; no kernel scheduling or hardware proof.')
        if args.compile_driver:
            evidence['compile'] = compile_objects(archive, lock, WORK, (BASE + 'cfg80211.o',))
        output.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    main()
