// SPDX-License-Identifier: GPL-2.0
/* Included alongside the production helper only in an isolated test kernel. */
#include <kunit/test.h>
#include <linux/delay.h>
#include <linux/kthread.h>

struct work_fixture {
	struct musb musb;
	struct device *device;
	struct task_struct *shutdown_thread;
	struct completion entered, release, stopped;
	atomic_t calls[3], timer_calls, bad_access, timeouts, pm_suspends;
	bool block, resources_live, take_session, requeued;
};

static int fixture_pm_suspend(struct device *dev)
{
	struct work_fixture *f = dev_get_drvdata(dev);

	atomic_inc(&f->pm_suspends);
	if (!READ_ONCE(f->resources_live))
		atomic_inc(&f->bad_access);
	return 0;
}

static const struct dev_pm_ops fixture_pm_ops = {
	.runtime_suspend = fixture_pm_suspend,
};

static const struct device_type fixture_device_type = {
	.name = "musb-work-test",
	.pm = &fixture_pm_ops,
};

static struct delayed_work *fixture_work(struct work_fixture *f, int index)
{
	switch (index) {
	case 0: return &f->musb.irq_work;
	case 1: return &f->musb.finish_resume_work;
	default: return &f->musb.deassert_reset_work;
	}
}

static void fixture_callback(struct work_fixture *f, int index)
{
	unsigned long flags;

	atomic_inc(&f->calls[index]);
	complete(&f->entered);
	if (READ_ONCE(f->block) &&
	    !wait_for_completion_timeout(&f->release, 5 * HZ))
		atomic_inc(&f->timeouts);
	spin_lock_irqsave(&f->musb.lock, flags);
	if (!READ_ONCE(f->resources_live))
		atomic_inc(&f->bad_access);
	spin_unlock_irqrestore(&f->musb.lock, flags);
	if (f->take_session && index == 0) {
		pm_runtime_get_noresume(f->device);
		f->musb.session = true;
	}
	if (f->block)
		f->requeued = schedule_delayed_work(fixture_work(f, index), 60 * HZ);
}

static void fixture_irq(struct work_struct *work)
{
	fixture_callback(container_of(work, struct work_fixture, musb.irq_work.work), 0);
}

static void fixture_resume(struct work_struct *work)
{
	fixture_callback(container_of(work, struct work_fixture, musb.finish_resume_work.work), 1);
}

static void fixture_reset(struct work_struct *work)
{
	fixture_callback(container_of(work, struct work_fixture, musb.deassert_reset_work.work), 2);
}

static void fixture_timer(struct timer_list *timer)
{
	struct work_fixture *f = timer_container_of(f, timer, musb.otg_timer);

	atomic_inc(&f->timer_calls);
}

static void fixture_init_work(struct work_fixture *f)
{
	spin_lock_init(&f->musb.lock);
	init_completion(&f->entered);
	init_completion(&f->release);
	init_completion(&f->stopped);
	INIT_DELAYED_WORK(&f->musb.irq_work, fixture_irq);
	INIT_DELAYED_WORK(&f->musb.finish_resume_work, fixture_resume);
	INIT_DELAYED_WORK(&f->musb.deassert_reset_work, fixture_reset);
	timer_setup(&f->musb.otg_timer, fixture_timer, 0);
	f->resources_live = true;
}

static int work_fixture_init(struct kunit *test)
{
	struct work_fixture *f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);

	if (!f)
		return -ENOMEM;
	fixture_init_work(f);
	test->priv = f;
	f->device = root_device_register("musb-work-kunit");
	if (IS_ERR(f->device))
		return PTR_ERR(f->device);
	f->musb.controller = f->device;
	f->device->type = &fixture_device_type;
	dev_set_drvdata(f->device, f);
	pm_runtime_set_active(f->device);
	pm_runtime_get_noresume(f->device);
	pm_runtime_get_noresume(f->device);
	pm_runtime_enable(f->device);
	return 0;
}

