/* Bounded actual-source lifetime tests. Linux PM/work/PHY effects are models. */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#define __rcu
#define EPROBE_DEFER 517
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
#define dev_dbg(...) ((void)0)
#define dev_err(...) ((void)0)
#define fallthrough __attribute__((__fallthrough__))
#define IS_ERR(p) ((uintptr_t)(p) > (uintptr_t)-4096)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define READ_ONCE(x) __atomic_load_n(&(x), __ATOMIC_ACQUIRE)
#define rcu_access_pointer(x) READ_ONCE(x)
#define rcu_assign_pointer(p, v) __atomic_store_n(&(p), (v), __ATOMIC_RELEASE)
#define RCU_INIT_POINTER(p, v) rcu_assign_pointer(p, v)
#define srcu_dereference(p, s) ((void)(s), READ_ONCE(p))
#define OTG_FORCESTDBY 0
#define OTG_INTERFSEL 1
#define ENABLEFORCE 1
#define ULPI_12PIN 2
#define UTMI_8BIT 4
#define MUSB_INTERFACE_UTMI 1
#define USB_MODE_HOST 1
#define USB_MODE_DEVICE 2
#define USB_MODE_DISCONNECT 3
#define USB_EVENT_ID 1
#define USB_EVENT_VBUS 2
#define USB_EVENT_NONE 3

typedef unsigned int u32;
typedef pthread_mutex_t spinlock_t;
#define DEFINE_MUTEX(n) pthread_mutex_t n = PTHREAD_MUTEX_INITIALIZER
#define mutex_lock(m) assert(!pthread_mutex_lock(m))
#define mutex_unlock(m) assert(!pthread_mutex_unlock(m))
#define spin_lock_irqsave(m, f) do { (f) = 0; mutex_lock(m); } while (0)
#define spin_unlock_irqrestore(m, f) do { (void)(f); mutex_unlock(m); } while (0)

enum phase { PHASE_NONE, PHASE_DISPATCH, PHASE_WORK, PHASE_PARENT };
enum actor_kind { ACTOR_NONE, ACTOR_DISPATCH, ACTOR_WORK, ACTOR_SUSPEND, ACTOR_RESUME };
static _Thread_local enum actor_kind current_actor;
struct srcu_struct {
	pthread_mutex_t lock;
	pthread_cond_t condition;
	int readers;
	enum phase phase;
};
#define DEFINE_STATIC_SRCU(n) static struct srcu_struct n = { \
	.lock = PTHREAD_MUTEX_INITIALIZER, .condition = PTHREAD_COND_INITIALIZER, \
	.phase = PHASE_DISPATCH }
struct work_struct {
	pthread_mutex_t lock;
	pthread_cond_t condition;
	void (*fn)(struct work_struct *);
	bool pending, running;
	int disabled;
};
enum musb_vbus_id_status { MUSB_UNKNOWN, MUSB_ID_GROUND, MUSB_VBUS_VALID,
	MUSB_ID_FLOAT, MUSB_VBUS_OFF };
enum { OTG_STATE_A_IDLE, OTG_STATE_A_WAIT_VRISE, OTG_STATE_A_WAIT_BCON,
	OTG_STATE_A_HOST, OTG_STATE_B_IDLE };
struct environment;
struct device {
	struct device *parent;
	void *data, *platform_data;
	struct environment *owner;
	pthread_mutex_t lock;
};
struct platform_device { struct device dev; };
struct phy { int initialized, powered; };
struct usb_otg { int state; };
struct usb_phy { struct usb_otg *otg; int last_event, notifier; };
struct musb;
struct musb_platform_ops {
	int (*phy_callback)(struct musb *, enum musb_vbus_id_status);
	void (*phy_callback_quiesce)(struct musb *);
};
struct musb {
	struct device *controller;
	struct phy *phy;
	struct usb_phy *xceiv;
	void *mregs, *gadget_driver;
	void (*isr)(void);
	const struct musb_platform_ops *ops;
	struct { u32 otg_interfsel; } context;
	int generation;
};
struct omap_musb_board_data { int interface_type; };
struct musb_hdrc_platform_data { struct omap_musb_board_data *board_data; };

#include "omap_mailbox_definitions.h"

