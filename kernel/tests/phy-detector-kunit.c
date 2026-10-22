// SPDX-License-Identifier: GPL-2.0-only
/* Included only by the generated offline test source, never the image queue. */
#include <kunit/test.h>
#include <linux/completion.h>
#include <linux/kthread.h>

struct detector_case {
	struct sun4i_usb_phy_data data;
	struct sun4i_usb_phy_cfg cfg;
	struct phy phy;
	struct device *parent;
	struct notifier_block notifier;
	struct completion notified, release_notify, retired, tail_entered, release_tail;
	struct completion transition_started;
	atomic_t calls, accesses, invalid;
	u64 scan_generation;
	unsigned int cable;
	bool powered, lifecycle, rebind, parallel, hold_tail, polling;
	bool registered, notifier_registered;
};

static struct detector_case *detector_case(struct sun4i_usb_phy_data *data)
{
	return container_of(data, struct detector_case, data);
}

static void sun4i_detector_test_access(struct sun4i_usb_phy_data *data)
{
	struct detector_case *ctx = detector_case(data);
	bool scan = current_work() == &data->detect.work;

	lockdep_assert_held(&ctx->phy.mutex);
	atomic_inc(&ctx->accesses);
	if (!ctx->powered || (scan && !ctx->lifecycle &&
			       ctx->scan_generation != data->phy0_generation))
		atomic_inc(&ctx->invalid);
	if (ctx->hold_tail && scan && !ctx->lifecycle && atomic_read(&ctx->calls)) {
		ctx->hold_tail = false;
		complete(&ctx->tail_entered);
		wait_for_completion(&ctx->release_tail);
	}
}

static void sun4i_detector_test_begin(struct sun4i_usb_phy_data *data, u64 generation)
{
	lockdep_assert_held(&data->phys[0].phy->mutex);
	detector_case(data)->scan_generation = generation;
}

static int sun4i_detector_test_get(struct sun4i_usb_phy_data *data, bool id)
{
	(void)id;
	lockdep_assert_held(&data->phys[0].phy->mutex);
	return 1;
}

static bool sun4i_detector_test_poll(struct sun4i_usb_phy_data *data)
{
	struct detector_case *ctx = detector_case(data);

	lockdep_assert_held(&data->phys[0].phy->mutex);
	if (!ctx->powered || ctx->scan_generation != data->phy0_generation)
		atomic_inc(&ctx->invalid);
	return ctx->polling;
}

static void sun4i_detector_test_delay(struct sun4i_usb_phy_data *data, unsigned int ms)
{
	if (data != sun4i_detector_test_data)
		msleep(ms);
}

static void detector_transition(struct detector_case *ctx)
{
	mutex_lock(&ctx->phy.mutex);
	ctx->lifecycle = true;
	sun4i_usb_phy_exit(&ctx->phy);
	ctx->powered = false;
	if (ctx->rebind) {
		ctx->powered = true;
		sun4i_usb_phy_init(&ctx->phy);
	}
	ctx->lifecycle = false;
	mutex_unlock(&ctx->phy.mutex);
	complete(&ctx->retired);
}

static int detector_notify(struct notifier_block *notifier, unsigned long event, void *arg)
{
	struct detector_case *ctx = container_of(notifier, struct detector_case, notifier);

	(void)event;
	(void)arg;
	if (atomic_inc_return(&ctx->calls) != 1)
		return NOTIFY_OK;
	complete(&ctx->notified);
	if (ctx->parallel)
		wait_for_completion(&ctx->release_notify);
	else if (!ctx->hold_tail)
		detector_transition(ctx);
	return NOTIFY_OK;
}

static int detector_exit_thread(void *arg)
{
	struct detector_case *ctx = arg;

	complete(&ctx->transition_started);
	detector_transition(ctx);
	/* Keep the task alive until its owner joins it after releasing all gates. */
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
	return 0;
}

static void detector_cleanup(void *arg)
{
	struct detector_case *ctx = arg;

	complete_all(&ctx->release_notify);
	complete_all(&ctx->release_tail);
	disable_delayed_work_sync(&ctx->data.detect);
	if (ctx->notifier_registered)
		extcon_unregister_notifier_sync(ctx->data.extcon, ctx->cable, &ctx->notifier);
	if (ctx->registered)
		extcon_dev_unregister(ctx->data.extcon);
	if (!IS_ERR_OR_NULL(ctx->data.extcon))
		devm_extcon_dev_free(ctx->parent, ctx->data.extcon);
	if (!IS_ERR_OR_NULL(ctx->parent))
		root_device_unregister(ctx->parent);
	sun4i_detector_test_data = NULL;
}

