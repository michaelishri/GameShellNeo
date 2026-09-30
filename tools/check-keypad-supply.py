#!/usr/bin/env python3
"""Verify the retention DTB and reject realistic misconfigurations before assembly."""
import json
from pathlib import Path
import subprocess
import tempfile

import keypad_supply as supply

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = ROOT / '.local/build/kernel/arch/arm/boot/dts/allwinner' / supply.DTB
    output = ROOT / '.local/build/keypad-supply.dtb'
    record = supply.prepare(base, output)
    negative = [
        ['-d', supply.NODE, supply.PROPERTY],
        ['-t', 'x', supply.NODE, supply.PROPERTY, '1'],
        ['-t', 's', '/soc/usb@1c1a400', 'status', 'disabled'],
        ['-t', 'x', supply.NODE, 'regulator-max-microvolt', '400000'],
        ['-t', 'x', '/soc/mmc@1c10000', 'wakeup-source'],
        ['-t', 'x', '/soc/mmc@1c10000', 'cap-power-off-card'],
    ]
    with tempfile.TemporaryDirectory() as directory:
        candidate = Path(directory) / 'bad.dtb'
        for args in negative:
            candidate.write_bytes(output.read_bytes())
            options = args[:1] if args[0] == '-d' else args[:2]
            remainder = args[len(options):]
            subprocess.run(['fdtput', *options, str(candidate), *remainder], check=True)
            try:
                supply.verify(base, candidate)
            except (ValueError, subprocess.CalledProcessError):
                pass
            else:
                raise ValueError('Bad retention DTB was accepted: ' + str(args))
    record['negative_controls_rejected'] = len(negative)
    (ROOT / '.local/build/keypad-supply.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Keypad supply DTB verified; six altered/missing-property negative controls rejected')


if __name__ == '__main__':
    main()
