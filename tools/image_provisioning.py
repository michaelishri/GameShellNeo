#!/usr/bin/env python3
"""Select existing private image inputs for a read-only container bind mount."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
FILES = ('identity.json', 'authorized_keys', 'ssh_host_ed25519_key',
         'ssh_host_ed25519_key.pub', 'machine-id', 'wpa_supplicant-wlan0.conf')


def directory(root=ROOT, environ=None):
    environ = os.environ if environ is None else environ
    selected = environ.get('NEO_IMAGE_PROVISIONING_DIRECTORY', '')
    path = Path(selected) if selected else root / '.local/provisioning/device'
    if selected and not path.is_absolute():
        raise ValueError('NEO_IMAGE_PROVISIONING_DIRECTORY must be an absolute directory')
    # Docker -v uses colons as separators; the shell consumes one output line.
    if any(character in str(path) for character in (':', '\n', '\r', '\0')):
        raise ValueError('Unsupported provisioning directory path')
    path = path.resolve(strict=True)
    if not path.is_dir() or any(character in str(path) for character in (':', '\n', '\r')):
        raise ValueError('Expected an existing provisioning directory with a supported path')
    for name in FILES:
        source = path / name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'Prepare existing private provisioning first: missing regular {name}')
    return path


def main():
    try:
        print(directory())
    except (OSError, ValueError) as error:
        sys.exit(f'Image provisioning selection failed: {error}')


if __name__ == '__main__':
    main()
