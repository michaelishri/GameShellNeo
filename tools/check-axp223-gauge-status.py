#!/usr/bin/env python3
"""Check actual AXP223/regmap cache paths; optionally compile the complete ARM MFD."""
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
WORK = ROOT / '.local/build/axp223-gauge-status-tests'
MFD = 'drivers/mfd/axp20x.c'
HEADER = 'include/linux/mfd/axp20x.h'
CORE = 'drivers/base/regmap/regmap.c'
CACHE = 'drivers/base/regmap/regcache.c'


def function(source, name):
    # The audited functions have no braces in strings/comments. Fail closed on
    # missing/ambiguous definitions, and extract their complete original bodies.
    matches = list(re.finditer(r'^.*\b' + re.escape(name) + r'\([^;]*?\)\n\{', source, re.M))
    if len(matches) != 1:
        raise ValueError('Expected one function definition: ' + name)
    start = matches[0].start()
    index = source.index('{', matches[0].start())
    depth = 1
    end = index + 1
    while depth:
        if source[end] == '{':
            depth += 1
        elif source[end] == '}':
            depth -= 1
        end += 1
    return source[start:end] + '\n'


def declaration(source, name):
    matches = re.findall(r'^static const struct [^\n]+\b' + re.escape(name) +
                         r'(?:\[\])? = \{.*?^\};', source, re.M | re.S)
    if len(matches) != 1:
        raise ValueError('Expected one declaration: ' + name)
    return matches[0] + '\n'


