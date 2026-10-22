// SPDX-License-Identifier: GPL-2.0
/* Included only in the explicitly combined, isolated Linux test kernel. */
#include <kunit/test.h>
#include <linux/delay.h>
#include <linux/irq.h>
#include <linux/irqdesc.h>
#include <linux/irq_sim.h>
#include <linux/kthread.h>

struct terminal_wake_fixture {
	struct musb musb;
	struct device *device;
	struct irq_domain *domain;
	struct irq_chip chip;
	struct irq_chip *original_chip;
	unsigned int irq;
	bool peer_registered;
	bool peer_wake;
	bool fail_arm;
	bool fail_disarm;
	bool block_handler;
	bool resources_live;
	bool reader_held;
	int reader_index;
	atomic_t arm_calls;
	atomic_t disarm_calls;
	atomic_t owner_calls;
	atomic_t peer_calls;
	atomic_t bad_access;
	atomic_t handler_timeout;
	struct completion handler_entered;
	struct completion handler_release;
	struct completion peer_seen;
	struct completion free_done;
	struct task_struct *free_thread;
};

/* The driver core holds this sleepable lock across probe/remove callbacks. */
static void terminal_retire(struct terminal_wake_fixture *f)
{
	if (IS_ERR_OR_NULL(f->device)) {
		musb_free_irq(&f->musb);
		return;
	}
	device_lock(f->device);
	musb_free_irq(&f->musb);
	device_unlock(f->device);
}

static int terminal_chip_wake(struct irq_data *data, unsigned int on)
{
	struct terminal_wake_fixture *f = container_of(data->chip,
						 struct terminal_wake_fixture, chip);

	if (data->irq != f->irq || !READ_ONCE(f->resources_live))
		atomic_inc(&f->bad_access);
	if (on) {
		atomic_inc(&f->arm_calls);
		return READ_ONCE(f->fail_arm) ? -EIO : 0;
	}
	atomic_inc(&f->disarm_calls);
	return READ_ONCE(f->fail_disarm) ? -EIO : 0;
}

static irqreturn_t terminal_owner_handler(int irq, void *data)
{
	struct terminal_wake_fixture *f = container_of(data, struct terminal_wake_fixture, musb);

	atomic_inc(&f->owner_calls);
	complete(&f->handler_entered);
	if (READ_ONCE(f->block_handler) &&
	    !wait_for_completion_timeout(&f->handler_release, 5 * HZ))
		atomic_inc(&f->handler_timeout);
	if (!READ_ONCE(f->resources_live))
		atomic_inc(&f->bad_access);
	return IRQ_HANDLED;
}

static irqreturn_t terminal_peer_handler(int irq, void *data)
{
	struct terminal_wake_fixture *f = container_of(data, struct terminal_wake_fixture, peer_calls);

	atomic_inc(&f->peer_calls);
	complete(&f->peer_seen);
	return IRQ_HANDLED;
}

static bool terminal_action_present(struct terminal_wake_fixture *f)
{
	struct irq_desc *desc = irq_to_desc(f->irq);
	struct irqaction *action;
	unsigned long flags;
	bool found = false;

	raw_spin_lock_irqsave(&desc->lock, flags);
	for (action = desc->action; action; action = action->next)
		if (action->dev_id == &f->musb)
			found = true;
	raw_spin_unlock_irqrestore(&desc->lock, flags);
	return found;
}

static int terminal_free_thread(void *data)
{
	struct terminal_wake_fixture *f = data;

	/* Both real wake-source teardown and action retirement can block here. */
	terminal_retire(f);
	WRITE_ONCE(f->resources_live, false);
	complete(&f->free_done);
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
	return 0;
}

static int terminal_request_owner(struct terminal_wake_fixture *f)
{
	int ret;

	WRITE_ONCE(f->resources_live, true);
	ret = request_threaded_irq(f->irq, NULL, terminal_owner_handler,
				   IRQF_SHARED | IRQF_ONESHOT, "terminal-owner", &f->musb);
	if (!ret)
		f->musb.nIrq = f->irq;
	return ret;
}

