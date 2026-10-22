// SPDX-License-Identifier: GPL-2.0
/* Included in musb_core.c only by the isolated test patch. */
#include <kunit/test.h>
#include <linux/delay.h>
#include <linux/irq.h>
#include <linux/irqdesc.h>
#include <linux/irq_sim.h>
#include <linux/kthread.h>

struct musb_irq_fixture {
	struct musb musb;
	struct irq_domain *domain;
	unsigned int irq;
	bool peer_registered;
	bool block_handler;
	bool resources_live;
	atomic_t owner_calls;
	atomic_t peer_calls;
	atomic_t bad_resource_access;
	atomic_t handler_timeout;
	struct completion handler_entered;
	struct completion handler_release;
	struct completion peer_seen;
	struct completion free_done;
	struct task_struct *free_thread;
};

static irqreturn_t musb_irq_test_thread(int irq, void *data)
{
	struct musb_irq_fixture *f = container_of(data, struct musb_irq_fixture, musb);

	atomic_inc(&f->owner_calls);
	complete(&f->handler_entered);
	if (READ_ONCE(f->block_handler) &&
	    !wait_for_completion_timeout(&f->handler_release, msecs_to_jiffies(5000)))
		atomic_inc(&f->handler_timeout);
	if (!READ_ONCE(f->resources_live))
		atomic_inc(&f->bad_resource_access);
	return IRQ_HANDLED;
}

static irqreturn_t musb_irq_test_peer(int irq, void *data)
{
	struct musb_irq_fixture *f = container_of(data, struct musb_irq_fixture, peer_calls);

	atomic_inc(&f->peer_calls);
	complete(&f->peer_seen);
	return IRQ_HANDLED;
}

static bool musb_irq_test_action_present(struct musb_irq_fixture *f)
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

static int musb_irq_test_free_thread(void *data)
{
	struct musb_irq_fixture *f = data;

	musb_free_irq(&f->musb);
	WRITE_ONCE(f->resources_live, false);
	complete(&f->free_done);
	/* Retain the task until fixture cleanup joins it. */
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
	return 0;
}

static int musb_irq_test_request_owner(struct musb_irq_fixture *f)
{
	int ret;

	WRITE_ONCE(f->resources_live, true);
	ret = request_threaded_irq(f->irq, NULL, musb_irq_test_thread,
				   IRQF_SHARED | IRQF_ONESHOT, "musb-test", &f->musb);
	if (!ret)
		f->musb.nIrq = f->irq;
	return ret;
}

static void musb_irq_test_exit(struct kunit *test)
{
	struct musb_irq_fixture *f = test->priv;

	if (!f)
		return;
	complete_all(&f->handler_release);
	if (f->free_thread)
		kthread_stop(f->free_thread);
	musb_free_irq(&f->musb);
	if (f->peer_registered)
		free_irq(f->irq, &f->peer_calls);
	if (f->irq)
		irq_dispose_mapping(f->irq);
	if (!IS_ERR_OR_NULL(f->domain))
		irq_domain_remove_sim(f->domain);
}

static int musb_irq_test_init(struct kunit *test)
{
	struct musb_irq_fixture *f;
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
	f->domain = irq_domain_create_sim(NULL, 1);
	if (IS_ERR(f->domain))
		return PTR_ERR(f->domain);
	f->irq = irq_create_mapping(f->domain, 0);
	if (!f->irq)
		return -EINVAL;
	ret = request_irq(f->irq, musb_irq_test_peer, IRQF_SHARED | IRQF_ONESHOT,
			  "musb-peer", &f->peer_calls);
	if (ret)
		return ret;
	f->peer_registered = true;
	return 0;
}

static void musb_irq_expect_peer(struct kunit *test)
{
	struct musb_irq_fixture *f = test->priv;
	int count = atomic_read(&f->peer_calls);

	reinit_completion(&f->peer_seen);
	KUNIT_ASSERT_EQ(test, irq_set_irqchip_state(f->irq, IRQCHIP_STATE_PENDING, true), 0);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->peer_seen, HZ), 0UL);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->peer_calls), count + 1);
}