static void work_fixture_exit(struct kunit *test)
{
	struct work_fixture *f = test->priv;

	if (!f)
		return;
	complete_all(&f->release);
	if (f->shutdown_thread)
		kthread_stop(f->shutdown_thread);
	musb_shutdown_work(&f->musb);
	if (!IS_ERR_OR_NULL(f->device)) {
		if (pm_runtime_enabled(f->device))
			pm_runtime_disable(f->device);
		musb_release_session(&f->musb);
		while (atomic_read(&f->device->power.usage_count) > 0)
			pm_runtime_put_noidle(f->device);
		f->device->type = NULL;
		root_device_unregister(f->device);
	}
}

static void expect_closed(struct kunit *test, struct work_fixture *f)
{
	int i;

	for (i = 0; i < 3; i++) {
		KUNIT_EXPECT_FALSE(test, schedule_delayed_work(fixture_work(f, i), 60 * HZ));
		KUNIT_EXPECT_FALSE(test, delayed_work_pending(fixture_work(f, i)));
	}
	mod_timer(&f->musb.otg_timer, jiffies + 60 * HZ);
	KUNIT_EXPECT_FALSE(test, timer_pending(&f->musb.otg_timer));
	KUNIT_EXPECT_PTR_EQ(test, f->musb.otg_timer.function, NULL);
}

static void work_pending_test(struct kunit *test)
{
	struct work_fixture *f = test->priv;
	int i;

	for (i = 0; i < 3; i++)
		KUNIT_ASSERT_TRUE(test, schedule_delayed_work(fixture_work(f, i), 60 * HZ));
	mod_timer(&f->musb.otg_timer, jiffies + 60 * HZ);
	KUNIT_ASSERT_TRUE(test, timer_pending(&f->musb.otg_timer));
	musb_shutdown_work(&f->musb);
	expect_closed(test, f);
	for (i = 0; i < 3; i++)
		KUNIT_EXPECT_EQ(test, atomic_read(&f->calls[i]), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->timer_calls), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 2);
}

static int fixture_shutdown(void *data)
{
	struct work_fixture *f = data;

	musb_shutdown_work(&f->musb);
	pm_runtime_disable(f->device);
	musb_release_session(&f->musb);
	WRITE_ONCE(f->resources_live, false);
	complete(&f->stopped);
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
	return 0;
}

static bool fixture_disabled(struct delayed_work *work)
{
	unsigned long data = atomic_long_read(&work->work.data);

	/* Pinned workqueue representation; observe admission closure before release. */
	return !(data & WORK_STRUCT_PWQ) && (data & WORK_OFFQ_DISABLE_MASK);
}

static void check_running_work(struct kunit *test, int index)
{
	struct work_fixture *f = test->priv;
	struct delayed_work *work = fixture_work(f, index);
	struct task_struct *thread;
	unsigned long deadline;

	f->block = true;
	f->take_session = index == 0;
	KUNIT_ASSERT_TRUE(test, schedule_delayed_work(work, 0));
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->entered, HZ), 0UL);
	thread = kthread_run(fixture_shutdown, f, "musb-work-stop");
	KUNIT_ASSERT_FALSE(test, IS_ERR(thread));
	f->shutdown_thread = thread;
	deadline = jiffies + HZ;
	while (!fixture_disabled(work) && time_before(jiffies, deadline))
		msleep(1);
	KUNIT_ASSERT_TRUE(test, fixture_disabled(work));
	KUNIT_EXPECT_FALSE(test, completion_done(&f->stopped));
	KUNIT_EXPECT_TRUE(test, READ_ONCE(f->resources_live));
	complete(&f->release);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->stopped, HZ), 0UL);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->calls[index]), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->timeouts), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 0);
	KUNIT_EXPECT_FALSE(test, f->requeued);
	KUNIT_EXPECT_FALSE(test, f->musb.session);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 2);
	expect_closed(test, f);
}

