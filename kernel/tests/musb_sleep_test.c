/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual driver functions; shims expose register/PM/work ownership boundaries. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define __iomem
#define CONFIG_PM 1
#define CONFIG_PM_SLEEP 1
#define IRQ_GET_DESC_CHECK_GLOBAL 0
#define IRQCHIP_SKIP_SET_WAKE 1
#define IRQD_WAKEUP_STATE 1
#define BIT(n) (1U << (n))
#define MUSB_C_NUM_EPS 2
#define MUSB_HOST 1
#define MUSB_PERIPHERAL 2
#define MUSB_OTG 3
#define OTG_STATE_UNDEFINED 0
#define PHY_MODE_INVALID 0
#define USB_STATE_NOTATTACHED 0
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#include "musb_sleep_defs.h"

struct list_head { struct list_head *next, *prev; };
struct device {
	bool wake, capable;
	int refs, get_error, init_error;
	struct { void *wakeirq, *wakeup; } power;
};
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; bool queued; };
struct usb_gadget { int unused; };
struct transceiver { void *otg; };
struct config { unsigned num_eps; };
struct musb_platform_ops { unsigned quirks; };
struct musb {
	void *mregs, *phy, *gadget_driver;
	struct transceiver *xceiv;
	struct device *controller;
	struct config *config;
	struct musb_platform_ops *ops;
	struct usb_gadget g;
	struct delayed_work gadget_work, irq_work;
	struct list_head pending_list;
	struct musb_context_registers context;
	struct { void *regs; } endpoints[MUSB_C_NUM_EPS];
	int port_mode, lock, list_lock, port1_status, nIrq;
	bool softconnect, gadget_suspended, flush_irq_work, dyn_fifo, is_active;
	bool irq_wake, wakeup_initialized;
	u16 intrtxe, intrrxe;
};
struct musb_pending_work {
	struct list_head node;
	int (*callback)(struct musb *, void *);
	void *data;
};
static struct musb *active;
static unsigned writes, scenarios;
static bool gated_case, restoring, restored, irq_ready, platform_ready, work_ready;
static bool cancel_runs_worker, unregister_queues, removing;
static int pm_boundary_intent, callback_intent, errors;
static u8 banks[8][128];
struct irq_chip;
struct irq_data { unsigned flags; struct irq_chip *chip; };
struct irq_chip { unsigned flags; int (*irq_set_wake)(struct irq_data *, unsigned); };
struct irq_desc { struct irq_data irq_data; unsigned wake_depth; bool locked; };
static struct irq_desc irqdesc;
static struct irq_chip irqchip;
static int wake_on_error, wake_off_error, wake_on_calls, wake_off_calls;
static bool wake_hardware, wake_backend_live;
static unsigned wake_init_calls, freed_irqs, freed_hosts;

#define spin_lock_irqsave(lock, flags) do { (flags) = 0; assert(!*(lock)); *(lock) = 1; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); assert(*(lock)); *(lock) = 0; } while (0)
#define WARN_ON(value) assert(!(value))
#define WARN(value, ...) assert(!(value))
#define dev_err(...) do { errors++; } while (0)
#define musb_dbg(...) do {} while (0)
#define is_host_active(m) ((m)->port_mode == MUSB_HOST)
#define list_for_each_entry_safe(w, nextw, head, member) \
	for (struct list_head *p = (head)->next, *nextp; \
	     p != (head) && ((nextp = p->next), \
	     (w = container_of(p, struct musb_pending_work, member)), \
	     (nextw = nextp == (head) ? NULL : container_of(nextp, struct musb_pending_work, member)), \
	     (void)nextw, 1); p = nextp)
