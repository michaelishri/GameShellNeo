// SPDX-License-Identifier: GPL-2.0-only
/* Included by power_supply_core.c only in the isolated instrumented kernel. */
#define PSY_TEST_TIMEOUT msecs_to_jiffies(5000)

static enum power_supply_property psy_lifetime_properties[] = {
	POWER_SUPPLY_PROP_ONLINE,
};

static int psy_lifetime_get_property(struct power_supply *psy,
				     enum power_supply_property property,
				     union power_supply_propval *value)
{
	value->intval = 1;
	return 0;
}

static const struct power_supply_desc psy_lifetime_desc = {
	.name = "lifetime-kunit",
	.type = POWER_SUPPLY_TYPE_MAINS,
	.properties = psy_lifetime_properties,
	.num_properties = ARRAY_SIZE(psy_lifetime_properties),
	.get_property = psy_lifetime_get_property,
};

static int psy_lifetime_remove(void *data)
{
	struct psy_lifetime_context *ctx = data;

	power_supply_unregister(ctx->psy);
	ctx->removed = true;
	complete_all(&ctx->removal_done);
	wait_event_interruptible(ctx->stop_wait, kthread_should_stop());
	return 0;
}

static int psy_lifetime_init(struct kunit *test)
{
	struct psy_lifetime_context *ctx;
	int i;

	ctx = kunit_kzalloc(test, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ctx->parent = root_device_register("psy-lifetime-kunit");
	if (IS_ERR(ctx->parent))
		return PTR_ERR(ctx->parent);
	for (i = 0; i < PSY_TEST_POINTS; i++)
		init_completion(&ctx->point[i]);
	init_completion(&ctx->release_deferred);
	init_completion(&ctx->release_changed);
	init_completion(&ctx->removal_done);
	init_waitqueue_head(&ctx->stop_wait);
	test->priv = ctx;
	return 0;
}

static void psy_lifetime_exit(struct kunit *test)
{
	struct psy_lifetime_context *ctx = test->priv;

	/* Release all gates even if a KUnit assertion aborted the test body. */
	complete_all(&ctx->release_deferred);
	complete_all(&ctx->release_changed);
	complete_all(&ctx->point[PSY_CHANGED_ENTER]);
	if (ctx->parent_locked)
		device_unlock(ctx->parent);
	if (!IS_ERR_OR_NULL(ctx->remover))
		kthread_stop(ctx->remover);
	if (!IS_ERR_OR_NULL(ctx->psy)) {
		if (!ctx->removed)
			power_supply_unregister(ctx->psy);
		/* The original-order control may leave real work beyond unregister. */
		cancel_delayed_work_sync(&ctx->psy->deferred_register_work);
		cancel_work_sync(&ctx->psy->changed_work);
		put_device(&ctx->psy->dev);
	}
	root_device_unregister(ctx->parent);
}

static void psy_lifetime_register(struct kunit *test)
{
	struct psy_lifetime_context *ctx = test->priv;
	struct power_supply_config config = { .drv_data = ctx };

	ctx->psy = power_supply_register(ctx->parent, &psy_lifetime_desc, &config);
	KUNIT_ASSERT_NOT_ERR_OR_NULL(test, ctx->psy);
	/* Keep storage alive for the negative control, without changing use_cnt. */
	get_device(&ctx->psy->dev);
}

static void psy_lifetime_start_remove(struct kunit *test)
{
	struct psy_lifetime_context *ctx = test->priv;

	ctx->remover = kthread_run(psy_lifetime_remove, ctx, "psy-remove-kunit");
	KUNIT_ASSERT_NOT_ERR_OR_NULL(test, ctx->remover);
}

static void psy_lifetime_expect_quiet(struct kunit *test)
{
	struct psy_lifetime_context *ctx = test->priv;

	KUNIT_EXPECT_EQ(test, work_busy(&ctx->psy->deferred_register_work.work), 0U);
	KUNIT_EXPECT_EQ(test, work_busy(&ctx->psy->changed_work), 0U);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->psy->use_cnt), 0);
}

