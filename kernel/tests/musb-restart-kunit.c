// SPDX-License-Identifier: GPL-2.0-only
/* Test-only inclusion alongside the real gadget driver in isolated UML. */
#include <kunit/test.h>

int musb_restart_test_run(struct musb *musb);

struct restart_fixture {
	struct kunit *test;
	struct musb *musb;
	struct device *device;
	struct usb_request *requests[3];
	struct usb_endpoint_descriptor desc;
	unsigned int starts[3], completions, complete_on_restart;
	bool resume_in_completion, requeue;
	int queue_target;
};

static struct musb_ep *fixture_ep(struct restart_fixture *f, int index)
{
	return &f->musb->endpoints[index + 1].ep_in;
}

static void fixture_complete(struct usb_ep *ep, struct usb_request *request)
{
	struct restart_fixture *f = request->context;
	unsigned long flags;

	f->completions++;
	if (f->resume_in_completion) {
		spin_lock_irqsave(&f->musb->lock, flags);
		KUNIT_EXPECT_EQ(f->test, musb_restart_test_run(f->musb), 0);
		f->musb->is_runtime_suspended = false;
		spin_unlock_irqrestore(&f->musb->lock, flags);
	}
	if (f->requeue)
		KUNIT_EXPECT_EQ(f->test, musb_gadget_queue(ep, request, GFP_ATOMIC), 0);
	if (f->queue_target >= 0) {
		struct usb_request *target = f->requests[f->queue_target];

		f->queue_target = -1;
		KUNIT_EXPECT_EQ(f->test, musb_gadget_queue(
			&to_musb_request(target)->ep->end_point, target, GFP_ATOMIC), 0);
	}
}

/* Replace only the hardware restart; queue/giveback/PM accounting are real. */
static void fixture_restart(struct musb *musb, struct musb_request *request)
{
	struct restart_fixture *f = request->request.context;
	int i;

	lockdep_assert_held(&musb->lock);
	KUNIT_EXPECT_FALSE(f->test, request->ep->busy);
	KUNIT_EXPECT_PTR_EQ(f->test, next_request(request->ep), request);
	for (i = 0; i < ARRAY_SIZE(f->requests); i++)
		if (f->requests[i] == &request->request)
			f->starts[i]++;
	if (f->complete_on_restart) {
		f->complete_on_restart--;
		musb_g_giveback(request->ep, &request->request, 0);
	}
}

static int fixture_init(struct kunit *test)
{
	struct restart_fixture *f;
	int i;

	f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	if (!f)
		return -ENOMEM;
	f->musb = kunit_kzalloc(test, sizeof(*f->musb), GFP_KERNEL);
	if (!f->musb)
		return -ENOMEM;
	f->device = root_device_register("musb-restart-kunit");
	if (IS_ERR(f->device))
		return PTR_ERR(f->device);
	f->test = test;
	f->queue_target = -1;
	f->musb->controller = f->device;
	spin_lock_init(&f->musb->lock);
	spin_lock_init(&f->musb->list_lock);
	INIT_LIST_HEAD(&f->musb->pending_list);
	f->musb->is_runtime_suspended = true;
	pm_runtime_set_active(f->device);
	pm_runtime_get_noresume(f->device);
	pm_runtime_enable(f->device);
	for (i = 0; i < 2; i++) {
		struct musb_ep *ep = fixture_ep(f, i);

		ep->musb = f->musb;
		ep->desc = &f->desc;
		ep->end_point.name = "kunit";
		ep->current_epnum = i + 1;
		ep->is_in = 1;
		INIT_LIST_HEAD(&ep->req_list);
	}
	for (i = 0; i < ARRAY_SIZE(f->requests); i++) {
		struct musb_ep *ep = fixture_ep(f, i == 2);

		f->requests[i] = musb_alloc_request(&ep->end_point, GFP_KERNEL);
		if (!f->requests[i])
			goto fail;
		f->requests[i]->buf = f;
		f->requests[i]->complete = fixture_complete;
		f->requests[i]->context = f;
	}
	test->priv = f;
	musb_restart_test_controller = f->musb;
	musb_restart_test_hook = fixture_restart;
	return 0;
fail:
	while (--i >= 0)
		musb_free_request(&to_musb_request(f->requests[i])->ep->end_point,
				  f->requests[i]);
	pm_runtime_disable(f->device);
	pm_runtime_put_noidle(f->device);
	root_device_unregister(f->device);
	return -ENOMEM;
}

static void fixture_exit(struct kunit *test)
{
	struct restart_fixture *f = test->priv;
	unsigned long flags;
	int i;

	f->resume_in_completion = f->requeue = false;
	f->queue_target = -1;
	spin_lock_irqsave(&f->musb->lock, flags);
	for (i = 0; i < 2; i++) {
		nuke(fixture_ep(f, i), -ESHUTDOWN);
		fixture_ep(f, i)->desc = NULL;
	}
	KUNIT_EXPECT_EQ(test, musb_restart_test_run(f->musb), 0);
	KUNIT_EXPECT_TRUE(test, list_empty(&f->musb->pending_list));
	spin_unlock_irqrestore(&f->musb->lock, flags);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
	musb_restart_test_controller = NULL;
	musb_restart_test_hook = NULL;
	for (i = 0; i < ARRAY_SIZE(f->requests); i++)
		musb_free_request(&to_musb_request(f->requests[i])->ep->end_point,
				  f->requests[i]);
	pm_runtime_disable(f->device);
	pm_runtime_put_noidle(f->device);
	root_device_unregister(f->device);
}

