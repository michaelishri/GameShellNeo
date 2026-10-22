// SPDX-License-Identifier: GPL-2.0-only
/* Provider admission and unbind against the real driver core and extcon. */
#include <kunit/test.h>
#include <linux/completion.h>
#include <linux/delay.h>
#include <linux/kthread.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/property.h>

#include "extcon.h"

#define PROVIDER_NAME "extcon-lifetime-supplier"
#define CONSUMER_NAME "extcon-lifetime-consumer"
#define TEST_WAIT msecs_to_jiffies(5000)

enum provider_test_op {
	ADD_PROVIDER,
	ADD_CONSUMER,
	UNBIND_PROVIDER,
	DISPATCH_EVENT,
};

struct provider_test_context;
struct provider_test_thread {
	struct provider_test_context *ctx;
	enum provider_test_op op;
	struct task_struct *task;
	struct completion started;
	struct completion done;
	int result;
};

struct provider_test_context {
	struct kunit *test;
	struct software_node node;
	struct platform_device *provider;
	struct platform_device *consumer;
	struct extcon_dev *edev;
	struct notifier_block nb;
	struct completion provider_probe;
	struct completion release_provider_probe;
	struct completion consumer_probe;
	struct completion release_consumer_probe;
	struct completion provider_remove;
	struct completion release_provider_remove;
	struct completion consumer_remove;
	struct completion callback;
	struct completion release_callback;
	struct provider_test_thread threads[3];
	wait_queue_head_t stop_wait;
	atomic_t sequence;
	atomic_t callbacks;
	int consumer_order;
	int provider_order;
	int lookup_error;
	int provider_lookup_error;
	bool provider_added;
	bool consumer_added;
	bool notifier_registered;
	bool hold_provider_probe;
	bool hold_consumer_probe;
	bool hold_provider_remove;
	bool hold_callback;
	bool fail_provider_probe;
	bool fail_consumer_probe;
	bool lookup_in_provider;
	bool dispatch_started;
};

static const unsigned int provider_test_cables[] = {
	EXTCON_USB_HOST, EXTCON_NONE,
};

static int provider_test_notify(struct notifier_block *nb, unsigned long event,
				void *data)
{
	struct provider_test_context *ctx = container_of(nb, typeof(*ctx), nb);

	atomic_inc(&ctx->callbacks);
	complete(&ctx->callback);
	if (ctx->hold_callback)
		wait_for_completion(&ctx->release_callback);
	return NOTIFY_DONE;
}

static void provider_test_drop_notifier(struct provider_test_context *ctx)
{
	int ret;

	if (ctx->notifier_registered) {
		ret = extcon_unregister_notifier_sync(ctx->edev, EXTCON_USB_HOST, &ctx->nb);
		KUNIT_EXPECT_EQ(ctx->test, ret, 0);
		ctx->notifier_registered = false;
	}
}

static void provider_test_free(struct provider_test_context *ctx)
{
	extcon_dev_unregister(ctx->edev);
	extcon_dev_free(ctx->edev);
	ctx->edev = NULL;
}

static int provider_test_probe(struct platform_device *pdev)
{
	struct provider_test_context *ctx = dev_get_platdata(&pdev->dev);
	struct extcon_dev *result;
	int ret;

	ctx->edev = extcon_dev_allocate(provider_test_cables);
	if (IS_ERR(ctx->edev)) {
		ret = PTR_ERR(ctx->edev);
		ctx->edev = NULL;
		return ret;
	}
	ctx->edev->dev.parent = &pdev->dev;
	ret = extcon_dev_register(ctx->edev);
	if (ret) {
		extcon_dev_free(ctx->edev);
		ctx->edev = NULL;
		return ret;
	}
	if (ctx->lookup_in_provider) {
		result = extcon_get_edev_by_fwnode(&pdev->dev,
						   software_node_fwnode(&ctx->node));
		ctx->provider_lookup_error = IS_ERR(result) ? PTR_ERR(result) : 0;
	}
	complete(&ctx->provider_probe);
	if (ctx->hold_provider_probe)
		wait_for_completion(&ctx->release_provider_probe);
	if (ctx->fail_provider_probe) {
		provider_test_free(ctx);
		return -EINVAL;
	}
	return 0;
}

