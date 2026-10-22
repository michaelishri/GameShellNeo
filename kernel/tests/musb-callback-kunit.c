// SPDX-License-Identifier: GPL-2.0-only
/* Included in musb_gadget.c only in the isolated ARM SMP test kernel. */
#include <kunit/test.h>
#include <linux/completion.h>
#include <linux/cpu.h>
#include <linux/delay.h>
#include <linux/kthread.h>
#include <linux/smp.h>

int musb_callback_test_setup(struct musb *musb);

enum callback_kind { CB_RESUME, CB_SUSPEND, CB_DISCONNECT, CB_RESET, CB_SETUP };
enum actor_kind { ACTOR_IRQ, ACTOR_TIMER, ACTOR_PROCESS, ACTOR_TWO_IRQS };

struct callback_fixture {
	struct musb musb;
	struct usb_gadget_ops ops;
	struct usb_gadget_driver driver;
	struct device *parent;
	struct completion entered, returned, unregistered, released;
	struct task_struct *actor, *unbinder;
	struct timer_list timer;
	call_single_data_t csd, second_csd;
	cpumask_var_t original_mask;
	atomic_t release, release_first, active, calls, unbound, timed_out, completions;
	unsigned int callback_cpu, unbind_cpu, callback_count_at_unbind;
	unsigned int second_cpu;
	bool callback_irq, callback_softirq, callback_irqs_disabled;
	bool registered, unregister_finished, multiple, unstarted_case;
	bool completion_gate_closed;
	int unregister_rc, setup_rc;
	struct musb_ep completion_ep;
	struct usb_request *request;
	enum callback_kind kind;
	enum actor_kind context;
	u8 registers[256];
	u8 (*old_readb)(void __iomem *, u32);
	void (*old_writeb)(void __iomem *, u32, u8);
};

static struct callback_fixture *callback_fixture(struct usb_gadget *g)
{
	return container_of(gadget_to_musb(g), struct callback_fixture, musb);
}

/* Only the unmodelled register bank is substituted, never admission/drain. */
static u8 callback_readb(void __iomem *base, u32 offset)
{
	return ((u8 __force *)base)[offset];
}

static void callback_writeb(void __iomem *base, u32 offset, u8 value)
{
	((u8 __force *)base)[offset] = value;
}

static void callback_observe(struct usb_gadget *g)
{
	struct callback_fixture *f = callback_fixture(g);
	u64 deadline;
	unsigned int cpu = raw_smp_processor_id();

	atomic_inc(&f->calls);
	/* UDC's synchronous disconnect is allowed; only hold the tested actor. */
	if ((cpu != 1 && !(f->multiple && cpu == 3)) || !atomic_read(&f->active))
		return;
	if (cpu == 1) {
		f->callback_cpu = cpu;
		f->callback_irq = in_hardirq();
		f->callback_softirq = in_serving_softirq();
		f->callback_irqs_disabled = irqs_disabled();
	} else {
		f->second_cpu = cpu;
	}
	deadline = ktime_get_mono_fast_ns() + 10ULL * NSEC_PER_SEC;
	complete(&f->entered);
	/* Atomic callbacks must never sleep, including this test handshake. */
	while (!atomic_read(&f->release) && !(cpu == 1 && atomic_read(&f->release_first))) {
		if (ktime_get_mono_fast_ns() >= deadline) {
			atomic_set(&f->timed_out, 1);
			break;
		}
		cpu_relax();
	}
}

static int callback_setup(struct usb_gadget *g, const struct usb_ctrlrequest *request)
{
	callback_observe(g);
	return 37; /* Preserve the actual forward_to_driver return value. */
}

static int callback_bind(struct usb_gadget *g, struct usb_gadget_driver *driver)
{
	return 0;
}

static void callback_unbind(struct usb_gadget *g)
{
	struct callback_fixture *f = callback_fixture(g);
	unsigned long flags;

	f->unbind_cpu = raw_smp_processor_id();
	spin_lock_irqsave(&f->musb.lock, flags);
	f->callback_count_at_unbind = f->musb.gadget_callback_count;
	spin_unlock_irqrestore(&f->musb.lock, flags);
	atomic_inc(&f->unbound);
}

/* Hardware start/stop/pullup have no emulated controller behind them. */
static int callback_start(struct usb_gadget *g, struct usb_gadget_driver *driver)
{
	struct musb *musb = gadget_to_musb(g);
	unsigned long flags;

	spin_lock_irqsave(&musb->lock, flags);
	musb->gadget_driver = driver;
	musb_set_state(musb, OTG_STATE_B_PERIPHERAL);
	musb->g.speed = USB_SPEED_HIGH;
	spin_unlock_irqrestore(&musb->lock, flags);
	return 0;
}