static bool list_empty(struct list_head *h) { return h->next == h; }
static void list_del(struct list_head *n) { n->prev->next = n->next; n->next->prev = n->prev; }
static void devm_kfree(struct device *d, void *p) { (void)d; (void)p; }
static struct musb *dev_to_musb(struct device *d) { assert(d == active->controller); return active; }
static struct musb *gadget_to_musb(struct usb_gadget *g) { return container_of(g, struct musb, g); }
static bool device_may_wakeup(struct device *d) { return d->wake; }
static bool device_can_wakeup(struct device *d) { return d->capable; }
static int device_init_wakeup(struct device *d, bool enable)
{
	wake_init_calls++;
	d->capable = enable;
	if (enable && d->init_error) return d->init_error;
	d->wake = enable;
	d->power.wakeup = enable ? d : NULL;
	return 0;
}
static struct irq_desc *irq_to_desc(unsigned irq) { assert(irq == 164); return &irqdesc; }
static struct irq_chip *irq_desc_get_chip(struct irq_desc *d) { return d->irq_data.chip; }
static bool irq_is_nmi(struct irq_desc *d) { (void)d; return false; }
static void irqd_set(struct irq_data *d, unsigned f) { d->flags |= f; }
static void irqd_clear(struct irq_data *d, unsigned f) { d->flags &= ~f; }
static struct irq_desc *get_desc(unsigned irq)
{
	struct irq_desc *d = irq_to_desc(irq);
	assert(!d->locked && !active->lock); d->locked = true; return d;
}
static struct irq_desc *put_desc(struct irq_desc *d)
{ if (d) { assert(d->locked); d->locked = false; } return NULL; }
static void cleanup_desc(struct irq_desc **d) { put_desc(*d); }
#define scoped_irqdesc_get_and_buslock(irq, check) \
	for (struct irq_desc *scoped_irqdesc __attribute__((cleanup(cleanup_desc))) = get_desc(irq); \
	     scoped_irqdesc; scoped_irqdesc = put_desc(scoped_irqdesc))
int irq_set_irq_wake(unsigned irq, unsigned on);
static int enable_irq_wake(unsigned irq) { return irq_set_irq_wake(irq, 1); }
static int disable_irq_wake(unsigned irq) { return irq_set_irq_wake(irq, 0); }
static int irqchip_wake(struct irq_data *d, unsigned on)
{
	assert(d == &irqdesc.irq_data && irqdesc.locked && wake_backend_live);
	if (on) { wake_on_calls++; if (wake_on_error) return wake_on_error; }
	else { wake_off_calls++; if (wake_off_error) return wake_off_error; }
	wake_hardware = on;
	return 0;
}
static void free_irq(int irq, struct musb *m)
{ assert(irq == 164 && m == active); freed_irqs++; }
static void musb_host_free(struct musb *m) { assert(m == active); freed_hosts++; }
static void musb_gadget_work(struct work_struct *work);
static int musb_gadget_pullup(struct usb_gadget *gadget, int is_on);
static int musb_gadget_stop(struct usb_gadget *gadget);

static int pm_runtime_get_sync(struct device *d) { assert(!active->lock); d->refs++; return d->get_error; }
static int pm_runtime_resume_and_get(struct device *d)
{
	assert(!active->lock);
	if (pm_boundary_intent >= 0) {
		int value = pm_boundary_intent;
		pm_boundary_intent = -1;
		/* Worker obtained PM after system sleep acquired the connection gate. */
		active->gadget_suspended = 1;
		musb_gadget_pullup(&active->g, value);
	}
	if (d->get_error) return d->get_error;
	d->refs++;
	return 0;
}
static void pm_runtime_put_noidle(struct device *d) { assert(d->refs > 0); d->refs--; }
static void pm_runtime_put_autosuspend(struct device *d) { assert(!active->lock); pm_runtime_put_noidle(d); }
static void pm_runtime_mark_last_busy(struct device *d) { (void)d; }
static void schedule_delayed_work(struct delayed_work *w, int delay)
{ assert(active->lock && !active->gadget_suspended && !delay && !removing); w->queued = true; }
static void cancel_delayed_work_sync(struct delayed_work *w)
{
	assert(!active->lock);
	if (cancel_runs_worker && w->queued) musb_gadget_work(&w->work);
	w->queued = false;
}
static bool flush_delayed_work(struct delayed_work *w) { assert(w == &active->irq_work); return false; }
static void usb_del_gadget_udc(struct usb_gadget *g)
{
	assert(!active->lock);
	if (unregister_queues) musb_gadget_pullup(g, 0);
	musb_gadget_stop(g);
	removing = true;
}
static u8 musb_readb(void *p, unsigned off) { assert(active->controller->refs > 0); return ((u8 *)p)[off]; }
static u16 musb_readw(void *p, unsigned off) { return musb_readb(p, off) | (musb_readb(p, off + 1) << 8); }
static void musb_writeb(void *p, unsigned off, u8 v)
{
	assert(active->controller->refs > 0);
	if (p == active->mregs && off == MUSB_POWER && (v & MUSB_POWER_SOFTCONN) && gated_case)
		assert(!restoring && restored && irq_ready && platform_ready && work_ready && !active->gadget_suspended);
	if (p == active->mregs && off == MUSB_DEVCTL && !v && gated_case && !restoring)
		assert(!(banks[0][MUSB_POWER] & MUSB_POWER_SOFTCONN));
	((u8 *)p)[off] = v;
	writes++;
}
static void musb_writew(void *p, unsigned off, u16 v) { musb_writeb(p, off, v); musb_writeb(p, off + 1, v >> 8); }
#define TARGET_HELPERS(name, off) \
static u8 musb_read_##name(struct musb *m, unsigned ep) \
{ (void)m; return musb_readb(banks[4 + ep], off); } \
static void musb_write_##name(struct musb *m, unsigned ep, u8 v) \
{ (void)m; musb_writeb(banks[4 + ep], off, v); }
TARGET_HELPERS(txfunaddr, 0)
TARGET_HELPERS(txhubaddr, 1)
TARGET_HELPERS(txhubport, 2)
TARGET_HELPERS(rxfunaddr, 3)
TARGET_HELPERS(rxhubaddr, 4)
TARGET_HELPERS(rxhubport, 5)

