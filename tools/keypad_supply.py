"""Build/verify the single-property keypad supply experiment using pinned dtc tools."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile

DTB = 'sun8i-r16-clockworkpi-cpi3.dtb'
BASE_DTB = 'sun8i-r16-clockworkpi-cpi3-power-off.dtb'
NODE = '/regulator-keypad'
PROPERTY = 'regulator-always-on'


def enabled(lock):
    experiments = lock.get('experiments', {})
    value = experiments.get('keypad_supply_retention', False)
    if type(value) is not bool or ('keypad_supply_retention' in experiments and
            (value is not True or experiments != {
                'suspend_diagnostics': True, 'keypad_supply_retention': True} or
             type(experiments.get('suspend_diagnostics')) is not bool)):
        raise ValueError('Keypad retention requires a dedicated suspend diagnostic image')
    return value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get(path, node, name, kind='s'):
    return subprocess.check_output(['fdtget', '-t', kind, str(path), node, name], text=True).strip()


def canonical(path):
    return subprocess.check_output(['dtc', '-q', '-s', '-I', 'dtb', '-O', 'dts', str(path)])


def verify(base, retained):
    # Anchor the modification to this board's existing 5 V, active-high PL2 supply.
    properties = subprocess.check_output(['fdtget', '-p', str(base), NODE], text=True).splitlines()
    if (PROPERTY in properties or get(base, NODE, 'compatible') != 'regulator-fixed' or
            get(base, NODE, 'regulator-name') != 'keypad-vbus' or
            get(base, NODE, 'regulator-min-microvolt', 'u') != '5000000' or
            get(base, NODE, 'regulator-max-microvolt', 'u') != '5000000' or
            get(base, NODE, 'enable-active-high', 'x') != ''):
        raise ValueError('Unexpected baseline keypad regulator')
    pio = get(base, '/soc/pinctrl@1f02c00', 'phandle', 'x')
    if get(base, NODE, 'gpio', 'x').split() != [pio, '0', '2', '0']:
        raise ValueError('Keypad supply must use active-high PL2')
    if (get(base, '/soc/phy@1c19400', 'usb1_vbus-supply', 'x') !=
            get(base, NODE, 'phandle', 'x')):
        raise ValueError('Unexpected internal USB supply binding')
    if get(retained, NODE, PROPERTY, 'x') != '':
        raise ValueError('Retention property must be an empty boolean')
    # Compare every node/property after removing exactly the allowed addition.
    # dtc sorting ignores string-table layout and serialization padding only.
    with tempfile.TemporaryDirectory() as directory:
        restored = Path(directory) / 'restored.dtb'
        shutil.copyfile(retained, restored)
        subprocess.run(['fdtput', '-d', str(restored), NODE, PROPERTY], check=True)
        if canonical(base) != canonical(restored):
            raise ValueError('Retention DTB changes more than the keypad supply property')
    return dict(policy='retain-keypad-supply', property=NODE + '/' + PROPERTY,
                baseline_sha256=digest(base), installed_sha256=digest(retained),
                semantic_difference='only the empty regulator-always-on property',
                hardware_qualified=False)


def prepare(base, retained):
    shutil.copyfile(base, retained)
    subprocess.run(['fdtput', '-t', 'x', str(retained), NODE, PROPERTY], check=True)
    return verify(base, retained)


def verify_image(boot, identity, expected_base):
    retained = enabled(identity['sources'])
    installed = boot / DTB
    if not retained:
        if 'keypad_supply' in identity or (boot / BASE_DTB).exists() or digest(installed) != expected_base:
            raise ValueError('Unexpected keypad supply experiment or installed DTB')
        return
    base = boot / BASE_DTB
    if digest(base) != expected_base or verify(base, installed) != identity.get('keypad_supply'):
        raise ValueError('Keypad supply identity/baseline mismatch')