struct environment {
	struct platform_device parent, child;
	struct omap2430_glue glue;
	struct musb instances[2];
	struct phy phys[2];
	struct usb_otg otg[2];
	struct usb_phy xceiv[2];
	struct musb_hdrc_platform_data platform_data;
	struct omap_musb_board_data board_data;
	bool clients_live;
	int selected, effects, accessed_generation, delivered, mmio, delay;
};
static struct environment env, other;
static pthread_mutex_t monitor = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static bool actor_entered, actor_release;
static enum actor_kind paused_actor;
static enum phase waiting_phase;
static atomic_bool retired;
static pthread_t actor_thread, retire_thread;

static struct timespec deadline(void)
{
	struct timespec ts;
	assert(!clock_gettime(CLOCK_REALTIME, &ts));
	ts.tv_sec += 5;
	return ts;
}

static void pause_if(enum actor_kind kind)
{
	if (current_actor != kind || paused_actor != kind)
		return;
	mutex_lock(&monitor);
	actor_entered = true;
	assert(!pthread_cond_broadcast(&changed));
	while (!actor_release)
		assert(!pthread_cond_wait(&changed, &monitor));
	mutex_unlock(&monitor);
}

static void observe_wait(enum phase phase)
{
	mutex_lock(&monitor);
	waiting_phase = phase;
	assert(!pthread_cond_broadcast(&changed));
	mutex_unlock(&monitor);
}

static void wait_actor(void)
{
	struct timespec ts = deadline();
	mutex_lock(&monitor);
	while (!actor_entered)
		assert(!pthread_cond_timedwait(&changed, &monitor, &ts));
	mutex_unlock(&monitor);
}

static void wait_retire(enum phase phase)
{
	struct timespec ts = deadline();
	mutex_lock(&monitor);
	while (waiting_phase != phase && !atomic_load(&retired))
		assert(!pthread_cond_timedwait(&changed, &monitor, &ts));
	assert(waiting_phase == phase && !atomic_load(&retired));
	assert(env.clients_live);
	mutex_unlock(&monitor);
}

static void release_actor(void)
{
	mutex_lock(&monitor);
	actor_release = true;
	assert(!pthread_cond_broadcast(&changed));
	mutex_unlock(&monitor);
}

static int srcu_read_lock(struct srcu_struct *srcu)
{
	mutex_lock(&srcu->lock);
	srcu->readers++;
	mutex_unlock(&srcu->lock);
	return 0;
}
static void srcu_read_unlock(struct srcu_struct *srcu, int idx)
{
	assert(idx == 0);
	mutex_lock(&srcu->lock);
	assert(srcu->readers > 0);
	srcu->readers--;
	assert(!pthread_cond_broadcast(&srcu->condition));
	mutex_unlock(&srcu->lock);
}
static void synchronize_srcu(struct srcu_struct *srcu)
{
	mutex_lock(&srcu->lock);
	if (srcu->readers)
		observe_wait(srcu->phase);
	while (srcu->readers)
		assert(!pthread_cond_wait(&srcu->condition, &srcu->lock));
	mutex_unlock(&srcu->lock);
}
static void cleanup_srcu_struct(struct srcu_struct *srcu) { assert(!srcu->readers); }

static bool schedule_work(struct work_struct *work)
{
	bool queued;
	mutex_lock(&work->lock);
	queued = !work->disabled && !work->pending;
	if (!work->disabled)
		work->pending = true;
	mutex_unlock(&work->lock);
	return queued;
}
static void disable_work_sync(struct work_struct *work)
{
	mutex_lock(&work->lock);
	work->disabled++;
	work->pending = false;
	if (work->running)
		observe_wait(PHASE_WORK);
	while (work->running)
		assert(!pthread_cond_wait(&work->condition, &work->lock));
	mutex_unlock(&work->lock);
}
static void enable_work(struct work_struct *work)
{
	mutex_lock(&work->lock);
	assert(work->disabled > 0);
	work->disabled--;
	mutex_unlock(&work->lock);
}
static void run_work(struct work_struct *work)
{
	mutex_lock(&work->lock);
	if (!work->pending || work->disabled) {
		mutex_unlock(&work->lock);
		return;
	}
	work->pending = false;
	work->running = true;
	mutex_unlock(&work->lock);
	current_actor = ACTOR_WORK;
	work->fn(work);
	current_actor = ACTOR_NONE;
	mutex_lock(&work->lock);
	work->running = false;
	assert(!pthread_cond_broadcast(&work->condition));
	mutex_unlock(&work->lock);
}