static int callback_stop(struct usb_gadget *g)
{
	struct musb *musb = gadget_to_musb(g);
	unsigned long flags;

	spin_lock_irqsave(&musb->lock, flags);
	musb->gadget_driver = NULL;
	spin_unlock_irqrestore(&musb->lock, flags);
	return 0;
}

static int callback_pullup(struct usb_gadget *g, int enabled)
{
	return 0;
}

static void callback_invoke(struct callback_fixture *f, enum callback_kind kind)
{
	unsigned long flags;

	spin_lock_irqsave(&f->musb.lock, flags);
	musb_set_state(&f->musb, OTG_STATE_B_PERIPHERAL);
	f->musb.g.speed = USB_SPEED_HIGH;
	switch (kind) {
	case CB_RESUME: musb_g_resume(&f->musb); break;
	case CB_SUSPEND: musb_g_suspend(&f->musb); break;
	case CB_DISCONNECT: musb_g_disconnect(&f->musb); break;
	case CB_RESET: musb_g_reset(&f->musb); break;
	case CB_SETUP: f->setup_rc = musb_callback_test_setup(&f->musb); break;
	}
	spin_unlock_irqrestore(&f->musb.lock, flags);
}

static void callback_actor(void *data)
{
	struct callback_fixture *f = data;

	atomic_inc(&f->active);
	callback_invoke(f, f->kind);
	atomic_dec(&f->active);
	complete(&f->returned);
}

static void callback_timer(struct timer_list *timer)
{
	struct callback_fixture *f = timer_container_of(f, timer, timer);

	callback_actor(f);
}

static int callback_thread(void *data)
{
	callback_actor(data);
	return 0;
}

static int callback_unregister_thread(void *data)
{
	struct callback_fixture *f = data;

	f->unregister_rc = usb_gadget_unregister_driver(&f->driver);
	f->unregister_finished = true;
	complete(&f->unregistered);
	return 0;
}

static struct task_struct *callback_create_thread(int (*run)(void *),
					       struct callback_fixture *f, int cpu)
{
	struct task_struct *task = kthread_create(run, f, "musb-callback-test");

	if (!IS_ERR(task)) {
		get_task_struct(task); /* Retain even if the thread exits before join. */
		kthread_bind(task, cpu);
	}
	return task;
}

static void callback_gadget_release(struct device *dev)
{
	complete(&callback_fixture(dev_to_usb_gadget(dev))->released);
}

static void callback_stop_ipi(void *unused)
{
}

static void callback_request_complete(struct usb_ep *ep, struct usb_request *request)
{
	struct callback_fixture *f = request->context;

	f->completion_gate_closed = !READ_ONCE(f->musb.gadget_async_callbacks);
	atomic_inc(&f->completions);
}

/* Stage a PIO-owned request; execute the real MUSB and UDC giveback paths. */
static void callback_giveback(struct kunit *test, struct callback_fixture *f)
{
	struct musb_request *request = to_musb_request(f->request);
	unsigned long flags;

	spin_lock_irqsave(&f->musb.lock, flags);
	f->request->status = -EINPROGRESS;
	list_add_tail(&request->list, &f->completion_ep.req_list);
	musb_g_giveback(&f->completion_ep, f->request, -ESHUTDOWN);
	spin_unlock_irqrestore(&f->musb.lock, flags);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->completions), 1);
	KUNIT_EXPECT_EQ(test, f->request->status, -ESHUTDOWN);
	KUNIT_EXPECT_TRUE(test, f->completion_gate_closed);
	KUNIT_EXPECT_TRUE(test, list_empty(&f->completion_ep.req_list));
	KUNIT_EXPECT_EQ(test, f->completion_ep.busy, 7U);
}

