/* SPDX-License-Identifier: GPL-2.0-only */
/* Source-order audit, NOT a safe-teardown or real-interrupt qualification. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define __iomem
#define __must_hold(lock)
#define RPM_GET_PUT 1
#define MUSB_HOST 1
#define MUSB_PERIPHERAL 2
#define OTG_STATE_UNDEFINED 0
#define PHY_MODE_INVALID 0
#define USB_STATE_NOTATTACHED 0
#define IRQ_HANDLED 1
#define dev_err(...) ((void)0)
#define musb_dbg(...) ((void)0)
#define spin_lock_irqsave(p, flags) do { (flags) = 0; assert(!*(p)); *(p) = 1; } while (0)
#define spin_unlock_irqrestore(p, flags) do { (void)(flags); assert(*(p)); *(p) = 0; } while (0)
#ifndef DRAIN_AFTER_CLEANUP
#define DRAIN_AFTER_CLEANUP 0
#endif
#ifndef FREE_IRQ_EARLY
#define FREE_IRQ_EARLY 0
#endif
typedef uint8_t u8;
typedef int irqreturn_t;
struct work { bool pending; unsigned cancels; };
struct device { int refs; struct device *parent; void *data; };
struct platform_device { struct device dev; };
struct usb_gadget;
struct usb_gadget_ops { int (*udc_stop)(struct usb_gadget *); };
struct usb_gadget { const struct usb_gadget_ops *ops; };
struct usb_udc { struct usb_gadget *gadget; bool started; };
struct transceiver { void *otg; };
struct musb {
	struct device *controller;
	struct usb_gadget g;
	struct transceiver *xceiv;
	void *phy, *gadget_driver, *dma_controller;
	u8 *mregs;
	struct { void *regs; } endpoints[2];
	struct work irq_work, finish_resume_work, deassert_reset_work, gadget_work;
	int lock, softconnect, is_active, port_mode, nIrq;
	unsigned intrtxe, intrrxe, int_usb, int_tx, int_rx;
};
struct usb_ep { const void *desc; const char *name; };
struct musb_ep {
	struct usb_ep end_point;
	struct musb *musb;
	const void *desc;
	unsigned current_epnum;
	bool is_in;
};
struct sunxi_glue {
	struct work work;
	unsigned long flags;
	void *phy, *rst, *clk;
};
static struct musb instance;
static struct sunxi_glue glue;
static struct musb_ep endpoint;
static struct usb_udc udc;
static u8 registers[256];
static bool accessible, irq_live, late_irq, inject_irq, configured;
static bool rpm_enabled;
static int pm_result;
static unsigned bad_mmio, late_reads, idle_after_exit, unbinds;
static unsigned stop_cases, remove_cases, failed_offline, residual_work, late_irq_cases;
static void (*musb_phy_callback)(void);
static int sunxi_musb_exit(struct musb *);
static void sunxi_musb_disable(struct musb *);
static irqreturn_t sunxi_musb_interrupt(int, void *);
static int musb_gadget_disable(struct usb_ep *);
static int musb_gadget_stop(struct usb_gadget *);
static inline void usb_gadget_udc_stop_locked(struct usb_udc *);

static struct musb *dev_to_musb(struct device *d)
{ assert(d == instance.controller); return &instance; }
static struct musb *gadget_to_musb(struct usb_gadget *g)
{ assert(g == &instance.g); return &instance; }
static struct musb_ep *to_musb_ep(struct usb_ep *ep)
{ assert(ep == &endpoint.end_point); return &endpoint; }
static void *dev_get_drvdata(struct device *d) { return d->data; }
static int __pm_runtime_resume(struct device *d, int flags)
{ assert(d == instance.controller && flags == RPM_GET_PUT); d->refs++; return pm_result; }
static int __pm_runtime_idle(struct device *d, int flags)
{
	assert(flags == RPM_GET_PUT && d->refs > 0);
	d->refs--;
	if (!accessible && rpm_enabled && !d->refs)
		idle_after_exit++;
	return 0;
}
static void pm_runtime_put(struct device *d) { assert(d->refs > 0); d->refs--; }
static void pm_runtime_put_autosuspend(struct device *d) { pm_runtime_put(d); }
static void __attribute__((unused)) pm_runtime_put_noidle(struct device *d) { pm_runtime_put(d); }
static void pm_runtime_mark_last_busy(struct device *d) { assert(d == instance.controller); }
static void pm_runtime_dont_use_autosuspend(struct device *d) { assert(d == instance.controller); }
static void pm_runtime_disable(struct device *d) { assert(d == instance.controller); rpm_enabled = false; }
static void access_register(bool read)
{
	assert(instance.lock);
	if (!accessible)
		bad_mmio++;
	if (late_irq && read)
		late_reads++;
}
static u8 readb(void *p) { (void)p; access_register(true); return 0; }
static unsigned readw(void *p) { return readb(p); }
static void writeb(unsigned value, void *p) { (void)value; (void)p; access_register(false); }
static void writew(unsigned value, void *p) { writeb(value, p); }
static void musb_writeb(void *base, unsigned reg, unsigned value) { writeb(value, (u8 *)base + reg); }
static void musb_writew(void *base, unsigned reg, unsigned value) { writew(value, (u8 *)base + reg); }
static void musb_clearb(void *base, unsigned reg) { (void)readb((u8 *)base + reg); }
static void musb_clearw(void *base, unsigned reg) { (void)readw((u8 *)base + reg); }
static void musb_ep_select(void *base, unsigned ep) { musb_writeb(base, 0, ep); }
static bool is_host_active(struct musb *m) { assert(m == &instance); return false; }
static void musb_interrupt(struct musb *m) { assert(m == &instance && m->lock); }
static void cancel_delayed_work_sync(struct work *w) { w->pending = false; w->cancels++; }
static void cancel_work_sync(struct work *w) { cancel_delayed_work_sync(w); }
static void schedule_delayed_work(struct work *w, unsigned delay) { assert(!delay); w->pending = true; }
static bool test_bit(unsigned bit, unsigned long *flags) { return (*flags & (1UL << bit)) != 0; }
static void clear_bit(unsigned bit, unsigned long *flags) { *flags &= ~(1UL << bit); }
static void phy_power_off(void *p) { assert(p == glue.phy); }
static void phy_exit(void *p) { assert(p == glue.phy); }
static void reset_control_assert(void *p) { assert(p == glue.rst); accessible = false; }
static void clk_disable_unprepare(void *p)
{
	assert(p == glue.clk && !instance.lock);
	accessible = false;
	/* A controlled already-dispatched/shared handler boundary, not an IRQ simulator. */
	if (inject_irq && irq_live) {
		late_irq = true;
		assert(sunxi_musb_interrupt(instance.nIrq, &instance) == IRQ_HANDLED);
		late_irq = false;
	}
}
static void sunxi_sram_release(struct device *d) { assert(d == instance.controller->parent); }
static void musb_platform_disable(struct musb *m) { sunxi_musb_disable(m); }
static int musb_platform_exit(struct musb *m) { return sunxi_musb_exit(m); }
static void musb_platform_try_idle(struct musb *m, unsigned delay) { assert(m == &instance && !delay); }
static void musb_hnp_stop(struct musb *m) { assert(m == &instance && m->lock); }
static int musb_gadget_vbus_draw(struct usb_gadget *g, unsigned value) { assert(g == &instance.g && !value); return 0; }
static void musb_set_state(struct musb *m, int state) { assert(m == &instance && !state); }
static void otg_set_peripheral(void *otg, void *g) { assert(otg == &glue && !g); }
static void phy_set_mode(void *phy, int mode) { assert(phy == glue.phy && !mode); }
static void musb_pullup(struct musb *m, int on) { assert(!on); musb_writeb(m->mregs, 0, 0); }
static void usb_gadget_set_state(struct usb_gadget *g, int state) { assert(g == &instance.g && !state); }
static void nuke(struct musb_ep *ep, int status) { assert(ep == &endpoint && status == -ESHUTDOWN); }
static void usb_del_gadget_udc(struct usb_gadget *g)
{
	assert(g == &instance.g);
	unbinds++;
	/* Model the function driver's valid endpoint-disable operation during unbind. */
	if (configured)
		assert(!musb_gadget_disable(&endpoint.end_point));
	usb_gadget_udc_stop_locked(&udc);
}
static void musb_host_cleanup(struct musb *m) { assert(m->port_mode == MUSB_PERIPHERAL); }
static void musb_host_free(struct musb *m) { assert(m == &instance); }
static void musb_exit_debugfs(struct musb *m) { assert(m == &instance); }
static void musb_cleanup_wakeup(struct musb *m) { assert(m == &instance); }
static void musb_dma_controller_destroy(void *dma) { assert(!dma); }
static void usb_phy_shutdown(struct transceiver *phy) { assert(phy == instance.xceiv); }
static void __attribute__((unused)) free_irq(int irq, struct musb *m) { assert(irq == 31 && m == &instance && irq_live); irq_live = false; }