static void provider_test_remove(struct platform_device *pdev)
{
	struct provider_test_context *ctx = dev_get_platdata(&pdev->dev);

	complete(&ctx->provider_remove);
	if (ctx->hold_provider_remove)
		wait_for_completion(&ctx->release_provider_remove);
	/* The provider must retire its whole event producer, including uevents. */
	if (ctx->dispatch_started)
		wait_for_completion(&ctx->threads[0].done);
	KUNIT_EXPECT_FALSE(ctx->test, ctx->notifier_registered);
	ctx->provider_order = atomic_inc_return(&ctx->sequence);
	provider_test_free(ctx);
}

static int consumer_test_probe(struct platform_device *pdev)
{
	struct provider_test_context *ctx = dev_get_platdata(&pdev->dev);
	struct extcon_dev *result;
	int ret;

	result = extcon_get_edev_by_fwnode(&pdev->dev, software_node_fwnode(&ctx->node));
	ctx->lookup_error = IS_ERR(result) ? PTR_ERR(result) : 0;
	/* Keep expected deferrals under test control, without automatic retries. */
	if (IS_ERR(result))
		return -EINVAL;
	KUNIT_EXPECT_PTR_EQ(ctx->test, result, ctx->edev);
	ret = extcon_register_notifier(result, EXTCON_USB_HOST, &ctx->nb);
	if (ret)
		return ret;
	ctx->notifier_registered = true;
	complete(&ctx->consumer_probe);
	if (ctx->hold_consumer_probe)
		wait_for_completion(&ctx->release_consumer_probe);
	if (ctx->fail_consumer_probe) {
		/* Failed-probe links disappear before generic devres cleanup. */
		provider_test_drop_notifier(ctx);
		ctx->consumer_order = atomic_inc_return(&ctx->sequence);
		return -EINVAL;
	}
	return 0;
}

static void consumer_test_remove(struct platform_device *pdev)
{
	struct provider_test_context *ctx = dev_get_platdata(&pdev->dev);

	complete(&ctx->consumer_remove);
	provider_test_drop_notifier(ctx);
	ctx->consumer_order = atomic_inc_return(&ctx->sequence);
}

static struct platform_driver provider_test_driver = {
	.probe = provider_test_probe,
	.remove = provider_test_remove,
	.driver = { .name = PROVIDER_NAME, .probe_type = PROBE_FORCE_SYNCHRONOUS },
};

static struct platform_driver consumer_test_driver = {
	.probe = consumer_test_probe,
	.remove = consumer_test_remove,
	.driver = { .name = CONSUMER_NAME, .probe_type = PROBE_FORCE_SYNCHRONOUS },
};

static int provider_test_run(void *data)
{
	struct provider_test_thread *thread = data;
	struct provider_test_context *ctx = thread->ctx;

	complete(&thread->started);
	switch (thread->op) {
	case ADD_PROVIDER:
		thread->result = platform_device_add(ctx->provider);
		ctx->provider_added = !thread->result;
		break;
	case ADD_CONSUMER:
		thread->result = platform_device_add(ctx->consumer);
		ctx->consumer_added = !thread->result;
		break;
	case UNBIND_PROVIDER:
		device_release_driver(&ctx->provider->dev);
		break;
	case DISPATCH_EVENT:
		thread->result = extcon_sync(ctx->edev, EXTCON_USB_HOST);
		break;
	}
	complete_all(&thread->done);
	wait_event_interruptible(ctx->stop_wait, kthread_should_stop());
	return 0;
}

static void provider_test_start(struct kunit *test, unsigned int slot,
				enum provider_test_op op)
{
	struct provider_test_context *ctx = test->priv;
	struct provider_test_thread *thread = &ctx->threads[slot];

	thread->op = op;
	thread->task = kthread_run(provider_test_run, thread, "extcon-link-test");
	KUNIT_ASSERT_FALSE(test, IS_ERR(thread->task));
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&thread->started, TEST_WAIT), 0UL);
}

static void provider_test_join(struct kunit *test, unsigned int slot)
{
	struct provider_test_context *ctx = test->priv;

	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&ctx->threads[slot].done,
							  TEST_WAIT), 0UL);
	KUNIT_EXPECT_EQ(test, ctx->threads[slot].result, 0);
}

