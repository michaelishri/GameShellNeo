// SPDX-License-Identifier: GPL-2.0-only
/* Consumer retirement against real notifier traversal, SRCU and kthreads. */
#include <kunit/test.h>
#include <linux/completion.h>
#include <linux/delay.h>
#include <linux/interrupt.h>
#include <linux/kthread.h>
#include <linux/module.h>
#include <linux/timer.h>

#include "extcon.h"

#define EXTCON_TEST_TIMEOUT msecs_to_jiffies(5000)

enum extcon_test_hold {
	HOLD_TARGET,
	HOLD_PREDECESSOR,
	HOLD_ALL,
};

struct extcon_test_context {
	struct device *parent;
	struct extcon_dev *edev;
	struct notifier_block target;
	struct notifier_block predecessor;
	struct notifier_block all;
	struct notifier_block nested;
	struct completion entered;
	struct completion release;
	struct completion dispatch_done;
	struct completion removal_started;
	struct completion removal_done;
	struct task_struct *dispatcher;
	struct task_struct *remover;
	struct timer_list timer;
	wait_queue_head_t stop_wait;
	atomic_t target_calls;
	atomic_t nested_calls;
	atomic_t atomic_calls;
	bool hold;
	bool recurse;
	bool ordinary;
	bool target_registered;
	bool predecessor_registered;
	bool all_registered;
	bool nested_registered;
	enum extcon_test_hold hold_where;
	int dispatch_result;
	int removal_result;
	int nested_result;
};

static const unsigned int extcon_test_cables[] = {
	EXTCON_USB, EXTCON_USB_HOST, EXTCON_NONE,
};

static void extcon_test_hold(struct extcon_test_context *ctx)
{
	complete(&ctx->entered);
	wait_for_completion(&ctx->release);
}

static int extcon_test_target(struct notifier_block *nb, unsigned long event,
			      void *data)
{
	struct extcon_test_context *ctx = container_of(nb, typeof(*ctx), target);

	atomic_inc(&ctx->target_calls);
	if (in_interrupt())
		atomic_inc(&ctx->atomic_calls);
	if (ctx->recurse)
		ctx->nested_result = extcon_sync(ctx->edev, EXTCON_USB_HOST);
	if (READ_ONCE(ctx->hold) && ctx->hold_where == HOLD_TARGET)
		extcon_test_hold(ctx);
	return NOTIFY_DONE;
}

static int extcon_test_predecessor(struct notifier_block *nb,
				   unsigned long event, void *data)
{
	struct extcon_test_context *ctx = container_of(nb, typeof(*ctx), predecessor);

	if (READ_ONCE(ctx->hold) && ctx->hold_where == HOLD_PREDECESSOR)
		extcon_test_hold(ctx);
	return NOTIFY_DONE;
}

static int extcon_test_all(struct notifier_block *nb, unsigned long event,
			   void *data)
{
	struct extcon_test_context *ctx = container_of(nb, typeof(*ctx), all);

	if (READ_ONCE(ctx->hold) && ctx->hold_where == HOLD_ALL)
		extcon_test_hold(ctx);
	return NOTIFY_DONE;
}

static int extcon_test_nested(struct notifier_block *nb, unsigned long event,
			      void *data)
{
	struct extcon_test_context *ctx = container_of(nb, typeof(*ctx), nested);

	atomic_inc(&ctx->nested_calls);
	if (in_interrupt())
		atomic_inc(&ctx->atomic_calls);
	return NOTIFY_DONE;
}

static int extcon_test_dispatch(void *data)
{
	struct extcon_test_context *ctx = data;

	ctx->dispatch_result = extcon_sync(ctx->edev, EXTCON_USB);
	complete(&ctx->dispatch_done);
	/* Keep the task alive until fixture teardown calls kthread_stop(). */
	wait_event_interruptible(ctx->stop_wait, kthread_should_stop());
	return 0;
}

