"""Generate test-only worker gates, separate from the production patch queue."""
import difflib
import hashlib
import tarfile

CORE = 'drivers/power/supply/power_supply_core.c'
FIX = '0037-power-supply-unregister-producer.patch'


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Power-supply test hook anchor changed: ' + before)
    return text.replace(before, after)


def instrument(core):
    core = replace_once(core, '#include "samsung-sdi-battery.h"',
                        '#include "samsung-sdi-battery.h"\n#include "power-supply-lifetime-hooks.h"')
    core = replace_once(core, '\t\t\t\t\t\tchanged_work);',
                        '\t\t\t\t\t\tchanged_work);\n\n'
                        '\tpsy_lifetime_hook(psy, PSY_CHANGED_ENTER);')
    core = replace_once(core, '\t\t\t\t\t\tdeferred_register_work.work);',
                        '\t\t\t\t\t\tdeferred_register_work.work);\n\n'
                        '\tpsy_lifetime_hook(psy, PSY_DEFER_ENTER);')
    core = replace_once(core, '\t\twhile (!device_trylock(psy->dev.parent)) {',
                        '\t\twhile (!device_trylock(psy->dev.parent)) {\n'
                        '\t\t\tpsy_lifetime_hook(psy, PSY_PARENT_BLOCKED);')
    core = replace_once(core, '\tpower_supply_changed(psy);\n\n\tif (psy->dev.parent)',
                        '\tpsy_lifetime_hook(psy, PSY_DEFER_NOTIFY);\n'
                        '\tpower_supply_changed(psy);\n'
                        '\tpsy_lifetime_hook(psy, PSY_DEFER_QUEUED);\n\n\tif (psy->dev.parent)')
    core = replace_once(core, '\tcancel_delayed_work_sync(&psy->deferred_register_work);',
                        '\tpsy_lifetime_hook(psy, PSY_CANCEL_DEFER_BEGIN);\n'
                        '\tcancel_delayed_work_sync(&psy->deferred_register_work);')
    core = replace_once(core, '\tcancel_work_sync(&psy->changed_work);',
                        '\tpsy_lifetime_hook(psy, PSY_CANCEL_CHANGED_BEGIN);\n'
                        '\tcancel_work_sync(&psy->changed_work);\n'
                        '\tpsy_lifetime_hook(psy, PSY_CANCEL_CHANGED_DONE);')
    return core + '\n#include "power-supply-lifetime-kunit.c"\n'


def test_patch(root, archive, lock, queue, variant, apply_queue, scratch):
    """Generate gates against the actual variant; preserve all queue semantics."""
    if variant not in ('original', 'reordered'):
        raise ValueError('Expected original or reordered variant')
    targets = (CORE, 'drivers/power/supply/Kconfig')
    prefix = 'linux-' + lock['linux']['tag'].removeprefix('v') + '/'
    with tarfile.open(archive, 'r:xz') as stream:
        for name in targets:
            destination = scratch / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(stream.extractfile(prefix + name).read())
    # Only these patches affect the core/Kconfig in the current queue. The full
    # replay below fails closed if another patch changes a hook's context.
    selected = [p for p in queue if p[0] in (
        '0013-power-supply-freezable-notifications.patch', FIX)]
    if [p[0] for p in selected] != ['0013-power-supply-freezable-notifications.patch'] + (
            [FIX] if variant == 'reordered' else []):
        raise ValueError('Unexpected power-supply candidate queue')
    apply_queue(scratch, selected)
    core = (scratch / CORE).read_text()
    deferred = core.index('cancel_delayed_work_sync(&psy->deferred_register_work)')
    changed = core.index('cancel_work_sync(&psy->changed_work)')
    if (deferred < changed) != (variant == 'reordered'):
        raise ValueError('Variant does not match the actual cancellation order')
    kconfig = (scratch / targets[1]).read_text()
    additions = '''
config POWER_SUPPLY_LIFETIME_KUNIT_TEST
	bool "Power-supply lifetime test gates (isolated test kernel only)"
	depends on KUNIT=y && POWER_SUPPLY=y

config POWER_SUPPLY_LIFETIME_ORIGINAL_ORDER
	bool "Expect the original cancellation ordering defect"
	depends on POWER_SUPPLY_LIFETIME_KUNIT_TEST
'''
    replacements = {CORE: (core, instrument(core)), targets[1]: (kconfig, kconfig + additions)}
    for name in ('power-supply-lifetime-hooks.h', 'power-supply-lifetime-kunit.c'):
        replacements['drivers/power/supply/' + name] = ('', (root / 'kernel/tests' / name).read_text())
    diff = ''.join(''.join(difflib.unified_diff(
        before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        for name, (before, after) in replacements.items())
    return ('9999-power-supply-test-only-gates.patch', diff.encode())


def manifest_for(queue):
    return [dict(name=name, sha256=hashlib.sha256(data).hexdigest()) for name, data in queue]
