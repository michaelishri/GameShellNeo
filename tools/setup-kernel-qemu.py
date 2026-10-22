#!/usr/bin/env python3
"""Build an isolated QEMU system-test container from the project's signed snapshots."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

from kernel_qemu import input_id, inputs, smoke
from kernel_sources import locked, atomic_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.umask(0o077)
    work = ROOT / '.local/build/kernel-qemu'
    work.mkdir(parents=True, exist_ok=True)
    with locked(work / '.lock'):
        lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
        source_paths = (Path(__file__), ROOT / 'tools/kernel_qemu.py',
                        ROOT / 'tools/managed_container.py', ROOT / 'tools/docker-stage.py',
                        ROOT / 'tools/build-bin/docker', ROOT / 'tools/run-logged.sh')
        sources = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
        files = inputs(lock)
        key = input_id(files)
        context = work / key
        context.mkdir(exist_ok=True)
        for name, text in files.items():
            (context / name).write_text(text)
        tag = 'gameshellneo-kunit-qemu:' + key[:24]
        print('Building isolated kernel-test emulator; no GameShell access.', flush=True)
        subprocess.run(['docker', 'build', '--platform=linux/amd64', '--pull=false',
                        '--tag', tag, str(context)], check=True)
        image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', tag], text=True))[0]
        if (image['Os'], image['Architecture']) != ('linux', 'amd64'):
            raise ValueError('Unexpected emulator container platform')
        identity = image['Id']
        evidence = context / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        evidence.mkdir()
        cpus = smoke(identity, evidence)
        for name in ('packages.txt', 'version.txt', 'binary.sha256'):
            output = subprocess.check_output(['docker', 'run', '--rm', '--pull=never',
                '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                '--entrypoint=cat', identity, '/opt/neo-qemu/' + name], timeout=20)
            (evidence / name).write_bytes(output)
        if files != inputs(json.loads((ROOT / 'build/sources.lock.json').read_text())):
            raise ValueError('Emulator build inputs changed')
        if sources != {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}:
            raise ValueError('Emulator setup sources changed during validation')
        receipt = dict(schema=1, complete=True, input_id=key, image_id=identity,
            sources=sources,
            base=lock['builder'], debian=lock['debian'], cpus=cpus,
            evidence=str(evidence.relative_to(ROOT)),
            files={str(p.relative_to(evidence)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(evidence.iterdir()) if p.is_file()},
            limits='Paused two-CPU ARM virtual-machine smoke test only; no guest kernel or MUSB qualification.')
        atomic_json(evidence / 'receipt.json', receipt)
        atomic_json(work / 'receipt.json', receipt)
        print('Two virtual ARM CPUs verified and QEMU exited normally. Receipt:', work / 'receipt.json')


if __name__ == '__main__':
    main()
