// SPDX-License-Identifier: GPL-2.0
/* Included with the production PM helper in an isolated UML kernel only. */
#include <kunit/test.h>
#include <linux/delay.h>
#include <linux/kthread.h>

struct pm_fixture {
	struct musb musb;
	struct device *device;
	struct task_struct *callback_thread, *disable_thread;
	struct completion entered, release, drained;
	atomic_t suspends, resumes, bad_access, timeouts;
	bool resources_live, block, resume;
	int callback_error, request_result;
};

static int pm_fixture_callback(struct device *dev, bool resume)
{
	struct pm_fixture *f = dev_get_drvdata(dev);
	unsigned long flags;

	atomic_inc(resume ? &f->resumes : &f->suspends);
	complete(&f->entered);
	if (READ_ONCE(f->block) &&
	    !wait_for_completion_timeout(&f->release, 5 * HZ))
		atomic_inc(&f->timeouts);
	/* The barrier must not retain the controller lock needed by callbacks. */
	spin_lock_irqsave(&f->musb.lock, flags);
	if (!READ_ONCE(f->resources_live))
		atomic_inc(&f->bad_access);
	spin_unlock_irqrestore(&f->musb.lock, flags);
	return f->callback_error;
}

static int pm_fixture_suspend(struct device *dev) { return pm_fixture_callback(dev, false); }
static int pm_fixture_resume(struct device *dev) { return pm_fixture_callback(dev, true); }

static const struct dev_pm_ops pm_fixture_ops = {
	.runtime_suspend = pm_fixture_suspend,
	.runtime_resume = pm_fixture_resume,
};

static const struct device_type pm_fixture_type = {
	.name = "musb-pm-test",
	.pm = &pm_fixture_ops,
};

static int pm_fixture_init(struct kunit *test)
{
	struct pm_fixture *f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);

	if (!f)
		return -ENOMEM;
	test->priv = f;
	spin_lock_init(&f->musb.lock);
	init_completion(&f->entered);
	init_completion(&f->release);
	init_completion(&f->drained);
	f->resources_live = true;
	f->device = root_device_register("musb-pm-kunit");
	if (IS_ERR(f->device))
		return PTR_ERR(f->device);
	f->musb.controller = f->device;
	f->device->type = &pm_fixture_type;
	dev_set_drvdata(f->device, f);
	pm_runtime_set_active(f->device);
	pm_runtime_set_autosuspend_delay(f->device, 500);
	pm_runtime_use_autosuspend(f->device);
	pm_runtime_get_noresume(f->device); /* retained core probe/remove reference */
	pm_runtime_enable(f->device);
	return 0;
}

static void pm_fixture_exit(struct kunit *test)
{
	struct pm_fixture *f = test->priv;

	if (!f)
		return;
	complete_all(&f->release);
	if (f->callback_thread)
		kthread_stop(f->callback_thread);
	if (f->disable_thread)
		kthread_stop(f->disable_thread);
	if (!IS_ERR_OR_NULL(f->device)) {
		if (pm_runtime_enabled(f->device))
			pm_runtime_disable(f->device);
		pm_runtime_dont_use_autosuspend(f->device);
		while (atomic_read(&f->device->power.usage_count) > 0)
			pm_runtime_put_noidle(f->device);
		f->device->type = NULL;
		root_device_unregister(f->device);
	}
}

