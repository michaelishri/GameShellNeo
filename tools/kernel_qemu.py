"""Pinned ARM system-emulation environment; no physical device access."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from managed_container import execute as run_managed


def inputs(lock):
    image = lock['builder']['image']
    if not re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', image):
        raise ValueError('The base builder must use an immutable digest')
    if lock['builder']['platform'] != 'linux/amd64':
        raise ValueError('Expected the Intel build host platform')
    blocks, expected = [], {}
    for archive, key, suite in (('debian', 'snapshot', 'trixie'),
                                ('debian-security', 'security_snapshot', 'trixie-security')):
        stamp = lock['debian'][key]
        digest = lock['debian']['inrelease_sha256' if key == 'snapshot' else 'security_inrelease_sha256']
        if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z', stamp) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Expected pinned repository timestamp and InRelease hash')
        blocks.append(f'Types: deb\nURIs: https://snapshot.debian.org/archive/{archive}/{stamp}/\n'
                      f'Suites: {suite}\nComponents: main\n'
                      'Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\n'
                      'Check-Valid-Until: no\n')
        expected[suite] = digest
    verify = '''import hashlib, json, pathlib
expected = json.loads(pathlib.Path('/opt/neo-qemu/releases.json').read_text())
for suite, digest in expected.items():
    files = list(pathlib.Path('/var/lib/apt/lists').glob('*_dists_' + suite + '_InRelease'))
    if len(files) != 1 or hashlib.sha256(files[0].read_bytes()).hexdigest() != digest:
        raise SystemExit('Pinned InRelease differs: ' + suite)
'''
    dockerfile = f'''FROM {image}
COPY debian.sources /opt/neo-qemu/debian.sources
COPY releases.json verify-releases.py /opt/neo-qemu/
RUN rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources \\
 && cp /opt/neo-qemu/debian.sources /etc/apt/sources.list.d/debian.sources \\
 && rm -rf /var/lib/apt/lists/* \\
 && apt-get update \\
 && python3 /opt/neo-qemu/verify-releases.py \\
 && DEBIAN_FRONTEND=noninteractive apt-get -y --no-install-recommends install qemu-system-arm \\
 && dpkg-query -W > /opt/neo-qemu/packages.txt \\
 && qemu-system-arm --version > /opt/neo-qemu/version.txt \\
 && sha256sum /usr/bin/qemu-system-arm > /opt/neo-qemu/binary.sha256 \\
 && rm -rf /var/lib/apt/lists/*
'''
    return {'.dockerignore': '*\n!Dockerfile\n!debian.sources\n!releases.json\n!verify-releases.py\n',
            'Dockerfile': dockerfile, 'debian.sources': '\n'.join(blocks),
            'releases.json': json.dumps(expected, sort_keys=True) + '\n', 'verify-releases.py': verify}


def input_id(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def checked_qmp(text):
    records = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not records or 'QMP' not in records[0] or any('error' in r for r in records):
        raise ValueError('QEMU greeting or command failed')
    replies = [r for r in records if 'id' in r]
    if [r['id'] for r in replies] != ['capabilities', 'cpus', 'quit']:
        raise ValueError('Missing, duplicate or out-of-order QMP reply')
    if replies[0].get('return') != {} or replies[2].get('return') != {}:
        raise ValueError('QEMU capabilities or exit was not acknowledged')
    cpus = replies[1].get('return')
    if (not isinstance(cpus, list) or len(cpus) != 2 or
            sorted(c.get('cpu-index', -1) for c in cpus) != [0, 1] or
            any(type(c.get('cpu-index')) is not int or
                c.get('target') != 'arm' or
                not isinstance(c.get('qom-path'), str) or not c['qom-path'] or
                type(c.get('thread-id')) is not int or c['thread-id'] <= 0 for c in cpus) or
            len({c['thread-id'] for c in cpus}) != 2):
        raise ValueError('Expected exactly two virtual ARM CPUs')
    return cpus


def smoke(image, destination):
    if not re.fullmatch('sha256:[0-9a-f]{64}', image):
        raise ValueError('Run only the inspected immutable local image ID')
    # QMP stdin belongs to an in-container pipe, so Docker remains a supported
    # noninteractive foreground stage. Both guest and observer are bounded.
    guest = ['timeout', '--signal=TERM', '--kill-after=3', '20', 'qemu-system-arm',
             '-no-user-config', '-nodefaults', '-display', 'none', '-nic', 'none',
             '-machine', 'virt', '-cpu', 'cortex-a15', '-accel', 'tcg,thread=multi',
             '-smp', '2', '-m', '128M', '-S', '-qmp', 'stdio']
    client = ('import subprocess,sys; '
              'r=subprocess.run(' + repr(guest) + ', input=sys.argv[1], '
              'text=True, capture_output=True, timeout=25); '
              'sys.stdout.write(r.stdout); sys.stderr.write(r.stderr); sys.exit(r.returncode)')
    requests = '\n'.join(json.dumps({'execute': op, 'id': identity}) for op, identity in
                         [('qmp_capabilities', 'capabilities'), ('query-cpus-fast', 'cpus'), ('quit', 'quit')]) + '\n'
    arguments = ['--pull=never', '--network=none', '--read-only',
                 '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64',
                 '--memory=512m', '--cpus=1', '--user=65534:65534',
                 '--entrypoint=python3', image, '-c', client, requests]
    try:
        result = run_managed('qemu-smoke', arguments, destination, timeout=40)
        output = (destination / 'container.log').read_text()
        (destination / 'qmp.jsonl').write_text(output)
        (destination / 'original-state.json').write_text(json.dumps(result['state'], indent=2) + '\n')
        return checked_qmp(output)
    except BaseException as error:
        (destination / 'smoke-error.json').write_text(json.dumps(
            dict(type=type(error).__name__, message=str(error)), indent=2) + '\n')
        raise