static void terminal_wake_exit(struct kunit *test)
{
	struct terminal_wake_fixture *f = test->priv;

	if (!f)
		return;
	complete_all(&f->handler_release);
	if (f->reader_held) {
		wakeup_sources_read_unlock(f->reader_index);
		f->reader_held = false;
	}
	if (f->free_thread)
		kthread_stop(f->free_thread);
	WRITE_ONCE(f->resources_live, true);
	WRITE_ONCE(f->fail_disarm, false);
	terminal_retire(f);
	/* Explicit fixture recovery AFTER debt assertions, using its saved IRQ.
	 * The production finalizer neither retries nor claims this recovery.
	 */
	if (f->musb.irq_wake) {
		KUNIT_EXPECT_EQ(test, disable_irq_wake(f->irq), 0);
		f->musb.irq_wake = false;
	}
	if (f->peer_wake)
		KUNIT_EXPECT_EQ(test, disable_irq_wake(f->irq), 0);
	if (f->peer_registered)
		free_irq(f->irq, &f->peer_calls);
	if (!IS_ERR_OR_NULL(f->device)) {
		/* Also release any deliberately foreign source owned by the fixture. */
		device_init_wakeup(f->device, false);
		root_device_unregister(f->device);
	}
	if (f->irq) {
		if (f->original_chip)
			irq_set_chip(f->irq, f->original_chip);
		irq_dispose_mapping(f->irq);
	}
	if (!IS_ERR_OR_NULL(f->domain))
		irq_domain_remove_sim(f->domain);
}

static int terminal_wake_init(struct kunit *test)
{
	struct terminal_wake_fixture *f;
	int ret;

	f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	if (!f)
		return -ENOMEM;
	test->priv = f;
	f->musb.nIrq = -ENODEV;
	spin_lock_init(&f->musb.lock);
	init_completion(&f->handler_entered);
	init_completion(&f->handler_release);
	init_completion(&f->peer_seen);
	init_completion(&f->free_done);
	f->device = root_device_register("musb-terminal-wake-test");
	if (IS_ERR(f->device))
		return PTR_ERR(f->device);
	f->musb.controller = f->device;
	f->domain = irq_domain_create_sim(NULL, 1);
	if (IS_ERR(f->domain))
		return PTR_ERR(f->domain);
	f->irq = irq_create_mapping(f->domain, 0);
	if (!f->irq)
		return -EINVAL;
	/* Keep the real simulator's delivery callbacks and chip_data. Only its
	 * wake hook is controlled; real IRQ-core depth/error accounting is intact.
	 */
	f->original_chip = irq_get_chip(f->irq);
	f->chip = *f->original_chip;
	f->chip.name = "terminal-wake-test";
	f->chip.flags &= ~IRQCHIP_SKIP_SET_WAKE;
	f->chip.irq_set_wake = terminal_chip_wake;
	irq_set_chip(f->irq, &f->chip);
	f->resources_live = true;
	ret = request_irq(f->irq, terminal_peer_handler, IRQF_SHARED | IRQF_ONESHOT,
			  "terminal-peer", &f->peer_calls);
	if (!ret)
		f->peer_registered = true;
	return ret;
}

static void terminal_expect_peer(struct kunit *test)
{
	struct terminal_wake_fixture *f = test->priv;
	int count = atomic_read(&f->peer_calls);

	reinit_completion(&f->peer_seen);
	KUNIT_ASSERT_EQ(test, irq_set_irqchip_state(f->irq, IRQCHIP_STATE_PENDING, true), 0);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->peer_seen, HZ), 0UL);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->peer_calls), count + 1);
}

static void terminal_unowned_test(struct kunit *test)
{
	struct terminal_wake_fixture *f = test->priv;

	terminal_retire(f);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->disarm_calls), 0);
	KUNIT_EXPECT_EQ(test, f->musb.nIrq, -ENODEV);
	terminal_expect_peer(test);
}

