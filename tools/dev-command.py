#!/usr/bin/env python3
"""Pass Task arguments as data to the fixed development helper selected by Task."""
import os
from pathlib import Path
import shlex
import subprocess
import sys


COMMANDS = {'card': 'build-dev-card.py', 'check-card': 'check-dev-card.py',
            'bundle': 'prepare-dev-bundle.py', 'pack-card': 'pack-dev-card.py', 'initramfs': 'build-dev-initramfs.py',
            'busybox': 'fetch-dev-busybox.py', 'systems': 'dev-systems.py',
            'store-pack': 'prepare-dev-store.py', 'store-install': 'install-dev-store.py',
            'store-check': 'check-dev-store.py', 'store-grow': 'grow-dev-store.py',
            'store-backup': 'checkpoint-dev-store.py'}

if __name__ == '__main__':
    script = Path(__file__).parent / COMMANDS[sys.argv[1]]
    sys.exit(subprocess.run([sys.executable, str(script),
                             *shlex.split(os.environ.get('NEO_COMMAND', ''))]).returncode)
