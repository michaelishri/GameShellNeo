/* Actual-source reference schedules; all hardware/device/work effects modeled. */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define EPROBE_DEFER 517
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
#define pr_err(...) ((void)0)
#define dev_dbg(...) ((void)0)
#define fallthrough __attribute__((__fallthrough__))
#define IS_ERR(p) ((uintptr_t)(p) > (uintptr_t)-4096)
#define OTG_FORCESTDBY 0
#define ENABLEFORCE 1
#define MUSB_DEVCTL 0
#define USB_MODE_HOST 1
#define USB_MODE_DEVICE 2
#define USB_MODE_DISCONNECT 3
#define USB_EVENT_ID 1
#define USB_EVENT_VBUS 2
#define USB_EVENT_NONE 3

typedef unsigned int u32;
enum musb_vbus_id_status { MUSB_UNKNOWN, MUSB_ID_GROUND, MUSB_VBUS_VALID,
	MUSB_ID_FLOAT, MUSB_VBUS_OFF };
enum { OTG_STATE_A_IDLE, OTG_STATE_A_WAIT_VRISE, OTG_STATE_A_WAIT_BCON,
	OTG_STATE_A_HOST, OTG_STATE_B_IDLE };
struct device { bool live; struct device *parent; };
struct musb;
struct platform_device { struct device dev; void *data; };
struct work_struct { bool pending; };
struct phy { bool live; };
struct usb_otg { int state; };
struct usb_phy { struct usb_otg *otg; int last_event, notifier; };
struct musb_platform_ops { int (*phy_callback)(enum musb_vbus_id_status); };
struct musb {
	struct device *controller;
	void *mregs;
	struct phy *phy;
	struct usb_phy *xceiv;
	void *gadget_driver;
	const struct musb_platform_ops *ops;
	int generation;
	bool irq_wake;
};

static pthread_mutex_t gate_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t gate_cond = PTHREAD_COND_INITIALIZER;
static bool entered, released, block_lookup, block_queue, block_pm;
static bool run_started, old_resources_live, child_bound;
static int late_access, generation_accessed, status_delivered, schedule_after_exit;
static int cancels;
static pthread_t actor;
static struct platform_device parent, child;

static void pause_actor(void)
{
	pthread_mutex_lock(&gate_lock);
	entered = true;
	pthread_cond_broadcast(&gate_cond);
	while (!released)
		pthread_cond_wait(&gate_cond, &gate_lock);
	pthread_mutex_unlock(&gate_lock);
}

static void wait_actor(void)
{
	pthread_mutex_lock(&gate_lock);
	while (!entered)
		pthread_cond_wait(&gate_cond, &gate_lock);
	pthread_mutex_unlock(&gate_lock);
}

static void release_actor(void)
{
	pthread_mutex_lock(&gate_lock);
	released = true;
	pthread_cond_broadcast(&gate_cond);
	pthread_mutex_unlock(&gate_lock);
}

static void *platform_get_drvdata(struct platform_device *dev)
{
	void *value = dev->data;

	if (dev == &child && block_lookup) {
		block_lookup = false;
		pause_actor();
	}
	return value;
}

static void *dev_get_drvdata(struct device *dev)
{
	assert(dev == &parent.dev);
	return parent.data;
}

static void observe_access(struct musb *musb)
{
	if (!old_resources_live && musb->generation == 1)
		late_access++;
	generation_accessed = musb->generation;
	status_delivered = musb->xceiv->last_event;
}

static u32 musb_readl(void *base, int reg) { (void)base; (void)reg; return 0; }
static void musb_writel(void *base, int reg, u32 val)
{ (void)base; (void)reg; (void)val; }
static void schedule_work(struct work_struct *work)
{
	if (block_queue) {
		block_queue = false;
		pause_actor();
	}
	if (!old_resources_live)
		schedule_after_exit++;
	work->pending = true;
}
static void cancel_work_sync(struct work_struct *work)
{
	cancels++;
	work->pending = false;
	if (run_started) {
		release_actor();
		assert(!pthread_join(actor, NULL));
		run_started = false;
	}
}
static void phy_power_off(struct phy *phy) { assert(phy); phy->live = false; }
static void phy_exit(struct phy *phy) { assert(phy); old_resources_live = false; }
static int pm_runtime_get_sync(struct device *dev)
{
	assert(dev);
	if (block_pm) {
		block_pm = false;
		pause_actor();
	}
	return 0;
}
static void pm_runtime_mark_last_busy(struct device *dev) { assert(dev); }
static void pm_runtime_put_autosuspend(struct device *dev) { assert(dev); }
static void pm_runtime_disable(struct device *dev) { assert(dev); }
static void device_init_wakeup(struct device *dev, int enable)
{ assert(dev); assert(!enable); }
static int musb_set_host(struct musb *musb) { observe_access(musb); return 0; }
static void musb_set_peripheral(struct musb *musb) { observe_access(musb); }
static void otg_set_vbus(struct usb_otg *otg, int on) { (void)on; assert(otg); }
static void omap_control_usb_set_mode(struct device *dev, int mode)
{ (void)mode; assert(dev); }
static void atomic_notifier_call_chain(int *chain, int event, void *data)
{ (void)chain; (void)data; status_delivered = event; }
static void put_device(struct device *dev) { assert(dev); }
static void platform_device_unregister(struct platform_device *dev)
{ assert(dev == &child && !child_bound); dev->dev.live = false; }
static void musb_shutdown_resume_work(struct musb *musb) { assert(musb); }
static int musb_platform_exit(struct musb *musb);

