#!/usr/bin/env python3
"""Audit sources and qualify pure fixtures; STOP never launches a device probe."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import uuid

from clock_reference_feasibility import FAMILIES, GATES, analyze, assess, fixtures
from kernel_sources import atomic_json
from managed_container import execute

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('drivers/clocksource/timer-sun4i.c', 'drivers/clocksource/mmio.c',
    'drivers/clocksource/timer-of.c', 'arch/arm/boot/dts/allwinner/sun8i-a23-a33.dtsi',
    'arch/arm/include/asm/arch_timer.h', 'arch/arm/include/asm/io.h', 'arch/arm/include/asm/barrier.h')
INPUTS = ('Taskfile.yml', 'build/sources.lock.json', 'tools/clock_reference_feasibility.py',
    'tools/check-clock-reference-feasibility.py', 'tools/tests/clock_reference_interval_test.c',
    'tools/tests/clock_reference_ordering_fragment.c', 'tools/tests/test_clock_reference_feasibility.py',
    'tools/managed_container.py', 'tools/docker-stage.py', 'tools/kernel_sources.py')
BASELINE = '1b924c53f9dff37cc4c96cafd9ed2e42bbc49ba50fa7c08636121508cf050cf6'
MANUAL = '294668ae6480133b32d85e9567cc77c5eb0e1232decdf42cac7ab480e884f6e0'
SCRIPT = r'''set -euo pipefail
python3 -m unittest discover -s tools/tests -p test_clock_reference_feasibility.py -v > /out/native-python.txt 2>&1
cc -std=gnu11 -O2 -Wall -Wextra -Werror tools/tests/clock_reference_interval_test.c -o /out/interval-native
/out/interval-native > /out/native.txt
cc -std=gnu11 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie tools/tests/clock_reference_interval_test.c -o /out/interval-sanitize
ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 /out/interval-sanitize > /out/sanitize.txt
arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -static tools/tests/clock_reference_interval_test.c -o /out/interval-arm
qemu-arm /out/interval-arm > /out/arm.txt
arm-linux-gnueabihf-gcc -std=gnu11 -O2 -Wall -Wextra -Werror -march=armv7-a -marm -mfpu=vfpv3-d16 -mfloat-abi=hard -c tools/tests/clock_reference_ordering_fragment.c -o /out/ordering-fragment.o
arm-linux-gnueabihf-objdump -dr /out/ordering-fragment.o > /out/proposed-ordering.txt
arm-linux-gnueabihf-readelf -h -A /out/ordering-fragment.o > /out/fragment-elf.txt
arm-linux-gnueabihf-gcc --version > /out/compiler.txt
arm-linux-gnueabihf-objdump --version > /out/objdump.txt
'''


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def audit_sources(archive, lock):
    if sha(archive) != lock['linux']['tarball_sha256']:
        raise ValueError('Linux archive does not match the unchanged lock')
    prefix = 'linux-' + lock['linux']['tag'].removeprefix('v') + '/'
    texts = {}
    with tarfile.open(archive, 'r|xz') as source:
        for entry in source:
            name = entry.name.removeprefix(prefix)
            if not entry.name.startswith(prefix) or name not in SOURCES:
                continue
            if name in texts or not entry.isfile() or entry.size > 1024 * 1024:
                raise ValueError('Duplicate, non-regular or oversized source')
            texts[name] = source.extractfile(entry).read().decode()
    if set(texts) != set(SOURCES):
        raise ValueError('Missing required Linux source')
    if not all(value in texts['drivers/clocksource/timer-sun4i.c'] for value in (
            'TIMER_CNTVAL_REG(1)', 'TIMER_CTL_CLK_SRC_OSC24M', 'clocksource_mmio_readl_down',
            'timer_of_init(node, &to)', '"allwinner,sun8i-a23-timer"')):
        raise ValueError('Timer mapping/initialization selection differs')
    if 'return ~(u64)readl_relaxed(to_mmio_clksrc(c)->reg) & c->mask;' not in texts[SOURCES[1]]:
        raise ValueError('Registered relaxed MMIO counter implementation differs')
    if not all(value in texts[SOURCES[3]] for value in (
            'timer@1c20c00', '"allwinner,sun8i-a23-timer"', 'clocks = <&osc24M>')):
        raise ValueError('Reference DT clock/mapping differs')
    if not all(value in texts[SOURCES[4]] for value in ('isb();', 'mrrc p15, 0, %Q0, %R0, c14')):
        raise ValueError('Original ARM physical-counter read differs')
    return texts


def audit_baseline(path, sources):
    if sha(path) != BASELINE:
        raise ValueError('Select the exact preserved read-only baseline receipt')
    baseline = json.loads(path.read_text())
    for name, expected in baseline['evidence_sha256'].items():
        if sha(Path(name)) != expected:
            raise ValueError('Preserved baseline evidence changed: ' + name)
    if (sha(Path(baseline['vmlinux']['path'])) != baseline['vmlinux']['sha256'] or
            sha(Path(baseline['config']['path'])) != baseline['config']['sha256']):
        raise ValueError('Retained emitted kernel/config differs')
    actual = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sources.items()}
    if actual != baseline['local_source_sha256']:
        raise ValueError('Complete seven-source map differs from inspected source')
    selected = baseline['config']['selected']
    if any(selected.get(key) != 'y' for key in (
            'CONFIG_ARM_DMA_MEM_BUFFERABLE', 'CONFIG_SUN4I_TIMER', 'CONFIG_CLKSRC_MMIO',
            'CONFIG_ARM_ARCH_TIMER', 'CONFIG_SMP')) or selected.get('CONFIG_HZ') != '100':
        raise ValueError('Captured reference/barrier configuration differs')
    return baseline, actual


def verify_cases(text):
    lines = text.splitlines()
    expected = fixtures()
    records = [json.loads(line.removeprefix('NEO_REFERENCE_FIXTURE '))
               for line in lines if line.startswith('NEO_REFERENCE_FIXTURE ')]
    if len(records) != 19 or len(lines) != 20 or not lines[-1].startswith('19 synthetic cases in six families passed;'):
        raise ValueError('Incomplete or extra pure fixture results')
    for original, result in zip(expected, records):
        model = analyze(original['first'], original['second'], original['gates'])
        mask = sum(1 << i for i, key in enumerate(GATES) if original['gates'][key])
        if any(result[key] != original[key] for key in ('name', 'family', 'first', 'second')):
            raise ValueError('Original synthetic values changed')
        if (result['gates'], result['code'], result['delta']) != (mask, original['expected_code'], model['counter_delta_ticks']):
            raise ValueError('Independent C/Python classification differs')
        if model['reference_spans'] is not None and (
                [result['first_span'], result['second_span']] != model['reference_spans'] or
                result['gap'] != model['reference_gap']):
            raise ValueError('Raw downcounter/wrap calculation differs')
        if bool(result['has_intervals']) != (model['counter_delta_interval'] is not None):
            raise ValueError('Ambiguous reference gained an interval')
        if result['has_intervals'] and (
                [result['lower'], result['upper']] != model['counter_delta_interval'] or
                result['uncertainty'] != model['uncertainty_ticks'] or
                bool(result['resolution']) != model['historical_18_tick_resolution']):
            raise ValueError('Quantization or resolution calculation differs')
    return records


def verify_fragment(text, elf):
    functions = {}
    for name in ('original', 'relaxed', 'readl'):
        match = re.search(r'<neo_reference_fragment_' + name + r'>:\n(.*?)(?=\n[0-9a-f]+ <|\Z)', text, re.S)
        if not match:
            raise ValueError('Missing compile-only comparison function')
        body = match.group(1)
        counts = {mnemonic: len(re.findall(r'\b' + mnemonic + r'\b', body)) for mnemonic in ('isb', 'mrrc', 'dsb')}
        if counts != dict(isb=1, mrrc=1, dsb=2 if name == 'readl' else 0):
            raise ValueError('Emitted ARM ordering fragment differs')
        if re.search(r'\b(?:svc|hvc|smc)\b', body):
            raise ValueError('Unexpected operational entry in comparison fragment')
        functions[name] = dict(instructions=counts, compile_only=True, executed=False)
    if not all(value in elf for value in ('ELF32', 'little endian', 'ARM', 'Version5 EABI',
                                        'Tag_ABI_VFP_args', 'VFP registers')):
        raise ValueError('Comparison fragment ARM ABI differs')
    return functions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('linux-archive', 'baseline-evidence', 'arm-manual'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    sources = audit_sources(args.linux_archive, lock)
    baseline, mapping = audit_baseline(args.baseline_evidence, sources)
    if sha(args.arm_manual) != MANUAL:
        raise ValueError('Primary ARM DDI0406C.d document differs')
    work = ROOT / '.local/build/clock-reference-feasibility' / uuid.uuid4().hex
    snapshot = work / 'input'
    snapshot.mkdir(parents=True)
    inputs = {name: sha(ROOT / name) for name in INPUTS}
    for name in INPUTS:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        if sha(target) != inputs[name]:
            raise ValueError('Source changed during isolated snapshot')
    print('Private feasibility attempt:', work, flush=True)
    atomic_json(work / 'source-audit.json', dict(schema=1, complete=True, sources=mapping,
        source_archive_sha256=lock['linux']['tarball_sha256'], baseline_receipt_sha256=BASELINE,
        config=baseline['config'], vmlinux=baseline['vmlinux'], build_id=baseline['build_id'],
        arm_manual_sha256=MANUAL, document='ARM DDI 0406C.d (ID040418)',
        source_lifetime='timer-of failure can unmap/disable; no diagnostic ready/accessor interface exists',
        abi=dict(counter_bits=64, reference_bits=32, arm_word_bits=32, little_endian=True),
        scope='Source/config/ABI and emitted baseline only; no ordering proof or new provider qualification.'))
    builder = lock['builder']
    result = execute('clock-reference-feasibility', ['--network', 'none', '--pull', 'never',
        '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--cpus', '1', '--memory', '512m', '--memory-swap', '512m',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m', '--user', f'{os.getuid()}:{os.getgid()}',
        '--platform', builder['platform'], '--entrypoint', 'bash',
        '-v', str(snapshot) + ':/input:ro', '-v', str(work) + ':/out', '-w', '/input',
        builder['image'], '-c', SCRIPT], work / 'managed', timeout=180)
    if inputs != {name: sha(ROOT / name) for name in INPUTS}:
        raise ValueError('Actual qualification inputs changed during original run')
    cases = {name: verify_cases((work / (name + '.txt')).read_text()) for name in ('native', 'sanitize', 'arm')}
    python = (work / 'native-python.txt').read_text()
    if 'Ran 9 tests' not in python or not python.rstrip().endswith('OK'):
        raise ValueError('Incomplete pure Python suite')
    fragment = verify_fragment((work / 'proposed-ordering.txt').read_text(), (work / 'fragment-elf.txt').read_text())
    paths = [p for p in work.iterdir() if p.is_file()]
    receipt = dict(schema=1, operation='clock-reference-offline-feasibility', complete=True,
        assessment=assess(), inputs=inputs, sources=mapping, builder=builder,
        managed_run=result['job']['run'], fixture_families=list(FAMILIES), cases_per_runtime=19,
        native_c=len(cases['native']), sanitized_c=len(cases['sanitize']), arm32_c=len(cases['arm']),
        native_python_tests=9, comparison_fragments=fragment, fragment_executed=False,
        outputs={p.name: sha(p) for p in paths}, primary_manual_sha256=MANUAL,
        no_hardware_contact=True, pm_admission=False, parent192_resolved=False)
    atomic_json(work / 'qualification.json', receipt)
    print('Complete bounded feasibility outcome: STOP; no probe or PM admission.', flush=True)


if __name__ == '__main__':
    main()