static void terminal_owned_wake_test(struct kunit *test)
{
	struct terminal_wake_fixture *f = test->priv;
	int before;

	KUNIT_ASSERT_EQ(test, terminal_request_owner(f), 0);
	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	KUNIT_ASSERT_NOT_NULL(test, f->device->power.wakeup);
	KUNIT_ASSERT_EQ(test, enable_irq_wake(f->irq), 0);
	f->musb.irq_wake = true;
	before = atomic_read(&f->disarm_calls);
	terminal_retire(f);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->disarm_calls), before + 1);
	KUNIT_EXPECT_EQ(test, irq_to_desc(f->irq)->wake_depth, 0U);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
	KUNIT_EXPECT_FALSE(test, f->musb.wakeup_initialized);
	KUNIT_EXPECT_FALSE(test, device_can_wakeup(f->device));
	KUNIT_EXPECT_NULL(test, f->device->power.wakeup);
	KUNIT_EXPECT_FALSE(test, terminal_action_present(f));
	KUNIT_EXPECT_EQ(test, f->musb.nIrq, -ENODEV);
	terminal_retire(f);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->disarm_calls), before + 1);
	terminal_expect_peer(test);
}

static void terminal_shared_peer_test(struct kunit *test)
{
	struct terminal_wake_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, enable_irq_wake(f->irq), 0);
	f->peer_wake = true;
	KUNIT_ASSERT_EQ(test, terminal_request_owner(f), 0);
	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	KUNIT_ASSERT_EQ(test, enable_irq_wake(f->irq), 0);
	f->musb.irq_wake = true;
	KUNIT_ASSERT_EQ(test, irq_to_desc(f->irq)->wake_depth, 2U);
	terminal_retire(f);
	KUNIT_EXPECT_EQ(test, irq_to_desc(f->irq)->wake_depth, 1U);
	KUNIT_EXPECT_TRUE(test, irqd_is_wakeup_set(irq_get_irq_data(f->irq)));
	KUNIT_EXPECT_EQ(test, atomic_read(&f->disarm_calls), 0);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
	terminal_expect_peer(test);
}

static void terminal_failed_disarm_test(struct kunit *test)
{
	struct terminal_wake_fixture *f = test->priv;
	int before;

	KUNIT_ASSERT_EQ(test, terminal_request_owner(f), 0);
	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	KUNIT_ASSERT_EQ(test, enable_irq_wake(f->irq), 0);
	f->musb.irq_wake = true;
	f->fail_disarm = true;
	before = atomic_read(&f->disarm_calls);
	terminal_retire(f);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->disarm_calls), before + 1);
	KUNIT_EXPECT_EQ(test, irq_to_desc(f->irq)->wake_depth, 1U);
	KUNIT_EXPECT_TRUE(test, f->musb.irq_wake);
	KUNIT_EXPECT_TRUE(test, irqd_is_wakeup_set(irq_get_irq_data(f->irq)));
	KUNIT_EXPECT_FALSE(test, terminal_action_present(f));
	KUNIT_EXPECT_EQ(test, f->musb.nIrq, -ENODEV);
	KUNIT_EXPECT_FALSE(test, f->musb.wakeup_initialized);
	terminal_retire(f);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->disarm_calls), before + 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 0);
	terminal_expect_peer(test);
}

static void terminal_wakeup_reader_test(struct kunit *test)
{
	struct terminal_wake_fixture *f = test->priv;
	struct task_struct *task;
	unsigned long deadline;

	KUNIT_ASSERT_EQ(test, terminal_request_owner(f), 0);
	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	KUNIT_ASSERT_NOT_NULL(test, f->device->power.wakeup);
	f->reader_index = wakeup_sources_read_lock();
	f->reader_held = true;
	task = kthread_run(terminal_free_thread, f, "terminal-wake-free");
	KUNIT_ASSERT_FALSE(test, IS_ERR(task));
	f->free_thread = task;
	deadline = jiffies + HZ;
	while (READ_ONCE(f->device->power.wakeup) && time_before(jiffies, deadline))
		msleep(1);
	/* Detach proves real source cleanup entered. Its SRCU grace period must
	 * finish before action release; no stub or held controller lock hides it.
	 */
	KUNIT_ASSERT_NULL(test, READ_ONCE(f->device->power.wakeup));
	KUNIT_EXPECT_FALSE(test, completion_done(&f->free_done));
	KUNIT_EXPECT_TRUE(test, terminal_action_present(f));
	KUNIT_EXPECT_EQ(test, f->musb.nIrq, (int)f->irq);
	KUNIT_EXPECT_TRUE(test, READ_ONCE(f->resources_live));
	wakeup_sources_read_unlock(f->reader_index);
	f->reader_held = false;
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->free_done, HZ), 0UL);
	KUNIT_EXPECT_FALSE(test, terminal_action_present(f));
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 0);
	terminal_expect_peer(test);
}