static int provider_test_init(struct kunit *test)
{
	struct provider_test_context *ctx;
	int ret, i;

	ctx = kunit_kzalloc(test, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	test->priv = ctx;
	ctx->test = test;
	ctx->node.name = "extcon-lifetime-node";
	ctx->nb.notifier_call = provider_test_notify;
	init_completion(&ctx->provider_probe);
	init_completion(&ctx->release_provider_probe);
	init_completion(&ctx->consumer_probe);
	init_completion(&ctx->release_consumer_probe);
	init_completion(&ctx->provider_remove);
	init_completion(&ctx->release_provider_remove);
	init_completion(&ctx->consumer_remove);
	init_completion(&ctx->callback);
	init_completion(&ctx->release_callback);
	init_waitqueue_head(&ctx->stop_wait);
	for (i = 0; i < ARRAY_SIZE(ctx->threads); i++) {
		ctx->threads[i].ctx = ctx;
		init_completion(&ctx->threads[i].started);
		init_completion(&ctx->threads[i].done);
	}
	ret = software_node_register(&ctx->node);
	if (ret)
		return ret;
	ctx->provider = platform_device_alloc(PROVIDER_NAME, PLATFORM_DEVID_AUTO);
	ctx->consumer = platform_device_alloc(CONSUMER_NAME, PLATFORM_DEVID_AUTO);
	if (!ctx->provider || !ctx->consumer) {
		ret = -ENOMEM;
		goto free_devices;
	}
	/* Set platform_data without add_data's copy; clear before device release. */
	ctx->provider->dev.platform_data = ctx;
	ctx->consumer->dev.platform_data = ctx;
	device_set_node(&ctx->provider->dev, software_node_fwnode(&ctx->node));
	ret = platform_driver_register(&provider_test_driver);
	if (ret)
		goto free_devices;
	ret = platform_driver_register(&consumer_test_driver);
	if (!ret)
		return 0;
	platform_driver_unregister(&provider_test_driver);
free_devices:
	if (ctx->consumer) {
		ctx->consumer->dev.platform_data = NULL;
		platform_device_put(ctx->consumer);
	}
	if (ctx->provider) {
		ctx->provider->dev.platform_data = NULL;
		platform_device_put(ctx->provider);
	}
	software_node_unregister(&ctx->node);
	return ret;
}

static void provider_test_exit(struct kunit *test)
{
	struct provider_test_context *ctx = test->priv;
	int i;

	complete_all(&ctx->release_callback);
	complete_all(&ctx->release_consumer_probe);
	complete_all(&ctx->release_provider_probe);
	complete_all(&ctx->release_provider_remove);
	for (i = 0; i < ARRAY_SIZE(ctx->threads); i++)
		if (!IS_ERR_OR_NULL(ctx->threads[i].task))
			kthread_stop(ctx->threads[i].task);
	if (ctx->consumer_added)
		platform_device_del(ctx->consumer);
	if (ctx->provider_added)
		platform_device_del(ctx->provider);
	ctx->consumer->dev.platform_data = NULL;
	ctx->provider->dev.platform_data = NULL;
	platform_device_put(ctx->consumer);
	platform_device_put(ctx->provider);
	platform_driver_unregister(&consumer_test_driver);
	platform_driver_unregister(&provider_test_driver);
	device_link_wait_removal();
	software_node_unregister(&ctx->node);
}

static void provider_test_add(struct kunit *test, bool consumer)
{
	struct provider_test_context *ctx = test->priv;
	int ret = platform_device_add(consumer ? ctx->consumer : ctx->provider);

	if (consumer)
		ctx->consumer_added = !ret;
	else
		ctx->provider_added = !ret;
	KUNIT_ASSERT_EQ(test, ret, 0);
}

static void extcon_provider_bound_test(struct kunit *test)
{
	struct provider_test_context *ctx = test->priv;
	int i;

	provider_test_add(test, false);
	provider_test_add(test, true);
	KUNIT_ASSERT_EQ(test, ctx->lookup_error, 0);
	for (i = 0; i < 3; i++) {
		KUNIT_ASSERT_TRUE(test, ctx->notifier_registered);
		KUNIT_EXPECT_EQ(test, extcon_sync(ctx->edev, EXTCON_USB_HOST), 0);
		device_release_driver(&ctx->consumer->dev);
		KUNIT_EXPECT_FALSE(test, ctx->notifier_registered);
		KUNIT_EXPECT_TRUE(test, list_empty(&ctx->consumer->dev.links.suppliers));
		KUNIT_EXPECT_EQ(test, device_attach(&ctx->consumer->dev), 1);
	}
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->callbacks), 3);
	device_release_driver(&ctx->provider->dev);
	KUNIT_EXPECT_LT(test, ctx->consumer_order, ctx->provider_order);
	KUNIT_EXPECT_PTR_EQ(test, ctx->edev, NULL);
}