static void psy_lifetime_overlap_test(struct kunit *test)
{
	struct psy_lifetime_context *ctx = test->priv;
	bool original = IS_ENABLED(CONFIG_POWER_SUPPLY_LIFETIME_ORIGINAL_ORDER);

	ctx->hold_deferred = true;
	ctx->hold_changed = true;
	psy_lifetime_register(test);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
		&ctx->point[PSY_DEFER_NOTIFY], PSY_TEST_TIMEOUT), 0UL);
	psy_lifetime_start_remove(test);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
		&ctx->point[PSY_CANCEL_DEFER_BEGIN], PSY_TEST_TIMEOUT), 0UL);
	KUNIT_EXPECT_EQ(test, completion_done(&ctx->point[PSY_CANCEL_CHANGED_DONE]),
			original);
	complete_all(&ctx->release_deferred);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
		&ctx->point[PSY_CHANGED_ENTER], PSY_TEST_TIMEOUT), 0UL);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
		&ctx->point[PSY_CANCEL_CHANGED_BEGIN], PSY_TEST_TIMEOUT), 0UL);
	if (original) {
		KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
			&ctx->removal_done, PSY_TEST_TIMEOUT), 0UL);
		KUNIT_EXPECT_NE(test, work_busy(&ctx->psy->changed_work), 0U);
	} else {
		KUNIT_EXPECT_EQ(test, wait_for_completion_timeout(
			&ctx->removal_done, msecs_to_jiffies(100)), 0UL);
	}
	complete_all(&ctx->release_changed);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
		&ctx->removal_done, PSY_TEST_TIMEOUT), 0UL);
	flush_work(&ctx->psy->changed_work);
	psy_lifetime_expect_quiet(test);
}

static void psy_lifetime_parent_locked_test(struct kunit *test)
{
	struct psy_lifetime_context *ctx = test->priv;

	device_lock(ctx->parent);
	ctx->parent_locked = true;
	psy_lifetime_register(test);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
		&ctx->point[PSY_PARENT_BLOCKED], PSY_TEST_TIMEOUT), 0UL);
	psy_lifetime_start_remove(test);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
		&ctx->removal_done, PSY_TEST_TIMEOUT), 0UL);
	KUNIT_EXPECT_FALSE(test, completion_done(&ctx->point[PSY_DEFER_NOTIFY]));
	device_unlock(ctx->parent);
	ctx->parent_locked = false;
	psy_lifetime_expect_quiet(test);
}

static void psy_lifetime_completed_test(struct kunit *test)
{
	struct psy_lifetime_context *ctx = test->priv;

	psy_lifetime_register(test);
	flush_delayed_work(&ctx->psy->deferred_register_work);
	flush_work(&ctx->psy->changed_work);
	psy_lifetime_start_remove(test);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
		&ctx->removal_done, PSY_TEST_TIMEOUT), 0UL);
	KUNIT_EXPECT_TRUE(test, completion_done(&ctx->point[PSY_CHANGED_ENTER]));
	psy_lifetime_expect_quiet(test);
}

static void psy_lifetime_active_notification_test(struct kunit *test)
{
	struct psy_lifetime_context *ctx = test->priv;

	ctx->hold_changed = true;
	psy_lifetime_register(test);
	flush_delayed_work(&ctx->psy->deferred_register_work);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
		&ctx->point[PSY_CHANGED_ENTER], PSY_TEST_TIMEOUT), 0UL);
	psy_lifetime_start_remove(test);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
		&ctx->point[PSY_CANCEL_CHANGED_BEGIN], PSY_TEST_TIMEOUT), 0UL);
	KUNIT_EXPECT_EQ(test, wait_for_completion_timeout(
		&ctx->removal_done, msecs_to_jiffies(100)), 0UL);
	complete_all(&ctx->release_changed);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(
		&ctx->removal_done, PSY_TEST_TIMEOUT), 0UL);
	psy_lifetime_expect_quiet(test);
}

static struct kunit_case psy_lifetime_cases[] = {
	KUNIT_CASE(psy_lifetime_overlap_test),
	KUNIT_CASE(psy_lifetime_parent_locked_test),
	KUNIT_CASE(psy_lifetime_completed_test),
	KUNIT_CASE(psy_lifetime_active_notification_test),
	{}
};

static struct kunit_suite psy_lifetime_suite = {
	.name = "power-supply-lifetime",
	.init = psy_lifetime_init,
	.exit = psy_lifetime_exit,
	.test_cases = psy_lifetime_cases,
};
kunit_test_suite(psy_lifetime_suite);