static int callback_init(struct kunit *test)
{
	struct callback_fixture *f;
	int ret;

	if (num_online_cpus() < 4 || !cpu_online(0) || !cpu_online(1) || !cpu_online(2))
		return -ENODEV; /* Never count a uniprocessor run as a skipped success. */
	f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	if (!f || !alloc_cpumask_var(&f->original_mask, GFP_KERNEL))
		return -ENOMEM;
	test->priv = f;
	cpumask_copy(f->original_mask, current->cpus_ptr);
	ret = set_cpus_allowed_ptr(current, cpumask_of(0));
	if (ret)
		goto free_mask;
	init_completion(&f->entered);
	init_completion(&f->returned);
	init_completion(&f->unregistered);
	init_completion(&f->released);
	spin_lock_init(&f->musb.lock);
	init_waitqueue_head(&f->musb.gadget_callback_wait);
	timer_setup(&f->timer, callback_timer, TIMER_PINNED);
	INIT_CSD(&f->csd, callback_actor, f);
	INIT_CSD(&f->second_csd, callback_actor, f);
	f->parent = root_device_register("musb-callback-kunit");
	if (IS_ERR(f->parent)) {
		ret = PTR_ERR(f->parent);
		goto restore_mask;
	}
	f->musb.controller = f->parent;
	f->completion_ep.musb = &f->musb;
	f->completion_ep.end_point.name = "kunit-completion";
	f->completion_ep.current_epnum = 1;
	f->completion_ep.busy = 7;
	INIT_LIST_HEAD(&f->completion_ep.req_list);
	f->request = musb_alloc_request(&f->completion_ep.end_point, GFP_KERNEL);
	if (!f->request) {
		ret = -ENOMEM;
		goto unregister_parent;
	}
	to_musb_request(f->request)->musb = &f->musb;
	f->request->context = f;
	f->request->complete = callback_request_complete;
	f->musb.mregs = (void __iomem *)f->registers;
	f->musb.nr_endpoints = 1;
	f->musb.endpoints[0].is_shared_fifo = true;
	musb_g_init_endpoints(&f->musb);
	f->ops = musb_gadget_operations;
	f->ops.udc_start = callback_start;
	f->ops.udc_stop = callback_stop;
	f->ops.pullup = callback_pullup;
	f->musb.g.ops = &f->ops;
	f->musb.g.name = "musb-callback-kunit";
	f->musb.g.max_speed = USB_SPEED_HIGH;
	f->driver = (struct usb_gadget_driver) {
		.function = "musb-callback-kunit", .driver.name = "musb-callback-kunit",
		.max_speed = USB_SPEED_HIGH, .match_existing_only = true,
		.bind = callback_bind, .unbind = callback_unbind,
		.setup = callback_setup, .resume = callback_observe,
		.suspend = callback_observe, .disconnect = callback_observe,
		.reset = callback_observe,
	};
	ret = usb_add_gadget_udc_release(f->parent, &f->musb.g, callback_gadget_release);
	if (ret)
		goto free_request;
	f->old_readb = musb_readb;
	f->old_writeb = musb_writeb;
	musb_readb = callback_readb;
	musb_writeb = callback_writeb;
	ret = usb_gadget_register_driver(&f->driver);
	if (!ret) {
		f->registered = true;
		return 0;
	}
	musb_readb = f->old_readb;
	musb_writeb = f->old_writeb;
	usb_del_gadget_udc(&f->musb.g);
free_request:
	musb_free_request(&f->completion_ep.end_point, f->request);
unregister_parent:
	root_device_unregister(f->parent);
restore_mask:
	set_cpus_allowed_ptr(current, f->original_mask);
free_mask:
	free_cpumask_var(f->original_mask);
	return ret;
}

static void callback_exit(struct kunit *test)
{
	struct callback_fixture *f = test->priv;

	atomic_set(&f->release, 1);
	timer_delete_sync(&f->timer);
	/* Join all possible actor contexts before releasing their fixture. */
	smp_call_function_single(1, callback_stop_ipi, NULL, 1);
	smp_call_function_single(3, callback_stop_ipi, NULL, 1);
	if (f->actor && !IS_ERR(f->actor)) {
		kthread_stop(f->actor);
		put_task_struct(f->actor);
	}
	if (f->unbinder && !IS_ERR(f->unbinder)) {
		kthread_stop(f->unbinder);
		put_task_struct(f->unbinder);
		/* A never-started thread can stop without running unregister. */
		if (f->unregister_finished)
			f->registered = f->unregister_rc != 0;
	}
	if (f->registered) {
		int ret = usb_gadget_unregister_driver(&f->driver);

		KUNIT_EXPECT_EQ(test, ret, 0);
		if (f->unstarted_case) {
			KUNIT_EXPECT_FALSE(test, f->unregister_finished);
			kunit_info(test, "Unstarted actor: cleanup unregister=%d\n", ret);
		}
	}
	KUNIT_EXPECT_FALSE(test, f->driver.is_bound);
	usb_del_gadget_udc(&f->musb.g);
	if (!wait_for_completion_timeout(&f->released, msecs_to_jiffies(2000)))
		panic("MUSB test gadget release did not finish; refusing unsafe fixture free");
	musb_readb = f->old_readb;
	musb_writeb = f->old_writeb;
	musb_free_request(&f->completion_ep.end_point, f->request);
	root_device_unregister(f->parent);
	set_cpus_allowed_ptr(current, f->original_mask);
	free_cpumask_var(f->original_mask);
}