#include "musb_teardown_functions.h"

static void setup(struct platform_device *pdev, struct device *parent, struct transceiver *xceiv,
		  int extra_refs, int result, bool power)
{
	static const struct usb_gadget_ops ops = {.udc_stop = musb_gadget_stop};
	*parent = (struct device){.data = &glue};
	*pdev = (struct platform_device){.dev = {.refs = 1 + extra_refs, .parent = parent}};
	glue = (struct sunxi_glue){.flags = (1UL << SUNXI_MUSB_FL_ENABLED) |
		(1UL << SUNXI_MUSB_FL_HAS_RESET) | (1UL << SUNXI_MUSB_FL_PHY_ON),
		.phy = registers, .rst = registers, .clk = registers};
	xceiv->otg = &glue;
	instance = (struct musb){.controller = &pdev->dev, .g = {.ops = &ops}, .mregs = registers,
		.phy = glue.phy, .xceiv = xceiv, .gadget_driver = registers, .is_active = 1,
		.softconnect = 1, .port_mode = MUSB_PERIPHERAL, .nIrq = 31};
	instance.endpoints[1].regs = registers;
	endpoint = (struct musb_ep){.musb = &instance, .current_epnum = 1,
		.desc = registers, .end_point = {.desc = registers, .name = "test"}};
	udc = (struct usb_udc){.gadget = &instance.g, .started = true};
	accessible = power; irq_live = rpm_enabled = true; late_irq = inject_irq = configured = false;
	bad_mmio = late_reads = idle_after_exit = unbinds = 0; pm_result = result;
}

