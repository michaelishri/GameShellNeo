"""Test-only hardware seams around the complete actual Sun4i PHY driver."""
import difflib

from musb_restart_kunit import checked_cases as checked_report
from phy_detector_source import FILE, function, prepare

CASES = ('detector_inline_exit_test', 'detector_inline_rebind_test',
         'detector_parallel_exit_test', 'detector_parallel_rebind_test',
         'detector_vbus_exit_test', 'detector_vbus_rebind_test',
         'detector_tail_mutex_test', 'detector_queued_exit_test',
         'detector_poll_test', 'detector_unguarded_control_test')
LIMITS = ('Complete Sun4i PHY driver with actual init/exit/scan code, Linux delayed work, '
          'mutexes, extcon/SRCU dispatch and controlled kthread interleavings under UML '
          'KASAN/lockdep. GPIO/MMIO/clock/reset effects and pulse delays are test seams; '
          'generic-PHY callers use its required mutex contract. No physical registers, '
          'SMP, full provider/consumer graph or board removal qualification.')


def once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Changed PHY kernel test anchor: ' + before)
    return text.replace(before, after, 1)


def checked_cases(report, log):
    return checked_report(report, log, suite_name='phy-detector', expected_cases=CASES)


def test_patch(root, archive, lock, directory):
    path, _ = prepare(root, archive, lock, directory)
    original = path.read_text()
    declarations = '''
#ifdef CONFIG_PHY_DETECTOR_KUNIT_TEST
static struct sun4i_usb_phy_data *sun4i_detector_test_data;
static void sun4i_detector_test_access(struct sun4i_usb_phy_data *data);
static void sun4i_detector_test_begin(struct sun4i_usb_phy_data *data, u64 generation);
static int sun4i_detector_test_get(struct sun4i_usb_phy_data *data, bool id);
static bool sun4i_detector_test_poll(struct sun4i_usb_phy_data *data);
static void sun4i_detector_test_delay(struct sun4i_usb_phy_data *data, unsigned int ms);
#define detector_delay(data, ms) sun4i_detector_test_delay(data, ms)
#else
#define detector_delay(data, ms) msleep(ms)
#endif

'''
    changed = once(original, 'static void sun4i_usb_phy0_update_iscr(',
                   declarations + 'static void sun4i_usb_phy0_update_iscr(')
    for name, anchor, owner in (
        ('sun4i_usb_phy0_update_iscr', '\tiscr = readl(data->base + REG_ISCR);', 'data'),
        ('sun4i_usb_phy_write', '\tspin_lock_irqsave(&phy_data->reg_lock, flags);', 'phy_data'),
        ('sun4i_usb_phy_passby', '\tif (!phy->pmu)', 'phy_data'),
        ('sun4i_usb_phy0_reroute', '\tregval = readl(data->base + REG_PHY_OTGCTL);', 'data'),
    ):
        body = function(changed, name)
        hook = ('#ifdef CONFIG_PHY_DETECTOR_KUNIT_TEST\n\tif (' + owner +
                ' == sun4i_detector_test_data) {\n\t\tsun4i_detector_test_access(' + owner +
                ');\n\t\treturn;\n\t}\n#endif\n\n')
        changed = once(changed, body, once(body, anchor, hook + anchor))
    for name, call in (('sun4i_usb_phy0_get_id_det', 'sun4i_detector_test_get(data, true)'),
                       ('sun4i_usb_phy0_get_vbus_det', 'sun4i_detector_test_get(data, false)'),
                       ('sun4i_usb_phy0_poll', 'sun4i_detector_test_poll(data)')):
        # poll returns bool; the common extractor deliberately handles both.
        start = changed.index('static ' + ('bool' if name.endswith('_poll') else 'int') + ' ' + name + '(')
        end = changed.index('\n}', start) + 3
        body = changed[start:end]
        hook = ('\n#ifdef CONFIG_PHY_DETECTOR_KUNIT_TEST\n\tif (data == sun4i_detector_test_data)\n'
                '\t\treturn ' + call + ';\n#endif\n')
        changed = once(changed, body, once(body, '\n{', '\n{' + hook))
    scan = function(changed, 'sun4i_usb_phy0_id_vbus_det_scan')
    scan_changed = once(scan, '\tgeneration = data->phy0_generation;\n',
        '\tgeneration = data->phy0_generation;\n#ifdef CONFIG_PHY_DETECTOR_KUNIT_TEST\n'
        '\tif (data == sun4i_detector_test_data)\n\t\tsun4i_detector_test_begin(data, generation);\n#endif\n')
    scan_changed = scan_changed.replace('msleep(200);', 'detector_delay(data, 200);')
    scan_changed = scan_changed.replace('msleep(1000);', 'detector_delay(data, 1000);')
    changed = once(changed, scan, scan_changed)
    guard = ('\t\tif (!data->phy0_init || data->phy0_generation != generation) {\n'
             '\t\t\tmutex_unlock(&phy0->mutex);\n\t\t\treturn;\n\t\t}\n')
    legacy = once(scan_changed, guard, '')
    legacy = once(legacy, 'sun4i_usb_phy0_id_vbus_det_scan(', 'sun4i_detector_unguarded_scan(')
    changed += ('\n#ifdef CONFIG_PHY_DETECTOR_KUNIT_TEST\n' + legacy +
                '\n#include "phy-detector-kunit.c"\n#endif\n')
    config_file = 'drivers/phy/allwinner/Kconfig'
    # The original Kconfig is read from the locked archive, independently of
    # source caches and without writing a shared immutable tree.
    import tarfile
    with tarfile.open(archive, 'r|xz') as stream:
        expected = 'linux-' + lock['linux']['tag'][1:] + '/' + config_file
        for member in stream:
            if member.name == expected:
                config = stream.extractfile(member).read().decode()
                break
        else:
            raise ValueError('Pinned Allwinner Kconfig absent')
    config_changed = config + '''
config PHY_DETECTOR_KUNIT_TEST
	bool "Sun4i detector lifetime tests (isolated test kernel only)"
	depends on KUNIT=y && PHY_SUN4I_USB=y
'''
    replacements = {FILE: (original, changed), config_file: (config, config_changed),
                    'drivers/phy/allwinner/phy-detector-kunit.c':
                    ('', (root / 'kernel/tests/phy-detector-kunit.c').read_text())}
    patch = ''.join(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        for name, (before, after) in replacements.items())
    return '9999-phy-detector-test-only.patch', patch.encode()
