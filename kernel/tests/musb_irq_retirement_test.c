/* Controlled boundaries around actual MUSB release/removal/failure functions. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

struct device { int unused; };
struct musb {
	int nIrq, lock, irq_work, finish_resume_work, deassert_reset_work;
	bool irq_wake;
	struct device *controller;
	void *mregs, *dma_controller, *xceiv;
};
struct platform_device { struct device dev; };
static struct musb instance;
static struct platform_device platform;
static bool irq_live, peer_live, backend_live, clients_done, masks_set;
static bool in_remove, need_masks;
static int original_irq, frees, disarms, wake_error, wake_logs, host_frees;
static unsigned int cases;
static void *musb_phy_callback;

#define MUSB_DEVCTL 0x60
#define dev_err(dev, ...) ((void)(dev), wake_logs++)
#define dev_err_probe(...) ((void)0)
#define spin_lock_irqsave(lock, flags) do { assert(!*(lock)); *(lock) = 1; (flags) = 0; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); assert(*(lock)); *(lock) = 0; } while (0)

static struct musb *dev_to_musb(struct device *dev)
{
	assert(dev == &platform.dev);
	return &instance;
}

static int disable_irq_wake(int irq)
{
	assert(irq == original_irq && irq_live && !instance.lock);
	disarms++;
	return wake_error;
}

static void disable_irq(int irq)
{
	(void)irq;
	peer_live = false;
}

static void free_irq(int irq, void *data)
{
	assert(irq == original_irq && data == &instance && irq_live);
	assert(backend_live && clients_done && !instance.lock && peer_live);
	assert(!need_masks || masks_set);
	/* Model the final handler's resource use before the drain returns. */
	assert(backend_live);
	irq_live = false;
	frees++;
}

static void musb_platform_disable(struct musb *musb)
{
	assert(musb == &instance && backend_live && !musb->lock && clients_done);
}

static void musb_disable_interrupts(struct musb *musb)
{
	assert(musb == &instance && backend_live && musb->lock);
	masks_set = true;
}

static void musb_writeb(void *base, int offset, int value)
{
	assert(base == instance.mregs && instance.lock && backend_live);
	assert(offset == MUSB_DEVCTL && !value && masks_set);
}

static void musb_platform_exit(struct musb *musb)
{
	assert(musb == &instance && !irq_live && clients_done);
	backend_live = false;
}

static void musb_host_free(struct musb *musb)
{
	assert(musb == &instance && !irq_live);
	host_frees++;
}

static void musb_dma_controller_destroy(void *dma)
{
	assert(dma && !irq_live);
}

static void musb_exit_debugfs(struct musb *musb) { assert(musb == &instance); }
static void musb_host_cleanup(struct musb *musb)
{
	assert(musb == &instance && irq_live && backend_live && !clients_done);
}
static void musb_gadget_cleanup(struct musb *musb)
{
	assert(musb == &instance && irq_live && backend_live && !clients_done);
	clients_done = true;
}
static void cancel_delayed_work_sync(int *work) { (void)work; }
static void pm_runtime_get_sync(struct device *dev) { (void)dev; }
static void pm_runtime_dont_use_autosuspend(struct device *dev) { (void)dev; }
static void pm_runtime_put_sync(struct device *dev) { (void)dev; }
static void pm_runtime_disable(struct device *dev) { (void)dev; }
static void usb_phy_shutdown(void *phy) { (void)phy; }
static void device_init_wakeup(struct device *dev, int value)
{
	assert(dev == &platform.dev && !value);
}

#include "musb_irq_functions.h"

static void prepare(int irq, bool wake, int error, bool dma)
{
	memset(&instance, 0, sizeof(instance));
	instance.nIrq = original_irq = irq;
	instance.irq_wake = wake;
	instance.controller = &platform.dev;
	instance.mregs = &instance;
	instance.dma_controller = dma ? &platform : NULL;
	irq_live = irq >= 0;
	peer_live = backend_live = clients_done = true;
	masks_set = false;
	need_masks = true;
	wake_error = error;
	frees = disarms = wake_logs = host_frees = 0;
}

static void expect_released(bool owned, bool wake, int error)
{
	assert(!irq_live && peer_live && instance.nIrq == -ENODEV);
	assert(frees == (owned ? 1 : 0));
	assert(disarms == (owned && wake ? 1 : 0));
	assert(wake_logs == (owned && wake && error ? 1 : 0));
	assert(!instance.lock);
	cases++;
}

int main(void)
{
	int irq, wake, dma, path;
	static const int irqs[] = { 0, 23 };

	for (irq = 0; irq < 2; irq++)
		for (wake = 0; wake < 3; wake++) {
			int error = wake == 2 ? -EIO : 0;

			for (dma = 0; dma < 2; dma++)
				for (path = 0; path < 2; path++) {
					prepare(irqs[irq], wake != 0, error, dma);
					in_remove = path == 0;
					clients_done = !in_remove;
					if (in_remove)
						musb_remove(&platform);
					else
						assert(probe_failure(&instance, &platform.dev) == -EIO);
					assert(!backend_live && host_frees == 1);
					expect_released(true, wake != 0, error);
				}
			/* The allocation finalizer can also retire an owned action once. */
			prepare(irqs[irq], wake != 0, error, false);
			need_masks = false;
			musb_free_irq(&instance);
			musb_free(&instance);
			expect_released(true, wake != 0, error);
		}
	for (dma = 0; dma < 2; dma++) {
		prepare(-ENODEV, false, 0, dma);
		assert(probe_failure(&instance, &platform.dev) == -EIO);
		expect_released(false, false, 0);
	}
	prepare(-ENODEV, false, 0, false);
	backend_live = false;
	musb_free(&instance);
	expect_released(false, false, 0);
	prepare(-ENODEV, false, 0, false);
	backend_live = false;
	musb_shutdown_irq(&instance);
	expect_released(false, false, 0);
	assert(cases == 34);
	printf("MUSB IRQ retirement: %u source scenarios passed\n", cases);
	return 0;
}
