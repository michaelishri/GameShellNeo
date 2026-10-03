/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual probe/remove and wake helpers; hardware/allocation boundaries are shims. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
#define __iomem
#define CONFIG_PM 1
#define CONFIG_PM_SLEEP 1
#define CONFIG_USB_PHY 1
#define EPROBE_DEFER 517
#define RPM_GET_PUT 1
#define IS_ENABLED(option) (option)
#define IRQ_GET_DESC_CHECK_GLOBAL 0
#define IRQCHIP_SKIP_SET_WAKE 1
#define IRQD_WAKEUP_STATE 1
#define IRQF_SHARED 1
#define MUSB_HOST 1
#define MUSB_PERIPHERAL 2
#define MUSB_OTG 3
#define MUSB_INDEXED_EP 1
#define MUSB_G_NO_SKB_RESERVE 2
#define MUSB_CONTROLLER_MHDRC 1
#define MUSB_CONTROLLER_HDRC 2
#define MUSB_DEVCTL 0
#define MUSB_POWER 1
#define MUSB_ULPI_BUSCONTROL 2
#define MUSB_ULPI_USE_EXTVBUS 1
#define OTG_STATE_B_IDLE 1
#define IS_ERR(p) ((intptr_t)(p) < 0 && (intptr_t)(p) > -4096)
#define PTR_ERR(p) ((int)(intptr_t)(p))

struct musb;
struct config { bool multipoint; };
struct device {
	bool capable, wake, runtime_enabled;
	int refs;
	void *dma_mask, *platdata;
	struct { void *wakeup, *wakeirq; } power;
};
struct platform_device { struct device dev; };
struct work_struct { bool initialized; };
struct transceiver { void *io_ops, *io_dev, *io_priv; };
typedef void (*io_fn)(void);
struct musb_platform_ops {
	unsigned quirks, fifo_mode;
	io_fn ep_offset, ep_select, fifo_offset, busctl_offset;
	io_fn read_fifo, write_fifo, get_toggle, set_toggle, phy_callback;
	u8 (*readb)(void *, unsigned);
	void (*writeb)(void *, unsigned, u8);
	u8 (*clearb)(void *, unsigned);
	u16 (*readw)(void *, unsigned);
	void (*writew)(void *, unsigned, u16);
	u16 (*clearw)(void *, unsigned);
	void *(*dma_init)(struct musb *, void *);
	void (*dma_exit)(void *);
};
struct musb_hdrc_platform_data {
	struct config *config;
	struct musb_platform_ops *platform_ops;
	int min_power, mode, power;
	bool extvbus;
};
struct musb {
	struct device *controller;
	struct musb_platform_ops *ops;
	struct transceiver *xceiv;
	void *mregs, *dma_controller;
	struct { io_fn ep_offset, ep_select, fifo_offset, busctl_offset;
		io_fn read_fifo, write_fifo, get_toggle, set_toggle; } io;
	struct { bool quirk_avoids_skb_reserve; } g;
	struct work_struct irq_work, finish_resume_work, deassert_reset_work;
	int nIrq, lock, list_lock, min_power, port_mode, otg_timer;
	bool irq_wake, wakeup_initialized, is_initialized;
	io_fn isr;
};
enum failure {
	OK, ALLOC, PLATFORM, NO_ISR, NO_DMA_OP, PHY, DMA, CORE, REQUEST,
	ARM_UNSUPPORTED, DISARM, SOURCE, HOST, GADGET, MODE, SOURCE_POLICY_RACE
};
static enum failure failure;
static bool permanent_disarm;
static struct musb instance;
static struct transceiver transceiver;
static struct musb_hdrc_platform_data plat;
static struct musb_platform_ops ops;
static struct config config;
static unsigned scenarios, request_calls, free_calls, wake_calls, source_calls;
static unsigned chip_off_calls, cleanup_calls, errors, host_frees;
static bool requested, platform_live, phy_live, chip_live, sources_masked;
static bool dma_live, capability_owned;
static bool hold_platform_ref, platform_ref, runtime_ready, autosuspend;
static int resume_result;
static unsigned get_calls, noidle_calls, put_calls, phy_calls, mmio_calls;
static int fifo_mode, musb_ulpi_access;
static bool use_dma;
static io_fn musb_phy_callback;
static void *(*musb_dma_controller_create)(struct musb *, void *);
static void (*musb_dma_controller_destroy)(void *);
static u8 registers[8];

