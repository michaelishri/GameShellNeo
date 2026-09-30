#!/usr/bin/env python3
"""Fail when Kconfig silently drops a requested diagnostic option."""
import argparse
import json
from pathlib import Path
import re
from keypad_supply import enabled as keypad_retention

ROOT = Path(__file__).resolve().parents[1]


def requirements(requested, lock):
    keypad_retention(lock)
    requested = dict(requested)
    experiments = lock.get('experiments', {})
    suspend_tests = experiments.get('suspend_diagnostics', False)
    if type(suspend_tests) is not bool:
        raise ValueError('Suspend diagnostics must be an explicit boolean')
    if suspend_tests:
        if 'usb_absent_poll' in experiments or 'usb_diagnostics' in experiments:
            raise ValueError('Suspend-test images must omit the USB experiment selectors')
        requested.update(CONFIG_SUSPEND='y', CONFIG_PM_SLEEP='y', CONFIG_PM_DEBUG='y',
                         CONFIG_PM_SLEEP_DEBUG='y', CONFIG_PM_ADVANCED_DEBUG='y',
                         CONFIG_HIBERNATION='n', CONFIG_PM_AUTOSLEEP='n', CONFIG_PM_WAKELOCKS='n',
                         CONFIG_ARM_PSCI_CPUIDLE='n', CONFIG_PM_TEST_SUSPEND='n')
    if 'usb_absent_poll' in experiments:
        requested.update(CONFIG_USB_MUSB_GADGET='y', CONFIG_USB_MUSB_SUNXI='y',
                         CONFIG_USB_MUSB_HOST='n', CONFIG_USB_MUSB_DUAL_ROLE='n',
                         CONFIG_PM_SLEEP='n', CONFIG_OF_DYNAMIC='n')
    return requested


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    actual = dict(re.findall(r'^(CONFIG_\w+)=(.*)$', args.config.read_text(), re.M))
    requested = dict(re.findall(r'^(CONFIG_\w+)=(.*)$',
                               (ROOT / 'kernel/gameshellneo.config').read_text(), re.M))
    requested.update(CONFIG_MMC_BLOCK='y', CONFIG_BLK_DEV_SD='y', CONFIG_SERIAL_8250_CONSOLE='y',
                     CONFIG_UNIX='y', CONFIG_INET='y', CONFIG_PROC_FS='y', CONFIG_SYSFS='y')
    lock = json.loads((ROOT / 'build/sources.lock.json').read_text())
    requested = requirements(requested, lock)
    errors = [f'{key}: requested {value}, resolved {actual.get(key, "n")}'
              for key, value in requested.items() if actual.get(key, 'n') != value]
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Kernel configuration: {len(requested)} assertions passed')


if __name__ == '__main__':
    main()
