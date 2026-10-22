"""Pinned Sun4i detector source slices for offline lifecycle qualification."""
import re
import subprocess
import tarfile

from kernel_candidates import candidate_paths

FILE = 'drivers/phy/allwinner/phy-sun4i-usb.c'
FIX = '0060-sun4i-phy-detector-generation.patch'


def function(source, name):
    match = re.search(r'^static (?:int|void|irqreturn_t) ' + name + r'\([^;{]*\)\n\{', source, re.M)
    if not match:
        raise ValueError('Missing pinned PHY function: ' + name)
    return source[match.start():source.index('\n}', match.end()) + 3] + '\n'


def prepare(root, archive, lock, directory):
    target = directory / FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r|xz') as stream:
        expected = 'linux-' + lock['linux']['tag'][1:] + '/' + FILE
        for member in stream:
            if member.name == expected:
                original = stream.extractfile(member).read().decode()
                target.write_text(original)
                break
        else:
            raise ValueError('Pinned Sun4i PHY source absent')
    selected = []
    for path in sorted([*(root / 'kernel/patches').glob('*.patch'),
                        *candidate_paths(root, 'musb-retirement')], key=lambda item: item.name):
        chunks = re.split(r'(?=^diff --git )', path.read_text(), flags=re.M)
        relevant = [chunk for chunk in chunks if chunk.startswith('diff --git a/' + FILE + ' ')]
        if relevant:
            subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], cwd=directory,
                           input=''.join(relevant), text=True, check=True)
            selected.append(path)
    return target, selected


def functions(source):
    # Generic PHY serializes init/exit on phy->mutex. Hardware preparation is
    # modeled; execute the exact publication from the full init implementation.
    init = function(source, 'sun4i_usb_phy_init')
    publication = '\t\tdata->phy0_generation++;\n\t\tdata->phy0_init = true;\n'
    if init.count(publication) != 1:
        raise ValueError('Missing initialized-generation publication under PHY ownership')
    result = ('static void detector_publish(struct sun4i_usb_phy_data *data)\n{\n' +
              publication + '}\n')
    result += ''.join(function(source, name) for name in (
        'sun4i_usb_phy_exit', 'sun4i_usb_phy0_id_vbus_det_scan',
        'sun4i_usb_phy0_id_vbus_det_irq', 'sun4i_usb_phy0_vbus_notify'))
    return result


def variants(source):
    good = functions(source)
    def changed(old, new, *, count=1):
        if good.count(old) != count:
            raise ValueError('Changed detector test anchor: ' + old)
        return good.replace(old, new)
    return {
        'candidate': good,
        'no-init-publication': changed('\t\tdata->phy0_generation++;\n', ''),
        'no-tail-active-check': changed('!data->phy0_init || data->phy0_generation != generation',
                                        'data->phy0_generation != generation'),
        'no-tail-generation-check': changed('!data->phy0_init || data->phy0_generation != generation',
                                            '!data->phy0_init'),
        'no-tail-lock': changed('\t\tmutex_lock(&phy0->mutex);\n\t\tif (!data->phy0_init ||',
                                '\t\tif (!data->phy0_init ||'),
        'no-poll-admission': changed('data->phy0_init && data->phy0_generation == generation &&\n\t    ', ''),
    }