static void extcon_provider_missing_test(struct kunit *test)
{
	struct provider_test_context *ctx = test->priv;

	provider_test_add(test, true);
	KUNIT_EXPECT_EQ(test, ctx->lookup_error, -EPROBE_DEFER);
	KUNIT_EXPECT_FALSE(test, ctx->notifier_registered);
	KUNIT_EXPECT_TRUE(test, list_empty(&ctx->consumer->dev.links.suppliers));
}

static void extcon_provider_existing_link_test(struct kunit *test)
{
	struct provider_test_context *ctx = test->priv;
	struct device_link *link;

	provider_test_add(test, false);
	link = device_link_add(&ctx->consumer->dev, &ctx->provider->dev, DL_FLAG_STATELESS);
	KUNIT_ASSERT_NOT_NULL(test, link);
	provider_test_add(test, true);
	KUNIT_ASSERT_EQ(test, ctx->lookup_error, 0);
	/* Release only our stateless reference; the lookup's managed owner stays. */
	device_link_del(link);
	KUNIT_EXPECT_FALSE(test, list_empty(&ctx->consumer->dev.links.suppliers));
	device_release_driver(&ctx->consumer->dev);
	/* Upgrading an existing stateless link retains managed ownership. */
	KUNIT_EXPECT_FALSE(test, list_empty(&ctx->consumer->dev.links.suppliers));
	KUNIT_EXPECT_EQ(test, READ_ONCE(link->status), DL_STATE_AVAILABLE);

	/* Existing persistent managed links keep their longer lifetime policy. */
	link = device_link_add(&ctx->consumer->dev, &ctx->provider->dev, 0);
	KUNIT_ASSERT_NOT_NULL(test, link);
	KUNIT_EXPECT_EQ(test, device_attach(&ctx->consumer->dev), 1);
	KUNIT_EXPECT_EQ(test, ctx->lookup_error, 0);
	device_release_driver(&ctx->consumer->dev);
	KUNIT_EXPECT_FALSE(test, list_empty(&ctx->consumer->dev.links.suppliers));
	KUNIT_EXPECT_FALSE(test, ctx->notifier_registered);
	KUNIT_EXPECT_EQ(test, device_attach(&ctx->consumer->dev), 1);
	device_release_driver(&ctx->provider->dev);
	KUNIT_EXPECT_LT(test, ctx->consumer_order, ctx->provider_order);
}

static void extcon_provider_invalid_test(struct kunit *test)
{
	struct provider_test_context *ctx = test->priv;
	struct fwnode_handle *node = software_node_fwnode(&ctx->node);

	KUNIT_EXPECT_EQ(test, PTR_ERR(extcon_get_edev_by_fwnode(NULL, node)), -EINVAL);
	KUNIT_EXPECT_EQ(test, PTR_ERR(extcon_get_edev_by_fwnode(&ctx->consumer->dev,
								node)), -EINVAL);
	ctx->lookup_in_provider = true;
	provider_test_add(test, false);
	KUNIT_EXPECT_EQ(test, ctx->provider_lookup_error, -EINVAL);
}

static void extcon_provider_probe_failure_test(struct kunit *test)
{
	struct provider_test_context *ctx = test->priv;

	provider_test_add(test, false);
	ctx->fail_consumer_probe = true;
	provider_test_add(test, true);
	KUNIT_EXPECT_EQ(test, ctx->lookup_error, 0);
	KUNIT_EXPECT_FALSE(test, ctx->notifier_registered);
	KUNIT_EXPECT_TRUE(test, list_empty(&ctx->consumer->dev.links.suppliers));
	device_release_driver(&ctx->provider->dev);
	KUNIT_EXPECT_LT(test, ctx->consumer_order, ctx->provider_order);
}

static void extcon_provider_probing(struct kunit *test, bool fail)
{
	struct provider_test_context *ctx = test->priv;

	ctx->hold_provider_probe = true;
	ctx->fail_provider_probe = fail;
	provider_test_start(test, 0, ADD_PROVIDER);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&ctx->provider_probe, TEST_WAIT), 0UL);
	provider_test_add(test, true);
	KUNIT_EXPECT_EQ(test, ctx->lookup_error, -EPROBE_DEFER);
	KUNIT_EXPECT_FALSE(test, ctx->notifier_registered);
	complete(&ctx->release_provider_probe);
	provider_test_join(test, 0);
	if (fail) {
		KUNIT_EXPECT_PTR_EQ(test, ctx->edev, NULL);
	} else {
		KUNIT_EXPECT_EQ(test, device_attach(&ctx->consumer->dev), 1);
		KUNIT_EXPECT_EQ(test, ctx->lookup_error, 0);
	}
}