static void pm_active_retirement_test(struct kunit *test)
{
	struct pm_fixture *f = test->priv;
	int backend, session, foreign, i;

	for (backend = 0; backend <= 1; backend++)
		for (session = 0; session <= 1; session++)
			for (foreign = 0; foreign <= 2; foreign += 2) {
				for (i = 0; i < backend + session + foreign; i++)
					pm_runtime_get_noresume(f->device);
				f->musb.session = session;
				musb_disable_runtime_pm(&f->musb);
				KUNIT_EXPECT_EQ(test, (int)f->device->power.disable_depth, 1);
				KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count),
					       1 + backend + session + foreign);
				if (backend)
					pm_runtime_put(f->device);
				WRITE_ONCE(f->resources_live, false);
				pm_runtime_put_noidle(f->device);
				musb_release_session(&f->musb);
				KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), foreign);
				KUNIT_EXPECT_EQ(test, atomic_read(&f->suspends), 0);
				KUNIT_EXPECT_EQ(test, atomic_read(&f->resumes), 0);
				KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 0);
				KUNIT_EXPECT_FALSE(test, f->device->power.request_pending);
				KUNIT_EXPECT_FALSE(test, f->device->power.use_autosuspend);
				for (i = 0; i < foreign; i++)
					pm_runtime_put_noidle(f->device);
				WRITE_ONCE(f->resources_live, true);
				pm_runtime_use_autosuspend(f->device);
				pm_runtime_get_noresume(f->device);
				pm_runtime_enable(f->device);
			}
}

static void pm_no_session_control_test(struct kunit *test)
{
	struct pm_fixture *f = test->priv;

	/* Deliberate old-order control: model Sunxi exit and the late core put. */
	pm_runtime_get_noresume(f->device);
	pm_runtime_put(f->device);
	WRITE_ONCE(f->resources_live, false);
	pm_runtime_dont_use_autosuspend(f->device);
	pm_runtime_put_sync(f->device);
	pm_runtime_disable(f->device);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->suspends), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 0);
}

static int pm_fixture_request(void *data)
{
	struct pm_fixture *f = data;

	f->request_result = f->resume ? pm_runtime_resume_and_get(f->device) :
				       pm_runtime_suspend(f->device);
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
	return 0;
}

static int pm_fixture_disable(void *data)
{
	struct pm_fixture *f = data;

	musb_disable_runtime_pm(&f->musb);
	WRITE_ONCE(f->resources_live, false);
	complete(&f->drained);
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
	return 0;
}

static bool pm_fixture_disabled(struct device *dev)
{
	unsigned long flags;
	bool disabled;

	spin_lock_irqsave(&dev->power.lock, flags);
	disabled = dev->power.disable_depth != 0;
	spin_unlock_irqrestore(&dev->power.lock, flags);
	return disabled;
}

static void check_running_pm(struct kunit *test, bool resume)
{
	struct pm_fixture *f = test->priv;
	struct task_struct *thread;
	unsigned long deadline;

	pm_runtime_put_noidle(f->device);
	if (resume) {
		pm_runtime_disable(f->device);
		KUNIT_ASSERT_EQ(test, pm_runtime_set_suspended(f->device), 0);
		pm_runtime_enable(f->device);
	}
	f->resume = resume;
	f->block = true;
	thread = kthread_run(pm_fixture_request, f, "musb-pm-request");
	KUNIT_ASSERT_FALSE(test, IS_ERR(thread));
	f->callback_thread = thread;
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->entered, HZ), 0UL);
	thread = kthread_run(pm_fixture_disable, f, "musb-pm-disable");
	KUNIT_ASSERT_FALSE(test, IS_ERR(thread));
	f->disable_thread = thread;
	deadline = jiffies + HZ;
	while (!pm_fixture_disabled(f->device) && time_before(jiffies, deadline))
		msleep(1);
	KUNIT_ASSERT_TRUE(test, pm_fixture_disabled(f->device));
	KUNIT_EXPECT_FALSE(test, completion_done(&f->drained));
	KUNIT_EXPECT_TRUE(test, READ_ONCE(f->resources_live));
	complete(&f->release);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->drained, HZ), 0UL);
	/* Join the request before inspecting its return and retained reference. */
	kthread_stop(f->callback_thread);
	f->callback_thread = NULL;
	KUNIT_EXPECT_EQ(test, f->request_result, 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->resumes), resume ? 1 : 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->suspends), resume ? 0 : 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), resume ? 1 : 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->timeouts), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 0);
}

