#!/usr/bin/env python3
"""Compare two isolated ARM kernels; never replace the completed image stage."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from build_preflight import GIB, check_space, filesystem
from kernel_checks import ROOT, archive_for, compile_objects, sha256
from kernel_sources import atomic_json, inventory, locked

FRAGMENT = 'kernel/candidates/cpi31-no-ethernet.config'
OVERRIDES = ('CONFIG_SUN4I_EMAC=n', 'CONFIG_STMMAC_ETH=n')
DTB = 'arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dtb'
KEEP = ('CONFIG_BRCMFMAC', 'CONFIG_BRCMFMAC_SDIO', 'CONFIG_MMC_SUNXI',
        'CONFIG_USB_MUSB_HDRC', 'CONFIG_USB_MUSB_SUNXI', 'CONFIG_USB_MUSB_GADGET',
        'CONFIG_USB_GADGET', 'CONFIG_USB_CONFIGFS', 'CONFIG_USB_CONFIGFS_ECM',
        'CONFIG_USB_U_ETHER', 'CONFIG_USB_F_ECM', 'CONFIG_PHY_SUN4I_USB')
REMOVALS = {'CONFIG_'+name for name in ('SUN4I_EMAC', 'STMMAC_ETH', 'STMMAC_PLATFORM',
            'DWMAC_GENERIC', 'DWMAC_SUNXI', 'DWMAC_SUN8I', 'DWMAC_SUN55I', 'MII', 'MDIO_BUS_MUX')}
BOUNDARIES = ('_text', '_stext', '_etext', '__init_begin', '__init_end',
              '__bss_start', '__bss_stop', '_end')


def symbol_layout(path):
    boundaries = {}; sizes = Counter(); addresses = []
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) not in (3, 4):
            continue
        if fields[-1] in BOUNDARIES:
            boundaries[fields[-1]] = int(fields[0], 16)
        if len(fields) == 4 and fields[2] in ('b', 'B'):
            sizes[(fields[3], int(fields[1], 16))] += 1
            addresses.append(int(fields[0], 16))
    if set(boundaries) != set(BOUNDARIES) or not addresses or boundaries['_end'] <= boundaries['_stext']:
        raise ValueError('Kernel layout symbols missing or invalid')
    positions = [boundaries[name] for name in BOUNDARIES]
    if positions != sorted(positions) or min(addresses) < boundaries['__bss_start'] or \
            max(addresses) >= boundaries['__bss_stop']:
        raise ValueError('Kernel layout boundaries are inconsistent')
    return dict(boundaries=boundaries, first_sized_bss_symbol=min(addresses),
                kernel_address_span=boundaries['_end']-boundaries['_stext'],
                bss_symbol_sizes=[[name, size, count] for (name, size), count in sorted(sizes.items())])


def comparison_space(work):
    _, free, existing = filesystem(work)
    required = 12*GIB  # Two 6 GiB planning allowances; not a reservation/peak guarantee.
    if free < required:
        raise ValueError('Insufficient paired-kernel headroom: 12 GiB required at '+existing)
    return dict(path=existing, free_bytes=free, required_bytes=required)


def config_values(path):
    return dict(re.findall(r'^(CONFIG_\w+)=(.*)$', path.read_text(), re.M))


def compare_configs(before, after):
    for name in KEEP:
        if before.get(name) not in ('y', 'm') or after.get(name) != before[name]:
            raise ValueError('Required network support changed: '+name)
    for assignment in OVERRIDES:
        name, value = assignment.split('=')
        if before.get(name) != 'y' or after.get(name, 'n') != value:
            raise ValueError('Expected enabled baseline and disabled candidate: '+name)
    changes = {name: [before.get(name, 'n'), after.get(name, 'n')]
            for name in sorted(before.keys() | after.keys())
            if before.get(name, 'n') != after.get(name, 'n')}
    if any(name not in REMOVALS or values != ['y', 'n'] for name, values in changes.items()):
        raise ValueError('Unaudited configuration change')
    return changes


def validate_pair(before, after):
    a, b = before['compile'], after['compile']
    if a['scratch'] == b['scratch'] or a['config_sha256'] == b['config_sha256']:
        raise ValueError('Expected different configuration and output directories')
    if a['shared_source'] != b['shared_source'] or a['builder'] != b['builder'] or \
            before['compiler_sha256'] != after['compiler_sha256']:
        raise ValueError('Source or compiler differs between kernels')
    if before['files'][DTB] != after['files'][DTB]:
        raise ValueError('Board DTB changed between configurations')
    modules = [{name: value for name, value in record['files'].items() if name.endswith('.ko')}
               for record in (before, after)]
    if not modules[0] or modules[0] != modules[1]:
        raise ValueError('Built module inventory or bytes changed')
    return len(modules[0])


def inspect_dtb(path, source):
    import libfdt  # Only the digest-pinned builder needs this dependency.
    tree = libfdt.Fdt(path.read_bytes())
    files = ['drivers/net/ethernet/allwinner/sun4i-emac.c'] + [
        'drivers/net/ethernet/stmicro/stmmac/'+name+'.c'
        for name in ('dwmac-generic', 'dwmac-sunxi', 'dwmac-sun8i', 'dwmac-sun55i')]
    compatible = set()
    for name in files:
        compatible.update(re.findall(r'\.compatible\s*=\s*"([^"]+)"', (source/name).read_text()))
    if len(compatible) < 10:
        raise ValueError('Ethernet match-table extraction is incomplete')
    nodes = []
    def prop(offset, name):
        try:
            return bytes(tree.getprop(offset, name)).rstrip(b'\0').decode().split('\0')
        except libfdt.FdtException as error:
            if error.err != -libfdt.NOTFOUND: raise
            return []
    def walk(offset):
        matches = prop(offset, 'compatible')
        if compatible.intersection(matches):
            raise ValueError('Board contains a target Ethernet compatible')
        nodes.append(dict(name=tree.get_name(offset), compatible=matches))
        try:
            child = tree.first_subnode(offset)
            while True:
                walk(child); child = tree.next_subnode(child)
        except libfdt.FdtException as error:
            if error.err != -libfdt.NOTFOUND: raise
    walk(0)
    present = {c for node in nodes for c in node['compatible']}
    if not {'clockwork,clockworkpi-cpi3', 'allwinner,sun8i-a33',
            'brcm,bcm4329-fmac', 'allwinner,sun8i-a33-musb'}.issubset(present):
        raise ValueError('Expected CPI network bindings missing')
    return dict(nodes=len(nodes), ethernet_matches=0, target_compatibles=sorted(compatible),
                match_sources={name:sha256(source/name) for name in files})


def full_build(record, lock, destination):
    scratch = ROOT/record['scratch']; source = ROOT/record['shared_source']['path']
    builder = lock['builder']
    subprocess.run(['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
        '--platform', builder['platform'], '--entrypoint', 'bash', '-v', f'{ROOT}:/project',
        '-v', f'{source}:/kernel-source:ro', '-e', 'ARCH=arm',
        '-e', 'CROSS_COMPILE='+builder['cross_compile'],
        '-e', 'LOCALVERSION='+lock['linux']['localversion'],
        '-e', 'KBUILD_BUILD_USER=gameshellneo', '-e', 'KBUILD_BUILD_HOST=builder',
        '-e', 'KBUILD_BUILD_VERSION=1', '-e', 'KBUILD_BUILD_TIMESTAMP=Thu Jan 1 00:00:00 UTC 1970',
        '-e', 'NEO_COMPARE_OUTPUT=/project/'+record['scratch']+'/output',
        builder['image'], '-c',
        'set -euo pipefail\n'
        'make -C /kernel-source O="$NEO_COMPARE_OUTPUT" -j1 zImage modules allwinner/sun8i-r16-clockworkpi-cpi3.dtb\n'
        '"${CROSS_COMPILE}size" "$NEO_COMPARE_OUTPUT/vmlinux" > "$NEO_COMPARE_OUTPUT/size.txt"\n'
        '"${CROSS_COMPILE}nm" -S --defined-only "$NEO_COMPARE_OUTPUT/vmlinux" > "$NEO_COMPARE_OUTPUT/symbols.txt"\n'
        '"${CROSS_COMPILE}readelf" -SW "$NEO_COMPARE_OUTPUT/vmlinux" > "$NEO_COMPARE_OUTPUT/sections.txt"\n'
        'export PYTHONPATH=/armbian-pip/base/lib/python3.13/site-packages\n'
        'python3 /project/tools/check-ethernet-config.py --dtb "$NEO_COMPARE_OUTPUT/'+DTB+'" '
        '--source /kernel-source > "$NEO_COMPARE_OUTPUT/network-dtb.json"\n'
        'python3 /project/tools/tests/ethernet_dtb_controls.py --dtb "$NEO_COMPARE_OUTPUT/'+DTB+'" '
        '--source /kernel-source > "$NEO_COMPARE_OUTPUT/dtb-controls.json"\n'], check=True)
    output = scratch/'output'
    if sha256(output/'.config') != record['config_sha256']:
        raise ValueError('Configuration changed during full kernel build')
    destination.mkdir()
    files = {}
    for name in ('.config', 'vmlinux', 'System.map', 'arch/arm/boot/zImage', DTB,
                 'network-dtb.json', 'dtb-controls.json', 'size.txt', 'modules.order', 'symbols.txt', 'sections.txt'):
        path = output/name; target = destination/Path(name).name
        shutil.copyfile(path, target)
        files[name] = dict(sha256=sha256(target), bytes=target.stat().st_size)
    modules = {Path(name).with_suffix('.ko') for name in (output/'modules.order').read_text().splitlines()}
    if not modules or any(path.is_absolute() or '..' in path.parts for path in modules):
        raise ValueError('Invalid or empty built module order')
    if modules != {path.relative_to(output) for path in output.rglob('*.ko')}:
        raise ValueError('Module outputs differ from Kbuild order')
    for name in sorted(modules):
        path = output/name; target = destination/'modules'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        files[str(name)] = dict(sha256=sha256(target), bytes=target.stat().st_size)
    fields = (output/'size.txt').read_text().splitlines()[1].split()
    size = dict(zip(('text', 'data', 'bss'), map(int, fields[:3])))
    return dict(compile=record, files=files, elf_size=size,
                layout=symbol_layout(output/'symbols.txt'),
                dtb=json.loads((output/'network-dtb.json').read_text()),
                dtb_controls=json.loads((output/'dtb-controls.json').read_text()),
                compiler_sha256=sha256(scratch/'compiler.txt'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dtb', type=Path); parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    if args.dtb:
        if not args.source: parser.error('--dtb requires --source')
        print(json.dumps(inspect_dtb(args.dtb, args.source), indent=2)); return
    os.umask(0o077)
    values = tuple(line for line in (ROOT/FRAGMENT).read_text().splitlines() if line.startswith('CONFIG_'))
    if values != OVERRIDES:
        raise ValueError('Candidate must contain only the two audited overrides')
    lock = json.loads((ROOT/'build/sources.lock.json').read_text())
    check_space(ROOT, 'kernel', lock)
    work = ROOT/'.local/build/ethernet-config-tests'
    storage = comparison_space(work)
    work.mkdir(parents=True, exist_ok=True)
    with locked(work/'.lock'):
        destination = work/('run-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
        destination.mkdir()
        print('Private Ethernet comparison:', destination, flush=True)
        inputs = {name:sha256(ROOT/name) for name in (FRAGMENT, 'kernel/gameshellneo.config',
                  'build/sources.lock.json', 'tools/check-ethernet-config.py', 'tools/kernel_checks.py',
                  'tools/kernel_sources.py', 'tools/kernel-inputs.py', 'tools/build_preflight.py',
                  'tools/tests/ethernet_dtb_controls.py')}
        records = []
        for label, overrides in (('baseline', ()), ('candidate', OVERRIDES)):
            print(label+': building isolated configuration', flush=True)
            record = compile_objects(archive_for(lock), lock, work,
                ['drivers/usb/gadget/function/f_ecm.o', 'drivers/net/wireless/broadcom/brcm80211/brcmfmac/sdio.o'],
                extra_config=overrides)
            if records:
                compare_configs(config_values(destination/'baseline/.config'),
                                config_values(ROOT/record['scratch']/'output/.config'))
            source = ROOT/record['shared_source']['path']; original = inventory(source)
            records.append(full_build(record, lock, destination/label))
            if inventory(source) != original:
                raise ValueError('Shared source changed during comparison')
        before, after = records
        unchanged_modules = validate_pair(before, after)
        baseline_symbols = (destination/'baseline/System.map').read_text()
        candidate_symbols = (destination/'candidate/System.map').read_text()
        for name in ('emac_probe', 'stmmac_dvr_probe'):
            if not re.search(r'\s'+name+r'$', baseline_symbols, re.M) or re.search(r'\s'+name+r'$', candidate_symbols, re.M):
                raise ValueError('Expected linked driver removal was not observed: '+name)
        if any(sha256(ROOT/name) != digest for name, digest in inputs.items()):
            raise ValueError('Comparison inputs changed during execution')
        summary = dict(passed=True, baseline=before, candidate=after, inputs=inputs,
            storage=storage, unchanged_modules=unchanged_modules,
            config_changes=compare_configs(config_values(destination/'baseline/.config'), config_values(destination/'candidate/.config')),
            zimage_bytes_removed=before['files']['arch/arm/boot/zImage']['bytes']-after['files']['arch/arm/boot/zImage']['bytes'],
            elf_bytes_removed={name:before['elf_size'][name]-after['elf_size'][name] for name in before['elf_size']},
            limits='Offline paired kernels only. No image, hardware, boot-time or energy qualification.')
        atomic_json(destination/'comparison.json', summary)
        print('Offline Ethernet comparison passed:', summary['zimage_bytes_removed'], 'zImage bytes removed', flush=True)


if __name__ == '__main__':
    main()