static void *dev_get_drvdata(struct device *dev)
{
	void *data = dev->data;
	pause_if(ACTOR_DISPATCH);
	return data;
}
static void *platform_get_drvdata(struct platform_device *dev) { return dev->dev.data; }
static void *dev_get_platdata(struct device *dev) { return dev->platform_data; }
static struct phy *devm_phy_get(struct device *dev, const char *name)
{ (void)name; return &dev->owner->phys[dev->owner->selected]; }
static struct usb_phy *devm_usb_get_phy_by_phandle(struct device *dev, const char *name, int n)
{ (void)name; assert(!n); return &dev->owner->xceiv[dev->owner->selected]; }
static int phy_init(struct phy *phy)
{ pause_if(ACTOR_RESUME); phy->initialized++; return 0; }
static int phy_exit(struct phy *phy)
{
	if (!phy->initialized)
		return -EINVAL;
	phy->initialized--;
	return 0;
}
static int phy_power_on(struct phy *phy) { phy->powered++; return 0; }
static int phy_power_off(struct phy *phy)
{
	pause_if(ACTOR_SUSPEND);
	if (!phy->powered)
		return -EINVAL;
	phy->powered--;
	return 0;
}
static void mmio_access(void *base)
{
	struct musb *musb = base;
	assert(musb->phy && musb->phy->initialized && musb->phy->powered);
	musb->controller->owner->mmio++;
}
static u32 musb_readl(void *base, int reg) { (void)reg; mmio_access(base); return 0; }
static void musb_writel(void *base, int reg, u32 val)
{ (void)reg; (void)val; mmio_access(base); }
static int pm_runtime_get_sync(struct device *dev)
{
	pause_if(ACTOR_WORK);
	if (current_actor == ACTOR_WORK)
		assert(READ_ONCE(dev->owner->glue.active_musb) == dev->data);
	return 0;
}
static void pm_runtime_mark_last_busy(struct device *dev) { assert(dev); }
static void pm_runtime_put_autosuspend(struct device *dev) { assert(dev); }
static void pm_runtime_disable(struct device *dev) { assert(dev); }
static void usleep_range(int lower, int upper)
{ assert(lower == 200000 && upper == 250000); env.delay++; }
static void effect(struct musb *musb)
{
	struct environment *e = musb->controller->owner;
	assert(e->clients_live && musb->phy && musb->phy->powered);
	e->effects++;
	e->accessed_generation = musb->generation;
}
static int musb_set_host(struct musb *musb) { effect(musb); return 0; }
static int musb_set_peripheral(struct musb *musb) { effect(musb); return 0; }
static void otg_set_vbus(struct usb_otg *otg, int value) { assert(otg); (void)value; }
static void omap_control_usb_set_mode(struct device *dev, int mode) { assert(dev); (void)mode; }
static void atomic_notifier_call_chain(int *chain, int event, void *data)
{ (void)chain; (void)data; env.delivered = event; }
static void put_device(struct device *dev) { assert(dev); }
static void platform_device_unregister(struct platform_device *dev);
static void omap2430_musb_interrupt(void) { }

#include "omap_mailbox_functions.h"

static const struct musb_platform_ops ops = {
	.phy_callback = omap2430_musb_mailbox,
	.phy_callback_quiesce = omap2430_musb_quiesce,
};

