/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual Sunxi hooks, deterministic modeled resource and dispatch boundaries. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define BIT(n) (1UL << (n))
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
#define EXTCON_USB_HOST 1
#define NOTIFY_DONE 0
#define OTG_STATE_A_WAIT_VRISE 1
#define OTG_STATE_B_IDLE 2
#define MUSB_DEVCTL_SESSION 1
#define MUSB_HOST 1
#define MUSB_PERIPHERAL 2
#define MUSB_OTG 3
#define USB_PORT_STAT_ENABLE 1
#define MUSB_HST_MODE(m) ((m)->host = true)
#define MUSB_DEV_MODE(m) ((m)->host = false)
#define WARN_ON(v) assert(!(v))
#define dev_err(...) ((void)0)
#define spin_lock_irqsave(p, f) do { (f) = 0; assert(!*(p)); *(p) = 1; } while (0)
#define spin_unlock_irqrestore(p, f) do { (void)(f); assert(*(p)); *(p) = 0; } while (0)
#define INIT_WORK(w, fn) (*(w) = (struct work_struct){.function = (fn)})
typedef uint8_t u8;
enum phy_mode { PHY_MODE_USB_HOST = 1, PHY_MODE_USB_DEVICE, PHY_MODE_USB_OTG };
struct device { struct device *parent; void *data; int holds; };
struct phy { int initialized, powered; enum phy_mode mode; };
struct clk { int on; };
struct reset_control { int deasserted; };
struct otg { int state; };
struct usb_phy { struct otg *otg; };
struct work_struct { unsigned disabled; bool pending; void (*function)(struct work_struct *); };
struct notifier_block { int (*notifier_call)(struct notifier_block *, unsigned long, void *); };
struct extcon_dev { int host; struct notifier_block *registered; bool selected; };
struct musb {
    struct device *controller;
    struct phy *phy;
    struct usb_phy *xceiv;
    u8 *mregs;
    int lock, port_mode, port1_status;
    bool host;
    void (*isr)(void);
};
#include "sunxi_owner_definitions.h"