static struct detector_case *detector_setup(struct kunit *test, bool legacy, bool vbus)
{
	struct detector_case *ctx = kunit_kzalloc(test, sizeof(*ctx), GFP_KERNEL);
	int ret;

	if (!ctx)
		return NULL;
	mutex_init(&ctx->phy.mutex);
	spin_lock_init(&ctx->data.reg_lock);
	ctx->data.cfg = &ctx->cfg;
	ctx->cfg.phy0_dual_route = true;
	ctx->data.phys[0].phy = &ctx->phy;
	phy_set_drvdata(&ctx->phy, &ctx->data.phys[0]);
	INIT_DELAYED_WORK(&ctx->data.detect, legacy ? sun4i_detector_unguarded_scan :
			  sun4i_usb_phy0_id_vbus_det_scan);
	init_completion(&ctx->notified);
	init_completion(&ctx->release_notify);
	init_completion(&ctx->retired);
	init_completion(&ctx->tail_entered);
	init_completion(&ctx->release_tail);
	init_completion(&ctx->transition_started);
	ctx->cable = vbus ? EXTCON_USB : EXTCON_USB_HOST;
	ret = kunit_add_action_or_reset(test, detector_cleanup, ctx);
	if (ret)
		return NULL;
	ctx->parent = root_device_register("phy-detector-kunit");
	if (IS_ERR(ctx->parent))
		return NULL;
	/* The managed allocator supplies the parent required by extcon registration. */
	ctx->data.extcon = devm_extcon_dev_allocate(ctx->parent, sun4i_usb_phy0_cable);
	if (IS_ERR(ctx->data.extcon))
		return NULL;
	ret = extcon_dev_register(ctx->data.extcon);
	if (ret)
		return NULL;
	ctx->registered = true;
	ctx->notifier.notifier_call = detector_notify;
	ret = extcon_register_notifier(ctx->data.extcon, ctx->cable, &ctx->notifier);
	if (ret)
		return NULL;
	ctx->notifier_registered = true;
	sun4i_detector_test_data = &ctx->data;
	ctx->powered = true;
	ctx->lifecycle = true;
	/* Hardware init is actual source; hold its initial queue until setup ends. */
	disable_delayed_work(&ctx->data.detect);
	mutex_lock(&ctx->phy.mutex);
	ret = sun4i_usb_phy_init(&ctx->phy);
	mutex_unlock(&ctx->phy.mutex);
	enable_delayed_work(&ctx->data.detect);
	ctx->lifecycle = false;
	if (ret)
		return NULL;
	return ctx;
}

static void detector_overlap(struct kunit *test, bool parallel, bool rebind, bool legacy, bool vbus)
{
	struct detector_case *ctx = detector_setup(test, legacy, vbus);
	struct task_struct *thread = NULL;
	unsigned long reached;

	KUNIT_ASSERT_NOT_NULL(test, ctx);
	ctx->parallel = parallel;
	ctx->rebind = rebind;
	ctx->polling = vbus;
	ctx->data.force_session_end = true;
	queue_delayed_work(system_wq, &ctx->data.detect, 0);
	reached = wait_for_completion_timeout(&ctx->notified, msecs_to_jiffies(5000));
	KUNIT_EXPECT_NE(test, reached, 0UL);
	if (parallel && reached) {
		thread = kthread_run(detector_exit_thread, ctx, "detector-exit");
		KUNIT_EXPECT_FALSE(test, IS_ERR(thread));
		if (!IS_ERR(thread)) {
			reached = wait_for_completion_timeout(&ctx->retired, msecs_to_jiffies(5000));
			KUNIT_EXPECT_NE(test, reached, 0UL);
		}
	}
	complete_all(&ctx->release_notify);
	flush_delayed_work(&ctx->data.detect);
	if (!IS_ERR_OR_NULL(thread))
		kthread_stop(thread);
	disable_delayed_work_sync(&ctx->data.detect);
	if (legacy)
		KUNIT_EXPECT_GT(test, atomic_read(&ctx->invalid), 0);
	else
		KUNIT_EXPECT_EQ(test, atomic_read(&ctx->invalid), 0);
	KUNIT_EXPECT_EQ(test, ctx->powered, rebind);
	KUNIT_EXPECT_EQ(test, ctx->data.phy0_generation, rebind ? 2ULL : 1ULL);
}

