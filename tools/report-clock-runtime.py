#!/usr/bin/env python3
"""Disassemble captured public runtime binaries offline in the pinned builder."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from remote import ROOT, LOCAL, evidence_directory


def verified_capture(value):
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}\.[0-9]{6}Z', value):
        raise ValueError('Use the timestamp CAPTURE printed by device:clock-runtime')
    capture = LOCAL / 'diagnostics' / value
    inventory = json.loads((capture / 'inventory.json').read_text())
    summary = json.loads((capture / 'summary.json').read_text())
    if (inventory.get('operation') != 'clock-runtime-inventory' or inventory.get('complete') is not True or
            summary.get('complete') is not True or summary.get('binaries_verified') is not True):
        raise ValueError('A completed runtime inventory is required')
    for role in ('python', 'libc'):
        file = capture / (role + '.elf')
        receipt = inventory['files'][role]
        if (not 0 < file.stat().st_size == receipt['size'] <= 32*1024*1024 or
                hashlib.sha256(file.read_bytes()).hexdigest() != receipt['sha256']):
            raise ValueError('Runtime ELF differs from its receipt')
    return capture


def main():
    os.umask(0o077)
    capture = verified_capture(os.environ.get('NEO_CAPTURE', ''))
    destination = evidence_directory()
    print('Private offline clock disassembly:', destination, flush=True)
    builder = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']
    for role, symbol in (('libc', '__clock_gettime64'), ('python', 'PyTime_Monotonic')):
        arguments = ['docker', 'run', '--rm', '--pull=never', '--network=none', '--read-only',
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--user', f'{os.getuid()}:{os.getgid()}',
            '--platform', builder['platform'], '--entrypoint', builder['cross_compile'] + 'objdump',
            '--mount', 'type=bind,source=' + str(capture.resolve()) + ',target=/capture,readonly',
            builder['image'], '-d', '--disassemble=' + symbol, '/capture/' + role + '.elf']
        with (destination / (role + '-clock-disassembly.txt')).open('xb') as output:
            subprocess.run(arguments, stdout=output, stderr=subprocess.STDOUT, check=True, timeout=60)
    (destination / 'disassembly-receipt.json').write_text(json.dumps(dict(
        capture=capture.name, builder=builder, inputs=json.loads((capture / 'inventory.json').read_text())['files'],
        producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        per_call_dispatch_proven=False), indent=2) + '\n')
    print('Offline clock disassembly saved:', destination)


if __name__ == '__main__':
    main()
