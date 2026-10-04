/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual MUSB callbacks and UDC unbind; pthread-controlled boundary races. */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdatomic.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef uint8_t u8;
typedef pthread_mutex_t spinlock_t;
typedef struct { pthread_mutex_t mutex; pthread_cond_t cv; } wait_queue_head_t;
#define __iomem
#define __releases(lock)
#define __acquires(lock)
#define __must_hold(lock)
#define TASK_INTERRUPTIBLE 1
#define TASK_WAKEKILL 2
#define TASK_UNINTERRUPTIBLE 4
#define WQ_FLAG_EXCLUSIVE 1
struct wait_queue_entry { wait_queue_head_t *queue; };
#define OTG_STATE_B_IDLE 1
#define OTG_STATE_B_WAIT_ACON 2
#define OTG_STATE_B_PERIPHERAL 3
#define OTG_STATE_A_IDLE 4
#define OTG_STATE_A_PERIPHERAL 5
#define OTG_STATE_A_WAIT_BCON 6
#define OTG_STATE_B_HOST 7
#define OTG_STATE_B_SRP_INIT 8
#define MUSB_DEVCTL 0
#define MUSB_POWER 1
#define MUSB_DEVCTL_VBUS 0x18
#define MUSB_DEVCTL_SESSION 1
#define MUSB_DEVCTL_HR 2
#define MUSB_DEVCTL_BDEVICE 0x80
#define MUSB_POWER_HSMODE 0x10
#define MUSB_EP0_STAGE_SETUP 0
#define USB_SPEED_UNKNOWN 0
#define USB_SPEED_HIGH 2
#define USB_SPEED_FULL 1
#define USB_STATE_DEFAULT 1
#define USB_STATE_NOTATTACHED 2
#define KOBJ_CHANGE 1
#define MUSB_HST_MODE(m) ((void)(m))
#define MUSB_DEV_MODE(m) ((void)(m))
#define musb_dbg(...) ((void)0)
#define dev_dbg(...) ((void)0)
#define dev_err(...) ((void)0)
#define WARNING(...) ((void)0)

struct usb_gadget;
struct usb_udc;
struct usb_ctrlrequest { int test; };
struct device_driver { int dummy; };
struct device { struct usb_gadget *owner; struct device_driver *driver; int kobj; };
struct usb_gadget_driver {
	struct device_driver driver;
	int (*bind)(struct usb_gadget *, struct usb_gadget_driver *);
	int max_speed;
	void (*resume)(struct usb_gadget *), (*suspend)(struct usb_gadget *);
	void (*disconnect)(struct usb_gadget *), (*reset)(struct usb_gadget *);
	void (*unbind)(struct usb_gadget *);
	int (*setup)(struct usb_gadget *, const struct usb_ctrlrequest *);
	bool is_bound;
};
struct usb_gadget_ops {
	int (*udc_start)(struct usb_gadget *, struct usb_gadget_driver *);
	void (*udc_async_callbacks)(struct usb_gadget *, bool);
	int (*udc_stop)(struct usb_gadget *);
};
struct usb_gadget {
	struct device dev;
	struct usb_udc *udc;
	const struct usb_gadget_ops *ops;
	int speed, state, irq;
	bool is_otg, is_a_peripheral, b_hnp_enable, a_alt_hnp_support, a_hnp_support, quirk_zlp_not_supp;
};
struct usb_udc {
	struct device dev;
	struct usb_gadget *gadget;
	struct usb_gadget_driver *driver;
	pthread_mutex_t connect_lock;
	bool started, allow_connect;
	int vbus_work;
};
struct musb {
	spinlock_t lock;
	struct usb_gadget g;
	struct usb_gadget_driver *gadget_driver;
	bool gadget_async_callbacks;
	unsigned int gadget_callback_count;
	wait_queue_head_t gadget_callback_wait;
	void *mregs;
	int state, address, ep0_state;
	bool is_active, is_suspended, may_wakeup;
};
struct usb_ep { int dummy; };
struct usb_request { int status, dma; };
struct musb_ep { struct musb *musb; struct usb_ep end_point; int busy; };
struct musb_request { struct usb_request request; struct musb *musb; struct musb_ep *ep; int list; };
static struct musb instance;
static struct usb_udc udc;
static struct usb_gadget_driver driver;
static struct usb_gadget_ops ops;
static pthread_mutex_t udc_lock = PTHREAD_MUTEX_INITIALIZER;
static u8 registers[2];
static _Thread_local bool locked, pause_on_unlock;
static _Thread_local bool queue_locked;
static _Thread_local wait_queue_head_t *current_wait;
static _Thread_local int worker = -1, depth;
static atomic_uint entered, finished, wait_sleeping, paused, resume_pause;
static atomic_uint releases[4], calls[5], alive, unbound, completions, wakeups;
static bool hold_callback, nested_callback, disconnect_completes, disconnect_recurses;
static void completion_check(void);
static int bind_fault;
static unsigned sequence, bind_calls, start_calls, stop_order, unbind_order;
static unsigned scenarios;
static void dispatch(int kind);
#define container_of(p, type, member) ((type *)((char *)(p) - offsetof(type, member)))