static void extcon_provider_still_probing_test(struct kunit *test)
{
	extcon_provider_probing(test, false);
}

static void extcon_provider_failed_supplier_test(struct kunit *test)
{
	extcon_provider_probing(test, true);
}

static void extcon_provider_unbinding_test(struct kunit *test)
{
	struct provider_test_context *ctx = test->priv;

	provider_test_add(test, false);
	ctx->hold_provider_remove = true;
	provider_test_start(test, 0, UNBIND_PROVIDER);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&ctx->provider_remove, TEST_WAIT), 0UL);
	provider_test_add(test, true);
	KUNIT_EXPECT_EQ(test, ctx->lookup_error, -EPROBE_DEFER);
	KUNIT_EXPECT_FALSE(test, ctx->notifier_registered);
	complete(&ctx->release_provider_remove);
	provider_test_join(test, 0);
}

static void extcon_provider_waits_probe_test(struct kunit *test)
{
	struct provider_test_context *ctx = test->priv;

	provider_test_add(test, false);
	ctx->hold_consumer_probe = true;
	provider_test_start(test, 0, ADD_CONSUMER);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&ctx->consumer_probe, TEST_WAIT), 0UL);
	provider_test_start(test, 1, UNBIND_PROVIDER);
	for (int i = 0; i < 5000; i++) {
		if (READ_ONCE(ctx->provider->dev.links.status) == DL_DEV_UNBINDING)
			break;
		usleep_range(1000, 2000);
	}
	KUNIT_ASSERT_EQ(test, READ_ONCE(ctx->provider->dev.links.status), DL_DEV_UNBINDING);
	msleep(100);
	KUNIT_EXPECT_FALSE(test, completion_done(&ctx->provider_remove));
	KUNIT_EXPECT_FALSE(test, completion_done(&ctx->threads[1].done));
	complete(&ctx->release_consumer_probe);
	provider_test_join(test, 0);
	provider_test_join(test, 1);
	KUNIT_EXPECT_LT(test, ctx->consumer_order, ctx->provider_order);
}

static void extcon_provider_waits_callback_test(struct kunit *test)
{
	struct provider_test_context *ctx = test->priv;

	provider_test_add(test, false);
	provider_test_add(test, true);
	ctx->hold_callback = true;
	provider_test_start(test, 0, DISPATCH_EVENT);
	ctx->dispatch_started = true;
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&ctx->callback, TEST_WAIT), 0UL);
	provider_test_start(test, 1, UNBIND_PROVIDER);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&ctx->consumer_remove, TEST_WAIT), 0UL);
	msleep(100);
	KUNIT_EXPECT_FALSE(test, completion_done(&ctx->provider_remove));
	KUNIT_EXPECT_FALSE(test, completion_done(&ctx->threads[1].done));
	complete(&ctx->release_callback);
	provider_test_join(test, 0);
	provider_test_join(test, 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&ctx->callbacks), 1);
	KUNIT_EXPECT_LT(test, ctx->consumer_order, ctx->provider_order);
}

static struct kunit_case provider_test_cases[] = {
	KUNIT_CASE(extcon_provider_bound_test),
	KUNIT_CASE(extcon_provider_existing_link_test),
	KUNIT_CASE(extcon_provider_missing_test),
	KUNIT_CASE(extcon_provider_invalid_test),
	KUNIT_CASE(extcon_provider_probe_failure_test),
	KUNIT_CASE(extcon_provider_still_probing_test),
	KUNIT_CASE(extcon_provider_failed_supplier_test),
	KUNIT_CASE(extcon_provider_unbinding_test),
	KUNIT_CASE(extcon_provider_waits_probe_test),
	KUNIT_CASE(extcon_provider_waits_callback_test),
	{}
};

static struct kunit_suite provider_test_suite = {
	.name = "extcon-provider-lifetime",
	.init = provider_test_init,
	.exit = provider_test_exit,
	.test_cases = provider_test_cases,
};

kunit_test_suite(provider_test_suite);

MODULE_DESCRIPTION("Extcon provider driver lifetime tests");
MODULE_LICENSE("GPL");