def harness_source(mfd, sources):
    # Copy the complete actual range/config declarations, callbacks and three
    # variant-selection cases. Only bus/cache storage and framework types are
    # modeled by the C harness; the read/cache decision functions are real.
    names = ('axp22x_writeable_ranges', 'axp22x_volatile_ranges',
             'axp22x_writeable_table', 'axp22x_volatile_table')
    text = ''.join(declaration(mfd, name) for name in names)
    if 'static bool axp223_volatile_reg(' in mfd:
        text += function(mfd, 'axp223_volatile_reg')
    text += declaration(mfd, 'axp22x_regmap_config')
    if 'static const struct regmap_config axp223_regmap_config' in mfd:
        text += declaration(mfd, 'axp223_regmap_config')
    body = 'static const struct regmap_config *select_config(int variant)\n{\n'
    body += 'struct axp20x_dev state = {0}, *axp20x = &state;\nswitch (variant) {\n'
    for name in ('AXP221_ID', 'AXP223_ID', 'AXP809_ID'):
        cases = re.findall(r'\tcase ' + name + r':\n.*?\t\tbreak;', mfd, re.S)
        if len(cases) != 1:
            raise ValueError('Expected one variant case: ' + name)
        body += cases[0] + '\n'
    text += body + '}\nreturn axp20x->regmap_cfg;\n}\n'
    for name in ('regmap_reg_in_ranges', 'regmap_check_range_table', 'regmap_volatile'):
        text += function(sources[CORE], name)
    for name in ('regcache_read', 'regcache_write'):
        text += function(sources[CACHE], name)
    text += function(sources[CORE], '_regmap_read')
    return text


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
        paths = (MFD, HEADER, CORE, CACHE)
        sources = {}
        with tarfile.open(archive, mode='r|xz') as tar:
            prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
            for member in tar:
                name = member.name.removeprefix(prefix)
                if name in paths:
                    sources[name] = tar.extractfile(member).read().decode()
                    target = WORK / 'patched' / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(sources[name])
                    if len(sources) == len(paths):
                        break
        if set(sources) != set(paths):
            raise RuntimeError('Incomplete locked source extraction')
        patch = ROOT / 'kernel/patches/0035-axp223-gauge-status-volatile.patch'
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
        candidate = (WORK / 'patched' / MFD).read_text()
        # Only AXP223's selection is allowed to change; all other variant cases
        # and write/range declarations remain byte-identical to locked Linux.
        old_match = function(sources[MFD], 'axp20x_match_device')
        new_match = function(candidate, 'axp20x_match_device')
        if new_match.replace('&axp223_regmap_config;', '&axp22x_regmap_config;') != old_match:
            raise RuntimeError('Unexpected variant selection change')
        for name in ('axp22x_writeable_ranges', 'axp22x_volatile_ranges',
                     'axp22x_writeable_table', 'axp22x_volatile_table', 'axp22x_regmap_config'):
            if declaration(sources[MFD], name) != declaration(candidate, name):
                raise RuntimeError('Changed shared configuration: ' + name)
        # These numeric macros are copied from the locked hardware header.
        macros = []
        continuation = False
        for line in sources[HEADER].splitlines(True):
            take = continuation or line.startswith('#define AXP')
            if take:
                macros.append(line)
            continuation = take and line.rstrip().endswith('\\')
        (WORK / 'axp_registers.h').write_text(''.join(macros))
        header = WORK / 'axp_status_functions.h'
        harness = ROOT / 'kernel/tests/axp223_gauge_status_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                 '-Wno-unused-parameter', '-Wno-sign-compare', '-I', str(WORK), str(harness)]
        cases = {
            'candidate': candidate,
            'original_cached_status': sources[MFD],
            'wrong_status_address': candidate.replace('reg == AXP20X_CC_CTRL', 'reg == 0xb7'),
            'lost_legacy_volatile': candidate.replace('regmap_reg_in_ranges(reg, axp22x_volatile_ranges,\n'
                '\t\t\t\t    ARRAY_SIZE(axp22x_volatile_ranges))', 'false'),
            'wrong_variant_routing': candidate.replace('&axp223_regmap_config;', '&axp22x_regmap_config;'),
            'changed_max_register': candidate.replace(declaration(candidate, 'axp223_regmap_config'),
                declaration(candidate, 'axp223_regmap_config').replace('AXP22X_BATLOW_THRES1', '0xe7')),
            'changed_write_access': candidate.replace(declaration(candidate, 'axp223_regmap_config'),
                declaration(candidate, 'axp223_regmap_config').replace('&axp22x_writeable_table', 'NULL')),
        }
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        good = harness_source(candidate, sources)
        try:
            for name, source in cases.items():
                content = harness_source(source, sources)
                if name != 'candidate' and content == good:
                    raise RuntimeError('Negative control did not change compiled source: ' + name)
                header.write_text(content)
                binary = WORK / name
                # The wrong-routing mutation leaves a deliberately unused config.
                run(['cc', *flags, '-Wno-unused-const-variable', '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Expected assertion failure: ' + name)
                results[name] = dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
                print(name + ': ' + ('passed' if name == 'candidate' else 'expected assertion failure'), flush=True)
        finally:
            header.write_text(good)
        builder = lock['builder']
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n'
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror '
            '-Wno-unused-parameter -Wno-sign-compare -static '
            '-I.local/build/axp223-gauge-status-tests kernel/tests/axp223_gauge_status_test.c '
            '-o .local/build/axp223-gauge-status-tests/arm\n'
            'qemu-arm .local/build/axp223-gauge-status-tests/arm'], text=True)
        print(arm, end='', flush=True)
        inputs = (patch, harness, Path(__file__), ROOT / 'tools/kernel_checks.py',
                  ROOT / 'tools/kernel_sources.py', ROOT / 'tools/kernel-inputs.py',
                  ROOT / 'build/sources.lock.json')
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
            inputs={str(path.relative_to(ROOT)): sha256(path) for path in inputs},
            extracted={name: sha256(WORK / 'patched' / name) for name in paths},
            generated={name: sha256(WORK / name) for name in ('axp_registers.h', 'axp_status_functions.h')},
            native=results, arm32=arm.strip(), builder=builder,
            limits='Actual variant cases, configuration, volatility and regmap/cache read decisions; '
                'modeled bus, readable-range admission and cache storage. Not a real Maple cache, '
                'kernel concurrency, RSB timing or live calibration/charging qualification.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, ['drivers/mfd/axp20x.o'])
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