static void initialize(struct environment *e)
{
	memset(e, 0, sizeof(*e));
	e->parent.dev = (struct device) { .data = &e->glue, .owner = e };
	e->child.dev = (struct device) { .parent = &e->parent.dev, .owner = e,
		.platform_data = &e->platform_data };
	assert(!pthread_mutex_init(&e->child.dev.lock, NULL));
	e->platform_data.board_data = &e->board_data;
	e->board_data.interface_type = MUSB_INTERFACE_UTMI;
	e->glue.dev = &e->parent.dev;
	e->glue.musb = &e->child;
	e->glue.control_otghs = &e->parent.dev;
	assert(!pthread_mutex_init(&e->glue.status_lock, NULL));
	assert(!pthread_mutex_init(&e->glue.child_srcu.lock, NULL));
	assert(!pthread_cond_init(&e->glue.child_srcu.condition, NULL));
	e->glue.child_srcu.phase = PHASE_PARENT;
	struct work_struct *work = &e->glue.omap_musb_mailbox_work;
	assert(!pthread_mutex_init(&work->lock, NULL));
	assert(!pthread_cond_init(&work->condition, NULL));
	work->fn = omap_musb_mailbox_work;
	disable_work_sync(work);
	e->clients_live = true;
	for (int i = 0; i < 2; i++) {
		e->xceiv[i].otg = &e->otg[i];
		e->instances[i] = (struct musb) { .controller = &e->child.dev,
			.ops = &ops, .generation = i + 1 };
		e->instances[i].mregs = &e->instances[i];
	}
}
static void destroy(struct environment *e)
{
	if (READ_ONCE(e->glue.active_musb))
		musb_quiesce_mailbox(READ_ONCE(e->glue.active_musb));
	omap2430_cleanup_srcu(&e->glue);
	assert(!e->glue.omap_musb_mailbox_work.running);
	assert(!pthread_mutex_destroy(&e->child.dev.lock));
	assert(!pthread_mutex_destroy(&e->glue.status_lock));
	assert(!pthread_mutex_destroy(&e->glue.child_srcu.lock));
	assert(!pthread_cond_destroy(&e->glue.child_srcu.condition));
	assert(!pthread_mutex_destroy(&e->glue.omap_musb_mailbox_work.lock));
	assert(!pthread_cond_destroy(&e->glue.omap_musb_mailbox_work.condition));
}
static void bind_child(struct environment *e, int index)
{
	e->selected = index;
	e->child.dev.data = &e->instances[index];
	e->clients_live = true;
	assert(omap2430_musb_init(&e->instances[index]) == 0);
	assert(musb_register_mailbox(&e->instances[index]) == 0);
}
static void platform_device_unregister(struct platform_device *dev)
{
	struct musb *musb = dev->dev.data;
	if (musb) {
		musb_quiesce_mailbox(musb);
		dev->dev.owner->clients_live = false;
		assert(!omap2430_musb_exit(musb));
		dev->dev.data = NULL;
	}
}
static void *dispatch_main(void *unused)
{
	(void)unused;
	current_actor = ACTOR_DISPATCH;
	assert(musb_mailbox(MUSB_VBUS_OFF) == 0);
	return NULL;
}
static void *work_main(void *unused)
{ (void)unused; run_work(&env.glue.omap_musb_mailbox_work); return NULL; }
static void *suspend_main(void *unused)
{ (void)unused; current_actor = ACTOR_SUSPEND; assert(!omap2430_runtime_suspend(&env.parent.dev)); return NULL; }
static void *resume_main(void *unused)
{ (void)unused; current_actor = ACTOR_RESUME; assert(!omap2430_runtime_resume(&env.parent.dev)); return NULL; }
static void *retire_main(void *unused)
{
	(void)unused;
	mutex_lock(&env.child.dev.lock);
	musb_quiesce_mailbox(&env.instances[0]);
	assert(READ_ONCE(env.glue.active_musb) == NULL);
	env.clients_live = false;
	mutex_unlock(&env.child.dev.lock);
	mutex_lock(&monitor);
	atomic_store(&retired, true);
	assert(!pthread_cond_broadcast(&changed));
	mutex_unlock(&monitor);
	return NULL;
}
static void held(enum actor_kind kind, enum phase phase)
{
	bind_child(&env, 0);
	paused_actor = kind;
	if (kind == ACTOR_WORK)
		assert(!musb_mailbox(MUSB_VBUS_OFF));
	if (kind == ACTOR_RESUME)
		assert(!omap2430_runtime_suspend(&env.parent.dev));
	void *(*fn)(void *) = kind == ACTOR_DISPATCH ? dispatch_main :
		kind == ACTOR_WORK ? work_main : kind == ACTOR_SUSPEND ? suspend_main : resume_main;
	assert(!pthread_create(&actor_thread, NULL, fn, NULL));
	wait_actor();
	assert(!pthread_create(&retire_thread, NULL, retire_main, NULL));
	wait_retire(phase);
	if (kind == ACTOR_WORK)
		assert(READ_ONCE(env.glue.active_musb) == &env.instances[0]);
	release_actor();
	assert(!pthread_join(actor_thread, NULL));
	assert(!pthread_join(retire_thread, NULL));
	assert(atomic_load(&retired) && musb_mailbox(MUSB_VBUS_OFF) == -ENODEV);
}