static struct sunxi_glue glue;
static struct musb *sunxi_musb;
static int failure, sram, reads, writes, work_runs, registrations, drains, scenarios;
static bool event_during_init, change_during_read;
static void set_bit(unsigned bit, unsigned long *flags) { *flags |= BIT(bit); }
static void clear_bit(unsigned bit, unsigned long *flags) { *flags &= ~BIT(bit); }
static bool test_bit(unsigned bit, const unsigned long *flags) { return !!(*flags & BIT(bit)); }
static bool test_and_clear_bit(unsigned bit, unsigned long *flags)
{ bool old = test_bit(bit, flags); clear_bit(bit, flags); return old; }
static bool test_and_set_bit(unsigned bit, unsigned long *flags)
{ bool old = test_bit(bit, flags); set_bit(bit, flags); return old; }
static void *dev_get_drvdata(struct device *d) { return d->data; }
static bool schedule_work(struct work_struct *w)
{ if (w->disabled) return false; bool old = w->pending; w->pending = true; return !old; }
static void __attribute__((unused)) enable_work(struct work_struct *w) { assert(w->disabled == 1); w->disabled--; }
static void disable_work(struct work_struct *w) { w->disabled++; }
static void disable_work_sync(struct work_struct *w)
{ assert(!w->disabled); w->disabled++; w->pending = false; }
static void __attribute__((unused)) cancel_work_sync(struct work_struct *w) { w->pending = false; }
static void run_work(void)
{
    for (int i = 0; glue.work.pending; i++) {
        assert(i < 10 && !glue.work.disabled);
        glue.work.pending = false;
        work_runs++;
        glue.work.function(&glue.work);
    }
}
static void no_async(void)
{
    assert(!glue.extcon->registered && !glue.extcon->selected);
    assert(glue.work.disabled == 1 && !glue.work.pending);
}
static void powered(void)
{
    assert(glue.clk->on);
    assert(!test_bit(SUNXI_MUSB_FL_HAS_RESET, &glue.flags) || glue.rst->deasserted);
}
static int sunxi_sram_claim(struct device *d)
{ if (failure == 1) return -EIO; assert(!sram); sram = 1; return 0; }
static void sunxi_sram_release(struct device *d)
{ no_async(); assert(sram); sram = 0; }
static int clk_prepare_enable(struct clk *c)
{ if (failure == 2) return -EIO; assert(!c->on); c->on = 1; return 0; }
static void clk_disable_unprepare(struct clk *c)
{ no_async(); assert(c->on); c->on = 0; }
static int reset_control_deassert(struct reset_control *r)
{ if (failure == 3) return -EIO; assert(!r->deasserted); r->deasserted = 1; return 0; }
static void reset_control_assert(struct reset_control *r)
{ no_async(); assert(r->deasserted); r->deasserted = 0; }
static u8 readb(u8 *p) { powered(); reads++; return *p; }
static void writeb(u8 v, u8 *p) { powered(); writes++; *p = v; }
static void emit(void)
{
    if (glue.extcon->registered)
        glue.extcon->registered->notifier_call(glue.extcon->registered, glue.extcon->host, glue.extcon);
}
static int __attribute__((unused)) extcon_get_state(struct extcon_dev *e, unsigned id)
{
    assert(e == glue.extcon && id == EXTCON_USB_HOST);
    int snapshot = e->host;
    if (change_during_read) {
        change_during_read = false;
        e->host = !snapshot;
        emit();
    }
    return snapshot;
}
static int extcon_register_notifier(struct extcon_dev *e, unsigned id, struct notifier_block *nb)
{
    assert(!e->registered && !e->selected && id == EXTCON_USB_HOST);
    if (failure == 4) return -EIO;
    e->registered = nb;
    registrations++;
    return 0;
}
static int __attribute__((unused)) extcon_unregister_notifier(struct extcon_dev *e, unsigned id,
                                                             struct notifier_block *nb)
{ assert(e->registered == nb && id == EXTCON_USB_HOST); e->registered = NULL; return 0; }
static int extcon_unregister_notifier_sync(struct extcon_dev *e, unsigned id, struct notifier_block *nb)
{
    extcon_unregister_notifier(e, id, nb);
    /* A reader selected this block before unlink; it can still enqueue work. */
    if (e->selected) {
        nb->notifier_call(nb, e->host, e);
        e->selected = false;
    }
    drains++;
    return 0;
}
static int phy_init(struct phy *p)
{
    powered();
    assert(glue.extcon->registered && !p->initialized);
    if (event_during_init) {
        emit(); run_work();
        /* Model a selected dispatch still in flight at the failure boundary. */
        glue.extcon->selected = true;
    }
    if (failure == 5) return -EIO;
    p->initialized = 1;
    return 0;
}
static void phy_exit(struct phy *p)
{ no_async(); powered(); assert(p->initialized && !p->powered); p->initialized = 0; }
static void phy_power_on(struct phy *p)
{ powered(); assert(p->initialized && !p->powered); p->powered = 1; }
static void phy_power_off(struct phy *p)
{ powered(); assert(p->initialized && p->powered); p->powered = 0; }
static void phy_set_mode(struct phy *p, enum phy_mode mode)
{ powered(); assert(p->initialized); p->mode = mode; }
static void pm_runtime_get(struct device *d) { assert(!d->holds); d->holds++; }
static void pm_runtime_put(struct device *d) { no_async(); assert(d->holds == 1); d->holds--; }
static void sunxi_musb_interrupt(void) {}
static void musb_root_disconnect(struct musb *m) { powered(); m->port1_status = 0; }

#include "sunxi_owner_functions.h"

static void check_idle(struct musb *m, unsigned long features)
{
    no_async();
    assert(!glue.clk->on && !glue.rst->deasserted && !sram);
    assert(!glue.phy->initialized && !glue.phy->powered && !m->controller->holds);
    assert((glue.flags & (BIT(SUNXI_MUSB_FL_HAS_SRAM) | BIT(SUNXI_MUSB_FL_HAS_RESET) |
                         BIT(SUNXI_MUSB_FL_NO_CONFIGDATA))) == features);
}