static int extcon_test_remove(void *data)
{
	struct extcon_test_context *ctx = data;

	complete(&ctx->removal_started);
	if (ctx->ordinary)
		ctx->removal_result = extcon_unregister_notifier(ctx->edev,
								 EXTCON_USB, &ctx->target);
	else
		ctx->removal_result = extcon_unregister_notifier_sync(ctx->edev,
								      EXTCON_USB, &ctx->target);
	if (!ctx->removal_result)
		ctx->target_registered = false;
	complete(&ctx->removal_done);
	wait_event_interruptible(ctx->stop_wait, kthread_should_stop());
	return 0;
}

static void extcon_test_timer(struct timer_list *timer)
{
	struct extcon_test_context *ctx = timer_container_of(ctx, timer, timer);

	ctx->dispatch_result = extcon_sync(ctx->edev, EXTCON_USB);
	complete(&ctx->dispatch_done);
}

static int extcon_test_init(struct kunit *test)
{
	struct extcon_test_context *ctx;
	int ret;

	ctx = kunit_kzalloc(test, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ctx->parent = root_device_register("extcon-notifier-kunit");
	if (IS_ERR(ctx->parent))
		return PTR_ERR(ctx->parent);
	ctx->edev = extcon_dev_allocate(extcon_test_cables);
	if (IS_ERR(ctx->edev)) {
		ret = PTR_ERR(ctx->edev);
		goto fail_parent;
	}
	ctx->edev->dev.parent = ctx->parent;
	ret = extcon_dev_register(ctx->edev);
	if (ret)
		goto fail_allocate;
	init_completion(&ctx->entered);
	init_completion(&ctx->release);
	init_completion(&ctx->dispatch_done);
	init_completion(&ctx->removal_started);
	init_completion(&ctx->removal_done);
	init_waitqueue_head(&ctx->stop_wait);
	timer_setup(&ctx->timer, extcon_test_timer, 0);
	ctx->target.notifier_call = extcon_test_target;
	ctx->predecessor.notifier_call = extcon_test_predecessor;
	ctx->predecessor.priority = 10;
	ctx->all.notifier_call = extcon_test_all;
	ctx->nested.notifier_call = extcon_test_nested;
	test->priv = ctx;
	return 0;

fail_allocate:
	extcon_dev_free(ctx->edev);
fail_parent:
	root_device_unregister(ctx->parent);
	return ret;
}

static void extcon_test_exit(struct kunit *test)
{
	struct extcon_test_context *ctx = test->priv;

	/* Assertion failures must release callbacks before draining the workers. */
	WRITE_ONCE(ctx->hold, false);
	complete_all(&ctx->release);
	timer_delete_sync(&ctx->timer);
	if (!IS_ERR_OR_NULL(ctx->dispatcher))
		kthread_stop(ctx->dispatcher);
	if (!IS_ERR_OR_NULL(ctx->remover))
		kthread_stop(ctx->remover);
	if (ctx->target_registered)
		extcon_unregister_notifier_sync(ctx->edev, EXTCON_USB, &ctx->target);
	if (ctx->predecessor_registered)
		extcon_unregister_notifier_sync(ctx->edev, EXTCON_USB, &ctx->predecessor);
	if (ctx->nested_registered)
		extcon_unregister_notifier_sync(ctx->edev, EXTCON_USB_HOST, &ctx->nested);
	/* No event producer remains: ordinary all-chain unlink is now safe. */
	if (ctx->all_registered)
		extcon_unregister_notifier_all(ctx->edev, &ctx->all);
	extcon_dev_unregister(ctx->edev);
	extcon_dev_free(ctx->edev);
	root_device_unregister(ctx->parent);
}

static bool extcon_test_target_linked(struct extcon_test_context *ctx)
{
	struct notifier_block *nb;
	unsigned long flags;
	bool found = false;

	/* USB is the first entry in this fixture's fixed cable list. */
	spin_lock_irqsave(&ctx->edev->lock, flags);
	for (nb = ctx->edev->nh[0].head; nb; nb = nb->next)
		if (nb == &ctx->target)
			found = true;
	spin_unlock_irqrestore(&ctx->edev->lock, flags);
	return found;
}

static void extcon_test_race(struct kunit *test, enum extcon_test_hold hold,
			     bool ordinary)
{
	struct extcon_test_context *ctx = test->priv;
	unsigned long deadline;
	unsigned long waited;

	KUNIT_ASSERT_EQ(test, extcon_register_notifier(ctx->edev, EXTCON_USB,
						       &ctx->target), 0);
	ctx->target_registered = true;
	if (hold == HOLD_PREDECESSOR) {
		KUNIT_ASSERT_EQ(test, extcon_register_notifier(ctx->edev, EXTCON_USB,
							       &ctx->predecessor), 0);
		ctx->predecessor_registered = true;
	}
	if (hold == HOLD_ALL) {
		KUNIT_ASSERT_EQ(test, extcon_register_notifier_all(ctx->edev, &ctx->all), 0);
		ctx->all_registered = true;
	}
	ctx->hold_where = hold;
	ctx->hold = true;
	ctx->ordinary = ordinary;
	ctx->dispatcher = kthread_run(extcon_test_dispatch, ctx, "extcon-dispatch");
	KUNIT_ASSERT_NOT_ERR_OR_NULL(test, ctx->dispatcher);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&ctx->entered,
							  EXTCON_TEST_TIMEOUT), 0UL);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->target_calls),
			hold == HOLD_PREDECESSOR ? 0 : 1);
	ctx->remover = kthread_run(extcon_test_remove, ctx, "extcon-remove");
	KUNIT_ASSERT_NOT_ERR_OR_NULL(test, ctx->remover);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&ctx->removal_started,
							  EXTCON_TEST_TIMEOUT), 0UL);
	deadline = jiffies + EXTCON_TEST_TIMEOUT;
	while (extcon_test_target_linked(ctx) && time_before(jiffies, deadline))
		usleep_range(1000, 2000);
	KUNIT_ASSERT_FALSE(test, extcon_test_target_linked(ctx));
	/* The ordinary control proves the remover can finish while the same
	 * callback is held. The synchronous case must wait for its SRCU reader.
	 */
	waited = wait_for_completion_timeout(&ctx->removal_done,
					     ordinary ? EXTCON_TEST_TIMEOUT : msecs_to_jiffies(100));
	if (ordinary)
		KUNIT_EXPECT_NE(test, waited, 0UL);
	else
		KUNIT_EXPECT_EQ(test, waited, 0UL);
	WRITE_ONCE(ctx->hold, false);
	complete(&ctx->release);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&ctx->dispatch_done,
							  EXTCON_TEST_TIMEOUT), 0UL);
	if (!ordinary)
		KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&ctx->removal_done,
								  EXTCON_TEST_TIMEOUT), 0UL);
	KUNIT_EXPECT_EQ(test, ctx->dispatch_result, 0);
	KUNIT_EXPECT_EQ(test, ctx->removal_result, 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->target_calls), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->atomic_calls), 0);
	KUNIT_EXPECT_EQ(test, extcon_sync(ctx->edev, EXTCON_USB), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->target_calls), 1);
	/* Re-registration is legal only after the old dispatch has drained. */
	KUNIT_ASSERT_EQ(test, extcon_register_notifier(ctx->edev, EXTCON_USB,
						       &ctx->target), 0);
	ctx->target_registered = true;
	KUNIT_EXPECT_EQ(test, extcon_sync(ctx->edev, EXTCON_USB), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->target_calls), 2);
}