static void no_owner(void) { assert(musb_mailbox(MUSB_VBUS_OFF) == -ENODEV); }
static void not_ready(void) { assert(omap2430_musb_mailbox(&env.instances[0], MUSB_VBUS_OFF) == -EPROBE_DEFER); }
static void delivery(void)
{ bind_child(&env, 0); assert(!musb_mailbox(MUSB_VBUS_OFF)); run_work(&env.glue.omap_musb_mailbox_work); assert(env.effects == 1 && env.accessed_generation == 1); }
static void coalescing(void)
{ bind_child(&env, 0); assert(!musb_mailbox(MUSB_VBUS_VALID)); assert(!musb_mailbox(MUSB_VBUS_OFF)); run_work(&env.glue.omap_musb_mailbox_work); assert(env.delivered == USB_EVENT_NONE && env.effects == 1); }
static void atomic_dispatch(void)
{ bind_child(&env, 0); assert(!musb_mailbox(MUSB_VBUS_OFF)); assert(!musb_mailbox_srcu.readers && !env.glue.child_srcu.readers && !env.effects); }
static void second_owner(void)
{ bind_child(&env, 0); other.child.dev.data = &other.instances[0]; assert(!omap2430_musb_init(&other.instances[0])); assert(musb_register_mailbox(&other.instances[0]) == -EBUSY); assert(READ_ONCE(musb_mailbox_owner) == &env.instances[0]); }
static void foreign_unregister(void)
{ bind_child(&env, 0); musb_quiesce_mailbox(&other.instances[0]); assert(!musb_mailbox(MUSB_VBUS_OFF)); assert(READ_ONCE(musb_mailbox_owner) == &env.instances[0]); }
static void owner_unregister(void)
{ bind_child(&env, 0); musb_quiesce_mailbox(&env.instances[0]); no_owner(); assert(!READ_ONCE(env.glue.active_musb)); }
static void held_dispatch(void) { held(ACTOR_DISPATCH, PHASE_DISPATCH); }
static void queued_retire(void)
{ bind_child(&env, 0); assert(!musb_mailbox(MUSB_VBUS_OFF)); musb_quiesce_mailbox(&env.instances[0]); run_work(&env.glue.omap_musb_mailbox_work); assert(!env.effects); }
static void held_work(void) { held(ACTOR_WORK, PHASE_WORK); }
static void clients_retire(void)
{ delivery(); musb_quiesce_mailbox(&env.instances[0]); env.clients_live = false; assert(!schedule_work(&env.glue.omap_musb_mailbox_work)); assert(env.effects == 1); }
static void child_remove(void)
{ bind_child(&env, 0); platform_device_unregister(&env.child); no_owner(); assert(!env.phys[0].powered && !env.phys[0].initialized); }
static void parent_remove(void)
{ bind_child(&env, 0); omap2430_remove(&env.parent); no_owner(); assert(!env.phys[0].powered && !env.phys[0].initialized); }
static void failed_parent(void) { no_owner(); assert(!READ_ONCE(env.glue.active_musb)); omap2430_cleanup_srcu(&env.glue); }
static void failed_probe(void)
{ bind_child(&env, 0); assert(!musb_mailbox(MUSB_VBUS_OFF)); candidate_failed_probe(&env.instances[0]); no_owner(); assert(!READ_ONCE(env.glue.active_musb)); run_work(&env.glue.omap_musb_mailbox_work); assert(!env.effects); }
static void rebind(void)
{ bind_child(&env, 0); assert(!musb_mailbox(MUSB_VBUS_VALID)); run_work(&env.glue.omap_musb_mailbox_work); assert(env.delivered == USB_EVENT_VBUS); platform_device_unregister(&env.child); bind_child(&env, 1); omap2430_musb_enable(&env.instances[1]); assert(env.delivered == USB_EVENT_VBUS); assert(!musb_mailbox(MUSB_VBUS_OFF)); run_work(&env.glue.omap_musb_mailbox_work); assert(env.accessed_generation == 2 && env.delivered == USB_EVENT_NONE); }
static void stale_dispatch(void)
{ bind_child(&env, 0); platform_device_unregister(&env.child); bind_child(&env, 1); assert(omap2430_musb_mailbox(&env.instances[0], MUSB_VBUS_OFF) == -EPROBE_DEFER); assert(env.glue.status == MUSB_UNKNOWN && !env.glue.omap_musb_mailbox_work.pending); }
static void stale_work(void)
{ bind_child(&env, 0); assert(!musb_mailbox(MUSB_VBUS_OFF)); platform_device_unregister(&env.child); bind_child(&env, 1); run_work(&env.glue.omap_musb_mailbox_work); assert(!env.effects); }
static void held_suspend(void) { held(ACTOR_SUSPEND, PHASE_PARENT); }
static void held_resume(void) { held(ACTOR_RESUME, PHASE_PARENT); }
static void no_child_suspend(void)
{ assert(!omap2430_runtime_suspend(&env.parent.dev)); assert(!env.mmio && !env.glue.is_runtime_suspended); }
static void no_child_resume(void)
{ assert(!omap2430_runtime_resume(&env.parent.dev)); assert(!env.mmio && !env.delay); }
static void closed_suspend(void)
{ bind_child(&env, 0); musb_quiesce_mailbox(&env.instances[0]); int before = env.mmio; assert(!omap2430_runtime_suspend(&env.parent.dev)); assert(env.mmio == before && !env.glue.is_runtime_suspended); }
static void closed_resume(void)
{ bind_child(&env, 0); musb_quiesce_mailbox(&env.instances[0]); int before = env.mmio; assert(!omap2430_runtime_resume(&env.parent.dev)); assert(env.mmio == before && !env.delay); }
static void rebound_suspend(void)
{ bind_child(&env, 0); platform_device_unregister(&env.child); bind_child(&env, 1); assert(!omap2430_runtime_suspend(&env.parent.dev)); assert(env.glue.is_runtime_suspended && !env.phys[1].powered && !env.phys[1].initialized); }
static void rebound_resume(void)
{ rebound_suspend(); assert(!omap2430_runtime_resume(&env.parent.dev)); assert(!env.glue.is_runtime_suspended && env.phys[1].powered == 1 && env.phys[1].initialized == 1 && env.delay == 1); }