#define dev_err(...) do { errors++; } while (0)
#define dev_err_probe(...) do { errors++; } while (0)
#define WARN(value, ...) assert(!(value))
#define spin_lock_init(p) (*(p) = 0)
#define spin_lock_irqsave(p, flags) do { (flags) = 0; assert(!*(p)); *(p) = 1; } while (0)
#define spin_unlock_irqrestore(p, flags) do { (void)(flags); assert(*(p)); *(p) = 0; } while (0)
#define INIT_DELAYED_WORK(p, fn) do { (void)(fn); (p)->initialized = true; } while (0)
#define timer_setup(p, fn, flags) do { (void)(fn); (void)(flags); *(p) = 1; } while (0)
#define MUSB_DEV_MODE(m) ((void)(m))
static void noop(void) {}
#define musb_indexed_ep_offset noop
#define musb_indexed_ep_select noop
#define musb_flat_ep_offset noop
#define musb_flat_ep_select noop
#define musb_default_fifo_offset noop
#define musb_default_busctl_offset noop
#define musb_default_read_fifo noop
#define musb_default_write_fifo noop
#define musb_default_get_toggle noop
#define musb_default_set_toggle noop
#define musb_irq_work noop
#define musb_deassert_reset noop
#define musb_host_finish_resume noop
#define musb_otg_timer_func noop
static void mmio_check(void)
{ assert(runtime_ready && instance.controller->refs > (int)platform_ref); mmio_calls++; }
static u8 musb_default_readb(void *p, unsigned off) { mmio_check(); return ((u8 *)p)[off]; }
static void musb_default_writeb(void *p, unsigned off, u8 v) { mmio_check(); ((u8 *)p)[off] = v; }
static u16 musb_default_readw(void *p, unsigned off) { return musb_default_readb(p, off); }
static void musb_default_writew(void *p, unsigned off, u16 v) { musb_default_writeb(p, off, v); }
static u8 (*musb_readb)(void *, unsigned), (*musb_clearb)(void *, unsigned);
static void (*musb_writeb)(void *, unsigned, u8);
static u16 (*musb_readw)(void *, unsigned), (*musb_clearw)(void *, unsigned);
static void (*musb_writew)(void *, unsigned, u16);

struct irq_chip;
struct irq_data { unsigned flags; struct irq_chip *chip; };
struct irq_chip { unsigned flags; int (*irq_set_wake)(struct irq_data *, unsigned); };
struct irq_desc { struct irq_data irq_data; unsigned wake_depth; bool locked; };
static struct irq_desc desc;
static struct irq_chip chip;
static struct irq_desc *irq_to_desc(unsigned irq) { assert(irq == 164); return &desc; }
static struct irq_chip *irq_desc_get_chip(struct irq_desc *d) { return d->irq_data.chip; }
static bool irq_is_nmi(struct irq_desc *d) { (void)d; return false; }
static void irqd_set(struct irq_data *d, unsigned f) { d->flags |= f; }
static void irqd_clear(struct irq_data *d, unsigned f) { d->flags &= ~f; }
static struct irq_desc *get_desc(unsigned irq)
{ assert(irq == 164 && !desc.locked && !instance.lock); desc.locked = true; return &desc; }
static struct irq_desc *put_desc(struct irq_desc *d)
{ if (d) { assert(d->locked); d->locked = false; } return NULL; }
static void cleanup_desc(struct irq_desc **d) { put_desc(*d); }
#define scoped_irqdesc_get_and_buslock(irq, check) \
	for (struct irq_desc *scoped_irqdesc __attribute__((cleanup(cleanup_desc))) = get_desc(irq); \
	     scoped_irqdesc; scoped_irqdesc = put_desc(scoped_irqdesc))