static void detector_inline_exit_test(struct kunit *test)
{
	detector_overlap(test, false, false, false, false);
}

static void detector_inline_rebind_test(struct kunit *test)
{
	detector_overlap(test, false, true, false, false);
}

static void detector_parallel_exit_test(struct kunit *test)
{
	detector_overlap(test, true, false, false, false);
}

static void detector_parallel_rebind_test(struct kunit *test)
{
	detector_overlap(test, true, true, false, false);
}

static void detector_vbus_exit_test(struct kunit *test)
{
	detector_overlap(test, true, false, false, true);
}

static void detector_vbus_rebind_test(struct kunit *test)
{
	detector_overlap(test, true, true, false, true);
}

static void detector_unguarded_control_test(struct kunit *test)
{
	detector_overlap(test, true, true, true, false);
}

static void detector_tail_mutex_test(struct kunit *test)
{
	struct detector_case *ctx = detector_setup(test, false, false);
	struct task_struct *thread = NULL;
	unsigned long reached;

	KUNIT_ASSERT_NOT_NULL(test, ctx);
	ctx->hold_tail = true;
	queue_delayed_work(system_wq, &ctx->data.detect, 0);
	reached = wait_for_completion_timeout(&ctx->tail_entered, msecs_to_jiffies(5000));
	KUNIT_EXPECT_NE(test, reached, 0UL);
	if (reached) {
		thread = kthread_run(detector_exit_thread, ctx, "detector-tail-exit");
		KUNIT_EXPECT_FALSE(test, IS_ERR(thread));
		if (!IS_ERR(thread)) {
			KUNIT_EXPECT_NE(test, wait_for_completion_timeout(&ctx->transition_started,
					msecs_to_jiffies(5000)), 0UL);
			KUNIT_EXPECT_EQ(test, wait_for_completion_timeout(&ctx->retired,
					msecs_to_jiffies(20)), 0UL);
		}
	}
	complete_all(&ctx->release_tail);
	flush_delayed_work(&ctx->data.detect);
	if (!IS_ERR_OR_NULL(thread))
		kthread_stop(thread);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->invalid), 0);
	KUNIT_EXPECT_FALSE(test, ctx->powered);
}

static void detector_queued_exit_test(struct kunit *test)
{
	struct detector_case *ctx = detector_setup(test, false, false);
	int before;

	KUNIT_ASSERT_NOT_NULL(test, ctx);
	queue_delayed_work(system_wq, &ctx->data.detect, msecs_to_jiffies(10000));
	detector_transition(ctx);
	before = atomic_read(&ctx->accesses);
	flush_delayed_work(&ctx->data.detect);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->accesses), before);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->calls), 0);
	KUNIT_EXPECT_FALSE(test, delayed_work_pending(&ctx->data.detect));
}

static void detector_poll_test(struct kunit *test)
{
	struct detector_case *ctx = detector_setup(test, false, false);

	KUNIT_ASSERT_NOT_NULL(test, ctx);
	/* Leave this notification live; the work tail must retain a bounded poll. */
	atomic_set(&ctx->calls, 1);
	ctx->polling = true;
	queue_delayed_work(system_wq, &ctx->data.detect, 0);
	flush_delayed_work(&ctx->data.detect);
	KUNIT_EXPECT_TRUE(test, delayed_work_pending(&ctx->data.detect));
	disable_delayed_work_sync(&ctx->data.detect);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->invalid), 0);
}

static struct kunit_case detector_cases[] = {
	KUNIT_CASE(detector_inline_exit_test),
	KUNIT_CASE(detector_inline_rebind_test),
	KUNIT_CASE(detector_parallel_exit_test),
	KUNIT_CASE(detector_parallel_rebind_test),
	KUNIT_CASE(detector_vbus_exit_test),
	KUNIT_CASE(detector_vbus_rebind_test),
	KUNIT_CASE(detector_tail_mutex_test),
	KUNIT_CASE(detector_queued_exit_test),
	KUNIT_CASE(detector_poll_test),
	KUNIT_CASE(detector_unguarded_control_test),
	{}
};

static struct kunit_suite detector_suite = {
	.name = "phy-detector",
	.test_cases = detector_cases,
};
kunit_test_suite(detector_suite);
