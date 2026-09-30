#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
image=$(python3 -c 'import json; print(json.load(open("build/sources.lock.json"))["builder"]["image"])')
docker run --rm --entrypoint bash -v "$PWD:/project" "$image" -c '
    set -euo pipefail
    # The digest-pinned builder includes its Python tools outside the default path.
    export PYTHONPATH=/armbian-pip/base/lib/python3.13/site-packages PATH=/armbian-pip/base/bin:$PATH
    python3 -m pip freeze > /project/.local/build/schema-validator-packages.txt
    cd /project/.local/sources/linux-6.18.54
    {
        dt-doc-validate Documentation/devicetree/bindings/display/panel/clockwork,cpi3-lcd.yaml \
            Documentation/devicetree/bindings/leds/backlight/ocs,ocp8178.yaml \
            Documentation/devicetree/bindings/pinctrl/allwinner,sun4i-a10-pinctrl.yaml
        dt-mk-schema -j Documentation/devicetree/bindings > /project/.local/build/schema.json
        dt-validate -s /project/.local/build/schema.json \
            /project/.local/build/kernel/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dtb
    } > /project/.local/build/dt-validation.log 2>&1
    if [[ -s /project/.local/build/dt-validation.log ]]; then
        cat /project/.local/build/dt-validation.log >&2
        exit 1
    fi
    echo "Device-tree schemas and board DTB: no diagnostics"
    python3 /project/tools/check-pm-board.py /project/.local/build/kernel/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dtb
    python3 /project/tools/check-keypad-supply.py
    dt-validate -s /project/.local/build/schema.json /project/.local/build/keypad-supply.dtb \
        > /project/.local/build/keypad-dt-validation.log 2>&1
    if [[ -s /project/.local/build/keypad-dt-validation.log ]]; then
        cat /project/.local/build/keypad-dt-validation.log >&2
        exit 1
    fi
    echo "Keypad retention DTB: no schema diagnostics"
    '