static void fixture_queue(struct restart_fixture *f, int index)
{
	struct usb_request *request = f->requests[index];

	KUNIT_EXPECT_EQ(f->test, musb_gadget_queue(
		&to_musb_request(request)->ep->end_point, request, GFP_KERNEL), 0);
}

static void fixture_resume(struct restart_fixture *f)
{
	unsigned long flags;

	spin_lock_irqsave(&f->musb->lock, flags);
	KUNIT_EXPECT_EQ(f->test, musb_restart_test_run(f->musb), 0);
	f->musb->is_runtime_suspended = false;
	spin_unlock_irqrestore(&f->musb->lock, flags);
}

static void restart_busy_giveback_test(struct kunit *test)
{
	struct restart_fixture *f = test->priv;

	fixture_queue(f, 0);
	fixture_queue(f, 1);
	f->resume_in_completion = true;
	KUNIT_EXPECT_EQ(test, musb_gadget_dequeue(&fixture_ep(f, 0)->end_point,
						f->requests[1]), 0);
	KUNIT_EXPECT_EQ(test, f->starts[0], 1U);
	KUNIT_EXPECT_FALSE(test, fixture_ep(f, 0)->restart_pending);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
}

static void restart_empty_requeue_test(struct kunit *test)
{
	struct restart_fixture *f = test->priv;

	fixture_queue(f, 0);
	f->resume_in_completion = f->requeue = true;
	KUNIT_EXPECT_EQ(test, musb_gadget_dequeue(&fixture_ep(f, 0)->end_point,
						f->requests[0]), 0);
	KUNIT_EXPECT_EQ(test, f->starts[0], 1U);
}

static void restart_same_endpoint_test(struct kunit *test)
{
	struct restart_fixture *f = test->priv;

	fixture_queue(f, 0);
	f->complete_on_restart = 1;
	f->requeue = true;
	fixture_resume(f);
	KUNIT_EXPECT_EQ(test, f->starts[0], 2U);
	KUNIT_EXPECT_EQ(test, f->completions, 1U);
}

static void restart_other_endpoint_test(struct kunit *test)
{
	struct restart_fixture *f = test->priv;

	fixture_queue(f, 0);
	f->complete_on_restart = 1;
	f->queue_target = 2;
	fixture_resume(f);
	KUNIT_EXPECT_EQ(test, f->starts[0], 1U);
	KUNIT_EXPECT_EQ(test, f->starts[2], 1U);
}

static void restart_follower_test(struct kunit *test)
{
	struct restart_fixture *f = test->priv;

	fixture_queue(f, 0);
	fixture_queue(f, 1);
	f->complete_on_restart = 1;
	fixture_resume(f);
	KUNIT_EXPECT_EQ(test, f->starts[0], 1U);
	KUNIT_EXPECT_EQ(test, f->starts[1], 1U);
}

static void restart_nuke_test(struct kunit *test)
{
	struct restart_fixture *f = test->priv;
	unsigned long flags;

	fixture_queue(f, 0);
	fixture_queue(f, 1);
	f->resume_in_completion = true;
	spin_lock_irqsave(&f->musb->lock, flags);
	nuke(fixture_ep(f, 0), -ESHUTDOWN);
	spin_unlock_irqrestore(&f->musb->lock, flags);
	KUNIT_EXPECT_EQ(test, f->completions, 2U);
	KUNIT_EXPECT_EQ(test, f->starts[0] + f->starts[1], 0U);
	KUNIT_EXPECT_FALSE(test, fixture_ep(f, 0)->restart_pending);
	KUNIT_EXPECT_FALSE(test, fixture_ep(f, 0)->restart_deferred);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
}

static int fixture_error(struct musb *musb, void *data)
{
	lockdep_assert_held(&musb->lock);
	return *(int *)data;
}

static void restart_first_error_test(struct kunit *test)
{
	struct restart_fixture *f = test->priv;
	int first = -EIO, second = -EINVAL, success = 0;
	unsigned long flags;

	spin_lock_irqsave(&f->musb->lock, flags);
	KUNIT_EXPECT_EQ(test, musb_queue_resume_work(f->musb, fixture_error, &first), 0);
	KUNIT_EXPECT_EQ(test, musb_queue_resume_work(f->musb, fixture_error, &second), 0);
	KUNIT_EXPECT_EQ(test, musb_queue_resume_work(f->musb, fixture_error, &success), 0);
	KUNIT_EXPECT_EQ(test, musb_restart_test_run(f->musb), first);
	KUNIT_EXPECT_TRUE(test, list_empty(&f->musb->pending_list));
	spin_unlock_irqrestore(&f->musb->lock, flags);
}

static struct kunit_case restart_cases[] = {
	KUNIT_CASE(restart_busy_giveback_test),
	KUNIT_CASE(restart_empty_requeue_test),
	KUNIT_CASE(restart_same_endpoint_test),
	KUNIT_CASE(restart_other_endpoint_test),
	KUNIT_CASE(restart_follower_test),
	KUNIT_CASE(restart_nuke_test),
	KUNIT_CASE(restart_first_error_test),
	{}
};

static struct kunit_suite restart_suite = {
	.name = "musb-restart",
	.init = fixture_init,
	.exit = fixture_exit,
	.test_cases = restart_cases,
};

kunit_test_suite(restart_suite);