static void extcon_sync_active_test(struct kunit *test)
{
	extcon_test_race(test, HOLD_TARGET, false);
}

static void extcon_sync_selected_next_test(struct kunit *test)
{
	extcon_test_race(test, HOLD_PREDECESSOR, false);
}

static void extcon_sync_all_chain_test(struct kunit *test)
{
	extcon_test_race(test, HOLD_ALL, false);
}

static void extcon_async_active_test(struct kunit *test)
{
	extcon_test_race(test, HOLD_TARGET, true);
}

static void extcon_async_selected_next_test(struct kunit *test)
{
	extcon_test_race(test, HOLD_PREDECESSOR, true);
}

static void extcon_async_all_chain_test(struct kunit *test)
{
	extcon_test_race(test, HOLD_ALL, true);
}

static void extcon_test_nesting(struct kunit *test, bool atomic)
{
	struct extcon_test_context *ctx = test->priv;

	KUNIT_ASSERT_EQ(test, extcon_register_notifier(ctx->edev, EXTCON_USB,
						       &ctx->target), 0);
	ctx->target_registered = true;
	KUNIT_ASSERT_EQ(test, extcon_register_notifier(ctx->edev, EXTCON_USB_HOST,
						       &ctx->nested), 0);
	ctx->nested_registered = true;
	ctx->recurse = true;
	if (atomic) {
		/* Isolate dispatch: the existing uevent tail may sleep. This test
		 * does not qualify unsuppressed extcon_sync() from an IRQ.
		 */
		ctx->edev->dev.kobj.uevent_suppress = 1;
		mod_timer(&ctx->timer, jiffies + 1);
		KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&ctx->dispatch_done,
								  EXTCON_TEST_TIMEOUT), 0UL);
		timer_delete_sync(&ctx->timer);
		ctx->edev->dev.kobj.uevent_suppress = 0;
	} else {
		ctx->dispatch_result = extcon_sync(ctx->edev, EXTCON_USB);
	}
	KUNIT_EXPECT_EQ(test, ctx->dispatch_result, 0);
	KUNIT_EXPECT_EQ(test, ctx->nested_result, 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->target_calls), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->nested_calls), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->atomic_calls), atomic ? 2 : 0);
}