static void work_irq_running_test(struct kunit *test) { check_running_work(test, 0); }
static void work_resume_running_test(struct kunit *test) { check_running_work(test, 1); }
static void work_reset_running_test(struct kunit *test) { check_running_work(test, 2); }

static void work_session_accounting_test(struct kunit *test)
{
	struct work_fixture *f = test->priv;
	int foreign, owned;

	pm_runtime_disable(f->device);
	for (foreign = 2; foreign >= 0; foreign -= 2) {
		for (owned = 0; owned <= 1; owned++) {
			if (owned)
				pm_runtime_get_noresume(f->device);
			f->musb.session = owned;
			musb_shutdown_work(&f->musb);
			KUNIT_EXPECT_EQ(test, f->musb.session, (bool)owned);
			KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), foreign + owned);
			musb_release_session(&f->musb);
			KUNIT_EXPECT_FALSE(test, f->musb.session);
			KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), foreign);
			musb_release_session(&f->musb);
			KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), foreign);
			KUNIT_EXPECT_EQ(test, f->device->power.request, RPM_REQ_NONE);
		}
		if (foreign) {
			pm_runtime_put_noidle(f->device);
			pm_runtime_put_noidle(f->device);
		}
	}
}

static void check_pm_tail(struct kunit *test, bool early_release)
{
	struct work_fixture *f = test->priv;

	/* Two existing holds model the Sunxi backend and remove's temporary get. */
	pm_runtime_get_noresume(f->device);
	f->musb.session = true;
	musb_shutdown_work(&f->musb);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 3);
	if (early_release) {
		/* Deliberate negative control: reproduce the rejected first candidate. */
		f->musb.session = false;
		pm_runtime_put_noidle(f->device);
	}
	pm_runtime_put(f->device); /* backend exit's put before clock/reset teardown */
	WRITE_ONCE(f->resources_live, false);
	pm_runtime_put_sync(f->device); /* the remaining core put */
	pm_runtime_disable(f->device);
	musb_release_session(&f->musb);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->pm_suspends), early_release ? 1 : 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), early_release ? 1 : 0);
}

static void work_pm_tail_test(struct kunit *test) { check_pm_tail(test, false); }
static void work_pm_tail_control_test(struct kunit *test) { check_pm_tail(test, true); }

static void work_fresh_instance_test(struct kunit *test)
{
	struct work_fixture *old = test->priv;
	struct work_fixture *fresh = kunit_kzalloc(test, sizeof(*fresh), GFP_KERNEL);
	int i;

	KUNIT_ASSERT_NOT_NULL(test, fresh);
	fixture_init_work(fresh);
	fresh->musb.controller = old->device;
	musb_shutdown_work(&old->musb);
	for (i = 0; i < 3; i++) {
		KUNIT_EXPECT_TRUE(test, schedule_delayed_work(fixture_work(fresh, i), 0));
		flush_delayed_work(fixture_work(fresh, i));
		KUNIT_EXPECT_EQ(test, atomic_read(&fresh->calls[i]), 1);
	}
	musb_shutdown_work(&fresh->musb);
	expect_closed(test, fresh);
	expect_closed(test, old);
}

static struct kunit_case musb_work_cases[] = {
	KUNIT_CASE(work_pending_test),
	KUNIT_CASE(work_irq_running_test),
	KUNIT_CASE(work_resume_running_test),
	KUNIT_CASE(work_reset_running_test),
	KUNIT_CASE(work_session_accounting_test),
	KUNIT_CASE(work_pm_tail_test),
	KUNIT_CASE(work_pm_tail_control_test),
	KUNIT_CASE(work_fresh_instance_test),
	{}
};

static struct kunit_suite musb_work_suite = {
	.name = "musb-work",
	.init = work_fixture_init,
	.exit = work_fixture_exit,
	.test_cases = musb_work_cases,
};
kunit_test_suite(musb_work_suite);