static void terminal_running_handler_test(struct kunit *test)
{
	struct terminal_wake_fixture *f = test->priv;
	struct task_struct *task;
	unsigned long deadline;

	f->block_handler = true;
	KUNIT_ASSERT_EQ(test, terminal_request_owner(f), 0);
	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	KUNIT_ASSERT_EQ(test, enable_irq_wake(f->irq), 0);
	f->musb.irq_wake = true;
	KUNIT_ASSERT_EQ(test, irq_set_irqchip_state(f->irq, IRQCHIP_STATE_PENDING, true), 0);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->handler_entered, HZ), 0UL);
	task = kthread_run(terminal_free_thread, f, "terminal-irq-free");
	KUNIT_ASSERT_FALSE(test, IS_ERR(task));
	f->free_thread = task;
	deadline = jiffies + HZ;
	while (terminal_action_present(f) && time_before(jiffies, deadline))
		msleep(1);
	KUNIT_ASSERT_FALSE(test, terminal_action_present(f));
	KUNIT_EXPECT_FALSE(test, completion_done(&f->free_done));
	KUNIT_EXPECT_TRUE(test, READ_ONCE(f->resources_live));
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
	KUNIT_EXPECT_NULL(test, READ_ONCE(f->device->power.wakeup));
	complete(&f->handler_release);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->free_done, HZ), 0UL);
	KUNIT_EXPECT_EQ(test, f->musb.nIrq, -ENODEV);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->handler_timeout), 0);
	terminal_expect_peer(test);
}

static void terminal_foreign_state_test(struct kunit *test)
{
	struct terminal_wake_fixture *f = test->priv;
	struct wakeup_source *source;

	KUNIT_ASSERT_EQ(test, device_init_wakeup(f->device, true), 0);
	source = f->device->power.wakeup;
	KUNIT_ASSERT_NOT_NULL(test, source);
	KUNIT_ASSERT_EQ(test, terminal_request_owner(f), 0);
	KUNIT_EXPECT_EQ(test, musb_init_wakeup(&f->musb), -EEXIST);
	terminal_retire(f);
	KUNIT_EXPECT_PTR_EQ(test, f->device->power.wakeup, source);
	KUNIT_EXPECT_TRUE(test, device_can_wakeup(f->device));
	KUNIT_EXPECT_EQ(test, atomic_read(&f->disarm_calls), 0);
	terminal_expect_peer(test);
}

static void terminal_unsupported_wake_test(struct kunit *test)
{
	struct terminal_wake_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, terminal_request_owner(f), 0);
	f->fail_arm = true;
	KUNIT_EXPECT_EQ(test, musb_init_wakeup(&f->musb), 0);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
	KUNIT_EXPECT_FALSE(test, f->musb.wakeup_initialized);
	terminal_retire(f);
	KUNIT_EXPECT_EQ(test, irq_to_desc(f->irq)->wake_depth, 0U);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->disarm_calls), 0);
	terminal_expect_peer(test);
}

static struct kunit_case terminal_wake_cases[] = {
	KUNIT_CASE(terminal_unowned_test),
	KUNIT_CASE(terminal_owned_wake_test),
	KUNIT_CASE(terminal_shared_peer_test),
	KUNIT_CASE(terminal_failed_disarm_test),
	KUNIT_CASE(terminal_wakeup_reader_test),
	KUNIT_CASE(terminal_running_handler_test),
	KUNIT_CASE(terminal_foreign_state_test),
	KUNIT_CASE(terminal_unsupported_wake_test),
	{}
};

static struct kunit_suite terminal_wake_suite = {
	.name = "musb-terminal-wake",
	.init = terminal_wake_init,
	.exit = terminal_wake_exit,
	.test_cases = terminal_wake_cases,
};
kunit_test_suite(terminal_wake_suite);