static void extcon_nested_process_test(struct kunit *test)
{
	extcon_test_nesting(test, false);
}

static void extcon_nested_softirq_test(struct kunit *test)
{
	extcon_test_nesting(test, true);
}

static void extcon_unregistered_allocation_test(struct kunit *test)
{
	struct extcon_test_context *ctx = test->priv;
	struct extcon_dev *edev;

	extcon_dev_free(NULL);
	KUNIT_EXPECT_EQ(test, PTR_ERR(extcon_dev_allocate(NULL)), -EINVAL);
	edev = extcon_dev_allocate(extcon_test_cables);
	KUNIT_ASSERT_NOT_ERR_OR_NULL(test, edev);
	extcon_dev_free(edev);
	KUNIT_EXPECT_EQ(test, extcon_unregister_notifier_sync(NULL, EXTCON_USB,
							      &ctx->target), -EINVAL);
	KUNIT_EXPECT_EQ(test, extcon_unregister_notifier_sync(ctx->edev, EXTCON_USB,
							      NULL), -EINVAL);
	KUNIT_EXPECT_EQ(test, extcon_unregister_notifier_sync(ctx->edev, EXTCON_USB,
							      &ctx->target), -ENOENT);
}

static struct kunit_case extcon_notifier_cases[] = {
	KUNIT_CASE(extcon_sync_active_test),
	KUNIT_CASE(extcon_sync_selected_next_test),
	KUNIT_CASE(extcon_sync_all_chain_test),
	KUNIT_CASE(extcon_async_active_test),
	KUNIT_CASE(extcon_async_selected_next_test),
	KUNIT_CASE(extcon_async_all_chain_test),
	KUNIT_CASE(extcon_nested_process_test),
	KUNIT_CASE(extcon_nested_softirq_test),
	KUNIT_CASE(extcon_unregistered_allocation_test),
	{}
};

static struct kunit_suite extcon_notifier_suite = {
	.name = "extcon-notifier-lifetime",
	.init = extcon_test_init,
	.exit = extcon_test_exit,
	.test_cases = extcon_notifier_cases,
};

kunit_test_suite(extcon_notifier_suite);

MODULE_LICENSE("GPL");