int irq_set_irq_wake(unsigned irq, unsigned on);
static int enable_irq_wake(unsigned irq)
{ assert(requested && chip_live); wake_calls++; return irq_set_irq_wake(irq, 1); }
static int disable_irq_wake(unsigned irq)
{ assert(requested && chip_live && phy_live); wake_calls++; return irq_set_irq_wake(irq, 0); }
static int chip_wake(struct irq_data *d, unsigned on)
{
	assert(d == &desc.irq_data && desc.locked && chip_live);
	if (on && failure == ARM_UNSUPPORTED) return -EINVAL;
	if (!on && failure == DISARM && (!chip_off_calls++ || permanent_disarm)) return -EIO;
	return 0;
}
static bool device_can_wakeup(struct device *d) { return d->capable; }
static int device_init_wakeup(struct device *d, bool enable)
{
	source_calls++;
	if (enable) {
		assert(requested && platform_live && phy_live && !d->capable);
		d->capable = capability_owned = true;
		if (failure == SOURCE) return -ENOMEM;
		if (failure == SOURCE_POLICY_RACE) {
			/* A sysfs enable attaches a source during our owned capability window. */
			d->wake = true; d->power.wakeup = d; return -EEXIST;
		}
	} else {
		assert(capability_owned && platform_live && phy_live);
		capability_owned = false; d->capable = false;
	}
	d->wake = enable; d->power.wakeup = enable ? d : NULL;
	return 0;
}
static void *dev_get_platdata(struct device *d) { return d->platdata; }
static const char *dev_name(struct device *d) { (void)d; return "musb-test"; }
static struct musb *dev_to_musb(struct device *d) { assert(d == instance.controller); return &instance; }
static struct musb *allocate_instance(struct device *d, struct config *c, void *regs)
{
	(void)c;
	if (failure == ALLOC) return NULL;
	assert(!requested); memset(&instance, 0, sizeof(instance));
	instance.controller = d; instance.mregs = regs; instance.nIrq = -ENODEV;
	return &instance;
}
static int musb_platform_init(struct musb *m)
{
	if (failure == PLATFORM) return -EIO;
	platform_live = true; m->xceiv = &transceiver;
	if (hold_platform_ref) { m->controller->refs++; platform_ref = true; }
	m->isr = failure == NO_ISR ? NULL : noop; return 0;
}
static void musb_platform_exit(struct musb *m)
{
	assert(m == &instance && platform_live && !capability_owned);
	assert(!m->irq_wake || (failure == DISARM && permanent_disarm));
	if (platform_ref) { assert(m->controller->refs > 0); m->controller->refs--; platform_ref = false; }
	platform_live = chip_live = false;
}
static void pm_runtime_use_autosuspend(struct device *d) { (void)d; assert(!autosuspend); autosuspend = true; }
static void pm_runtime_set_autosuspend_delay(struct device *d, int n) { (void)d; assert(n == 500); }
static void pm_runtime_enable(struct device *d) { assert(!d->runtime_enabled); d->runtime_enabled = true; }
static int __pm_runtime_resume(struct device *d, int flags)
{
	assert(d->runtime_enabled && flags == RPM_GET_PUT); d->refs++; get_calls++;
	runtime_ready = resume_result >= 0; return resume_result;
}
static int pm_runtime_get_sync(struct device *d) { return __pm_runtime_resume(d, RPM_GET_PUT); }
static void __attribute__((unused)) pm_runtime_put_noidle(struct device *d)
{ assert(d->refs > (int)platform_ref); d->refs--; noidle_calls++; }
static void pm_runtime_put_sync(struct device *d) { assert(d->refs > (int)platform_ref); d->refs--; put_calls++; }
static void pm_runtime_put_autosuspend(struct device *d) { pm_runtime_put_sync(d); }
static void pm_runtime_mark_last_busy(struct device *d) { (void)d; }
static void pm_runtime_dont_use_autosuspend(struct device *d)
{
	assert(autosuspend);
	/* update_autosuspend can call rpm_idle: no unprotected idle on failure. */
	assert(!d->runtime_enabled || d->refs > (int)platform_ref);
	autosuspend = false;
}
static void pm_runtime_disable(struct device *d)
{ assert(d->refs == (int)platform_ref && d->runtime_enabled); d->runtime_enabled = false; }
static int usb_phy_init(struct transceiver *p)
{ assert(runtime_ready && p == &transceiver && platform_live); phy_calls++;
  if (failure == PHY) return -EIO;
  phy_live = true; return 0; }
