// SPDX-License-Identifier: GPL-2.0-only
/* Included only in the complete, test-instrumented MPFS source. */
#include <kunit/test.h>
#include <linux/clk-provider.h>
#include <linux/completion.h>
#include <linux/kthread.h>

struct mpfs_owner_case {
	struct mpfs_glue glue;
	struct clk_hw clock_hw;
	struct clk *clock;
	struct platform_device *parent, *child, *phy;
	struct task_struct *thread;
	struct completion child_entered, release_child, removed;
	atomic_t clock_on, child_calls, invalid, wrong_owner;
	bool hold_child, original, parent_driver_registered, child_driver_registered;
	bool child_reference, phy_reference;
};

static struct mpfs_owner_case *mpfs_owner_case;

static int mpfs_owner_clock_enable(struct clk_hw *hw)
{
	struct mpfs_owner_case *ctx = container_of(hw, struct mpfs_owner_case, clock_hw);

	atomic_set(&ctx->clock_on, 1);
	return 0;
}

static void mpfs_owner_clock_disable(struct clk_hw *hw)
{
	struct mpfs_owner_case *ctx = container_of(hw, struct mpfs_owner_case, clock_hw);

	atomic_set(&ctx->clock_on, 0);
}

static int mpfs_owner_clock_enabled(struct clk_hw *hw)
{
	return atomic_read(&container_of(hw, struct mpfs_owner_case, clock_hw)->clock_on);
}

static const struct clk_ops mpfs_owner_clock_ops = {
	.enable = mpfs_owner_clock_enable,
	.disable = mpfs_owner_clock_disable,
	.is_enabled = mpfs_owner_clock_enabled,
};

static int mpfs_owner_probe(struct platform_device *pdev)
{
	return 0;
}

static void mpfs_owner_child_remove(struct platform_device *pdev)
{
	struct mpfs_glue *glue = dev_get_drvdata(pdev->dev.parent);
	struct mpfs_owner_case *ctx = container_of(glue, struct mpfs_owner_case, glue);

	atomic_inc(&ctx->child_calls);
	if (!atomic_read(&ctx->clock_on))
		atomic_inc(&ctx->invalid);
	complete(&ctx->child_entered);
	if (ctx->hold_child)
		wait_for_completion(&ctx->release_child);
	if (!atomic_read(&ctx->clock_on))
		atomic_inc(&ctx->invalid);
}

static void mpfs_test_phy_unregister(struct platform_device *pdev)
{
	/* Safely observe the original wrong argument without recursively unbinding. */
	if (mpfs_owner_case && pdev == mpfs_owner_case->parent) {
		atomic_inc(&mpfs_owner_case->wrong_owner);
		return;
	}
	usb_phy_generic_unregister(pdev);
}

static void mpfs_owner_parent_remove(struct platform_device *pdev)
{
	struct mpfs_glue *glue = platform_get_drvdata(pdev);
	struct mpfs_owner_case *ctx = container_of(glue, struct mpfs_owner_case, glue);

	if (ctx->original)
		mpfs_original_remove(pdev);
	else
		mpfs_remove(pdev);
}

static struct platform_driver mpfs_owner_child_driver = {
	.probe = mpfs_owner_probe,
	.remove = mpfs_owner_child_remove,
	.driver.name = "mpfs-owner-child",
};

static struct platform_driver mpfs_owner_parent_driver = {
	.probe = mpfs_owner_probe,
	.remove = mpfs_owner_parent_remove,
	.driver.name = "mpfs-owner-parent",
};

static int mpfs_owner_remove_thread(void *arg)
{
	struct mpfs_owner_case *ctx = arg;

	device_release_driver(&ctx->parent->dev);
	complete(&ctx->removed);
	/* Keep the task alive until its owner joins it after releasing the child. */
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
	return 0;
}

static void mpfs_owner_cleanup(void *arg)
{
	struct mpfs_owner_case *ctx = arg;

	complete_all(&ctx->release_child);
	if (!IS_ERR_OR_NULL(ctx->thread))
		kthread_stop(ctx->thread);
	if (ctx->parent)
		device_release_driver(&ctx->parent->dev);
	if (ctx->child && device_is_registered(&ctx->child->dev))
		platform_device_unregister(ctx->child);
	if (!IS_ERR_OR_NULL(ctx->phy) && device_is_registered(&ctx->phy->dev))
		usb_phy_generic_unregister(ctx->phy);
	if (ctx->child_reference)
		put_device(&ctx->child->dev);
	if (ctx->phy_reference)
		put_device(&ctx->phy->dev);
	if (ctx->parent)
		platform_device_unregister(ctx->parent);
	if (ctx->parent_driver_registered)
		platform_driver_unregister(&mpfs_owner_parent_driver);
	if (ctx->child_driver_registered)
		platform_driver_unregister(&mpfs_owner_child_driver);
	if (!IS_ERR_OR_NULL(ctx->clock)) {
		if (atomic_read(&ctx->clock_on))
			clk_disable_unprepare(ctx->clock);
		clk_unregister(ctx->clock);
	}
	mpfs_owner_case = NULL;
}

static struct mpfs_owner_case *mpfs_owner_setup(struct kunit *test)
{
	struct mpfs_owner_case *ctx = kunit_kzalloc(test, sizeof(*ctx), GFP_KERNEL);
	const struct clk_init_data clock_init = {
		.name = "mpfs-owner-clock",
		.ops = &mpfs_owner_clock_ops,
	};
	int ret;