static void brief_yield(void) { struct timespec t = {.tv_nsec = 100000}; nanosleep(&t, NULL); }
static void wait_for(atomic_uint *value, unsigned expected)
{
	struct timespec start, now;
	clock_gettime(CLOCK_MONOTONIC, &start);
	while (atomic_load(value) < expected) {
		clock_gettime(CLOCK_MONOTONIC, &now);
		assert(now.tv_sec - start.tv_sec < 5);
		brief_yield();
	}
}
static void spin_lock(spinlock_t *lock)
{ assert(!locked && lock == &instance.lock); assert(!pthread_mutex_lock(lock)); locked = true; }
static void spin_unlock(spinlock_t *lock)
{
	assert(locked && lock == &instance.lock); locked = false;
	assert(!pthread_mutex_unlock(lock));
	if (pause_on_unlock) {
		pause_on_unlock = false; atomic_store(&paused, 1); wait_for(&resume_pause, 1);
	}
}
#define lockdep_assert_held(p) do { assert(locked && (p) == &instance.lock); } while (0)
#define spin_lock_irqsave(lock, flags) do { (flags) = 0; spin_lock(lock); } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); spin_unlock(lock); } while (0)
#define spin_lock_irq(p) spin_lock(p)
#define spin_unlock_irq(p) spin_unlock(p)
static unsigned count_now(void)
{ spin_lock(&instance.lock); unsigned n = instance.gadget_callback_count; spin_unlock(&instance.lock); return n; }
static void init_waitqueue_head(wait_queue_head_t *q)
{ assert(!pthread_mutex_init(&q->mutex, NULL)); assert(!pthread_cond_init(&q->cv, NULL)); }
static void __attribute__((unused)) wake_up_all(wait_queue_head_t *q)
{
	assert(locked); atomic_fetch_add(&wakeups, 1);
	assert(!pthread_mutex_lock(&q->mutex)); assert(!pthread_cond_broadcast(&q->cv));
	assert(!pthread_mutex_unlock(&q->mutex));
}
static void __attribute__((unused)) init_wait_entry(struct wait_queue_entry *e, int flags)
{ assert(locked && !flags); e->queue = NULL; }
static int __attribute__((unused)) prepare_to_wait_event(wait_queue_head_t *q, struct wait_queue_entry *e, int state)
{
	assert(locked && !queue_locked && state == TASK_UNINTERRUPTIBLE);
	assert(!pthread_mutex_lock(&q->mutex)); queue_locked = true; current_wait = e->queue = q;
	return 0;
}
static void __attribute__((unused)) schedule(void)
{
	assert(!locked && queue_locked && current_wait);
	struct timespec deadline; clock_gettime(CLOCK_REALTIME, &deadline); deadline.tv_sec += 2;
	atomic_fetch_add(&wait_sleeping, 1);
	int rc = pthread_cond_timedwait(&current_wait->cv, &current_wait->mutex, &deadline);
	assert(rc == 0); assert(!pthread_mutex_unlock(&current_wait->mutex)); queue_locked = false;
}
static void __attribute__((unused)) finish_wait(wait_queue_head_t *q, struct wait_queue_entry *e)
{
	assert(locked && current_wait == q && e->queue == q);
	if (queue_locked) { assert(!pthread_mutex_unlock(&q->mutex)); queue_locked = false; }
	current_wait = NULL;
}
static void mutex_lock(pthread_mutex_t *m) { assert(!locked); assert(!pthread_mutex_lock(m)); }
static void mutex_unlock(pthread_mutex_t *m) { assert(!pthread_mutex_unlock(m)); }
static struct musb *gadget_to_musb(struct usb_gadget *g) { assert(g == &instance.g); return &instance; }
static struct usb_gadget *dev_to_usb_gadget(struct device *d) { return d->owner; }
static int musb_get_state(struct musb *m) { assert(locked); return m->state; }
static void musb_set_state(struct musb *m, int state) { assert(locked); m->state = state; }
static u8 musb_readb(void *regs, unsigned off) { assert(locked && regs == registers && off < 2); return registers[off]; }
static void musb_writeb(void *regs, unsigned off, u8 value)
{ assert(locked && regs == registers && off < 2); registers[off] = value; }
static int musb_gadget_vbus_draw(struct usb_gadget *g, int amount) { (void)amount; assert(g == &instance.g); return 0; }
static void usb_gadget_set_state(struct usb_gadget *g, int state) { g->state = state; }
static void usb_gadget_udc_set_speed(struct usb_udc *u, int speed)
{ assert(u == &udc && speed == USB_SPEED_HIGH && !locked); }
static int usb_udc_connect_control_locked(struct usb_udc *u)
{ assert(u == &udc && instance.gadget_async_callbacks); dispatch(4); return bind_fault == 3 ? -EIO : 0; }
static void cancel_work_sync(int *work) { assert(work == &udc.vbus_work && !locked); }
static void synchronize_irq(int irq) { (void)irq; assert(false); }
static int usb_gadget_disconnect_locked(struct usb_gadget *g) { assert(g == &instance.g); return 0; }
static void kobject_uevent(int *kobj, int event) { (void)kobj; assert(event == KOBJ_CHANGE); }
#define to_musb_request(req) ((struct musb_request *)(req))
static void list_del(int *p) { assert(locked); *p = 0; }
static bool dma_mapping_error(struct device *dev, int dma) { (void)dev; return dma == -1; }
static void unmap_dma_buffer(struct musb_request *req, struct musb *m) { (void)req; (void)m; assert(!locked); }
#define trace_musb_req_gb(req) ((void)(req))
static void usb_gadget_giveback_request(struct usb_ep *ep, struct usb_request *req)
{ (void)ep; assert(!locked && req->status != -EINPROGRESS); atomic_fetch_add(&completions, 1); }