int main(void)
{
	const int errors[] = {0, 1, -EIO, -EACCES, -EBUSY, -ETIMEDOUT};
	for (unsigned error = 0; error < sizeof(errors) / sizeof(errors[0]); error++)
	for (int backend = 0; backend < 2; backend++)
	for (int power = 0; power < 2; power++) {
		if (errors[error] >= 0 && !power)
			continue;
		struct platform_device pdev; struct device parent; struct transceiver xceiv;
		setup(&pdev, &parent, &xceiv, 1, errors[error], power);
		if (!backend)
			instance.xceiv = NULL;
		usb_gadget_udc_stop_locked(&udc);
		assert(!udc.started && !instance.gadget_driver && !instance.softconnect && !instance.is_active);
		assert(pdev.dev.refs == 2 && !instance.lock);
		assert((bad_mmio > 0) == !power);
		failed_offline += !power;
		stop_cases++;
	}
	for (int extra = 0; extra < 2; extra++)
	for (int error = 0; error < 2; error++)
	for (int power = 0; power < 2; power++)
	for (int active_ep = 0; active_ep < 2; active_ep++)
	for (int interrupt = 0; interrupt < 2; interrupt++) {
		if (!error && !power)
			continue;
		struct platform_device pdev; struct device parent; struct transceiver xceiv;
		setup(&pdev, &parent, &xceiv, extra, error ? -EIO : 0, power);
		configured = active_ep; inject_irq = interrupt;
		glue.work.pending = true;
		instance.irq_work.pending = instance.finish_resume_work.pending = true;
		instance.deassert_reset_work.pending = instance.gadget_work.pending = true;
		musb_remove(&pdev);
		assert(!irq_live && !accessible && !rpm_enabled && !instance.lock && unbinds == 1);
		assert(!instance.gadget_driver && !udc.started && pdev.dev.refs == extra);
		assert(!glue.work.pending && !test_bit(SUNXI_MUSB_FL_ENABLED, &glue.flags));
		if (configured)
			assert(!endpoint.desc && !endpoint.end_point.desc);
		assert(!instance.finish_resume_work.pending && !instance.deassert_reset_work.pending && !instance.gadget_work.pending);
		assert(instance.irq_work.pending == (active_ep && !DRAIN_AFTER_CLEANUP));
		assert(late_reads == (interrupt && !FREE_IRQ_EARLY ? 3U : 0U));
		/* Final put attempts idle only with no external reference, not a full PM simulation. */
		assert(idle_after_exit == !extra);
		residual_work += instance.irq_work.pending;
		late_irq_cases += late_reads > 0;
		remove_cases++;
	}
	printf("MUSB teardown audit: stop=%u remove=%u offline-stop-access=%u residual-work=%u post-clock-handler=%u\n",
		stop_cases, remove_cases, failed_offline, residual_work, late_irq_cases);
	return 0;
}
