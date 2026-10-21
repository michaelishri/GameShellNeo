"""Negative controls against the actual compiled CPI DTB in the pinned builder."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

import libfdt

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('ethernet_config', TOOLS/'check-ethernet-config.py')
ethernet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ethernet)


def check(path, source):
    original = path.read_bytes()
    baseline = ethernet.inspect_dtb(path, source)
    rejected = []
    with tempfile.TemporaryDirectory() as directory:
        changed = Path(directory)/'mutated.dtb'
        for compatible in baseline['target_compatibles']:
            tree = libfdt.Fdt(original); tree.resize(len(original)+1024)
            offset = tree.add_subnode(0, 'ethernet-negative-control')
            tree.setprop(offset, 'compatible', compatible.encode()+b'\0')
            tree.setprop(offset, 'status', b'disabled\0')
            changed.write_bytes(tree.as_bytearray())
            try:
                ethernet.inspect_dtb(changed, source)
            except ValueError as error:
                if str(error) != 'Board contains a target Ethernet compatible': raise
                rejected.append('disabled '+compatible)
            else:
                raise AssertionError('Accepted target Ethernet compatible: '+compatible)
        for compatible in ('brcm,bcm4329-fmac', 'allwinner,sun8i-a33-musb'):
            tree = libfdt.Fdt(original); tree.resize(len(original)+1024)
            offset = libfdt.fdt_node_offset_by_compatible(tree.as_bytearray(), -1, compatible)
            if offset < 0:
                raise AssertionError('Required baseline network node absent')
            tree.setprop(offset, 'compatible', b'negative-control,missing-network\0')
            changed.write_bytes(tree.as_bytearray())
            try:
                ethernet.inspect_dtb(changed, source)
            except ValueError as error:
                if str(error) != 'Expected CPI network bindings missing': raise
                rejected.append('missing '+compatible)
            else:
                raise AssertionError('Accepted missing required network binding')
    if path.read_bytes() != original:
        raise AssertionError('Original compiled DTB changed')
    return dict(passed=True, rejected=rejected)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dtb', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.dtb, args.source), indent=2))