static void musb_platform_disable(struct musb *m) { (void)m; platform_ready = false; }
static void musb_disable_interrupts(struct musb *m) { (void)m; irq_ready = false; }
static void musb_enable_interrupts(struct musb *m) { (void)m; restored = true; irq_ready = true; }
static void musb_platform_enable(struct musb *m) { (void)m; assert(irq_ready); platform_ready = true; }
static void musb_hnp_stop(struct musb *m) { (void)m; }
static int musb_gadget_vbus_draw(struct usb_gadget *g, unsigned n) { (void)g; (void)n; return 0; }
static void musb_set_state(struct musb *m, int n) { (void)m; (void)n; }
static void musb_stop(struct musb *m) { (void)m; }
static void otg_set_peripheral(void *otg, void *p) { (void)otg; (void)p; }
static void phy_set_mode(void *phy, int mode) { (void)phy; (void)mode; }
static void musb_platform_try_idle(struct musb *m, int n) { (void)m; (void)n; }
static void usb_gadget_set_state(struct usb_gadget *g, int n) { (void)g; (void)n; }

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsign-compare"
#include "musb_sleep_functions.h"
#pragma GCC diagnostic pop

static void init(struct musb *m, struct device *d, struct config *c, struct musb_platform_ops *ops)
{
	memset(m, 0, sizeof(*m)); memset(d, 0, sizeof(*d)); memset(ops, 0, sizeof(*ops));
	memset(banks, 0, sizeof(banks)); c->num_eps = MUSB_C_NUM_EPS;
	m->controller = d; m->config = c; m->ops = ops; m->mregs = banks[0];
	m->port_mode = MUSB_PERIPHERAL; m->softconnect = true; m->gadget_driver = m;
	m->pending_list.next = m->pending_list.prev = &m->pending_list;
	for (unsigned i = 0; i < MUSB_C_NUM_EPS; i++) m->endpoints[i].regs = banks[i + 1];
	banks[0][MUSB_POWER] = MUSB_POWER_SOFTCONN | MUSB_POWER_HSENAB;
	active = m; writes = errors = 0; gated_case = restoring = false;
	restored = irq_ready = platform_ready = work_ready = true;
	cancel_runs_worker = unregister_queues = removing = false;
	pm_boundary_intent = callback_intent = -1;
	m->nIrq = 164;
	irqchip = (struct irq_chip){.irq_set_wake = irqchip_wake};
	irqdesc = (struct irq_desc){.irq_data = {.chip = &irqchip}};
	wake_on_error = wake_off_error = wake_on_calls = wake_off_calls = 0;
	wake_hardware = false; wake_backend_live = true;
	wake_init_calls = freed_irqs = freed_hosts = 0;
}
static int callback(struct musb *m, void *data)
{
	assert(m->lock && irq_ready && platform_ready);
	assert(!gated_case || !(banks[0][MUSB_POWER] & MUSB_POWER_SOFTCONN));
	if (callback_intent >= 0) m->softconnect = callback_intent;
	work_ready = true;
	return *(int *)data;
}
static void add_work(struct musb *m, struct musb_pending_work *w, int *result)
{
	w->callback = callback; w->data = result;
	w->node = (struct list_head){&m->pending_list, m->pending_list.prev};
	m->pending_list.prev->next = &w->node; m->pending_list.prev = &w->node;
}
static bool connected(void) { return banks[0][MUSB_POWER] & MUSB_POWER_SOFTCONN; }

