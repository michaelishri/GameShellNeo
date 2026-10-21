#!/usr/bin/env python3
"""Check actual AXP ADC byte assembly and callers; optionally build both ARM users."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tarfile

from kernel_checks import archive_for, compile_objects, run, sha256

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.local/build/axp-adc-width-tests'
HEADER = 'include/linux/mfd/axp20x.h'
ADC = 'drivers/iio/adc/axp20x_adc.c'
USB = 'drivers/power/supply/axp20x_usb_power.c'
HELPER = 'axp20x_read_variable_width'
CALLERS = ('axp192_adc_raw', 'axp20x_adc_raw', 'axp22x_adc_raw', 'axp813_adc_raw')


def function(source, name):
    # These audited bodies contain no braces in comments or strings. Copy the
    # complete definition; do not replace driver logic with a modeled formula.
    matches = list(re.finditer(r'^static (?:inline )?int ' + re.escape(name) +
                              r'\([^;]+?\)\n\{', source, re.M))
    if len(matches) != 1:
        raise ValueError('Expected one function definition: ' + name)
    start = matches[0].start()
    index = source.index('{', start) + 1
    depth = 1
    while depth and index < len(source):
        depth += (source[index] == '{') - (source[index] == '}')
        index += 1
    if depth:
        raise ValueError('Unterminated function: ' + name)
    return source[start:index] + '\n'


def extract(archive, lock):
    sources, references = {}, {}
    prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
    with tarfile.open(archive, mode='r|xz') as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith(('.c', '.h')):
                continue
            data = tar.extractfile(member).read()
            name = member.name.removeprefix(prefix)
            if HELPER.encode() in data:
                references[name] = [i for i, line in enumerate(data.splitlines(), 1)
                                    if HELPER.encode() in line]
            if name in (HEADER, ADC, USB):
                sources[name] = data.decode()
    if {name: len(lines) for name, lines in references.items()} != {HEADER: 1, ADC: 4, USB: 3}:
        raise ValueError('Variable-width helper call inventory changed: ' + repr(references))
    if set(sources) != {HEADER, ADC, USB}:
        raise ValueError('Incomplete locked source extraction')
    return sources, references


def harness_source(header, original, adc):
    text = function(header, HELPER)
    text += function(original, HELPER).replace(HELPER, 'original_read_variable_width')
    for variant in ('192', '20x', '22x', '813'):
        for kind in ('v', 'i'):
            if variant == '813' and kind == 'i':
                continue  # AXP813 uses the AXP22x current channel identifiers.
            name = f'axp{variant}_adc_channel_{kind}'
            enums = re.findall(r'^enum ' + name + r' \{.*?^\};', adc, re.M | re.S)
            if len(enums) != 1:
                raise ValueError('Expected one channel enumeration: ' + name)
            text += enums[0] + '\n'
    return text + ''.join(function(adc, name) for name in CALLERS)


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
        sources, references = extract(archive, lock)
        for name, source in sources.items():
            target = WORK / 'patched' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
        patch = ROOT / 'kernel/patches/0036-axp-adc-width-mask.patch'
        run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=WORK / 'patched')
        candidate = (WORK / 'patched' / HEADER).read_text()
        expression = 'result |= reg_val & (BIT(width - 8) - 1);'
        if candidate.count(expression) != 1 or candidate.replace(expression, 'result |= reg_val;') != sources[HEADER]:
            raise ValueError('Unexpected changes outside the low-byte width mask')
        good = harness_source(candidate, sources[HEADER], sources[ADC])
        cases = {
            'candidate': good,
            'original_unmasked': harness_source(sources[HEADER], sources[HEADER], sources[ADC]),
            'fixed_12bit_mask': good.replace(expression, 'result |= reg_val & 0x0f;'),
            'mask_after_or': good.replace(expression, 'result |= reg_val; result &= BIT(width) - 1;'),
            'wrong_high_shift': good.replace('result = reg_val << (width - 8);',
                                            'result = reg_val << (width - 9);', 1),
            'wrong_low_address': good.replace('reg + 1, &reg_val', 'reg + 2, &reg_val', 1),
            'ignored_high_error': good.replace('if (err)\n\t\treturn err;',
                                              'if (err)\n\t\treturn 0;', 1),
            'ignored_low_error': good.replace(
                'err = regmap_read(regmap, reg + 1, &reg_val);\n\tif (err)\n\t\treturn err;',
                'err = regmap_read(regmap, reg + 1, &reg_val);\n\tif (err)\n\t\treturn 0;', 1),
            'wrong_13bit_caller': harness_source(candidate, sources[HEADER],
                                                sources[ADC].replace('size = 13;', 'size = 12;')),
        }
        generated = WORK / 'axp_adc_functions.h'
        harness = ROOT / 'kernel/tests/axp_adc_width_test.c'
        flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(WORK), str(harness)]
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        results = {}
        try:
            for name, source in cases.items():
                if name != 'candidate' and source == good:
                    raise ValueError('Negative control did not change source: ' + name)
                generated.write_text(source)
                binary = WORK / name
                run(['cc', *flags, '-o', str(binary)])
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
                (WORK / (name + '.txt')).write_text(result.stdout + result.stderr)
                if name == 'candidate':
                    result.check_returncode()
                elif result.returncode == 0 or 'Assertion' not in result.stderr:
                    raise RuntimeError('Expected assertion failure: ' + name)
                results[name] = dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
                print(name + ': ' + ('passed' if name == 'candidate' else 'expected assertion failure'), flush=True)
        finally:
            generated.write_text(good)
        run(['cc', *flags, '-fsanitize=undefined', '-fno-sanitize-recover=undefined',
             '-o', str(WORK / 'sanitized')])
        sanitized = subprocess.check_output([str(WORK / 'sanitized')], text=True, timeout=30)
        builder = lock['builder']
        arm = subprocess.check_output([
            'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', 'bash',
            '-v', f'{ROOT}:/project', '-w', '/project', builder['image'], '-c',
            'set -euo pipefail\n'
            'arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static '
            '-I.local/build/axp-adc-width-tests kernel/tests/axp_adc_width_test.c '
            '-o .local/build/axp-adc-width-tests/arm\n'
            'qemu-arm .local/build/axp-adc-width-tests/arm'], text=True)
        print(arm, end='', flush=True)
        inputs = (patch, harness, Path(__file__), ROOT / 'tools/kernel_checks.py',
                  ROOT / 'tools/kernel_sources.py', ROOT / 'tools/kernel-inputs.py',
                  ROOT / 'kernel/gameshellneo.config', ROOT / 'build/sources.lock.json')
        evidence = dict(linux=lock['linux']['tag'], archive_sha256=sha256(archive),
            inputs={str(path.relative_to(ROOT)): sha256(path) for path in inputs},
            originals={name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()},
            reference_lines=references, patched_header_sha256=sha256(WORK / 'patched' / HEADER),
            generated_sha256=sha256(generated), native=results, sanitized=sanitized.strip(),
            arm32=arm.strip(), builder=builder,
            limits='Actual 9-16 bit helper and four IIO callbacks; scripted regmap reads and framework types. '
                   'Exhaustive byte decoding, ordered/error reads and unchanged valid values. '
                   'No hardware byte-latch/coherence, ADC calibration, charging or energy qualification. '
                   'Caller contract excludes widths outside 9-16; no new runtime width policy.')
        if args.compile_driver:
            evidence['arm_build'] = compile_objects(archive, lock, WORK, [
                'drivers/iio/adc/axp20x_adc.o', 'drivers/power/supply/axp20x_usb_power.o'])
            evidence['arm_usb_fallback_build'] = compile_objects(archive, lock, WORK,
                ['drivers/power/supply/axp20x_usb_power.o'],
                extra_config=('CONFIG_AXP20X_ADC=n',), project_config=False)
        output.write_text(json.dumps(evidence, indent=2) + '\n')
        print('Evidence:', output.relative_to(ROOT), flush=True)


if __name__ == '__main__':
    main()