int main(void)
{
    for (unsigned features_i = 0; features_i < 8; features_i++)
    for (enum phy_mode mode = PHY_MODE_USB_HOST; mode <= PHY_MODE_USB_OTG; mode++)
    for (int fail = 0; fail <= 5; fail++)
    for (int event = 0; event <= 1; event++) {
        unsigned long features = (features_i & 1 ? BIT(SUNXI_MUSB_FL_HAS_SRAM) : 0) |
                                 (features_i & 2 ? BIT(SUNXI_MUSB_FL_HAS_RESET) : 0) |
                                 (features_i & 4 ? BIT(SUNXI_MUSB_FL_NO_CONFIGDATA) : 0);
        if ((fail == 1 && !(features_i & 1)) || (fail == 3 && !(features_i & 2))) continue;
        struct clk clk = {0}; struct reset_control rst = {0}; struct phy phy = {0};
        struct extcon_dev extcon = {.host = mode == PHY_MODE_USB_HOST};
        struct otg otg = {0}; struct usb_phy xceiv = {.otg = &otg};
        struct device parent = {.data = &glue}, child = {.parent = &parent};
        u8 regs[256] = {0};
        struct musb m = {.controller = &child, .mregs = regs, .port_mode = mode};
        glue = (struct sunxi_glue){.dev = &parent, .clk = &clk, .rst = &rst, .phy = &phy,
                                  .extcon = &extcon, .xceiv = &xceiv, .flags = features,
                                  .phy_mode = mode};
        parent_work_init(&glue);
        failure = fail; event_during_init = event; change_during_read = false;
        sram = reads = writes = work_runs = registrations = drains = 0;
        int ret = sunxi_musb_init(&m);
        assert(ret == (fail ? -EIO : 0));
        if (fail) {
            check_idle(&m, features);
            assert(registrations == (fail == 5) && drains == (fail == 5));
            failure = 0;
            assert(!sunxi_musb_init(&m));
        }
        assert(glue.musb == &m && sunxi_musb == &m && !glue.work.disabled);
        assert(glue.phy_mode == mode && !test_bit(SUNXI_MUSB_FL_ENABLED, &glue.flags));
        int before_reads = reads;
        sunxi_musb_enable(&m); sunxi_musb_enable(&m); run_work();
        assert(reads == before_reads + 1 && m.host == !!extcon.host && phy.powered == !!extcon.host);

        /* Event comes after worker's snapshot: its second pass must see new state. */
        change_during_read = true; emit(); run_work();
        assert(!change_during_read && m.host == !!extcon.host && phy.powered == !!extcon.host);

        /* Transient disable/enable remains restartable and does not retire work. */
        sunxi_musb_disable(&m); before_reads = reads; extcon.host = !extcon.host; emit(); run_work();
        assert(reads == before_reads && !glue.work.disabled);
        sunxi_musb_enable(&m); run_work();
        assert(m.host == !!extcon.host);

        /* All other glue producers still run on a live controller. */
        sunxi_musb_set_vbus(&m, 1); run_work(); assert(phy.powered);
        sunxi_musb_set_vbus(&m, 0); run_work(); assert(!phy.powered);
        assert(sunxi_musb_set_mode(&m, 99) == -EINVAL);
        if (m.port_mode == MUSB_OTG) {
            assert(!sunxi_musb_set_mode(&m, MUSB_HOST)); run_work();
            assert(phy.mode == PHY_MODE_USB_HOST);
        } else {
            assert(sunxi_musb_set_mode(&m, MUSB_OTG) == -EINVAL);
        }
        assert(!sunxi_musb_recover(&m)); run_work();

        /* Selected callback and queued work at exit must both be retired. */
        extcon.selected = true; emit();
        assert(!sunxi_musb_exit(&m)); check_idle(&m, features);
        int previous_runs = work_runs;
        sunxi_musb_set_vbus(&m, 1); sunxi_musb_recover(&m); sunxi_musb_enable(&m); run_work();
        assert(work_runs == previous_runs && !glue.work.pending);
        glue.phy_mode = mode == PHY_MODE_USB_HOST ? PHY_MODE_USB_DEVICE : PHY_MODE_USB_HOST;

        /* Same parent, fresh child, no PHY event: sample current provider state. */
        struct musb next = {.controller = &child, .mregs = regs, .port_mode = mode};
        event_during_init = false; extcon.host = !extcon.host;
        assert(!sunxi_musb_init(&next));
        assert(glue.musb == &next && glue.phy_mode == mode && !glue.work.disabled);
        before_reads = reads; sunxi_musb_enable(&next); run_work();
        assert(reads == before_reads + 1 && next.host == !!extcon.host && phy.powered == !!extcon.host);
        extcon.selected = true;
        assert(!sunxi_musb_exit(&next)); check_idle(&next, features);
        assert(registrations == drains);
        scenarios++;
    }
    printf("Sunxi child ownership: %d actual-source scenarios passed\n", scenarios);
    return 0;
}