static void wake_cases(void)
{
	struct musb m; struct device d; struct config c; struct musb_platform_ops ops;
	/* Fresh probe tests wake capability without leaving its reference held. */
	for (int foreign = 0; foreign < 3; foreign++)
	for (int skip = 0; skip < 2; skip++) {
		init(&m, &d, &c, &ops);
		irqchip.flags = skip ? IRQCHIP_SKIP_SET_WAKE : 0;
		for (int i = 0; i < foreign; i++) assert(!enable_irq_wake(m.nIrq));
		assert(!musb_init_wakeup(&m));
		assert(d.capable && d.wake && m.wakeup_initialized && !m.irq_wake);
		assert(irqdesc.wake_depth == (unsigned)foreign);
		assert(wake_on_calls == (!skip && !foreign ? 1 : !skip));
		assert(wake_off_calls == (!skip && !foreign ? 1 : 0));
		musb_cleanup_wakeup(&m);
		assert(!d.capable && !d.wake && !m.wakeup_initialized && !m.irq_wake);
		assert(irqdesc.wake_depth == (unsigned)foreign);
		for (int i = 0; i < foreign; i++) assert(!disable_irq_wake(m.nIrq));
		wake_backend_live = false; musb_free(&m);
		assert(freed_irqs == 1 && freed_hosts == 1 && !irqdesc.wake_depth); scenarios++;
	}
	/* Unsupported wake is optional, not a reason to lose normal USB. */
	init(&m, &d, &c, &ops); irqchip.irq_set_wake = NULL;
	assert(!musb_init_wakeup(&m) && !d.capable && !wake_init_calls && !irqdesc.wake_depth);
	musb_cleanup_wakeup(&m); assert(!errors); scenarios++;
	/* Reject a preexisting capability/source/wakeirq without taking ownership. */
	for (int kind = 0; kind < 3; kind++) {
		init(&m, &d, &c, &ops);
		d.capable = kind == 0; d.power.wakeup = kind == 1 ? &d : NULL;
		d.power.wakeirq = kind == 2 ? &d : NULL;
		assert(musb_init_wakeup(&m) == -EEXIST);
		musb_cleanup_wakeup(&m);
		assert(!wake_init_calls && !wake_on_calls && !m.wakeup_initialized);
		assert(d.capable == (kind == 0) && !!d.power.wakeup == (kind == 1));
		assert(!!d.power.wakeirq == (kind == 2)); scenarios++;
	}
	/* Partial capability initialization is owned until probe unwind. */
	init(&m, &d, &c, &ops); d.init_error = -ENOMEM;
	assert(musb_init_wakeup(&m) == -ENOMEM && d.capable && m.wakeup_initialized);
	assert(!irqdesc.wake_depth && !m.irq_wake);
	musb_cleanup_wakeup(&m); assert(!d.capable && !d.wake && !m.wakeup_initialized); scenarios++;
	/* A failed probe disarm is reported and retained, then recovered on unwind. */
	init(&m, &d, &c, &ops); wake_off_error = -EIO;
	assert(musb_init_wakeup(&m) == -EIO && m.irq_wake && irqdesc.wake_depth == 1);
	assert(!d.capable && !wake_init_calls);
	musb_cleanup_wakeup(&m); assert(errors == 1 && m.irq_wake && irqdesc.wake_depth == 1);
	wake_off_error = 0; musb_cleanup_wakeup(&m);
	assert(!m.irq_wake && !irqdesc.wake_depth && !wake_hardware); scenarios++;
	/* Policy may change before resume: release our arm, not another owner's. */
	for (int foreign = 0; foreign < 3; foreign++)
	for (int policy = 0; policy < 2; policy++)
	for (int changed = 0; changed < 2; changed++) {
		init(&m, &d, &c, &ops); d.wake = policy;
		for (int i = 0; i < foreign; i++) assert(!enable_irq_wake(m.nIrq));
		assert(!musb_suspend(&d)); assert(m.irq_wake == !!policy);
		assert(irqdesc.wake_depth == (unsigned)(foreign + policy));
		d.wake = changed;
		assert(!musb_resume(&d) && !d.refs && !m.irq_wake);
		assert(irqdesc.wake_depth == (unsigned)foreign);
		for (int i = 0; i < foreign; i++) assert(!disable_irq_wake(m.nIrq));
		scenarios++;
	}
	/* Wake-arm failure occurs before any gadget/register/platform changes. */
	init(&m, &d, &c, &ops); d.wake = true; wake_on_error = -EIO;
	assert(musb_suspend(&d) == -EIO && !d.refs && !writes && !m.gadget_suspended);
	assert(!m.irq_wake && !irqdesc.wake_depth && connected() && platform_ready && irq_ready); scenarios++;
	/* Failed resume disarm restores the controller/PM reference but retains debt. */
	init(&m, &d, &c, &ops); d.wake = true; assert(!musb_suspend(&d));
	d.wake = false; wake_off_error = -EIO;
	assert(musb_resume(&d) == -EIO && !d.refs && m.irq_wake && irqdesc.wake_depth == 1);
	assert(platform_ready && irq_ready);
	unsigned before = writes; int arms = wake_on_calls;
	assert(musb_suspend(&d) == -EIO && !d.refs && writes == before && wake_on_calls == arms);
	assert(m.irq_wake && irqdesc.wake_depth == 1);
	wake_off_error = 0;
	assert(!musb_suspend(&d) && !m.irq_wake && !irqdesc.wake_depth);
	assert(!musb_resume(&d) && !d.refs); scenarios++;
	/* No acquired runtime reference: do not touch even an old wake debt. */
	init(&m, &d, &c, &ops); assert(!enable_irq_wake(m.nIrq)); m.irq_wake = true;
	d.get_error = -EIO; before = wake_off_calls;
	assert(musb_suspend(&d) == -EIO && !d.refs && m.irq_wake);
	assert(wake_off_calls == (int)before && irqdesc.wake_depth == 1);
	musb_cleanup_wakeup(&m); assert(!m.irq_wake && !irqdesc.wake_depth); scenarios++;
	/* Terminal hardware-disarm failure is exposed; no fake balance or retry loop. */
	init(&m, &d, &c, &ops); assert(!musb_init_wakeup(&m));
	assert(!enable_irq_wake(m.nIrq)); m.irq_wake = true; wake_off_error = -EIO;
	musb_cleanup_wakeup(&m);
	assert(errors == 1 && m.irq_wake && irqdesc.wake_depth == 1 && !d.capable);
	before = wake_off_calls; wake_backend_live = false; musb_free(&m);
	assert(wake_off_calls == (int)before && freed_irqs == 1 && m.irq_wake); scenarios++;
}

