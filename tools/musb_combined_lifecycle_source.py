"""Source admission for joined tests of the unchanged terminal-wake queue."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

from kernel_sources import digest, inventory, real_directory, real_file, source_spec
from musb_terminal_wake_source import once, queue_for


PROFILE = 'musb-terminal-wake'
SPEC_SHA256 = '1ce7fd6a292db3d116efda91014bf5cf85ab8999d87b910ae363887b1c99bfca'
TREE_SHA256 = 'cefbf14db681303831ff3edfd710e98c5d90eb2104567b0ca0c5d48b08345047'
CORE = 'drivers/usb/musb/musb_core.c'
GADGET = 'drivers/usb/musb/musb_gadget.c'
SUNXI = 'drivers/usb/musb/sunxi.c'
PHY = 'drivers/phy/allwinner/phy-sun4i-usb.c'
FILES = (CORE, GADGET, SUNXI, PHY, 'drivers/usb/musb/musb_core.h',
         'drivers/usb/musb/Kconfig', 'drivers/phy/allwinner/Kconfig',
         'include/linux/pm_runtime.h', 'kernel/irq/manage.c')

CASES = (
    'combined_policy_disabled_remove_test', 'combined_policy_enabled_remove_test',
    'combined_shared_peer_rebind_test', 'combined_startup_pm_error_test',
    'combined_phy_init_error_test', 'combined_foreign_wakeup_probe_error_test',
    'combined_dpm_arm_error_remove_test', 'combined_dpm_late_error_remove_test',
    'combined_resume_debt_remove_test', 'combined_held_notifier_remove_test',
    'combined_held_work_remove_test', 'combined_held_irq_remove_test',
    'combined_detector_exit_rebind_test', 'combined_closed_producer_rebind_test',
)
CONTROLS = {
    'terminal-wake-cleanup': (CASES[1], ('wakeup_initialized', 'wakeup_capability', 'wakeup_source')),
    'sunxi-work-disable': (CASES[0], ('late_work_queue',)),
}
LIMITS = (
    'Unchanged terminal45 queue; native framework/hardware effects are modeled. '
    'Linux qualification starts at actual controller initialization after synthetic '
    'mapping and uses real UDC, device-DPM/globalIRQ, runtime-PM, IRQ/source, '
    'extcon/SRCU, work and generic-PHY ownership with simulated hardware. '
    'No full OF parent/resource mapping, physical ISR, complete provider/backend '
    'graph, failed-power recovery, DMA, SMP, image, board or clock-clearance claim.'
)


def function(source, name):
    match = re.search(r'^(?:static\s+)?(?:inline\s+)?(?:void|int|bool|irqreturn_t)\s+' +
                      re.escape(name) + r'\([^;{]*\)\n\{', source, re.M)
    if not match:
        raise ValueError('Missing joined lifecycle function: ' + name)
    return source[match.start():source.index('\n}', match.end()) + 2] + '\n'


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def queue(root):
    """Fail when a changing profile would relabel the fixed qualified source."""
    selected = queue_for(root, PROFILE)
    manifest = [dict(name=name, sha256=hashlib.sha256(data).hexdigest())
                for name, data in selected]
    lock = json.loads((root / 'build/sources.lock.json').read_text())
    spec = source_spec(lock, manifest)
    if len(selected) != 45 or digest(spec) != SPEC_SHA256:
        raise ValueError('Joined qualification requires the exact terminal45 specification')
    return selected, spec


def verified_source(root, path):
    """Read an explicitly supplied, complete immutable non-test source only."""
    path = Path(path).absolute()
    real_directory(path)
    real_directory(path.parent)
    if path.name != 'source' or path.parent.name != 'source-' + SPEC_SHA256:
        raise ValueError('Expected the exact non-test terminal45 source entry')
    if {entry.name for entry in path.parent.iterdir()} != {'source', 'metadata.json'}:
        raise ValueError('Unexpected shared-source entry contents')
    metadata_path = path.parent / 'metadata.json'
    real_file(metadata_path)
    before = metadata_path.read_bytes()
    metadata = json.loads(before)
    _, spec = queue(root)
    if metadata != dict(spec=spec, tree_sha256=TREE_SHA256):
        raise ValueError('Wrong qualified source metadata')
    entries = inventory(path)
    if digest(entries) != TREE_SHA256 or metadata_path.read_bytes() != before:
        raise ValueError('Qualified source inventory changed')
    if json.loads((path / '.gameshellneo-patches.json').read_text()) != spec['patches']:
        raise ValueError('Qualified source queue stamp changed')
    texts = {}
    for name in FILES:
        file = path / name
        real_file(file)
        if file.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Unexpected joined source member size: ' + name)
        texts[name] = file.read_text()
    return texts, dict(path=str(path), **metadata,
                       files={name: sha256(path / name) for name in FILES})


def control_functions(core, sunxi):
    """Named compiling copies: one omitted operation in each ownership path."""
    release = function(core, 'musb_free_irq')
    release = once(release, '\tmusb_cleanup_wakeup(musb);\n', '')
    copies = [release]
    for name in ('musb_shutdown_irq', 'musb_free', 'musb_remove'):
        copies.append(function(core, name))
    renamed = '\n'.join(copies)
    # Rename declarations and their internal calls, leaving every other token.
    for name in ('musb_free_irq', 'musb_shutdown_irq', 'musb_free', 'musb_remove'):
        renamed = re.sub(r'\b' + name + r'\b', 'control_' + name, renamed)
    exit_body = function(sunxi, 'sunxi_musb_exit')
    exit_body = once(exit_body, '\tdisable_work_sync(&glue->work);\n', '')
    exit_body = once(exit_body, 'sunxi_musb_exit(', 'control_sunxi_musb_exit(')
    return renamed + '\n' + exit_body


def native_functions(texts):
    """Project complete function bodies; model only called boundary APIs."""
    names = {
        'include/linux/pm_runtime.h': ('pm_runtime_get_active', 'pm_runtime_resume_and_get'),
        'kernel/irq/manage.c': ('set_irq_wake_real', 'irq_set_irq_wake'),
        PHY: ('sun4i_usb_phy_init', 'sun4i_usb_phy_exit', 'sun4i_usb_phy_set_mode',
              'sun4i_usb_phy0_id_vbus_det_scan', 'sun4i_usb_phy0_id_vbus_det_irq'),
        SUNXI: ('sunxi_musb_work', 'sunxi_musb_host_notifier', 'sunxi_musb_init',
                'sunxi_musb_exit', 'sunxi_musb_enable', 'sunxi_musb_disable',
                'sunxi_musb_set_mode', 'sunxi_musb_recover'),
        CORE: ('musb_start', 'musb_disarm_wake', 'musb_init_wakeup', 'musb_cleanup_wakeup',
               'musb_free_irq', 'musb_shutdown_irq', 'musb_shutdown_work',
               'musb_disable_runtime_pm', 'musb_release_session', 'musb_free',
               'musb_init_roles', 'musb_init_controller', 'musb_remove',
               'musb_suspend', 'musb_resume'),
        GADGET: ('musb_gadget_start',),
    }
    bodies = []
    pins = {}
    for file, functions in names.items():
        for name in functions:
            body = function(texts[file], name)
            bodies.append(body)
            pins[file + ':' + name] = hashlib.sha256(body.encode()).hexdigest()
    bodies.append(control_functions(texts[CORE], texts[SUNXI]))
    return '\n'.join(bodies), pins


def production_manifest(root):
    spec = importlib.util.spec_from_file_location('combined_kernel_inputs', root / 'tools/kernel-inputs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [dict(name=name, sha256=hashlib.sha256(data).hexdigest())
            for name, data in module.patches()]
