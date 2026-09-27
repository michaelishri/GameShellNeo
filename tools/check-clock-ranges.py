#!/usr/bin/env python3
"""Compare actual locked clock searches; optionally build isolated ARM objects."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

from kernel_checks import archive_for, compile_objects, run, sha256

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/build/clock-range-tests'
PREFIX = 'drivers/clk/sunxi-ng/'
PATCH = ROOT / 'kernel/patches/0007-sunxi-clock-rate-range.patch'
FILES = [PREFIX + name for name in ('ccu_common.c', 'ccu_common.h', 'ccu_nm.c',
                                    'ccu_nkm.c', 'ccu-sun8i-a33.c')]
FILES += ['drivers/clk/clk.c', 'include/linux/math.h']


def function(source, marker):
    """Extract one locked-source function with a column-zero closing brace."""
    if source.count(marker) != 1:
        raise RuntimeError('Review changed function marker: ' + marker)
    start = source.index(marker)
    end = source.index('\n}\n', start) + 3
    return source[start:end]


def unchanged_outside(old, new, marker):
    before, after = function(old, marker), function(new, marker)
    if old.replace(before, '') != new.replace(after, ''):
        raise RuntimeError('Patch changes code outside tested function: ' + marker)


def capture(command):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    print(result.stdout, end='', flush=True)
    result.check_returncode()
    return result.stdout


def prepare_header(archive, lock):
    version = lock['linux']['tag'].removeprefix('v')
    original = {}
    print('Reading clock sources from the hash-verified Linux archive...', flush=True)
    with tarfile.open(archive, mode='r|xz') as source:
        for member in source:
            name = member.name.removeprefix(f'linux-{version}/')
            if name in FILES:
                with source.extractfile(member) as stream:
                    original[name] = stream.read().decode()
            if len(original) == len(FILES):
                break
    if set(original) != set(FILES):
        raise RuntimeError('Locked clock inputs missing from archive')
    for name, content in original.items():
        target = WORK / 'patched' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCH)], cwd=WORK / 'patched')
    candidate = {name: (WORK / 'patched' / name).read_text() for name in FILES}
    markers = {
        'ccu_common.c': 'bool ccu_is_better_rate(struct ccu_common *common,',
        'ccu_nm.c': 'static unsigned long ccu_nm_find_best(struct ccu_common *common,',
        'ccu_nkm.c': 'static unsigned long ccu_nkm_find_best(unsigned long parent,',
    }
    for name, marker in markers.items():
        unchanged_outside(original[PREFIX + name], candidate[PREFIX + name], marker)
    header_name = PREFIX + 'ccu_common.h'
    inline = function(candidate[header_name], 'static inline bool ccu_is_better_rate_with_range(')
    added = '/* The caller owns the rate-range snapshot for this comparison. */\n' + inline + '\n'
    if candidate[header_name].replace(added, '').replace('#include <linux/math.h>\n', '') != original[header_name]:
        raise RuntimeError('Unexpected changes outside the extracted header helper')
    for name in (PREFIX + 'ccu-sun8i-a33.c', 'drivers/clk/clk.c', 'include/linux/math.h'):
        if original[name] != candidate[name]:
            raise RuntimeError('Unexpected changes to locked reference: ' + name)

    # Check the A33 factor widths used by the test before calling them board cases.
    a33 = re.sub(r'/\*.*?\*/', '', original[PREFIX + 'ccu-sun8i-a33.c'], flags=re.S)
    a33 = re.sub(r'\s+', '', a33)
    expected = [
        'SUNXI_CCU_NM_WITH_FRAC_GATE_LOCK(pll_video_clk,"pll-video","osc24M",0x010,8,7,0,4,',
        'SUNXI_CCU_NM_WITH_SDM_GATE_LOCK(pll_audio_base_clk,"pll-audio-base","osc24M",0x008,8,7,0,5,',
        'SUNXI_CCU_NKM_WITH_GATE_LOCK(pll_ddr0_clk,"pll-ddr0","osc24M",0x020,8,5,4,2,0,2,',
        'SUNXI_CCU_NKM_WITH_GATE_LOCK(pll_mipi_clk,"pll-mipi","pll-video",0x040,8,4,4,2,0,4,',
    ]
    if any(item not in a33 for item in expected):
        raise RuntimeError('Review changed A33 factor definitions')

    math = original['include/linux/math.h']
    abs_macros = math[math.index('#define abs(x)'):math.index('/**\n * abs_diff')]
    core = original['drivers/clk/clk.c']
    boundary = function(core, 'static void clk_core_get_boundaries(')
    getter = function(core, 'void clk_hw_get_rate_range(').replace('\n{\n', '\n{\n\trange_queries++;\n', 1)
    feature = re.search(r'^#define CCU_FEATURE_CLOSEST_RATE.*$', original[header_name], re.M).group()
    pieces = ['/* Generated from locked GPL kernel source; do not edit. */\n',
              abs_macros, feature + '\n', boundary, getter, inline]
    for kind in ('nm', 'nkm'):
        source = original[PREFIX + f'ccu_{kind}.c']
        start = source.index(f'struct _ccu_{kind} {{')
        pieces.append(source[start:source.index('\n};', start) + 4] + '\n')
    pieces.append(function(original[PREFIX + 'ccu_nkm.c'], 'static bool ccu_nkm_is_valid_rate('))
    for label, sources in (('reference', original), ('candidate', candidate)):
        comparator = function(sources[PREFIX + 'ccu_common.c'], markers['ccu_common.c'])
        pieces.append(comparator.replace('ccu_is_better_rate(', f'{label}_compare('))
        nm = sources[PREFIX + 'ccu_nm.c']
        calc = function(nm, 'static unsigned long ccu_nm_calc_rate(')
        search = function(nm, markers['ccu_nm.c'])
        for text in (calc, search):
            pieces.append(text.replace('ccu_nm_calc_rate', f'{label}_nm_calc_rate')
                          .replace('ccu_nm_find_best', f'{label}_nm_find_best')
                          .replace('ccu_is_better_rate(', f'{label}_compare('))
        nkm = function(sources[PREFIX + 'ccu_nkm.c'], markers['ccu_nkm.c'])
        pieces.append(nkm.replace('ccu_nkm_find_best', f'{label}_nkm_find_best')
                      .replace('ccu_is_better_rate(', f'{label}_compare('))
    header = WORK / 'clock_range_functions.h'
    header.write_text('\n'.join(pieces))
    return header


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-driver', action='store_true')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / '.lock').open('a') as lockfile:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        evidence_path = WORK / ('compile-evidence.json' if args.compile_driver else 'evidence.json')
        evidence_path.unlink(missing_ok=True)
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        archive = archive_for(lock)
        header = prepare_header(archive, lock)
        harness = ROOT / 'kernel/tests/clock_range_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-fno-strict-overflow']
        native_compiler = capture(['cc', '--version'])
        run(['cc', *flags, '-I', str(WORK), str(harness), '-o', str(WORK / 'native')])
        native = capture([str(WORK / 'native')])
        builder = lock['builder']
        arm = capture([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project',
            '-e', f'NEO_CLOCK_CROSS={builder["cross_compile"]}', builder['image'], '-c',
            'set -euo pipefail\n'
            '"${NEO_CLOCK_CROSS}gcc" --version\n'
            '"${NEO_CLOCK_CROSS}gcc" -std=gnu11 -O2 -Wall -Wextra -Werror -fno-strict-overflow '
            '-I.local/build/clock-range-tests kernel/tests/clock_range_test.c '
            '-o .local/build/clock-range-tests/arm32\n'
            'qemu-arm -L /usr/arm-linux-gnueabihf .local/build/clock-range-tests/arm32\n'
        ])
        (WORK / 'native.txt').write_text(native_compiler + native)
        (WORK / 'arm32.txt').write_text(arm)
        evidence = dict(
            linux=lock['linux']['tag'], archive_sha256=sha256(archive), builder=builder,
            sha256={str(path.relative_to(ROOT)): sha256(path) for path in (
                PATCH, harness, header, Path(__file__).resolve(), ROOT / 'tools/kernel_checks.py')},
            native=native.strip(), arm32=arm.strip(),
            limits='Actual search, comparator, abs and boundary code with modeled clock objects '
                   'and do_div quotient; not running-kernel locking, hardware or timing tests.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [
                PREFIX + name + '.o' for name in ('ccu_common', 'ccu_nm', 'ccu_nkm', 'ccu_mux')])
        evidence_path.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', evidence_path.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