int main(void)
{
	struct musb m; struct device d; struct config c; struct musb_platform_ops ops;
	/* Role/wake/quirk matrix, latest intent, queued worker, and unbound gadget. */
	for (int role = MUSB_HOST; role <= MUSB_OTG; role++)
	for (int wake = 0; wake < 2; wake++)
	for (int preserve = 0; preserve < 2; preserve++)
	for (int intent = 0; intent < 2; intent++)
	for (int bound = 0; bound < 2; bound++) {
		init(&m, &d, &c, &ops); m.port_mode = role; d.wake = wake;
		ops.quirks = preserve ? MUSB_PRESERVE_SESSION : 0;
		gated_case = role == MUSB_PERIPHERAL && !wake && !preserve;
		m.gadget_driver = bound ? &m : NULL;
		m.gadget_work.queued = true; cancel_runs_worker = true;
		/* PM boundary worker must see the gate before cancel drains it. */
		assert(!musb_suspend(&d)); assert(d.refs == 1);
		assert(m.gadget_suspended == gated_case);
		if (gated_case) {
			assert(!connected() && !m.gadget_work.queued && m.softconnect);
			assert(banks[0][MUSB_POWER] == MUSB_POWER_HSENAB);
			musb_gadget_pullup(&m.g, 0); musb_gadget_pullup(&m.g, intent);
			assert(!m.gadget_work.queued);
			/* Even unexpectedly stale saved SOFTCONN cannot attach early. */
			m.context.power |= MUSB_POWER_SOFTCONN;
			work_ready = false; restored = false;
		} else m.softconnect = intent;
		int ok = 0; struct musb_pending_work pending;
		add_work(&m, &pending, &ok);
		assert(!musb_resume(&d)); assert(d.refs == 0 && !m.gadget_suspended);
		assert(list_empty(&m.pending_list));
		if (gated_case) assert(connected() == (intent && bound));
		if (role == MUSB_HOST && !preserve) assert(banks[0][MUSB_DEVCTL] & MUSB_DEVCTL_SESSION);
		scenarios++;
	}
	/* Already-disconnected intent stays disconnected, even with queued work. */
	for (int queued = 0; queued < 2; queued++) {
		init(&m, &d, &c, &ops); gated_case = true; m.softconnect = false;
		banks[0][MUSB_POWER] &= ~MUSB_POWER_SOFTCONN;
		m.gadget_work.queued = queued; cancel_runs_worker = true;
		assert(!musb_suspend(&d)); assert(!musb_resume(&d));
		assert(!connected() && !m.softconnect && !d.refs && !m.gadget_work.queued); scenarios++;
	}
	/* Failed suspend get: no MMIO, no gate, no leaked reference. */
	init(&m, &d, &c, &ops); d.get_error = -5;
	assert(musb_suspend(&d) == -5 && !writes && !d.refs && !m.gadget_suspended); scenarios++;
	/* Worker get failure: no MMIO and no unowned put. */
	musb_gadget_work(&m.gadget_work.work); assert(!writes && !d.refs && errors == 1); scenarios++;
	/* A worker paused at the runtime-PM boundary cannot defeat a new gate. */
	init(&m, &d, &c, &ops); pm_boundary_intent = 0;
	musb_gadget_work(&m.gadget_work.work); assert(m.gadget_suspended && !writes && !d.refs); scenarios++;
	/* Ordinary unbound worker never reconnects; no system gate required. */
	init(&m, &d, &c, &ops); m.gadget_driver = NULL;
	musb_gadget_work(&m.gadget_work.work); assert(!connected() && !d.refs); scenarios++;
	/* Both first and later failures survive following successful callbacks. */
	for (int failure = 0; failure < 2; failure++) {
		init(&m, &d, &c, &ops); gated_case = true;
		assert(!musb_suspend(&d)); work_ready = false;
		struct musb_pending_work pending[3]; int results[] = {-5, -19, 0};
		if (failure) results[0] = 0;
		for (unsigned i = 0; i < 3; i++) add_work(&m, &pending[i], &results[i]);
		assert(musb_resume(&d) == (failure ? -19 : -5));
		assert(!connected() && m.gadget_suspended && !d.refs && list_empty(&m.pending_list)); scenarios++;
	}
	/* A later-device suspend abort uses the same resume path, with new intent. */
	for (int intent = 0; intent < 2; intent++) {
		init(&m, &d, &c, &ops); gated_case = true; assert(!musb_suspend(&d));
		callback_intent = intent; work_ready = false; int ok = 0; struct musb_pending_work pending;
		add_work(&m, &pending, &ok); assert(!musb_resume(&d));
		assert(connected() == intent && !d.refs && !m.gadget_suspended); scenarios++;
	}
	/* Stop overrides old intent and queued work; unregister-generated work is drained. */
	init(&m, &d, &c, &ops); assert(!musb_gadget_stop(&m.g));
	assert(!m.gadget_driver && !m.softconnect && !connected() && !d.refs);
	musb_gadget_work(&m.gadget_work.work); assert(!connected() && !d.refs); scenarios++;
	init(&m, &d, &c, &ops); unregister_queues = true;
	musb_gadget_cleanup(&m); assert(!m.gadget_work.queued && !connected() && !d.refs); scenarios++;
	/* Context use outside system sleep must retain the saved pull-up. */
	init(&m, &d, &c, &ops); d.refs = 1;
	musb_save_context(&m); banks[0][MUSB_POWER] = MUSB_POWER_RESUME;
	musb_restore_context(&m); assert(connected() && (banks[0][MUSB_POWER] & MUSB_POWER_RESUME)); scenarios++;
	wake_cases();
	printf("MUSB sleep/wake: %u source-function scenarios passed\n", scenarios);
	return 0;
}