static void irq_unowned_test(struct kunit *test)
{
	struct musb_irq_fixture *f = test->priv;

	musb_free_irq(&f->musb);
	KUNIT_EXPECT_EQ(test, f->musb.nIrq, -ENODEV);
	musb_irq_expect_peer(test);
}

static void irq_shared_release_test(struct kunit *test)
{
	struct musb_irq_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, musb_irq_test_request_owner(f), 0);
	KUNIT_ASSERT_TRUE(test, musb_irq_test_action_present(f));
	musb_free_irq(&f->musb);
	KUNIT_EXPECT_FALSE(test, musb_irq_test_action_present(f));
	KUNIT_EXPECT_EQ(test, f->musb.nIrq, -ENODEV);
	/* A repeated finalizer must not free the peer's remaining action. */
	musb_free_irq(&f->musb);
	musb_irq_expect_peer(test);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->owner_calls), 0);
}

static void irq_running_handler_test(struct kunit *test)
{
	struct musb_irq_fixture *f = test->priv;
	unsigned long deadline;
	struct task_struct *task;

	WRITE_ONCE(f->block_handler, true);
	KUNIT_ASSERT_EQ(test, musb_irq_test_request_owner(f), 0);
	KUNIT_ASSERT_EQ(test, irq_set_irqchip_state(f->irq, IRQCHIP_STATE_PENDING, true), 0);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->handler_entered, HZ), 0UL);
	task = kthread_run(musb_irq_test_free_thread, f, "musb-irq-free");
	KUNIT_ASSERT_FALSE(test, IS_ERR(task));
	f->free_thread = task;
	deadline = jiffies + HZ;
	while (musb_irq_test_action_present(f) && time_before(jiffies, deadline))
		msleep(1);
	/* Unlink proves free_irq has entered, rather than a delayed test task. */
	KUNIT_ASSERT_FALSE(test, musb_irq_test_action_present(f));
	KUNIT_EXPECT_FALSE(test, completion_done(&f->free_done));
	KUNIT_EXPECT_TRUE(test, READ_ONCE(f->resources_live));
	complete(&f->handler_release);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->free_done, HZ), 0UL);
	KUNIT_EXPECT_EQ(test, f->musb.nIrq, -ENODEV);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->owner_calls), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->handler_timeout), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_resource_access), 0);
	musb_irq_expect_peer(test);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->owner_calls), 1);
}

static void irq_request_again_test(struct kunit *test)
{
	struct musb_irq_fixture *f = test->priv;
	int i;

	for (i = 0; i < 3; i++) {
		reinit_completion(&f->handler_entered);
		KUNIT_ASSERT_EQ(test, musb_irq_test_request_owner(f), 0);
		KUNIT_ASSERT_EQ(test, irq_set_irqchip_state(f->irq, IRQCHIP_STATE_PENDING, true), 0);
		KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->handler_entered, HZ), 0UL);
		musb_free_irq(&f->musb);
		KUNIT_EXPECT_EQ(test, atomic_read(&f->owner_calls), i + 1);
		KUNIT_EXPECT_FALSE(test, musb_irq_test_action_present(f));
		musb_irq_expect_peer(test);
	}
}

static struct kunit_case musb_irq_cases[] = {
	KUNIT_CASE(irq_unowned_test),
	KUNIT_CASE(irq_shared_release_test),
	KUNIT_CASE(irq_running_handler_test),
	KUNIT_CASE(irq_request_again_test),
	{}
};

static struct kunit_suite musb_irq_suite = {
	.name = "musb-irq",
	.init = musb_irq_test_init,
	.exit = musb_irq_test_exit,
	.test_cases = musb_irq_cases,
};
kunit_test_suite(musb_irq_suite);
