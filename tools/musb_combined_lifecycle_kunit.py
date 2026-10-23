"""Disposable joined lifecycle view of the exact, immutable terminal45 source."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil

from kernel_sources import digest, inventory, real_file, source_spec
from musb_combined_lifecycle_source import (
    CASES, CORE, PHY, SPEC_SHA256, SUNXI, TREE_SHA256, control_functions,
    function, queue, sha256, verified_source,
)
from musb_terminal_wake_source import once

CONFIG = 'CONFIG_MUSB_COMBINED_LIFECYCLE_KUNIT_TEST'
KCONFIG = 'drivers/usb/musb/Kconfig'
STAMP = '.gameshellneo-patches.json'
TARGETS = (CORE, SUNXI, PHY, KCONFIG, STAMP)
PATCH_NAME = '9999-musb-combined-lifecycle-test-only.patch'
SUITES = {
    'positive': ('musb-combined-lifecycle', CASES),
    'terminal-control': ('musb-combined-terminal-control', (CASES[1],)),
    'work-control': ('musb-combined-work-control', (CASES[0],)),
}
HARD_CAP = 384 * 1024**2
FLOOR = 3 * 1024**3
HEADROOM = 128 * 1024**2


def guarded(text):
    return '\n#ifdef ' + CONFIG + '\n' + text + '\n#endif\n'


def _fragment(root, name, header):
    path = root / 'kernel/tests' / name
    real_file(path)
    if path.stat().st_size > 256 * 1024:
        raise ValueError('Unexpected joined fixture size: ' + name)
    text = once(path.read_text(), '#include "musb-combined-lifecycle-kunit.h"\n', '')
    return header + '\n' + text


def _aliases(mapping):
    # I/O headers already define self-macros for these function names. Only
    # calls belong to the seam; structure fields and bare addresses must stay
    # intact. All declarations/includes precede this temporary alias scope.
    return ''.join('#undef ' + name + '\n#define ' + name + '(...) ' + value +
                   '(__VA_ARGS__)\n' for name, value in mapping.items())


def _undef(mapping):
    return '\n'.join('#undef ' + name for name in mapping) + '\n'


def _core(root, original, header, controls):
    declaration = '''static int neo_joined_request_irq(unsigned int irq, irq_handler_t handler,
                                 unsigned long flags, const char *name, void *data);
static void neo_joined_irq_retiring(struct musb *musb);
'''
    text = once(original, '#include "musb_trace.h"\n',
                '#include "musb_trace.h"\n' + guarded(declaration))
    # An IRQ delivery seam, not a replacement for action lifetime or IRQ-core APIs.
    call = 'request_irq(nIrq, musb->isr, IRQF_SHARED, dev_name(dev), musb)'
    text = once(text, call, 'neo_joined_request_irq(nIrq, musb->isr, IRQF_SHARED, dev_name(dev), musb)')
    text = once(text, '\tfree_irq(musb->nIrq, musb);\n',
                guarded('\tneo_joined_irq_retiring(musb);') + '\tfree_irq(musb->nIrq, musb);\n')
    # Keep the translation unit usable without selecting this test symbol.
    text = once(text, guarded(declaration), guarded(declaration) +
                '\n#ifndef ' + CONFIG + '\n#define neo_joined_request_irq request_irq\n#endif\n')
    fragment = _fragment(root, 'musb-combined-lifecycle-kunit.c', header)
    fragment = once(fragment, 'NEO_JOINED_CORE_CONTROL_BODIES', controls)
    return text + guarded(fragment)


def _sunxi(root, original, header, control):
    aliases = dict(readb='neo_sunxi_readb', readw='neo_sunxi_readw',
        writeb='neo_sunxi_writeb', writew='neo_sunxi_writew',
        clk_prepare_enable='neo_sunxi_clock_on', clk_disable_unprepare='neo_sunxi_clock_off',
        reset_control_deassert='neo_sunxi_reset_off', reset_control_assert='neo_sunxi_reset_on',
        extcon_register_notifier='neo_sunxi_notifier_register',
        extcon_unregister_notifier_sync='neo_sunxi_notifier_unregister',
        disable_work_sync='neo_sunxi_work_disable')
    declarations = header + '''
static u8 neo_sunxi_readb(void __iomem *address);
static u16 neo_sunxi_readw(void __iomem *address);
static void neo_sunxi_writeb(u8 value, void __iomem *address);
static void neo_sunxi_writew(u16 value, void __iomem *address);
static int neo_sunxi_clock_on(struct clk *clock);
static void neo_sunxi_clock_off(struct clk *clock);
static int neo_sunxi_reset_off(struct reset_control *reset);
static int neo_sunxi_reset_on(struct reset_control *reset);
static int neo_sunxi_notifier_register(struct extcon_dev *edev, unsigned int cable,
                                     struct notifier_block *notifier);
static int neo_sunxi_notifier_unregister(struct extcon_dev *edev, unsigned int cable,
                                       struct notifier_block *notifier);
static bool neo_sunxi_work_disable(struct work_struct *work);
static void neo_sunxi_notifier_enter(struct notifier_block *notifier);
'''
    text = once(original, '#include "musb_core.h"\n',
                '#include "musb_core.h"\n' + guarded(declarations + _aliases(aliases)))
    text = _replace_function(text, 'sunxi_musb_host_notifier',
        '\t/* The worker samples current state, including after child rebind. */',
        guarded('\tneo_sunxi_notifier_enter(nb);') +
        '\t/* The worker samples current state, including after child rebind. */')
    text = once(text, '\tglue->musb = musb;\n', '\tglue->musb = musb;\n' + guarded(
        '\tif (neo_joined_current && neo_joined_current->controller == musb->controller)\n'
        '\t\tneo_joined_current->musb = musb;'))
    fragment = _fragment(root, 'musb-combined-sunxi-kunit.c', header)
    # The copy must still pass through the same hardware observation seams.
    fragment = once(fragment, 'NEO_JOINED_SUNXI_CONTROL_BODY',
                    _aliases(aliases) + control + _undef(aliases))
    return text + guarded(_undef(aliases) + fragment)


def _replace_function(text, name, before, after):
    body = function(text, name)
    changed = once(body, before, after)
    return once(text, body, changed)


def _phy(root, original, header):
    declarations = header + '''
struct sun4i_usb_phy_data;
static struct sun4i_usb_phy_data *neo_phy_data(void);
static void neo_phy_access(struct sun4i_usb_phy_data *data);
static int neo_phy_clock_on(struct clk *clock);
static void neo_phy_clock_off(struct clk *clock);
static void neo_phy_after_notification(struct sun4i_usb_phy_data *data, u64 generation);
static void neo_phy_scan_done(struct sun4i_usb_phy_data *data);
static void neo_phy_after_mode(struct sun4i_usb_phy_data *data);
static int neo_phy_vbus(struct sun4i_usb_phy_data *data);
'''
    aliases = dict(clk_prepare_enable='neo_phy_clock_on', clk_disable_unprepare='neo_phy_clock_off')
    anchor = '#define to_sun4i_usb_phy_data(phy) \\\n\tcontainer_of((phy), struct sun4i_usb_phy_data, phys[(phy)->index])\n'
    text = once(original, anchor, anchor + guarded(declarations + _aliases(aliases)))
    for name, variable, anchor in (
        ('sun4i_usb_phy0_update_iscr', 'data', '\tiscr = readl(data->base + REG_ISCR);'),
        ('sun4i_usb_phy_write', 'phy_data', '\tspin_lock_irqsave(&phy_data->reg_lock, flags);'),
        ('sun4i_usb_phy_passby', 'phy_data', '\tif (!phy->pmu)'),
        ('sun4i_usb_phy0_reroute', 'data', '\tregval = readl(data->base + REG_PHY_OTGCTL);'),
    ):
        hook = guarded('\tif (' + variable + ' == neo_phy_data()) {\n'
                       '\t\tneo_phy_access(' + variable + ');\n\t\treturn;\n\t}')
        text = _replace_function(text, name, anchor, hook + anchor)
    text = _replace_function(text, 'sun4i_usb_phy0_get_vbus_det',
        '\n{\n', '\n{\n' + guarded('\tif (data == neo_phy_data())\n\t\treturn neo_phy_vbus(data);'))
    # The exact A33 shape has no detector GPIO/supply/regulator: its poll result is
    # already false. Keep the real decision and real delayed-work admission.
    body = function(text, 'sun4i_usb_phy_set_mode')
    changed = once(body, '\treturn 0;\n}', guarded('\tneo_phy_after_mode(data);') + '\treturn 0;\n}')
    text = once(text, body, changed)
    text = _replace_function(text, 'sun4i_usb_phy0_id_vbus_det_scan',
        '\t\textcon_set_state_sync(data->extcon, EXTCON_USB_HOST,\n\t\t\t\t\t!id_det);\n',
        '\t\textcon_set_state_sync(data->extcon, EXTCON_USB_HOST,\n\t\t\t\t\t!id_det);\n' +
        guarded('\t\tneo_phy_after_notification(data, generation);'))
    # The marker stays active through the actual post-notification tail, and is
    # cleared at both real exits. A subsequent scan may reuse the same worker.
    text = _replace_function(text, 'sun4i_usb_phy0_id_vbus_det_scan',
        '\t\tif (!data->phy0_init || data->phy0_generation != generation) {\n'
        '\t\t\tmutex_unlock(&phy0->mutex);\n\t\t\treturn;\n\t\t}\n',
        '\t\tif (!data->phy0_init || data->phy0_generation != generation) {\n'
        '\t\t\tmutex_unlock(&phy0->mutex);\n' + guarded('\t\t\tneo_phy_scan_done(data);') +
        '\t\t\treturn;\n\t\t}\n')
    text = _replace_function(text, 'sun4i_usb_phy0_id_vbus_det_scan',
        '\tmutex_unlock(&phy0->mutex);\n}',
        '\tmutex_unlock(&phy0->mutex);\n' + guarded('\tneo_phy_scan_done(data);') + '}')
    # Only the simulated electrical settling effect is skipped. Exit/generation
    # checks, generic-PHY mutex, notifications and work calls are not replaced.
    for delay in (200, 1000):
        text = _replace_function(text, 'sun4i_usb_phy0_id_vbus_det_scan',
            '\t\t\tmsleep(' + str(delay) + ');',
            '#ifdef ' + CONFIG + '\n\t\t\tif (data != neo_phy_data())\n#endif\n'
            '\t\t\t\tmsleep(' + str(delay) + ');')
    return text + guarded(_undef(aliases) + _fragment(root, 'musb-combined-phy-kunit.c', header))


def replacements(root, texts):
    """Return four complete generated files, with strict single source anchors."""
    header = (root / 'kernel/tests/musb-combined-lifecycle-kunit.h').read_text()
    controls = control_functions(texts[CORE], texts[SUNXI])
    marker = 'static int control_sunxi_musb_exit('
    start = controls.index(marker)
    core_control, sunxi_control = controls[:start], controls[start:]
    before = ('config USB_MUSB_SUNXI\n\ttristate "Allwinner (sunxi)"\n'
              '\tdepends on ARCH_SUNXI\n')
    after = before.replace('depends on ARCH_SUNXI',
                           'depends on ARCH_SUNXI || (COMPILE_TEST && KUNIT)')
    kconfig = once(texts[KCONFIG], before, after) + '''
config MUSB_COMBINED_LIFECYCLE_KUNIT_TEST
	bool "Joined MUSB startup/wake/Sunxi lifecycle tests (isolated test only)"
	depends on KUNIT=y && USB_MUSB_HDRC=y && USB_MUSB_SUNXI=y
	depends on USB_MUSB_GADGET && PHY_SUN4I_USB=y && PM_SLEEP && MUSB_PIO_ONLY
	select IRQ_SIM
'''
    return {CORE: _core(root, texts[CORE], header, core_control),
            SUNXI: _sunxi(root, texts[SUNXI], header, sunxi_control),
            PHY: _phy(root, texts[PHY], header), KCONFIG: kconfig}


def generated_view(root, source):
    """No extraction/copy: derive the exact five-file view from admitted45."""
    texts, original = verified_source(root, source)
    changed = replacements(root, texts)
    patch = ''.join(''.join(difflib.unified_diff(texts[name].splitlines(True), data.splitlines(True),
        fromfile='a/' + name, tofile='b/' + name)) for name, data in changed.items()).encode()
    selected, _ = queue(root)
    selected.append((PATCH_NAME, patch))
    manifest = [dict(name=name, sha256=hashlib.sha256(data).hexdigest()) for name, data in selected]
    lock = json.loads((root / 'build/sources.lock.json').read_text())
    spec = source_spec(lock, manifest)
    changed[STAMP] = json.dumps(manifest, sort_keys=True, indent=2) + '\n'
    return {name: data.encode() for name, data in changed.items()}, patch, dict(
        spec=spec, spec_sha256=digest(spec), base=original, targets=list(TARGETS),
        test_append=dict(name=PATCH_NAME, sha256=hashlib.sha256(patch).hexdigest()),
        replacements={name: hashlib.sha256(data.encode()).hexdigest() for name, data in changed.items()},
        kconfig_seam='Only generated46 USB_MUSB_SUNXI dependency adds COMPILE_TEST && KUNIT; original45 unchanged')


def resources(root, work, *, starting=False):
    """Admit the declared budget; never delete or terminate to restore it."""
    used = sum(path.lstat().st_blocks * 512 for path in work.rglob('*') if not path.is_symlink())
    free = shutil.disk_usage(root).free
    reserve = max(0, HARD_CAP - used) if starting else 0
    if used > HARD_CAP or free < FLOOR + HEADROOM + reserve:
        raise RuntimeError('Joined qualification resource floor/cap refused; retain original operation')
    return dict(allocated_bytes=used, free_bytes=free, hard_cap_bytes=HARD_CAP,
                floor_bytes=FLOOR, independent_headroom_bytes=HEADROOM, remaining_reservation_bytes=reserve)


def verify_view(source, expected):
    """Called inside the actual mounted view before compilation/execution."""
    entries = inventory(source)
    if entries != expected:
        raise ValueError('Actual mounted joined source view differs from its complete inventory')
    return dict(tree_sha256=digest(entries), entries=len(entries))


# These are source-backed normal messages from the declared actual failure
# paths. Everything else inside a case is rejected, including parser-preserved
# KUnit warnings. Error-number/IRQ/name fields have bounded semantic values.
DEVICE = r'musb-combined-child musb-combined-child\.0: '
FRAMEWORK_MESSAGES = {
    CASES[3]: [DEVICE + r'error -EIO: musb_init_controller failed',
               r'musb-combined-child musb-combined-child\.0: probe with driver musb-combined-child failed with error -5'],
    CASES[4]: [r'phy phy-musb-combined-parent\.0: phy init failed --> -5',
               DEVICE + r'error -EIO: musb_init_controller failed',
               r'musb-combined-child musb-combined-child\.0: probe with driver musb-combined-child failed with error -5'],
    CASES[5]: [DEVICE + r'error -EEXIST: musb_init_controller failed',
               r'musb-combined-child musb-combined-child\.0: probe with driver musb-combined-child failed with error -17'],
    CASES[6]: [DEVICE + r'wake IRQ [1-9][0-9]* suspend failed: -5',
               DEVICE + r'PM: dpm_run_callback\(\): platform_pm_suspend returns -5',
               DEVICE + r'PM: failed to suspend: error -5'],
    CASES[7]: [DEVICE + r'PM: dpm_run_callback\(\): neo_late returns -5',
               DEVICE + r'PM: failed to suspend late: error -5'],
    CASES[8]: [DEVICE + r'wake IRQ [1-9][0-9]* resume failed: -5',
               DEVICE + r'PM: dpm_run_callback\(\): platform_pm_resume returns -5',
               DEVICE + r'PM: failed to resume: error -5',
               DEVICE + r'wake IRQ [1-9][0-9]* cleanup failed: -5'],
}


def ownership(case, mode):
    source = cap = int(case == CASES[5])
    core = late = 0
    if mode == 'terminal-control':
        core = source = cap = 1
    if mode == 'work-control':
        late = 1
    debt = int(case == CASES[8])
    return f'owned core={core} source={source} cap={cap} late={late} refs=0 debt={debt} bad=0'


def failure_lines(case, expression):
    return [r'# ' + re.escape(case) + r': EXPECTATION FAILED at drivers/usb/musb/musb_core\.c:[1-9][0-9]*',
            re.escape('Expected ' + expression + ' to be false, but is true')]


def diagnostic_contract(mode):
    """Entire ordered KTAP stream, not a list of warning words to ignore."""
    if mode not in SUITES:
        raise ValueError('Unknown joined suite mode')
    suite, cases = SUITES[mode]
    expected = [re.escape(line) for line in (
        'KTAP version 1', '1..1', 'KTAP version 1', '# Subtest: ' + suite,
        '# module: musb_hdrc', '1..' + str(len(cases)))]
    for number, case in enumerate(cases, 1):
        expected.append(re.escape('# ' + case + ': begin joined lifecycle'))
        expected.extend(FRAMEWORK_MESSAGES.get(case, ()))
        if mode == 'terminal-control':
            for expression in ('f->last.wakeup_initialized', 'f->last.capable', 'f->last.source'):
                expected.extend(failure_lines(case, expression))
        elif mode == 'work-control':
            expected.extend(failure_lines(case, 'f->last_late_queue'))
        expected.extend(re.escape(line) for line in (
            '# ' + case + ': ' + ownership(case, mode),
            '# ' + case + ': joined cleanup complete',
            '# ' + case + '.speed: slow',
            ('ok' if mode == 'positive' else 'not ok') + f' {number} {case}'))
    passed, failed = (len(cases), 0) if mode == 'positive' else (0, 1)
    counts = f'pass:{passed} fail:{failed} skip:0 total:{len(cases)}'
    if len(cases) > 1:  # Pinned default kunit.stats_enabled=1.
        expected.extend(re.escape(line) for line in (f'# {suite}: {counts}', f'# Totals: {counts}'))
    expected.extend(re.escape(line) for line in (
        ('ok' if mode == 'positive' else 'not ok') + ' 1 ' + suite, 'reboot: System halted'))
    return expected


def checked_cases(report, log, *, mode):
    suite_name, names = SUITES[mode]
    failed = int(mode != 'positive')
    counts = dict(tests=len(names), passed=len(names) - failed, failed=failed,
                  crashed=0, skipped=0, errors=0)
    if (not isinstance(report, dict) or report.get('name') != 'KUnit Test Group' or
            report.get('arch') != 'um' or report.get('misc') != counts or
            report.get('test_cases') != [] or len(report.get('sub_groups', [])) != 1):
        raise ValueError('Expected complete fresh joined KUnit report')
    suite = report['sub_groups'][0]
    cases = suite.get('test_cases', [])
    if (suite.get('name') != suite_name or suite.get('arch') != 'um' or
            suite.get('misc') != counts or suite.get('sub_groups') != [] or
            tuple(case.get('name') for case in cases) != names or
            any(case.get('status') != ('PASS' if mode == 'positive' else 'FAIL') for case in cases)):
        raise ValueError('Different or incomplete joined lifecycle outcomes')
    # Also reject critical diagnostics emitted before the first KTAP header.
    if re.search(r'WARNING:|BUG:|possible circular locking|suspicious RCU|sleeping function called|'
                 r'Kernel panic|rcu:.*detected .*stalls|INFO: task .*blocked for more than', log):
        raise ValueError('Kernel diagnostic invalidates joined lifecycle observation')
    lines = [line.strip() for line in log.splitlines() if line.strip()]
    try:
        actual = lines[lines.index('KTAP version 1'):]
    except ValueError as error:
        raise ValueError('Missing complete joined KTAP stream') from error
    expected = diagnostic_contract(mode)
    if len(actual) != len(expected) or any(re.fullmatch(pattern, line) is None
            for pattern, line in zip(expected, actual)):
        raise ValueError('Unexpected entire joined per-case diagnostic stream')
    return cases


def terminal_result(result, *, mode):
    """Expected controls require authoritative exit1 and released ownership."""
    wanted = 0 if mode == 'positive' else 1
    if not isinstance(result, dict):
        raise ValueError('Joined execution lacks an authoritative result')
    state = result.get('state') or {}
    if (type(result.get('exit_code')) is not int or type(result.get('returncode')) is not int or
            result.get('outcome') != 'exited' or result.get('exit_code') != wanted or
            result.get('returncode') != wanted or result.get('stop_requested') or
            state.get('Running') is not False or state.get('Status') != 'exited' or
            state.get('ExitCode') != wanted or state.get('OOMKilled') or state.get('Error')):
        raise ValueError('Joined execution lacks the exact authoritative terminal outcome')


def mounted_admission(entry, source, view_directory):
    """Recheck the original and actual five-target Docker view, not just a stamp."""
    expected = json.loads((view_directory / 'base-inventory.json').read_text())
    base = inventory(entry / 'source')
    metadata = json.loads((entry / 'metadata.json').read_text())
    view = json.loads((view_directory / 'view.json').read_text())
    if (base != expected or digest(base) != TREE_SHA256 or
            metadata != dict(spec=view['base']['spec'], tree_sha256=TREE_SHA256) or
            digest(metadata['spec']) != SPEC_SHA256):
        raise ValueError('Original immutable terminal45 source changed')
    wanted = json.loads((view_directory / 'view-inventory.json').read_text())
    observed = verify_view(source, wanted)
    if (observed['tree_sha256'] != view['tree_sha256'] or
            json.loads((source / STAMP).read_text()) != view['spec']['patches']):
        raise ValueError('Joined mounted46 source identity changed')
    return dict(base_tree_sha256=TREE_SHA256, view_tree_sha256=observed['tree_sha256'],
                base_entries=len(base), view_entries=observed['entries'])


def guest(source, kernel, directory, *, mode):
    """One bounded suite, fixed512MiB guest; pinned parser/source remain read-only."""
    import subprocess
    import sys
    from kernel_sources import atomic_json

    suite, _ = SUITES[mode]
    raw = directory / 'test.log'
    report = directory / 'results.json'
    if raw.exists() or report.exists():
        raise ValueError('Fresh guest output required; stale output is never accepted')
    command = [str(kernel), 'mem=512M', 'console=tty', 'kunit_shutdown=halt',
               'kunit.enable=1', 'kunit.stats_enabled=1', 'printk.time=0',
               'kunit.filter_glob=' + suite, 'uml_dir=/uml-tmp/state']
    atomic_json(directory / 'guest-command.json', command)
    before = sha256(kernel)
    with raw.open('xb') as output:
        process = subprocess.run(command, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.STDOUT)
    atomic_json(directory / 'guest-result.json', dict(returncode=process.returncode,
        kernel_sha256=before, kernel_after_sha256=sha256(kernel), raw_log_sha256=sha256(raw)))
    if process.returncode != 0 or sha256(kernel) != before:
        raise RuntimeError('Guest exit/kernel identity is inconclusive; retain the original execution')
    # The pinned kunit.py exec launcher always appends mem=1G. Invoke the same
    # pinned parser directly with explicit UML metadata after our512MiB launch.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source / 'tools/testing/kunit'))
    import kunit
    import kunit_json
    request = kunit.KunitParseRequest(raw_output=None, json=str(report), summary=False, failed=False)
    metadata = kunit_json.Metadata(arch='um', build_dir=str(directory), def_config='kunit_defconfig')
    with raw.open() as data:
        outcome, _ = kunit.parse_tests(request, metadata, data)
    code = 0 if outcome.status == kunit.KunitStatus.SUCCESS else 1
    atomic_json(directory / 'parser-result.json', dict(returncode=code, raw_log_sha256=sha256(raw),
        report_sha256=sha256(report), parser_sha256=sha256(source / 'tools/testing/kunit/kunit.py'),
        limits='Parser result only; complete stream and actual managed ownership checked by host'))
    return code