#include "musb_callback_functions.h"

static void user_callback(int kind)
{
	assert(!locked && atomic_load(&alive));
	assert(count_now() > 0);
	atomic_fetch_add(&calls[kind], 1); depth++;
	if (nested_callback && depth == 1) {
		spin_lock(&instance.lock); musb_g_resume(&instance); spin_unlock(&instance.lock);
	}
	if (depth == 1 && worker >= 0) {
		atomic_fetch_add(&entered, 1);
		if (hold_callback) wait_for(&releases[worker], 1);
	}
	assert(atomic_load(&alive)); depth--;
}
static void resume_cb(struct usb_gadget *g) { assert(g == &instance.g); user_callback(0); }
static void suspend_cb(struct usb_gadget *g) { assert(g == &instance.g); user_callback(1); }
static void disconnect_cb(struct usb_gadget *g)
{
	assert(g == &instance.g); user_callback(2);
	if (disconnect_completes) completion_check();
	if (disconnect_recurses) {
		spin_lock(&instance.lock); musb_g_disconnect(&instance); spin_unlock(&instance.lock);
	}
}
static void reset_cb(struct usb_gadget *g) { assert(g == &instance.g); user_callback(3); }
static int setup_cb(struct usb_gadget *g, const struct usb_ctrlrequest *req)
{ assert(g == &instance.g && req->test == 73); user_callback(4); return -EREMOTEIO; }
static void unbind_cb(struct usb_gadget *g)
{
	assert(g == &instance.g && !locked && !instance.gadget_async_callbacks);
	assert(!count_now());
	unbind_order = ++sequence; atomic_store(&alive, 0); atomic_store(&unbound, 1);
}
static int bind_cb(struct usb_gadget *g, struct usb_gadget_driver *d)
{
	assert(g == &instance.g && d == &driver && !instance.gadget_async_callbacks && !count_now());
	bind_calls++; atomic_store(&alive, bind_fault != 1); atomic_store(&unbound, 0);
	return bind_fault == 1 ? -EINVAL : 0;
}
static int start_cb(struct usb_gadget *g, struct usb_gadget_driver *d)
{
	assert(g == &instance.g && d == &driver && !instance.gadget_async_callbacks); start_calls++;
	if (bind_fault == 2) return -EIO;
	spin_lock(&instance.lock); instance.gadget_driver = d; spin_unlock(&instance.lock); return 0;
}
static int stop_cb(struct usb_gadget *g)
{
	assert(g == &instance.g && !instance.gadget_async_callbacks && !count_now()); stop_order = ++sequence;
	spin_lock(&instance.lock); instance.gadget_driver = NULL; spin_unlock(&instance.lock); return 0;
}
static void dispatch(int kind)
{
	spin_lock(&instance.lock);
	instance.state = OTG_STATE_B_PERIPHERAL; instance.g.speed = USB_SPEED_HIGH;
	if (kind == 0) musb_g_resume(&instance);
	if (kind == 1) musb_g_suspend(&instance);
	if (kind == 2) musb_g_disconnect(&instance);
	if (kind == 3) musb_g_reset(&instance);
	if (kind == 4) {
		struct usb_ctrlrequest req = {.test = 73};
		bool admitted = instance.gadget_async_callbacks && instance.gadget_driver;
		assert(forward_to_driver(&instance, &req) == (admitted ? -EREMOTEIO : -EOPNOTSUPP));
	}
	spin_unlock(&instance.lock);
}
struct thread_arg { int id, kind; bool pause; };
static void *callback_thread(void *arg)
{
	struct thread_arg *a = arg; worker = a->id; pause_on_unlock = a->pause;
	dispatch(a->kind); atomic_fetch_add(&finished, 1); return NULL;
}
static void *unbind_thread(void *arg)
{ (void)arg; gadget_unbind_driver(&instance.g.dev); return NULL; }
static void init(void)
{
	memset(&instance, 0, sizeof(instance)); memset(&udc, 0, sizeof(udc));
	assert(!pthread_mutex_init(&instance.lock, NULL)); assert(!pthread_mutex_init(&udc.connect_lock, NULL));
	init_waitqueue_head(&instance.gadget_callback_wait);
	driver = (struct usb_gadget_driver){.bind = bind_cb, .max_speed = USB_SPEED_HIGH, .resume = resume_cb, .suspend = suspend_cb,
		.disconnect = disconnect_cb, .reset = reset_cb, .setup = setup_cb, .unbind = unbind_cb, .is_bound = true};
	ops = (struct usb_gadget_ops){.udc_start = start_cb, .udc_async_callbacks = musb_gadget_async_callbacks, .udc_stop = stop_cb};
	instance.g.ops = &ops; instance.g.udc = &udc; instance.g.dev.owner = &instance.g;
	instance.g.dev.driver = &driver.driver;
	instance.gadget_driver = &driver; instance.mregs = registers;
	udc.gadget = &instance.g; udc.driver = &driver; udc.started = udc.allow_connect = true;
	registers[0] = MUSB_DEVCTL_BDEVICE | MUSB_DEVCTL_VBUS; registers[1] = MUSB_POWER_HSMODE;
	atomic_store(&entered, 0); atomic_store(&finished, 0); atomic_store(&wait_sleeping, 0);
	atomic_store(&paused, 0); atomic_store(&resume_pause, 0); atomic_store(&alive, 1);
	atomic_store(&unbound, 0); atomic_store(&completions, 0); atomic_store(&wakeups, 0);
	for (unsigned i = 0; i < 4; i++) atomic_store(&releases[i], 0);
	for (unsigned i = 0; i < 5; i++) atomic_store(&calls[i], 0);
	hold_callback = nested_callback = disconnect_completes = disconnect_recurses = false;
	bind_fault = 0; sequence = bind_calls = start_calls = stop_order = unbind_order = 0;
}
static void destroy(void)
{
	assert(!locked && !count_now());
	assert(!pthread_mutex_destroy(&instance.lock)); assert(!pthread_mutex_destroy(&udc.connect_lock));
	assert(!pthread_mutex_destroy(&instance.gadget_callback_wait.mutex));
	assert(!pthread_cond_destroy(&instance.gadget_callback_wait.cv)); scenarios++;
}
static void completion_check(void)
{
	struct musb_ep ep = {.musb = &instance, .busy = 7};
	struct musb_request req = {.request = {.status = -EINPROGRESS, .dma = -1}, .musb = &instance, .ep = &ep, .list = 1};
	unsigned before = atomic_load(&completions);
	spin_lock(&instance.lock); musb_g_giveback(&ep, &req.request, -ESHUTDOWN); spin_unlock(&instance.lock);
	assert(atomic_load(&completions) == before + 1 && req.request.status == -ESHUTDOWN && ep.busy == 7 && !req.list);
}
int main(void)
{
	alarm(30);
	/* Disconnect retires a session before its callback; request giveback and
	 * even a nested/late duplicate disconnect must not notify it twice.
	 */
	for (int nested = 0; nested < 2; nested++) {
		init(); usb_gadget_enable_async_callbacks(&udc);
		disconnect_completes = true; disconnect_recurses = nested;
		dispatch(2);
		spin_lock(&instance.lock); musb_g_disconnect(&instance); spin_unlock(&instance.lock);
		assert(atomic_load(&calls[2]) == 1 && atomic_load(&completions) == 1);
		assert(instance.g.speed == USB_SPEED_UNKNOWN && instance.g.state == USB_STATE_NOTATTACHED);
		destroy();
	}
	/* Gate each event independently; preserve completion and callback results. */
	for (int kind = 0; kind < 5; kind++) {
		init(); dispatch(kind); assert(!atomic_load(&calls[kind])); completion_check();
		usb_gadget_enable_async_callbacks(&udc); dispatch(kind); assert(atomic_load(&calls[kind]) == 1);
		usb_gadget_disable_async_callbacks(&udc); dispatch(kind); assert(atomic_load(&calls[kind]) == 1); completion_check();
		usb_gadget_enable_async_callbacks(&udc); dispatch(kind); assert(atomic_load(&calls[kind]) == 2);
		usb_gadget_disable_async_callbacks(&udc); destroy();
	}
	/* Optional hooks may be absent; reset/setup remain mandatory. */
	for (int kind = 0; kind < 3; kind++) {
		init(); driver.resume = driver.suspend = driver.disconnect = NULL;
		usb_gadget_enable_async_callbacks(&udc); dispatch(kind); assert(!atomic_load(&calls[kind])); destroy();
	}
	/* Retain each existing event's state-specific notification predicate. */
	for (int kind = 0; kind < 3; kind++)
	for (int state = OTG_STATE_B_IDLE; state <= OTG_STATE_B_SRP_INIT; state++)
	for (int enabled = 0; enabled < 2; enabled++) {
		init(); if (enabled) usb_gadget_enable_async_callbacks(&udc);
		spin_lock(&instance.lock); instance.state = state; instance.g.speed = USB_SPEED_HIGH;
		if (kind == 0) musb_g_resume(&instance);
		if (kind == 1) musb_g_suspend(&instance);
		if (kind == 2) musb_g_disconnect(&instance);
		spin_unlock(&instance.lock);
		bool expected = enabled && (kind == 2 || state == OTG_STATE_B_PERIPHERAL ||
			(kind == 0 && state == OTG_STATE_B_WAIT_ACON));
		assert(atomic_load(&calls[kind]) == expected); destroy();
	}
	/* Unknown-speed reset must not acquire a callback; preserve role/reset work. */
	for (int enabled = 0; enabled < 2; enabled++)
	for (int known = 0; known < 2; known++)
	for (int otg = 0; otg < 2; otg++)
	for (int bdev = 0; bdev < 2; bdev++)
	for (int hr = 0; hr < 2; hr++) {
		init(); if (enabled) usb_gadget_enable_async_callbacks(&udc);
		instance.g.is_otg = otg; instance.g.speed = known ? USB_SPEED_FULL : USB_SPEED_UNKNOWN;
		registers[0] = (bdev ? MUSB_DEVCTL_BDEVICE : 0) | (hr ? MUSB_DEVCTL_HR : 0);
		spin_lock(&instance.lock); musb_g_reset(&instance); spin_unlock(&instance.lock);
		assert(atomic_load(&calls[3]) == (unsigned)(enabled && known));
		assert(instance.g.speed == USB_SPEED_HIGH && instance.g.is_a_peripheral == (otg && !bdev));
		if (hr && !(enabled && known)) assert(registers[0] == MUSB_DEVCTL_SESSION);
		destroy();
	}
	for (int dma = -1; dma <= 0; dma++)
	for (int finished_status = 0; finished_status < 2; finished_status++) {
		init(); struct musb_ep ep = {.musb = &instance};
		struct musb_request req = {.request = {.status = finished_status ? -EIO : -EINPROGRESS, .dma = dma},
			.musb = &instance, .ep = &ep, .list = 1};
		spin_lock(&instance.lock); musb_g_giveback(&ep, &req.request, -ESHUTDOWN); spin_unlock(&instance.lock);
		assert(atomic_load(&completions) == 1 && req.request.status == (finished_status ? -EIO : -ESHUTDOWN));
		destroy();
	}
	/* Admission drains the last callback, including nested and mixed events. */
	for (int kind = 0; kind < 5; kind++)
	for (int count = 1; count <= 4; count *= 2)
	for (int nested = 0; nested < 2; nested++) {
		pthread_t threads[4], unbinder;
		struct thread_arg args[4];
		init(); hold_callback = true; nested_callback = nested;
		usb_gadget_enable_async_callbacks(&udc);
		for (int i = 0; i < count; i++) {
			args[i] = (struct thread_arg){.id = i, .kind = (kind + i) % 5};
			assert(!pthread_create(&threads[i], NULL, callback_thread, &args[i]));
		}
		wait_for(&entered, count); assert(count_now() == (unsigned)count);
		assert(!pthread_create(&unbinder, NULL, unbind_thread, NULL));
		wait_for(&wait_sleeping, 1); assert(!atomic_load(&unbound));
		/* An unrelated wake does not retire callbacks that are still running. */
		spin_lock(&instance.lock); wake_up_all(&instance.gadget_callback_wait); spin_unlock(&instance.lock);
		wait_for(&wait_sleeping, 2); assert(!atomic_load(&unbound));
		unsigned before[5]; for (int i = 0; i < 5; i++) before[i] = atomic_load(&calls[i]);
		for (int i = 0; i < 5; i++) dispatch(i);
		for (int i = 0; i < 5; i++) assert(before[i] == atomic_load(&calls[i]));
		completion_check();
		for (int i = count - 1; i >= 0; i--) {
			atomic_store(&releases[i], 1); assert(!pthread_join(threads[i], NULL));
			if (i) assert(!atomic_load(&unbound) && count_now() == (unsigned)i);
		}
		assert(!pthread_join(unbinder, NULL));
		assert(atomic_load(&unbound) && !driver.is_bound && !udc.driver && !udc.started && !instance.gadget_driver);
		assert(atomic_load(&wakeups) == 2);
		for (int i = 0; i < 5; i++) dispatch(i);
		destroy();
	}
	/* Real UDC bind handles failures before admission and after connect starts. */
	for (int fault = 0; fault < 4; fault++) {
		init(); bind_fault = fault; driver.is_bound = false; udc.driver = NULL;
		udc.started = udc.allow_connect = false; instance.gadget_driver = NULL;
		int ret = gadget_bind_driver(&instance.g.dev);
		assert(ret == (fault == 1 ? -EINVAL : fault ? -EIO : 0));
		assert(bind_calls == 1 && start_calls == (unsigned)(fault != 1));
		if (!fault) {
			assert(driver.is_bound && udc.started && instance.gadget_async_callbacks && atomic_load(&calls[4]) == 1);
			gadget_unbind_driver(&instance.g.dev); assert(unbind_order < stop_order);
		} else if (fault == 1) {
			assert(!unbind_order && !stop_order);
		} else if (fault == 2) {
			assert(unbind_order && !stop_order);
		} else {
			assert(stop_order && stop_order < unbind_order && atomic_load(&calls[4]) == 1);
		}
		assert(!driver.is_bound && !udc.driver && !udc.started && !instance.gadget_async_callbacks && !instance.gadget_driver);
		destroy();
	}
	init(); driver.is_bound = false; udc.driver = NULL; udc.started = false; instance.gadget_driver = NULL;
	for (int cycle = 0; cycle < 8; cycle++) {
		assert(!gadget_bind_driver(&instance.g.dev)); gadget_unbind_driver(&instance.g.dev);
		assert(!instance.gadget_async_callbacks && !count_now() && !instance.gadget_driver);
	}
	destroy();
	/* A soft-stop pointer-clear window does not invalidate an admitted pointer.
	 * This models stop's logical boundary; function-driver unbind has not run.
	 */
	for (int kind = 0; kind < 5; kind++) {
		pthread_t t; struct thread_arg arg = {.id = 0, .kind = kind, .pause = true};
		init(); usb_gadget_enable_async_callbacks(&udc);
		assert(!pthread_create(&t, NULL, callback_thread, &arg)); wait_for(&paused, 1);
		spin_lock(&instance.lock); instance.gadget_driver = NULL; spin_unlock(&instance.lock);
		atomic_store(&resume_pause, 1); assert(!pthread_join(t, NULL));
		assert(atomic_load(&calls[kind]) == 1); dispatch(kind); assert(atomic_load(&calls[kind]) == 1);
		spin_lock(&instance.lock); instance.gadget_driver = &driver; spin_unlock(&instance.lock);
		dispatch(kind); assert(atomic_load(&calls[kind]) == 2); destroy();
	}
	printf("MUSB callback lifetime: %u actual-source scenarios passed\n", scenarios);
	return 0;
}
