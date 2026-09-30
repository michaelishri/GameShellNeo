#!/usr/bin/env python3
"""Validate the compiled CPI speaker route and reject incompatible board shapes."""
import json
from pathlib import Path
import struct
import sys


def verify(tree):
    def prop(node, name):
        return bytes(tree.getprop(tree.path_offset(node), name))
    def cell(value):
        return struct.pack('>I', value)
    for path in ('/soc/dai@1c22c00', '/soc/codec@1c22e00', '/sound'):
        if prop(path, 'status') != b'okay\0':
            raise ValueError('Disabled speaker DAI/codec/card')
    if prop('/speaker-amplifier', 'compatible') != b'simple-audio-amplifier\0':
        raise ValueError('Unexpected speaker amplifier driver')
    pio = prop('/soc/pinctrl@1f02c00', 'phandle')
    if prop('/speaker-amplifier', 'enable-gpios') != pio + cell(0) + cell(3) + cell(0):
        raise ValueError('Speaker amplifier must use active-high PL3')
    if tree.path_offset('/soc/pinctrl@1f02c00/amplifier-disable-hog', quiet=(1,)) >= 0:
        raise ValueError('Speaker GPIO still owned by a hog')
    if (prop('/speaker-amplifier', 'VCC-supply') != prop('/regulator-speaker-supply', 'phandle') or
            prop('/regulator-speaker-supply', 'regulator-always-on') != b''):
        raise ValueError('Speaker PS supply must remain continuously available')
    if (prop('/sound', 'simple-audio-card,name') != b'GameShellNeo\0' or
            prop('/sound', 'simple-audio-card,pin-switches') != b'Speaker\0' or
            prop('/speaker-amplifier', 'sound-name-prefix') != b'Speaker Amp\0'):
        raise ValueError('Unexpected named card/speaker controls')
    expected = ['Left DAC', 'DACL', 'Right DAC', 'DACR', 'Speaker Amp INL', 'HP',
                'Speaker Amp INR', 'HP', 'Speaker', 'Speaker Amp OUTL', 'Speaker', 'Speaker Amp OUTR']
    if prop('/sound', 'simple-audio-card,routing') != ('\0'.join(expected) + '\0').encode():
        raise ValueError('Speaker must use the board AC-coupled stereo route')
    aux = prop('/sound', 'simple-audio-card,aux-devs')
    if aux != (prop('/soc/prcm@1f01400/codec-analog', 'phandle') +
               prop('/speaker-amplifier', 'phandle')):
        raise ValueError('Missing analogue codec or speaker auxiliary component')


def main():
    import libfdt
    root = Path(__file__).resolve().parents[1]
    if json.loads((root / 'build/sources.lock.json').read_text()).get('features', {}).get('speaker_audio') is not True:
        return
    data = Path(sys.argv[1]).read_bytes()
    verify(libfdt.Fdt(data))
    changes = [('/soc/codec@1c22e00', 'status', b'disabled\0'),
               ('/sound', 'simple-audio-card,routing', b'Speaker\0HP\0'),
               ('/speaker-amplifier', 'enable-gpios', struct.pack('>IIII', 0, 0, 4, 0)),
               ('/speaker-amplifier', 'VCC-supply', struct.pack('>I', 0)),
               ('/sound', 'simple-audio-card,aux-devs', struct.pack('>I', 0))]
    for path, name, value in changes:
        tree = libfdt.Fdt(data)
        tree.resize(len(data) + 1024)
        tree.setprop(tree.path_offset(path), name, value)
        try:
            verify(tree)
        except ValueError:
            continue
        raise ValueError('Speaker negative control unexpectedly passed: ' + name)
    print('Compiled speaker card/route/PL3/supply checks passed; five negative controls rejected')


if __name__ == '__main__':
    main()
