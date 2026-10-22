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
    # The SSH transfer adapter belongs to task check on the host. Its Paramiko
    # dependency is intentionally absent from this pinned, offline root builder.
    suite = '''import pathlib, unittest
loader = unittest.TestLoader()
tests = unittest.TestSuite()
for path in sorted(pathlib.Path('/project/tools/tests').glob('test_dev_*.py')):
    if path.name != 'test_dev_transfer.py':
        tests.addTests(loader.discover(str(path.parent), pattern=path.name))
result = unittest.TextTestRunner(verbosity=2).run(tests)
raise SystemExit(not result.wasSuccessful())
'''
    subprocess.run(['docker', 'run', '--rm', '--network=none', '--pull=never', '--privileged',
        '--platform=' + builder['platform'], '--entrypoint=python3',
        '-v', str(ROOT) + ':/project:ro', builder['image'], '-c', suite], check=True)