static void callback_race(struct kunit *test, enum callback_kind kind, enum actor_kind context)
{
	struct callback_fixture *f = test->priv;
	unsigned long flags, deadline;
	bool closed = false;
	unsigned int count = 0;
	int calls, i;

	f->kind = kind;
	f->context = context;
	f->multiple = context == ACTOR_TWO_IRQS;
	KUNIT_ASSERT_TRUE(test, f->driver.is_bound);
	KUNIT_ASSERT_PTR_EQ(test, f->musb.gadget_driver, &f->driver);
	KUNIT_ASSERT_TRUE(test, f->musb.gadget_async_callbacks);
	/* kthread_create itself needs kthreadd/new-task scheduling. Complete it
	 * before occupying CPU 1 with a non-sleeping callback; wake only later.
	 */
	f->unbinder = callback_create_thread(callback_unregister_thread, f, 2);
	KUNIT_ASSERT_FALSE(test, IS_ERR(f->unbinder));
	if (context == ACTOR_IRQ || f->multiple) {
		KUNIT_ASSERT_EQ(test, smp_call_function_single_async(1, &f->csd), 0);
		if (f->multiple)
			KUNIT_ASSERT_EQ(test, smp_call_function_single_async(3, &f->second_csd), 0);
	} else if (context == ACTOR_TIMER) {
		f->timer.expires = jiffies + 1;
		add_timer_on(&f->timer, 1);
	} else {
		f->actor = callback_create_thread(callback_thread, f, 1);
		KUNIT_ASSERT_FALSE(test, IS_ERR(f->actor));
		wake_up_process(f->actor);
	}
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->entered, msecs_to_jiffies(2000)), 0UL);
	if (f->multiple)
		KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->entered, msecs_to_jiffies(2000)), 0UL);
	wake_up_process(f->unbinder);
	deadline = jiffies + msecs_to_jiffies(2000);
	do {
		spin_lock_irqsave(&f->musb.lock, flags);
		closed = !f->musb.gadget_async_callbacks;
		count = f->musb.gadget_callback_count;
		spin_unlock_irqrestore(&f->musb.lock, flags);
		if (closed)
			break;
		msleep(1);
	} while (time_before(jiffies, deadline));
	KUNIT_EXPECT_TRUE(test, closed);
	KUNIT_EXPECT_EQ(test, count, f->multiple ? 2U : 1U);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->unbound), 0);
	KUNIT_EXPECT_FALSE(test, completion_done(&f->unregistered));
	/* Real callback entry points must all reject new admission during drain. */
	calls = atomic_read(&f->calls);
	for (i = CB_RESUME; i <= CB_SETUP; i++)
		callback_invoke(f, i);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->calls), calls);
	KUNIT_EXPECT_EQ(test, f->setup_rc, -EOPNOTSUPP);
	callback_giveback(test, f);
	KUNIT_EXPECT_FALSE(test, completion_done(&f->unregistered));
	if (f->multiple) {
		atomic_set(&f->release_first, 1);
		KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->returned, msecs_to_jiffies(2000)), 0UL);
		spin_lock_irqsave(&f->musb.lock, flags);
		count = f->musb.gadget_callback_count;
		spin_unlock_irqrestore(&f->musb.lock, flags);
		KUNIT_EXPECT_EQ(test, count, 1U);
		KUNIT_EXPECT_EQ(test, atomic_read(&f->unbound), 0);
		KUNIT_EXPECT_FALSE(test, completion_done(&f->unregistered));
		KUNIT_EXPECT_EQ(test, f->second_cpu, 3U);
		kunit_info(test, "Second callback CPU=%u remaining after first=%u\n", f->second_cpu, count);
	}
	atomic_set(&f->release, 1);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->returned, msecs_to_jiffies(2000)), 0UL);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->unregistered, msecs_to_jiffies(2000)), 0UL);
	KUNIT_EXPECT_EQ(test, f->unregister_rc, 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->timed_out), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->unbound), 1);
	KUNIT_EXPECT_EQ(test, f->callback_count_at_unbind, 0U);
	KUNIT_EXPECT_EQ(test, f->callback_cpu, 1U);
	KUNIT_EXPECT_EQ(test, f->unbind_cpu, 2U);
	KUNIT_EXPECT_EQ(test, f->callback_irq, context == ACTOR_IRQ || f->multiple);
	KUNIT_EXPECT_EQ(test, f->callback_softirq, context == ACTOR_TIMER);
	KUNIT_EXPECT_TRUE(test, f->callback_irqs_disabled);
	KUNIT_EXPECT_EQ(test, f->musb.gadget_callback_count, 0U);
	KUNIT_EXPECT_FALSE(test, f->musb.gadget_async_callbacks);
	KUNIT_EXPECT_PTR_EQ(test, f->musb.gadget_driver, NULL);
	if (kind == CB_SETUP)
		KUNIT_EXPECT_EQ(test, f->setup_rc, 37);
	kunit_info(test, "SMP callback=%u unbind=%u observer=%u online=%u kind=%u context=%u drained=%u completions=%d\n",
		f->callback_cpu, f->unbind_cpu, raw_smp_processor_id(), num_online_cpus(),
		kind, context, f->callback_count_at_unbind, atomic_read(&f->completions));
}

