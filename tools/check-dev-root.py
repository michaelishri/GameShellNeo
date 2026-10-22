#!/usr/bin/env python3
"""Run development metadata fixtures as real root in the pinned offline builder."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    if not os.environ.get('NEO_BUILD_STAGE'):
        raise ValueError('Use the saved test:dev-root Task')
    builder = json.loads((ROOT / 'build/sources.lock.json').read_text())['builder']
    subprocess.run(['docker', 'run', '--rm', '--network=none', '--pull=never', '--privileged',
        '--platform=' + builder['platform'], '--entrypoint=python3',
        '-v', str(ROOT) + ':/project:ro', builder['image'], '-m', 'unittest', 'discover',
        '-s', '/project/tools/tests', '-p', 'test_dev_*.py', '-v'], check=True)