static const struct { const char *name; void (*test)(void); } cases[] = {
	{ "no-owner", no_owner }, { "owner-not-ready", not_ready },
	{ "normal-delivery", delivery }, { "latest-status-coalescing", coalescing },
	{ "dispatch-atomic-context", atomic_dispatch }, { "second-owner-rejected", second_owner },
	{ "foreign-unregister-preserves-owner", foreign_unregister }, { "owner-unregister", owner_unregister },
	{ "dispatch-held-retire", held_dispatch }, { "queued-work-retire", queued_retire },
	{ "running-work-retire", held_work }, { "clients-after-work-drain", clients_retire },
	{ "child-remove", child_remove }, { "parent-remove", parent_remove },
	{ "failed-parent-probe-before-publish", failed_parent },
	{ "failed-core-runtime-get", failed_probe }, { "failed-core-phy-init", failed_probe },
	{ "failed-core-DMA", failed_probe }, { "failed-core-core-init", failed_probe },
	{ "failed-core-IRQ", failed_probe }, { "failed-core-role", failed_probe },
	{ "same-parent-rebind", rebind }, { "stale-dispatch-generation", stale_dispatch },
	{ "stale-work-generation", stale_work },
	{ "parent-suspend-held-drain", held_suspend }, { "parent-resume-held-drain", held_resume },
	{ "parent-suspend-closed-noop", closed_suspend }, { "parent-resume-closed-noop", closed_resume },
	{ "parent-suspend-no-child-noop", no_child_suspend }, { "parent-resume-no-child-noop", no_child_resume },
	{ "parent-suspend-after-rebind-newowner", rebound_suspend },
	{ "parent-resume-after-rebind-newowner", rebound_resume },
};

int main(void)
{
	assert(sizeof(cases) / sizeof(cases[0]) == 32);
	for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
		initialize(&env);
		initialize(&other);
		actor_entered = actor_release = false;
		paused_actor = ACTOR_NONE;
		waiting_phase = PHASE_NONE;
		atomic_store(&retired, false);
		cases[i].test();
		destroy(&other);
		destroy(&env);
		assert(!READ_ONCE(musb_mailbox_owner));
	}
	puts("OMAP mailbox candidate: 32 bounded lifetime scenarios passed");
	return 0;
}