static void unstarted_unbinder(struct kunit *test)
{
	struct callback_fixture *f = test->priv;

	f->unbinder = callback_create_thread(callback_unregister_thread, f, 2);
	KUNIT_ASSERT_FALSE(test, IS_ERR(f->unbinder));
	f->unstarted_case = true;
	/* Fixture exit must unregister exactly once even though this actor never ran. */
}

static void rebind_cycles(struct kunit *test)
{
	struct callback_fixture *f = test->priv;
	int round, kind, calls;

	for (round = 0; round < 4; round++) {
		KUNIT_ASSERT_EQ(test, usb_gadget_unregister_driver(&f->driver), 0);
		f->registered = false;
		KUNIT_EXPECT_FALSE(test, f->musb.gadget_async_callbacks);
		KUNIT_EXPECT_PTR_EQ(test, f->musb.gadget_driver, NULL);
		KUNIT_ASSERT_EQ(test, usb_gadget_register_driver(&f->driver), 0);
		f->registered = true;
		KUNIT_EXPECT_TRUE(test, f->musb.gadget_async_callbacks);
		KUNIT_EXPECT_TRUE(test, f->driver.is_bound);
		calls = atomic_read(&f->calls);
		for (kind = CB_RESUME; kind <= CB_SETUP; kind++)
			callback_invoke(f, kind);
		KUNIT_EXPECT_EQ(test, atomic_read(&f->calls), calls + 5);
		KUNIT_EXPECT_EQ(test, f->setup_rc, 37);
		KUNIT_EXPECT_EQ(test, f->musb.gadget_callback_count, 0U);
	}
	kunit_info(test, "Rebind cycles=4 admitted callbacks=20\n");
}

#define CALLBACK_CASE(name, kind, context) \
static void name(struct kunit *test) { callback_race(test, kind, context); }
#define CALLBACK_CONTEXTS(name, kind) \
CALLBACK_CASE(name##_irq, kind, ACTOR_IRQ) \
CALLBACK_CASE(name##_timer, kind, ACTOR_TIMER) \
CALLBACK_CASE(name##_process, kind, ACTOR_PROCESS)
CALLBACK_CONTEXTS(resume, CB_RESUME)
CALLBACK_CONTEXTS(suspend, CB_SUSPEND)
CALLBACK_CONTEXTS(disconnect, CB_DISCONNECT)
CALLBACK_CONTEXTS(reset, CB_RESET)
CALLBACK_CONTEXTS(setup, CB_SETUP)
CALLBACK_CASE(two_callbacks_irq, CB_RESUME, ACTOR_TWO_IRQS)
#define CALLBACK_ENTRIES(name) KUNIT_CASE(name##_irq), KUNIT_CASE(name##_timer), KUNIT_CASE(name##_process)
static struct kunit_case callback_cases[] = {
	CALLBACK_ENTRIES(resume), CALLBACK_ENTRIES(suspend),
	CALLBACK_ENTRIES(disconnect), CALLBACK_ENTRIES(reset), CALLBACK_ENTRIES(setup),
	KUNIT_CASE(two_callbacks_irq), KUNIT_CASE(rebind_cycles), KUNIT_CASE(unstarted_unbinder), {}
};
static struct kunit_suite callback_suite = {
	.name = "musb-callback-smp", .init = callback_init, .exit = callback_exit,
	.test_cases = callback_cases,
};
kunit_test_suite(callback_suite);
