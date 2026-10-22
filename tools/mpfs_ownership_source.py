"""Pinned MPFS acquisition/removal and the actual platform ownership helpers."""
import re
import subprocess
import tarfile

from kernel_candidates import candidate_paths

MPFS = 'drivers/usb/musb/mpfs.c'
PHY = 'drivers/usb/phy/phy-generic.c'
PLATFORM = 'drivers/base/platform.c'
FILES = (MPFS, PHY, PLATFORM)


def function(source, name):
    match = re.search(r'^(?:static )?(?:int|void|struct platform_device \*)\s*' +
                      re.escape(name) + r'\([^;{]*\)\n\{', source, re.M)
    if not match:
        raise ValueError('Missing actual MPFS ownership function: ' + name)
    return source[match.start():source.index('\n}', match.end()) + 3] + '\n'


def once(source, before, after):
    if source.count(before) != 1:
        raise ValueError('Changed MPFS ownership source anchor: ' + before)
    return source.replace(before, after, 1)


def prepare(root, archive, lock, directory):
    prefix = 'linux-' + lock['linux']['tag'][1:] + '/'
    originals = {}
    with tarfile.open(archive, 'r|xz') as stream:
        for member in stream:
            name = member.name.removeprefix(prefix)
            if name in FILES:
                originals[name] = stream.extractfile(member).read().decode()
    if set(originals) != set(FILES):
        raise ValueError('Pinned MPFS/platform/PHY ownership source is incomplete')
    paths = {name: directory / name for name in FILES}
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(originals[name])
    patches = []
    for patch in sorted([*(root / 'kernel/patches').glob('*.patch'),
                         *candidate_paths(root, 'musb-retirement')], key=lambda p: p.name):
        chunks = re.split(r'(?=^diff --git )', patch.read_text(), flags=re.M)
        selected = [chunk for chunk in chunks
                    if any(chunk.startswith('diff --git a/' + name + ' ') for name in FILES)]
        if selected:
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], cwd=directory,
                           input=''.join(selected), text=True, check=True)
            patches.append(patch)
    return paths, patches, originals


def declarations(mpfs):
    start = mpfs.index('struct mpfs_glue {')
    return mpfs[start:mpfs.index('\n};', start) + 4] + '\n'


def functions(sources):
    return ''.join(function(sources[name], symbol) for name, symbol in (
        (PLATFORM, 'platform_device_put'), (PLATFORM, 'platform_device_del'),
        (PLATFORM, 'platform_device_unregister'), (PHY, 'usb_phy_generic_register'),
        (PHY, 'usb_phy_generic_unregister'), (MPFS, 'mpfs_probe'), (MPFS, 'mpfs_remove')))


def variants(body, original):
    remove = function(body, 'mpfs_remove')
    child = '\tplatform_device_unregister(glue->musb);\n'
    clock = '\tclk_disable_unprepare(glue->clk);\n'
    early = once(remove, clock, '')
    early = once(early, child, clock + child)
    return {
        'candidate': body,
        'original': once(body, remove, function(original, 'mpfs_remove')),
        'clock-before-child': once(body, remove, early),
        'unregister-parent': once(body, remove, once(remove,
            '\tusb_phy_generic_unregister(glue->phy);', '\tusb_phy_generic_unregister(pdev);')),
        'leak-owned-phy': once(body, remove, once(remove,
            '\tusb_phy_generic_unregister(glue->phy);\n', '')),
    }