static void pm_running_suspend_test(struct kunit *test) { check_running_pm(test, false); }
static void pm_running_resume_test(struct kunit *test) { check_running_pm(test, true); }

static void pm_failed_resume_test(struct kunit *test)
{
	struct pm_fixture *f = test->priv;

	pm_runtime_disable(f->device);
	KUNIT_ASSERT_EQ(test, pm_runtime_set_suspended(f->device), 0);
	f->callback_error = -EIO;
	pm_runtime_enable(f->device);
	KUNIT_ASSERT_EQ(test, pm_runtime_get_sync(f->device), -EIO);
	KUNIT_ASSERT_EQ(test, atomic_read(&f->device->power.usage_count), 2);
	musb_disable_runtime_pm(&f->musb);
	WRITE_ONCE(f->resources_live, false);
	pm_runtime_put_noidle(f->device); /* balance the failed get, retain foreign hold */
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->resumes), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 0);
}

static void pm_future_requests_test(struct kunit *test)
{
	struct pm_fixture *f = test->priv;

	musb_disable_runtime_pm(&f->musb);
	WRITE_ONCE(f->resources_live, false);
	/* Disabled-but-active requests report active without invoking a callback. */
	KUNIT_EXPECT_EQ(test, pm_runtime_get_sync(f->device), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 2);
	pm_runtime_put_noidle(f->device);
	KUNIT_EXPECT_EQ(test, pm_request_resume(f->device), 1);
	pm_runtime_put_sync(f->device);
	KUNIT_ASSERT_EQ(test, pm_runtime_set_suspended(f->device), 0);
	KUNIT_EXPECT_EQ(test, pm_runtime_get_sync(f->device), -EACCES);
	pm_runtime_put_noidle(f->device);
	KUNIT_EXPECT_EQ(test, pm_request_resume(f->device), -EACCES);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->suspends), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->resumes), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 0);
	KUNIT_EXPECT_FALSE(test, f->device->power.request_pending);
}

static void pm_reenable_test(struct kunit *test)
{
	struct pm_fixture *f = test->priv;

	musb_disable_runtime_pm(&f->musb);
	pm_runtime_put_noidle(f->device);
	pm_runtime_enable(f->device);
	KUNIT_ASSERT_EQ(test, pm_runtime_suspend(f->device), 0);
	KUNIT_ASSERT_EQ(test, pm_runtime_resume_and_get(f->device), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->suspends), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->resumes), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 0);
}

static void pm_autosuspend_policy_test(struct kunit *test)
{
	struct pm_fixture *f = test->priv;

	pm_runtime_set_autosuspend_delay(f->device, -1);
	KUNIT_ASSERT_EQ(test, atomic_read(&f->device->power.usage_count), 2);
	musb_disable_runtime_pm(&f->musb);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
	KUNIT_EXPECT_FALSE(test, f->device->power.use_autosuspend);
	WRITE_ONCE(f->resources_live, false);
	pm_runtime_put_noidle(f->device);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->suspends), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->resumes), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 0);
}

static struct kunit_case musb_pm_cases[] = {
	KUNIT_CASE(pm_active_retirement_test),
	KUNIT_CASE(pm_no_session_control_test),
	KUNIT_CASE(pm_running_suspend_test),
	KUNIT_CASE(pm_running_resume_test),
	KUNIT_CASE(pm_failed_resume_test),
	KUNIT_CASE(pm_future_requests_test),
	KUNIT_CASE(pm_reenable_test),
	KUNIT_CASE(pm_autosuspend_policy_test),
	{}
};

static struct kunit_suite musb_pm_suite = {
	.name = "musb-pm",
	.init = pm_fixture_init,
	.exit = pm_fixture_exit,
	.test_cases = musb_pm_cases,
};
kunit_test_suite(musb_pm_suite);
