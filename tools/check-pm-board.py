#!/usr/bin/env python3
"""Check the compiled SDIO contract for staged PM diagnostics in the pinned builder."""
import json
from pathlib import Path
import sys


def verify(tree):
    import libfdt
    node = tree.path_offset('/soc/mmc@1c10000')
    def prop(name):
        try:
            return bytes(tree.getprop(node, name))
        except libfdt.FdtException as error:
            if error.err != -libfdt.NOTFOUND:
                raise
            return None
    if (prop('status') != b'okay\0' or prop('non-removable') != b'' or
            prop('keep-power-in-suspend') != b'' or prop('cap-power-off-card') is not None or
            prop('wakeup-source') is not None or prop('enable-sdio-wakeup') is not None):
        raise ValueError('Staged PM requires retained SDIO power without radio wake or card power-off')


def main():
    import libfdt
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / 'build/sources.lock.json').read_text())
    if lock.get('experiments', {}).get('suspend_diagnostics') is not True:
        return
    data = Path(sys.argv[1]).read_bytes()
    tree = libfdt.Fdt(data)
    verify(tree)
    # The omitted capability was the concrete driver mismatch. Verify the
    # assertion rejects the original compiled shape, not just the good DTS text.
    tree.delprop(tree.path_offset('/soc/mmc@1c10000'), 'keep-power-in-suspend')
    try:
        verify(tree)
    except ValueError:
        pass
    else:
        raise ValueError('Missing SDIO suspend capability was not rejected')
    print('Compiled PM board contract passed; missing KEEP_POWER negative control rejected')


if __name__ == '__main__':
    main()