#include "omap_mailbox_reference_definitions.h"
#include "omap_mailbox_reference_functions.h"

static int musb_platform_exit(struct musb *musb) { return omap2430_musb_exit(musb); }

static struct omap2430_glue glue;
static struct usb_otg otg[2];
static struct usb_phy xceiv[2];
static struct phy phys[2];
static const struct musb_platform_ops ops = { .phy_callback = omap2430_musb_mailbox };
static struct musb instances[2];

static void reset(void)
{
	memset(&glue, 0, sizeof(glue));
	memset(instances, 0, sizeof(instances));
	memset(otg, 0, sizeof(otg));
	parent = (struct platform_device) { .dev.live = true, .data = &glue };
	child = (struct platform_device) { .dev = { .live = true, .parent = &parent.dev },
		.data = &instances[0] };
	glue.dev = &parent.dev;
	glue.musb = &child;
	glue.control_otghs = &parent.dev;
	_glue = &glue;
	for (int i = 0; i < 2; i++) {
		phys[i].live = true;
		xceiv[i] = (struct usb_phy) { .otg = &otg[i] };
		instances[i] = (struct musb) { .controller = &child.dev, .phy = &phys[i],
			.xceiv = &xceiv[i], .ops = &ops, .generation = i + 1 };
	}
	entered = released = block_lookup = block_queue = block_pm = false;
	run_started = false;
	old_resources_live = child_bound = true;
	late_access = generation_accessed = status_delivered = schedule_after_exit = cancels = 0;
	reference_publish(&instances[0]);
}

static void *worker_actor(void *unused)
{
	(void)unused;
	omap_musb_mailbox_work(&glue.omap_musb_mailbox_work);
	return NULL;
}

static void *dispatch_actor(void *unused)
{
	(void)unused;
	assert(musb_mailbox(MUSB_VBUS_OFF) == 0);
	return NULL;
}

int main(void)
{
	/* A: a running worker resumes only after exit has released the PHY. */
	reset();
	glue.status = MUSB_VBUS_OFF;
	block_pm = true;
	run_started = true;
	assert(!pthread_create(&actor, NULL, worker_actor, NULL));
	wait_actor();
	assert(!omap2430_musb_exit(&instances[0]));
	assert(late_access == 1 && cancels == 1 && !run_started);

	/* B: a dispatcher admitted before cancel queues after cancel returns. */
	reset();
	block_lookup = true;
	assert(!pthread_create(&actor, NULL, dispatch_actor, NULL));
	wait_actor();
	assert(!omap2430_musb_exit(&instances[0]));
	release_actor();
	assert(!pthread_join(actor, NULL));
	assert(schedule_after_exit == 1 && glue.omap_musb_mailbox_work.pending);
	omap_musb_mailbox_work(&glue.omap_musb_mailbox_work);
	assert(late_access == 1);

	/* C: exact published fail2 arm never revokes owner/callback. */
	reset();
	reference_fail2(&instances[0]);
	child_bound = false;
	child.data = NULL;
	omap2430_remove(&parent);
	assert(musb_phy_callback == omap2430_musb_mailbox && _glue == &glue);
	assert(!child.dev.live && musb_mailbox(MUSB_VBUS_OFF) == -EPROBE_DEFER);

	/* D: an old admitted dispatch queues work for the replacement child. */
	reset();
	block_queue = true;
	assert(!pthread_create(&actor, NULL, dispatch_actor, NULL));
	wait_actor();
	assert(!omap2430_musb_exit(&instances[0]));
	child.data = &instances[1];
	reference_publish(&instances[1]);
	release_actor();
	assert(!pthread_join(actor, NULL));
	omap_musb_mailbox_work(&glue.omap_musb_mailbox_work);
	assert(generation_accessed == 2 && status_delivered == USB_EVENT_NONE);
	puts("OMAP mailbox baseline: 4 actual-source schedules reproduced");
	return 0;
}
