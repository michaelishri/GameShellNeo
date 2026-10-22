"""Test-only platform fixtures around the complete actual MPFS backend."""
import difflib
import re
import subprocess
import tarfile

from kernel_candidates import candidate_paths
from mpfs_ownership_source import MPFS, function, once, prepare
from musb_restart_kunit import checked_cases as checked_report

CASES = ('mpfs_owned_phy_test', 'mpfs_held_child_test', 'mpfs_original_control_test')
LIMITS = ('Complete actual MPFS remove and real Linux platform parent/child driver cleanup, '
          'generic-PHY unregister and common-clock APIs, with a held child remove under UML '
          'KASAN/lockdep. Acquisition is a synthetic fixture; clock provider state is a seam. '
          'Original wrong-parent unregister is intercepted to avoid recursive unbinding. '
          'No MMIO, MUSB client IRQ/DMA/timer graph, SMP or physical MPFS qualification.')


def checked_cases(report, log):
    return checked_report(report, log, suite_name='mpfs-ownership', expected_cases=CASES)


def test_patch(root, archive, lock, directory):
    paths, _, raw = prepare(root, archive, lock, directory)
    original = paths[MPFS].read_text()
    remove = function(original, 'mpfs_remove')
    hook = '''#ifdef CONFIG_MPFS_OWNERSHIP_KUNIT_TEST
static void mpfs_test_phy_unregister(struct platform_device *pdev);
#define mpfs_unregister_phy mpfs_test_phy_unregister
#else
#define mpfs_unregister_phy usb_phy_generic_unregister
#endif

'''
    modified = once(remove, 'usb_phy_generic_unregister(glue->phy);',
                    'mpfs_unregister_phy(glue->phy);')
    changed = once(original, remove, hook + modified)
    baseline = function(raw[MPFS], 'mpfs_remove')
    baseline = once(baseline, 'mpfs_remove(', 'mpfs_original_remove(')
    baseline = once(baseline, 'usb_phy_generic_unregister(pdev);', 'mpfs_unregister_phy(pdev);')
    changed += ('\n#ifdef CONFIG_MPFS_OWNERSHIP_KUNIT_TEST\n' + baseline +
                '\n#include "mpfs-ownership-kunit.c"\n#endif\n')
    config_file = 'drivers/usb/musb/Kconfig'
    target = directory / config_file
    with tarfile.open(archive, 'r|xz') as stream:
        expected = 'linux-' + lock['linux']['tag'][1:] + '/' + config_file
        for member in stream:
            if member.name == expected:
                target.write_bytes(stream.extractfile(member).read())
                break
        else:
            raise ValueError('Pinned MUSB Kconfig is absent')
    for patch in sorted([*(root / 'kernel/patches').glob('*.patch'),
                         *candidate_paths(root, 'musb-retirement')], key=lambda p: p.name):
        chunks = re.split(r'(?=^diff --git )', patch.read_text(), flags=re.M)
        selected = [part for part in chunks if part.startswith('diff --git a/' + config_file + ' ')]
        if selected:
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], cwd=directory,
                           input=''.join(selected), text=True, check=True)
    config = target.read_text()
    config_changed = config + '''
config MPFS_OWNERSHIP_KUNIT_TEST
	bool "MPFS resource lifetime tests (isolated test kernel only)"
	depends on KUNIT=y && USB_MUSB_POLARFIRE_SOC=y
'''
    replacements = {MPFS: (original, changed), config_file: (config, config_changed),
                    'drivers/usb/musb/mpfs-ownership-kunit.c':
                    ('', (root / 'kernel/tests/mpfs-ownership-kunit.c').read_text())}
    patch = ''.join(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        for name, (before, after) in replacements.items())
    return '9999-mpfs-ownership-test-only.patch', patch.encode()