static void usb_phy_shutdown(struct transceiver *p)
{
	assert(p == &transceiver && phy_live && !capability_owned);
	assert(!instance.irq_wake || (failure == DISARM && permanent_disarm));
	phy_live = false;
}
static void *dma_create(struct musb *m, void *regs)
{
	assert(m == &instance && regs == registers && phy_live);
	if (failure == DMA) return (void *)(intptr_t)-ENOMEM;
	dma_live = true; return &dma_live;
}
static void dma_destroy(void *p) { assert(p == &dma_live && dma_live); dma_live = false; }
static void musb_platform_disable(struct musb *m) { assert(m == &instance); }
static void musb_disable_interrupts(struct musb *m) { assert(m == &instance); sources_masked = true; }
static int musb_core_init(int type, struct musb *m)
{ (void)type; assert(m == &instance && sources_masked); return failure == CORE ? -EIO : 0; }
static void cancel_delayed_work_sync(struct work_struct *w)
{ assert(!instance.lock && w->initialized); cleanup_calls++; }
static int request_irq(int irq, io_fn fn, int flags, const char *name, struct musb *m)
{
	(void)name;
	assert(irq == 164 && fn && flags == IRQF_SHARED && m == &instance);
	assert(sources_masked && !registers[MUSB_POWER] && m->otg_timer);
	assert(m->irq_work.initialized && m->deassert_reset_work.initialized && m->finish_resume_work.initialized);
	request_calls++; if (failure == REQUEST) return -EBUSY;
	assert(!requested); requested = true; return 0;
}
static void free_irq(int irq, struct musb *m)
{
	assert(irq == 164 && requested && m == &instance && !m->wakeup_initialized);
	assert(!capability_owned && !platform_live && !phy_live);
	assert(!m->irq_wake || (failure == DISARM && permanent_disarm));
	requested = false; free_calls++;
}
static void musb_host_free(struct musb *m) { assert(m == &instance); host_frees++; }
static void musb_set_state(struct musb *m, int state) { (void)m; assert(state == OTG_STATE_B_IDLE); }
static int musb_host_setup(struct musb *m, int power)
{ (void)power; assert(m == &instance); return failure == HOST ? -EIO : 0; }
static int musb_gadget_setup(struct musb *m) { assert(m == &instance); return failure == GADGET ? -EIO : 0; }
static int musb_platform_set_mode(struct musb *m, int mode)
{ assert(m == &instance && mode == m->port_mode); return failure == MODE ? -EIO : 0; }
static void musb_host_cleanup(struct musb *m) { assert(m == &instance); }
static void musb_gadget_cleanup(struct musb *m) { assert(m == &instance); }
static void musb_init_debugfs(struct musb *m) { assert(m == &instance); }
static void musb_exit_debugfs(struct musb *m) { assert(m == &instance); }

#include "musb_wake_probe_functions.h"

static void init(struct platform_device *pdev, int role, enum failure fault, unsigned foreign)
{
	memset(&instance, 0, sizeof(instance)); memset(pdev, 0, sizeof(*pdev));
	memset(&transceiver, 0, sizeof(transceiver)); memset(registers, 0xff, sizeof(registers));
	request_calls = free_calls = wake_calls = source_calls = chip_off_calls = 0;
	cleanup_calls = errors = host_frees = 0;
	requested = platform_live = phy_live = sources_masked = dma_live = capability_owned = false;
	hold_platform_ref = platform_ref = runtime_ready = autosuspend = false;
	resume_result = 0; get_calls = noidle_calls = put_calls = phy_calls = mmio_calls = 0;
	chip_live = true; failure = fault; permanent_disarm = false;
	ops = (struct musb_platform_ops){.dma_init = dma_create, .dma_exit = dma_destroy};
	if (fault == NO_DMA_OP) ops.dma_exit = NULL;
	config = (struct config){.multipoint = true};
	plat = (struct musb_hdrc_platform_data){.mode = role, .platform_ops = &ops, .config = &config};
	pdev->dev.platdata = &plat; pdev->dev.dma_mask = pdev;
	chip = (struct irq_chip){.irq_set_wake = chip_wake};
	desc = (struct irq_desc){.irq_data = {.chip = &chip, .flags = foreign ? IRQD_WAKEUP_STATE : 0},
		.wake_depth = foreign};
	use_dma = true;
}

