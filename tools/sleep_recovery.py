#!/usr/bin/env python3
"""Read-only sleep postmortem; no register dumps, PM requests or policy cleanup."""
import json
from pathlib import Path
import re
import sys
import time


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError as error:
        return {'errno': error.errno, 'error': type(error).__name__}


def snapshot(token):
    if not re.fullmatch(r'[0-9a-f]{32}', token):
        raise ValueError('Expected original sleep run ID')
    cpu = Path('/sys/devices/system/cpu')
    udc = Path('/sys/class/udc')
    return dict(
        run_id=token, boot_id=read('/proc/sys/kernel/random/boot_id'),
        monotonic_seconds=time.monotonic(),
        original_recovery=read('/var/lib/gameshellneo/sleep-tests/'+token+'/recovery.json'),
        cpu_online=read(cpu/'online'),
        cpuidle_driver=read(cpu/'cpuidle/current_driver'),
        cpuidle_governor=read(cpu/'cpuidle/current_governor_ro'),
        idle_states={str(p): read(p) for p in sorted(cpu.glob('cpu[0-9]*/cpuidle/state*/name'))},
        udc={p.name: {k: read(p/k) for k in ('state', 'current_speed', 'maximum_speed')}
             for p in sorted(udc.glob('*'))},
        gadget_bindings={str(p): read(p) for p in Path('/sys/kernel/config/usb_gadget').glob('*/UDC')},
        extcon={str(p.resolve()): read(p) for p in Path('/sys/class/extcon').glob('*/state')},
        musb_mode=read('/sys/devices/platform/soc/1c19000.usb/musb-hdrc.2.auto/mode'),
        usb_network={k: read('/sys/class/net/usb0/'+k) for k in ('operstate', 'carrier')},
        usb_supply={k: read('/sys/class/power_supply/axp20x-usb/'+k) for k in ('present', 'online')},
        battery=read('/run/gameshellneo/battery.json'),
        controls={k: read('/sys/power/'+k) for k in ('state', 'pm_test', 'pm_async', 'pm_wakeup_irq')},
        owners={str(p): read(p) for p in (
            Path('/run/gameshellneo-power-policy.json'),
            Path('/run/systemd/logind.conf.d/zz-gameshellneo-pm-guard.conf'),
            Path('/run/gameshellneo-sleep-controls.json'))},
        interrupts=read('/proc/interrupts'))


if __name__ == '__main__':
    print(json.dumps(snapshot(sys.argv[1])))
