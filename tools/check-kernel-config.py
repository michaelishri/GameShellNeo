#!/usr/bin/env python3
"""Fail when Kconfig silently drops a requested diagnostic option."""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    actual = dict(re.findall(r'^(CONFIG_\w+)=(.*)$', args.config.read_text(), re.M))
    requested = dict(re.findall(r'^(CONFIG_\w+)=(.*)$',
                               (ROOT / 'kernel/gameshellneo.config').read_text(), re.M))
    requested.update(CONFIG_MMC_BLOCK='y', CONFIG_BLK_DEV_SD='y', CONFIG_SERIAL_8250_CONSOLE='y',
                     CONFIG_UNIX='y', CONFIG_INET='y', CONFIG_PROC_FS='y', CONFIG_SYSFS='y')
    errors = [f'{key}: requested {value}, resolved {actual.get(key, "n")}'
              for key, value in requested.items() if actual.get(key, 'n') != value]
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Kernel configuration: {len(requested)} assertions passed')


if __name__ == '__main__':
    main()