int main(void)
{
	struct platform_device pdev;
	for (int role = MUSB_HOST; role <= MUSB_OTG; role++)
	for (int fault = OK; fault <= SOURCE_POLICY_RACE; fault++)
	for (unsigned foreign = 0; foreign < 2; foreign++) {
		/* These faults are not reached in the selected role/shared-depth path. */
		if ((fault == HOST && role == MUSB_PERIPHERAL) || (fault == GADGET && role == MUSB_HOST) ||
		    (foreign && (fault == ARM_UNSUPPORTED || fault == DISARM))) continue;
		init(&pdev, role, fault, foreign);
		int ret = musb_init_controller(&pdev.dev, 164, registers);
		if (fault == OK || fault == ARM_UNSUPPORTED) {
			assert(!ret && instance.is_initialized && requested && !instance.irq_wake);
			assert(desc.wake_depth == foreign && !pdev.dev.refs);
			assert(pdev.dev.capable == (fault == OK));
			musb_remove(&pdev);
		} else {
			int expected = fault == ALLOC || fault == DMA || fault == SOURCE ? -ENOMEM :
				fault == NO_ISR || fault == NO_DMA_OP || fault == REQUEST ? -ENODEV :
				fault == SOURCE_POLICY_RACE ? -EEXIST : -EIO;
			assert(ret == expected);
			if (fault <= REQUEST) assert(!wake_calls && !source_calls);
		}
		assert(!requested && !platform_live && !phy_live && !dma_live && !capability_owned);
		assert(!pdev.dev.refs && !pdev.dev.runtime_enabled && !pdev.dev.capable && !pdev.dev.wake);
		assert(!instance.irq_wake && !instance.wakeup_initialized && desc.wake_depth == foreign);
		assert(free_calls == (fault > REQUEST || fault == OK));
		assert(host_frees == (fault != ALLOC)); scenarios++;
	}
	/* Existing state is rejected, with its source/policy/attachment untouched. */
	for (int kind = 0; kind < 4; kind++) {
		init(&pdev, MUSB_PERIPHERAL, OK, 0);
		pdev.dev.capable = kind < 2; pdev.dev.wake = kind == 0;
		pdev.dev.power.wakeup = kind == 0 || kind == 2 ? &pdev : NULL;
		pdev.dev.power.wakeirq = kind == 3 ? &pdev : NULL;
		assert(musb_init_controller(&pdev.dev, 164, registers) == -EEXIST);
		assert(!wake_calls && !source_calls && free_calls == 1 && !pdev.dev.refs);
		assert(pdev.dev.capable == (kind < 2) && pdev.dev.wake == (kind == 0));
		assert(!!pdev.dev.power.wakeup == (kind == 0 || kind == 2));
		assert(!!pdev.dev.power.wakeirq == (kind == 3)); scenarios++;
	}
	/* A terminal probe disarm failure is diagnosed and remains outstanding. */
	init(&pdev, MUSB_PERIPHERAL, DISARM, 0); permanent_disarm = true;
	assert(musb_init_controller(&pdev.dev, 164, registers) == -EIO);
	assert(errors >= 2 && desc.wake_depth == 1 && instance.irq_wake && free_calls == 1);
	assert(!platform_live && !phy_live && !requested && !pdev.dev.refs); scenarios++;
	/* Repeated real probe/remove functions must not accumulate references. */
	init(&pdev, MUSB_PERIPHERAL, OK, 1);
	for (int cycle = 0; cycle < 8; cycle++) {
		chip_live = true;
		assert(!musb_init_controller(&pdev.dev, 164, registers));
		assert(desc.wake_depth == 1 && !instance.irq_wake);
		musb_remove(&pdev);
		assert(desc.wake_depth == 1 && !requested && !pdev.dev.refs && !pdev.dev.capable);
		scenarios++;
	}
	/* Core reference accounting with and without a Sunxi-style backend hold.
	 * The lower PM engine reports both successful return values and failures;
	 * get_active/resume_and_get are extracted from the actual kernel header.
	 */
	const int results[] = {0, 1, -EIO, -EBUSY, -EACCES, -EPROBE_DEFER, -ETIMEDOUT};
	for (int role = MUSB_HOST; role <= MUSB_OTG; role++)
	for (unsigned hold = 0; hold < 2; hold++)
	for (unsigned i = 0; i < sizeof(results) / sizeof(results[0]); i++) {
		init(&pdev, role, OK, 0); hold_platform_ref = hold; resume_result = results[i];
		int ret = musb_init_controller(&pdev.dev, 164, registers);
		if (results[i] < 0) {
			assert(ret == results[i] && get_calls == 1 && noidle_calls == 1 && !put_calls);
			assert(!phy_calls && !mmio_calls && !request_calls && !cleanup_calls && !wake_calls);
			assert(!platform_live && !platform_ref && !pdev.dev.refs && !pdev.dev.runtime_enabled);
			assert(!instance.is_initialized && !autosuspend && !phy_live && !dma_live && host_frees == 1);
			/* A later reprobe must work without inheriting failed-get debt. */
			chip_live = true; resume_result = 0;
			assert(!musb_init_controller(&pdev.dev, 164, registers));
		} else {
			assert(!ret && get_calls == 1 && !noidle_calls && put_calls == 1);
		}
		assert(instance.is_initialized && phy_calls == 1 && mmio_calls && pdev.dev.refs == (int)hold);
		resume_result = 0; musb_remove(&pdev);
		assert(!platform_live && !platform_ref && !phy_live && !dma_live && !requested);
		assert(!pdev.dev.refs && !pdev.dev.runtime_enabled && !autosuspend); scenarios++;
	}
	printf("MUSB probe/remove wake: %u actual-source scenarios passed\n", scenarios);
	return 0;
}
