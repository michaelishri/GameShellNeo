#!/usr/bin/env python3
"""Verify ARM time64 inputs and preserve one awake API/kernel comparison."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tarfile

from private_config import load_env
from remote import ROOT, LOCAL, device, evidence_directory, run
from kernel_checks import sha256

FILES = ('arch/arm/tools/syscall.tbl', 'include/uapi/linux/time_types.h',
         'include/uapi/asm-generic/posix_types.h', 'include/uapi/linux/time.h',
         'arch/arm/include/uapi/asm/unistd.h', 'arch/arm/include/asm/elf.h',
         'include/uapi/linux/elf.h', 'include/uapi/linux/elf-em.h')


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_headers(files):
    if set(files) != set(FILES):
        raise ValueError('Missing clock ABI source inputs')
    clean = {name: re.sub(r'/\*.*?\*/', '', data, flags=re.S) for name, data in files.items()}
    if not re.search(r'^403\s+common\s+clock_gettime64\s+sys_clock_gettime\s*$',
                     clean[FILES[0]], re.M):
        raise ValueError('ARM time64 syscall number/entry differs')
    compact = lambda name: re.sub(r'\s+', ' ', clean[name])
    if ('struct __kernel_timespec { __kernel_time64_t tv_sec; long long tv_nsec; };' not in compact(FILES[1]) or
            'typedef long long __kernel_time64_t;' not in compact(FILES[2])):
        raise ValueError('Kernel time64 structure differs')
    if ('#if defined(__thumb__) || defined(__ARM_EABI__) #define __NR_SYSCALL_BASE 0 ' not in
            compact(FILES[4])):
        raise ValueError('ARM EABI syscall base differs')
    for filename, constants in (
        (FILES[3], {'CLOCK_MONOTONIC': '1', 'CLOCK_MONOTONIC_RAW': '4', 'CLOCK_BOOTTIME': '7'}),
        (FILES[5], {'EF_ARM_EABI_MASK': '0xff000000', 'EF_ARM_EABI_VER5': '0x05000000'}),
        (FILES[6], {'ELFCLASS32': '1', 'ELFDATA2LSB': '1'}), (FILES[7], {'EM_ARM': '40'})):
        for name, value in constants.items():
            if not re.search(r'^#define\s+' + name + r'\s+' + value + r'\s*$', clean[filename], re.M):
                raise ValueError('Clock ABI constant differs: ' + name)


def source_receipt(lock):
    version = lock['linux']['tag'].removeprefix('v')
    archive = LOCAL / 'downloads' / ('linux-' + version + '.tar.xz')
    if not archive.is_file() or sha256(archive) != lock['linux']['tarball_sha256']:
        raise ValueError('Prepare the matching hash-verified Linux archive before this check')
    files = {}
    with tarfile.open(archive, 'r|xz') as source:
        for member in source:
            name = member.name.removeprefix('linux-' + version + '/')
            if name in FILES:
                files[name] = source.extractfile(member).read().decode()
            if len(files) == len(FILES):
                break
    verify_headers(files)
    return dict(linux=lock['linux'], files={name: hashlib.sha256(text.encode()).hexdigest()
                                          for name, text in files.items()})


def validate_result(result, before, after):
    recorder = load('clock_paths_recorder', 'compare-clock-paths.py')
    if (result.get('schema') != 1 or result.get('operation') != 'awake-clock-path-comparison' or
            result.get('complete') is not True or result.get('batches') != recorder.BATCHES or
            result.get('per_batch') != recorder.PER_BATCH or result.get('pause_seconds') != recorder.PAUSE):
        raise ValueError('Clock comparison incomplete or has unexpected bounds')
    recorder.check_abi(result['abi'])
    metadata = result['metadata']
    affinity = metadata['affinity']
    if (metadata != result['after_metadata'] or metadata['boot_id'] != before['boot_id'] or
            not metadata['clocksource'] or not affinity or
            any(type(cpu) is not int or cpu not in range(4) for cpu in affinity) or
            affinity != sorted(set(affinity))):
        raise ValueError('Boot, clocksource or process affinity is unqualified/changed')
    obs = result['observation']
    count, total = obs['discrepancy_samples'], recorder.BATCHES * recorder.PER_BATCH
    if (obs['complete'] is not True or 'error' in obs or obs['samples'] != total or
            type(count) is not int or not 0 <= count <= total or
            len(obs['events']) != min(count, recorder.MAX_EVENTS) or
            obs['truncated'] is not (count > recorder.MAX_EVENTS)):
        raise ValueError('Clock comparison has incomplete observations')

    def sample(value):
        if type(value) is not dict or set(value) != set(recorder.CLOCKS):
            raise ValueError('Incomplete clock family evidence')
        for record in value.values():
            for key in ('cpu_before', 'cpu_after'):
                if type(record[key]) is not int or record[key] not in affinity:
                    raise ValueError('CPU context outside observed affinity')
        recorder.discrepancies(None, value)

    sample(obs['first']); sample(obs['last'])
    if set(obs['cpu_before_counts']) != set(recorder.CLOCKS) or set(obs['cpu_brackets_differ']) != set(recorder.CLOCKS):
        raise ValueError('Missing CPU context')
    for name in recorder.CLOCKS:
        cpus, changed = obs['cpu_before_counts'][name], obs['cpu_brackets_differ'][name]
        if (not set(cpus) <= {str(cpu) for cpu in affinity} or
                any(type(n) is not int or n <= 0 for n in cpus.values()) or sum(cpus.values()) != total or
                type(changed) is not int or not 0 <= changed <= total):
            raise ValueError('Incomplete CPU counts')
    seen, last_index = {}, 0
    for event in obs['events']:
        index = event['index']
        if type(index) is not int or not last_index < index <= total:
            raise ValueError('Unordered discrepancy evidence')
        sample(event['sample'])
        if index == 1:
            if event['previous'] is not None or event['sample'] != obs['first']:
                raise ValueError('Invalid first discrepancy context')
        else:
            sample(event['previous'])
        reasons = recorder.discrepancies(event['previous'], event['sample'])
        if not reasons or reasons != event['reasons']:
            raise ValueError('Discrepancy classification differs from original readings')
        for reason in reasons:
            seen[reason] = seen.get(reason, 0) + 1
        last_index = index
    allowed = {name + '.' + path + suffix for name in recorder.CLOCKS
               for path in ('python', 'syscall', 'interleaved') for suffix in ('', '_between')}
    counts = obs['counts']
    if (not set(counts) <= allowed or any(type(n) is not int or not 1 <= n <= count for n in counts.values()) or
            not count <= sum(counts.values()) <= 18 * count or
            any(counts.get(key, 0) < n for key, n in seen.items()) or
            (count <= recorder.MAX_EVENTS and counts != seen)):
        raise ValueError('Discrepancy counts disagree with retained readings')
    load('clock_paths_state', 'check-clock-observation.py').validate_state(before, after)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-abi', action='store_true', help='Verify pinned ABI inputs offline only')
    args = parser.parse_args()
    os.umask(0o077)
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    capture = evidence_directory()
    print('Private clock-path evidence:', capture, flush=True)
    receipt = source_receipt(lock)
    (capture / 'abi-sources.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if args.check_abi:
        print('Pinned ARM EABI/time64 inputs verified; no device accessed.', flush=True)
        return
    pm = load('clock_paths_pm', 'check-pm-stages.py')
    config = load_env()
    with (LOCAL / 'pm-stages.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with device(config, 'usb') as client:
            before = json.loads(pm.inline(client, '--inspect'))
            (capture / 'before.json').write_text(json.dumps(before, indent=2) + '\n')
            if (before['kernel'] != lock['linux']['tag'][1:] + lock['linux']['localversion'] or
                    before['image']['version'] != lock['image_version'] or
                    before['pm']['pm_test'].split()[0] != '[none]' or before['usb'] != ['configured'] or
                    before['external_power']['axp20x-usb'] != {'type': 'USB', 'present': '1', 'online': '1'} or
                    any(v['ActiveState'] != 'active' for v in before['services'].values())):
                raise ValueError('Comparison needs matching awake image, active services and USB power')
            active = run(client, 'systemctl list-units --all --plain --no-legend '
                         '--state=active,activating,deactivating gameshellneo-pm-test.service '
                         'gameshellneo-sleep-test.service', display=False).strip()
            if active:
                raise ValueError('A PM diagnostic is active')
            source = (ROOT / 'tools/compare-clock-paths.py').read_bytes()
            (capture / 'source.json').write_text(json.dumps(dict(
                device_sha256=hashlib.sha256(source).hexdigest(), host_sha256=sha256(Path(__file__)))) + '\n')
            try:
                with (capture / 'comparison.json').open('wb') as output:
                    data = run(client, 'timeout --signal=TERM --kill-after=5 90 /usr/bin/python3 -B -',
                               input_data=source, output=output, display=False, timeout=105)
            finally:
                after = json.loads(pm.inline(client, '--inspect'))
                (capture / 'after.json').write_text(json.dumps(after, indent=2) + '\n')
            result = json.loads(data)
            validate_result(result, before, after)
            pm.wifi_proof(config, after)
    summary = dict(complete=True, observation_validated=True,
                   discrepancy_samples=result['observation']['discrepancy_samples'],
                   clock_reliability_qualified=False, pm_admission=False,
                   device_state_unchanged=True, usb_ssh_verified=True, wifi_ssh_verified=True)
    (capture / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
