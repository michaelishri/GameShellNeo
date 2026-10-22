"""Test-only instrumentation for complete core and OMAP mailbox lifetime."""
import difflib

from musb_restart_kunit import checked_cases as validate_cases
from omap_musb_mailbox_source import CORE, HEADER, OMAP, once, prepare

CASES = ('no_owner_test', 'held_dispatch_test', 'held_work_test', 'coalesced_status_test',
         'owner_identity_test', 'probe_unwind_test', 'child_rebind_test', 'parent_remove_test',
         'held_parent_suspend_test', 'held_parent_resume_test', 'closed_parent_pm_test',
         'rebound_parent_pm_test')
LIMITS = ('Complete core and OMAP backend with actual dispatch/quiesce/work/parent-PM bodies, '
          'Linux SRCU, workqueue, platform parent/child and generic-PHY ownership under UML '
          'KASAN/lockdep. Parent callbacks execute via actual runtime-PM APIs. Controller '
          'construction, MMIO and PHY lookup/provider effects are fixture seams. Probe unwind '
          'executes actual core initialization through injected runtime-get rejection; other '
          'child callbacks use actual lifetime helpers in a synthetic platform driver. '
          'Cached level is retained information, not fresh physical-state proof. No complete '
          'system-PM graph, DMA, inaccessible-MMIO recovery, SMP or hardware qualification.')


def checked_cases(report, log):
    return validate_cases(report, log, suite_name='omap-musb-mailbox', expected_cases=CASES)


def test_patch(root, archive, lock, scratch):
    paths, _ = prepare(root, archive, lock, scratch)
    original = {name: path.read_text() for name, path in paths.items()}
    core = original[CORE] + '''
#ifdef CONFIG_OMAP_MUSB_MAILBOX_KUNIT_TEST
int musb_omap_test_register(struct musb *musb)
{
	return musb_register_mailbox(musb);
}

void musb_omap_test_quiesce(struct musb *musb)
{
	musb_quiesce_mailbox(musb);
}

bool musb_omap_test_owned(struct musb *musb)
{
	return musb && rcu_access_pointer(musb_mailbox_owner) == musb;
}

int musb_omap_test_probe(struct device *dev, void __iomem *base)
{
	return musb_init_controller(dev, 0, base);
}
#endif
'''
    header = original[HEADER] + '''
#ifdef CONFIG_OMAP_MUSB_MAILBOX_KUNIT_TEST
int musb_omap_test_register(struct musb *musb);
void musb_omap_test_quiesce(struct musb *musb);
bool musb_omap_test_owned(struct musb *musb);
int musb_omap_test_probe(struct device *dev, void __iomem *base);
#endif
'''
    hooks = '''
#ifdef CONFIG_OMAP_MUSB_MAILBOX_KUNIT_TEST
static void *omap_test_drvdata(const struct device *dev);
static u32 omap_test_readl(void __iomem *addr, u32 offset);
static void omap_test_writel(void __iomem *addr, u32 offset, u32 value);
static struct phy *omap_test_get_phy(struct device *dev, const char *name);
static struct usb_phy *omap_test_get_usb_phy(struct device *dev, const char *name, u8 index);
#define dev_get_drvdata omap_test_drvdata
#define musb_readl omap_test_readl
#define musb_writel omap_test_writel
#define devm_phy_get omap_test_get_phy
#define devm_usb_get_phy_by_phandle omap_test_get_usb_phy
#endif
'''
    omap = once(original[OMAP], '#include "omap2430.h"\n', '#include "omap2430.h"\n' + hooks)
    omap += '\n#ifdef CONFIG_OMAP_MUSB_MAILBOX_KUNIT_TEST\n#include "omap-musb-mailbox-kunit.c"\n#endif\n'
    config_path = 'drivers/usb/musb/Kconfig'
    config = original[config_path] + '''
config OMAP_MUSB_MAILBOX_KUNIT_TEST
	bool "OMAP MUSB mailbox lifetime tests (isolated test kernel only)"
	depends on KUNIT=y && USB_MUSB_OMAP2PLUS=y && PM
	select IRQ_WORK
'''
    filename = 'drivers/usb/musb/omap-musb-mailbox-kunit.c'
    replacements = {CORE: (original[CORE], core), HEADER: (original[HEADER], header),
                    OMAP: (original[OMAP], omap), config_path: (original[config_path], config),
                    filename: ('', (root / 'kernel/tests/omap-musb-mailbox-kunit.c').read_text())}
    patch = ''.join(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
        fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        for name, (before, after) in replacements.items())
    return '9999-omap-musb-mailbox-test-only.patch', patch.encode()
