#!/usr/bin/env python3
"""Export the compiled DTB into the actual-policy C test's OF shim (pinned libfdt)."""
import json
from pathlib import Path
import struct
import sys

import libfdt


def fixture(path):
    tree = libfdt.Fdt(Path(path).read_bytes())
    offsets = []

    def walk(offset):
        offsets.append(offset)
        try:
            child = tree.first_subnode(offset)
            while True:
                walk(child)
                child = tree.next_subnode(child)
        except libfdt.FdtException as error:
            if error.err != -libfdt.NOTFOUND:
                raise

    walk(0)
    if len(offsets) > 512:
        raise ValueError('Board exceeds the test node bound')
    index = {offset: i for i, offset in enumerate(offsets)}

    def prop(offset, name):
        try:
            return bytes(tree.getprop(offset, name))
        except libfdt.FdtException as error:
            if error.err != -libfdt.NOTFOUND:
                raise
            return None

    def strings(value):
        return [] if value is None else value.rstrip(b'\0').decode().split('\0')

    def cells(value):
        if value is None or len(value) % 4:
            raise ValueError('Missing or malformed cell property')
        return list(struct.unpack('>' + 'I' * (len(value) // 4), value))

    def target(phandle):
        return index[tree.node_offset_by_phandle(phandle)]

    root = strings(prop(0, 'compatible'))
    result = ['/* Generated from the compiled board DTB; do not edit. */',
              'static void board_tests(void) {', 'reset_graph();',
              'memset(nodes, 0, sizeof(nodes));', f'node_count = {len(offsets)};',
              f'board_match = {int("clockwork,clockworkpi-cpi3" in root)};',
              f'soc_match = {int("allwinner,sun8i-a33" in root)};']
    found = {}
    extras = ['usb0_vbus-supply', 'usb0_vbus_det-gpios', 'usb0_vbus_det-gpio',
              'usb0_id_det-gpios', 'usb0_id_det-gpio', 'usb-role-switch', 'extcon',
              'vbus-supply', 'x-powers,drive-vbus-en']
    for offset, i in index.items():
        prefix = f'nodes[{i}]'
        status = strings(prop(offset, 'status'))
        result += [f'{prefix}.enabled = {int(not status or status[0] in ("ok", "okay"))};',
                   f'{prefix}.parse_error = -1;']
        if offset:
            result.append(f'{prefix}.parent = &nodes[{index[tree.parent_offset(offset)]}];')
        compatible = strings(prop(offset, 'compatible'))
        if compatible:
            result.append(f'{prefix}.compatible = {json.dumps(compatible[0])};')
        for name in ('x-powers,axp223', 'x-powers,axp223-usb-power-supply',
                     'allwinner,sun8i-a33-usb-phy', 'allwinner,sun8i-a33-musb'):
            if name in compatible:
                if name in found:
                    raise ValueError('Expected unique board node: ' + name)
                found[name] = i
        flags = sum(1 << bit for bit, name in enumerate(extras) if prop(offset, name) is not None)
        result.append(f'{prefix}.property_bits = {flags};')
        value = prop(offset, '#phy-cells')
        if value is not None:
            result.append(f'{prefix}.phy_cells = {cells(value)[0]};')
        value = prop(offset, 'dr_mode')
        if value is not None:
            result.append(f'{prefix}.mode = {json.dumps(strings(value)[0])};')
        value = prop(offset, 'usb0_vbus_power-supply')
        if value is not None:
            values = cells(value)
            result += [f'{prefix}.supply_property = true;', f'{prefix}.supply_cells = {len(values)};',
                       f'{prefix}.supply = &nodes[{target(values[0])}];']
        value = prop(offset, 'extcon')
        if value is not None:
            values = cells(value)
            result += [f'{prefix}.extcon_cells = {len(values)};',
                       f'{prefix}.extcon = &nodes[{target(values[0])}];',
                       f'{prefix}.extcon_port = {values[1] if len(values) > 1 else -1};']
        value = prop(offset, 'phys')
        if value is not None:
            values = cells(value)
            count = 0
            while values:
                provider = tree.node_offset_by_phandle(values.pop(0))
                size = cells(prop(provider, '#phy-cells'))[0]
                if count >= 4 or size > 1 or len(values) < size:
                    raise ValueError('PHY list exceeds supported fixture shape')
                argument = values.pop(0) if size else 0
                result.append(f'{prefix}.phys[{count}] = (struct of_phandle_args)'
                              f'{{ &nodes[{index[provider]}], {size}, {{ {argument} }} }};')
                count += 1
            result += [f'{prefix}.phys_property = true;', f'{prefix}.phys_count = {count};']
    pmic = found['x-powers,axp223']
    supply = found['x-powers,axp223-usb-power-supply']
    controller = found['allwinner,sun8i-a33-musb']
    result += [f'struct device parent = {{ .of_node = &nodes[{pmic}] }};',
               f'struct device dev = {{ .parent = &parent, .of_node = &nodes[{supply}] }};',
               'struct axp20x_dev pmic = { .variant = AXP223_ID };',
               'struct axp20x_usb_power power = { .dev = &dev, .num_irqs = 2, .axp_data = &test_data };',
               'gameshellneo_slow_poll = true;',
               'assert(gameshellneo_poll_refusal(&power, &pmic) == NULL); no_refs(); policy_cases++;',
               f'nodes[{controller}].extcon_port = 1;',
               'assert(gameshellneo_poll_refusal(&power, &pmic) != NULL); no_refs(); policy_cases++;',
               f'nodes[{controller}].extcon_port = 0;',
               f'nodes[{controller}].mode = "host";',
               'assert(gameshellneo_poll_refusal(&power, &pmic) != NULL); no_refs(); policy_cases++;',
               f'printf("Compiled board DTB: {len(offsets)} nodes, accepted peripheral and rejected mutations\\n");',
               '}']
    return '\n'.join(result) + '\n'


if __name__ == '__main__':
    print(fixture(sys.argv[1]), end='')