	if (!ctx)
		return NULL;
	init_completion(&ctx->child_entered);
	init_completion(&ctx->release_child);
	init_completion(&ctx->removed);
	ret = kunit_add_action_or_reset(test, mpfs_owner_cleanup, ctx);
	if (ret)
		return NULL;
	mpfs_owner_case = ctx;
	ret = platform_driver_register(&mpfs_owner_child_driver);
	if (ret)
		return NULL;
	ctx->child_driver_registered = true;
	ctx->clock_hw.init = &clock_init;
	ctx->clock = clk_register(NULL, &ctx->clock_hw);
	if (IS_ERR(ctx->clock))
		return NULL;
	ret = clk_prepare_enable(ctx->clock);
	if (ret)
		return NULL;
	ctx->glue.clk = ctx->clock;
	ctx->parent = platform_device_alloc("mpfs-owner-parent", PLATFORM_DEVID_AUTO);
	if (!ctx->parent)
		return NULL;
	platform_set_drvdata(ctx->parent, &ctx->glue);
	ctx->glue.dev = &ctx->parent->dev;
	ret = platform_device_add(ctx->parent);
	if (ret) {
		platform_device_put(ctx->parent);
		ctx->parent = NULL;
		return NULL;
	}
	ctx->child = platform_device_alloc("mpfs-owner-child", PLATFORM_DEVID_AUTO);
	if (!ctx->child)
		return NULL;
	ctx->child->dev.parent = &ctx->parent->dev;
	ret = platform_device_add(ctx->child);
	if (ret) {
		platform_device_put(ctx->child);
		ctx->child = NULL;
		return NULL;
	}
	ctx->glue.musb = ctx->child;
	ctx->phy = usb_phy_generic_register();
	if (IS_ERR(ctx->phy))
		return NULL;
	ctx->glue.phy = ctx->phy;
	/* Keep objects inspectable after their real unregister drops its reference. */
	get_device(&ctx->child->dev);
	ctx->child_reference = true;
	get_device(&ctx->phy->dev);
	ctx->phy_reference = true;
	/* Bind the parent only once every resource its actual remove owns is valid. */
	ret = platform_driver_register(&mpfs_owner_parent_driver);
	if (ret)
		return NULL;
	ctx->parent_driver_registered = true;
	if (ctx->parent->dev.driver != &mpfs_owner_parent_driver.driver ||
	    ctx->child->dev.driver != &mpfs_owner_child_driver.driver)
		return NULL;
	return ctx;
}

static void mpfs_owner_run(struct kunit *test, bool held, bool original)
{
	struct mpfs_owner_case *ctx = mpfs_owner_setup(test);
	unsigned long reached;

	KUNIT_ASSERT_NOT_NULL(test, ctx);
	ctx->hold_child = held;
	ctx->original = original;
	ctx->thread = kthread_run(mpfs_owner_remove_thread, ctx, "mpfs-owner-remove");
	KUNIT_ASSERT_FALSE(test, IS_ERR(ctx->thread));
	if (held) {
		reached = wait_for_completion_timeout(&ctx->child_entered, msecs_to_jiffies(5000));
		KUNIT_EXPECT_NE(test, reached, 0UL);
		KUNIT_EXPECT_EQ(test, atomic_read(&ctx->clock_on), 1);
		KUNIT_EXPECT_FALSE(test, completion_done(&ctx->removed));
	}
	complete_all(&ctx->release_child);
	reached = wait_for_completion_timeout(&ctx->removed, msecs_to_jiffies(5000));
	KUNIT_EXPECT_NE(test, reached, 0UL);
	KUNIT_EXPECT_EQ(test, kthread_stop(ctx->thread), 0);
	ctx->thread = NULL;
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->child_calls), 1);
	KUNIT_EXPECT_TRUE(test, device_is_registered(&ctx->parent->dev));
	KUNIT_EXPECT_FALSE(test, device_is_registered(&ctx->child->dev));
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->clock_on), 0);
	if (original) {
		KUNIT_EXPECT_GT(test, atomic_read(&ctx->invalid), 0);
		KUNIT_EXPECT_EQ(test, atomic_read(&ctx->wrong_owner), 1);
		KUNIT_EXPECT_TRUE(test, device_is_registered(&ctx->phy->dev));
	} else {
		KUNIT_EXPECT_EQ(test, atomic_read(&ctx->invalid), 0);
		KUNIT_EXPECT_EQ(test, atomic_read(&ctx->wrong_owner), 0);
		KUNIT_EXPECT_FALSE(test, device_is_registered(&ctx->phy->dev));
	}
}

static void mpfs_owned_phy_test(struct kunit *test)
{
	mpfs_owner_run(test, false, false);
}

static void mpfs_held_child_test(struct kunit *test)
{
	mpfs_owner_run(test, true, false);
}

static void mpfs_original_control_test(struct kunit *test)
{
	mpfs_owner_run(test, false, true);
}

static struct kunit_case mpfs_owner_cases[] = {
	KUNIT_CASE(mpfs_owned_phy_test),
	KUNIT_CASE(mpfs_held_child_test),
	KUNIT_CASE(mpfs_original_control_test),
	{}
};

static struct kunit_suite mpfs_owner_suite = {
	.name = "mpfs-ownership",
	.test_cases = mpfs_owner_cases,
};
kunit_test_suite(mpfs_owner_suite);
