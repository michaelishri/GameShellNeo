// SPDX-License-Identifier: GPL-2.0-only
/* Test-only inclusion alongside the real gadget driver in isolated UML. */
#include <kunit/test.h>
#include <linux/delay.h>
#include <linux/kthread.h>

int musb_restart_test_run(struct musb *musb);
void musb_restart_test_stop(struct musb *musb);

struct restart_fixture {
	struct kunit *test;
	struct musb *musb;
	struct device *device;
	struct usb_request *requests[3];
	struct usb_endpoint_descriptor desc;
	unsigned int starts[3], completions, complete_on_restart;
	bool resume_in_completion, requeue;
	int queue_target;
	int expected_queue_result, invoke_result;
	struct task_struct *invoke_thread, *stop_thread;
	struct completion entered, release, invoked, stopped;
	unsigned int calls, late_calls, timeouts;
	bool queued, hold_completion, dequeue, handoff_running;
};

/* The test callback opens a controlled scheduling gap in process context. */
static void fixture_pause(struct restart_fixture *f)
{
	complete(&f->entered);
	local_irq_enable();
	if (!wait_for_completion_timeout(&f->release, 5 * HZ))
		f->timeouts++;
	local_irq_disable();
}

static struct musb_ep *fixture_ep(struct restart_fixture *f, int index)
{
	return &f->musb->endpoints[index + 1].ep_in;
}

static void fixture_complete(struct usb_ep *ep, struct usb_request *request)
{
	struct restart_fixture *f = request->context;
	unsigned long flags;

	f->completions++;
	if (f->expected_queue_result == -ESHUTDOWN)
		KUNIT_EXPECT_EQ(f->test, request->status, -ESHUTDOWN);
	if (f->resume_in_completion) {
		spin_lock_irqsave(&f->musb->lock, flags);
		KUNIT_EXPECT_EQ(f->test, musb_restart_test_run(f->musb), 0);
		f->musb->is_runtime_suspended = false;
		spin_unlock_irqrestore(&f->musb->lock, flags);
	}
	if (f->requeue)
		KUNIT_EXPECT_EQ(f->test, musb_gadget_queue(ep, request, GFP_ATOMIC),
				f->expected_queue_result);
	if (f->queue_target >= 0) {
		struct usb_request *target = f->requests[f->queue_target];

		f->queue_target = -1;
		KUNIT_EXPECT_EQ(f->test, musb_gadget_queue(
			&to_musb_request(target)->ep->end_point, target, GFP_ATOMIC), 0);
	}
	if (f->hold_completion && (!f->handoff_running || f->completions == 2))
		fixture_pause(f);
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
	init_waitqueue_head(&f->musb->resume_work_wait);
	init_completion(&f->entered);
	init_completion(&f->release);
	init_completion(&f->invoked);
	init_completion(&f->stopped);
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

	complete_all(&f->release);
	if (f->invoke_thread)
		kthread_stop(f->invoke_thread);
	if (f->stop_thread)
		kthread_stop(f->stop_thread);
	f->hold_completion = false;
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

static int fixture_late(struct musb *musb, void *data)
{
	struct restart_fixture *f = data;

	lockdep_assert_held(&musb->lock);
	f->late_calls++;
	return 0;
}

static int fixture_held(struct musb *musb, void *data)
{
	struct restart_fixture *f = data;

	lockdep_assert_held(&musb->lock);
	f->calls++;
	spin_unlock(&musb->lock);
	fixture_pause(f);
	spin_lock(&musb->lock);
	return 0;
}

static void resume_cancel_test(struct kunit *test)
{
	struct restart_fixture *f = test->priv;
	unsigned long flags;

	fixture_queue(f, 0);
	fixture_queue(f, 1);
	spin_lock_irqsave(&f->musb->lock, flags);
	KUNIT_EXPECT_EQ(test, musb_queue_resume_work(f->musb, fixture_late, f), 0);
	spin_unlock_irqrestore(&f->musb->lock, flags);
	musb_restart_test_stop(f->musb);
	musb_restart_test_stop(f->musb);
	KUNIT_EXPECT_TRUE(test, list_empty(&f->musb->pending_list));
	KUNIT_EXPECT_EQ(test, f->completions, 0U);
	/* Records are gone; requests still belong to endpoint cleanup. */
	f->requeue = true;
	f->expected_queue_result = -ESHUTDOWN;
	spin_lock_irqsave(&f->musb->lock, flags);
	nuke(fixture_ep(f, 0), -ESHUTDOWN);
	KUNIT_EXPECT_EQ(test, musb_restart_test_run(f->musb), 0);
	spin_unlock_irqrestore(&f->musb->lock, flags);
	KUNIT_EXPECT_EQ(test, f->completions, 2U);
	KUNIT_EXPECT_EQ(test, f->late_calls, 0U);
	KUNIT_EXPECT_EQ(test, f->starts[0] + f->starts[1], 0U);
	KUNIT_EXPECT_FALSE(test, fixture_ep(f, 0)->restart_pending);
	KUNIT_EXPECT_FALSE(test, fixture_ep(f, 0)->restart_deferred);
	KUNIT_EXPECT_TRUE(test, list_empty(&fixture_ep(f, 0)->req_list));
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
}

static void check_resume_gate(struct kunit *test, bool suspended)
{
	struct restart_fixture *f = test->priv;
	unsigned long flags;

	f->musb->is_runtime_suspended = suspended;
	musb_restart_test_stop(f->musb);
	spin_lock_irqsave(&f->musb->lock, flags);
	KUNIT_EXPECT_EQ(test, musb_queue_resume_work(f->musb, fixture_late, f), -ESHUTDOWN);
	spin_unlock_irqrestore(&f->musb->lock, flags);
	KUNIT_EXPECT_EQ(test, musb_gadget_queue(&fixture_ep(f, 0)->end_point,
					      f->requests[0], GFP_KERNEL), -ESHUTDOWN);
	KUNIT_EXPECT_EQ(test, f->late_calls, 0U);
	KUNIT_EXPECT_TRUE(test, list_empty(&f->musb->pending_list));
	KUNIT_EXPECT_TRUE(test, list_empty(&fixture_ep(f, 0)->req_list));
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
}

static void resume_active_gate_test(struct kunit *test) { check_resume_gate(test, false); }
static void resume_suspended_gate_test(struct kunit *test) { check_resume_gate(test, true); }

static int fixture_invoke(void *data)
{
	struct restart_fixture *f = data;
	unsigned long flags;

	if (f->dequeue) {
		f->invoke_result = musb_gadget_dequeue(&fixture_ep(f, 0)->end_point,
						     f->requests[1]);
	} else if (f->hold_completion) {
		f->invoke_result = musb_gadget_queue(&fixture_ep(f, 0)->end_point,
						   f->requests[0], GFP_KERNEL);
	} else {
		spin_lock_irqsave(&f->musb->lock, flags);
		if (f->queued)
			f->invoke_result = musb_restart_test_run(f->musb);
		else
			f->invoke_result = musb_queue_resume_work(f->musb, fixture_held, f);
		spin_unlock_irqrestore(&f->musb->lock, flags);
	}
	complete(&f->invoked);
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
	return 0;
}

static int fixture_stop(void *data)
{
	struct restart_fixture *f = data;

	musb_restart_test_stop(f->musb);
	complete_all(&f->stopped);
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
	return 0;
}

static void check_resume_running(struct kunit *test, bool queued, bool handoff, bool restart)
{
	struct restart_fixture *f = test->priv;
	struct task_struct *thread;
	unsigned long flags, deadline;
	bool closed = false;

	f->queued = queued;
	f->dequeue = handoff;
	f->hold_completion = handoff || restart;
	f->resume_in_completion = handoff;
	f->complete_on_restart = restart;
	f->handoff_running = handoff && restart;
	f->musb->is_runtime_suspended = queued || handoff;
	if (handoff) {
		fixture_queue(f, 0);
		fixture_queue(f, 1);
	} else if (queued) {
		spin_lock_irqsave(&f->musb->lock, flags);
		KUNIT_EXPECT_EQ(test, musb_queue_resume_work(f->musb, fixture_held, f), 0);
		KUNIT_EXPECT_EQ(test, musb_queue_resume_work(f->musb, fixture_late, f), 0);
		spin_unlock_irqrestore(&f->musb->lock, flags);
	}
	thread = kthread_run(fixture_invoke, f, "musb-resume-invoke");
	KUNIT_ASSERT_FALSE(test, IS_ERR(thread));
	f->invoke_thread = thread;
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->entered, HZ), 0UL);
	thread = kthread_run(fixture_stop, f, "musb-resume-stop");
	KUNIT_ASSERT_FALSE(test, IS_ERR(thread));
	f->stop_thread = thread;
	deadline = jiffies + HZ;
	do {
		spin_lock_irqsave(&f->musb->lock, flags);
		closed = f->musb->resume_work_stopping;
		spin_unlock_irqrestore(&f->musb->lock, flags);
		if (!closed)
			msleep(1);
	} while (!closed && time_before(jiffies, deadline));
	KUNIT_ASSERT_TRUE(test, closed);
	if (handoff && !restart) {
		/* The callback returned, handing the hold to giveback. Gate it too. */
		KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->stopped, HZ), 0UL);
		KUNIT_EXPECT_TRUE(test, fixture_ep(f, 0)->restart_deferred);
		KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 2);
	} else {
		KUNIT_EXPECT_FALSE(test, completion_done(&f->stopped));
		spin_lock_irqsave(&f->musb->lock, flags);
		KUNIT_EXPECT_EQ(test, f->musb->resume_work_count, 1U);
		spin_unlock_irqrestore(&f->musb->lock, flags);
	}
	spin_lock_irqsave(&f->musb->lock, flags);
	KUNIT_EXPECT_EQ(test, musb_queue_resume_work(f->musb, fixture_late, f), -ESHUTDOWN);
	spin_unlock_irqrestore(&f->musb->lock, flags);
	complete(&f->release);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->invoked, HZ), 0UL);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->stopped, HZ), 0UL);
	KUNIT_EXPECT_EQ(test, f->invoke_result, 0);
	KUNIT_EXPECT_EQ(test, f->timeouts, 0U);
	KUNIT_EXPECT_EQ(test, f->late_calls, 0U);
	KUNIT_EXPECT_EQ(test, f->musb->resume_work_count, 0U);
	KUNIT_EXPECT_TRUE(test, list_empty(&f->musb->pending_list));
	KUNIT_EXPECT_EQ(test, f->starts[0], restart ? 1U : 0U);
	KUNIT_EXPECT_FALSE(test, fixture_ep(f, 0)->restart_deferred);
	KUNIT_EXPECT_FALSE(test, fixture_ep(f, 0)->restart_pending);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
}

static void resume_immediate_running_test(struct kunit *test)
{
	check_resume_running(test, false, false, false);
}

static void resume_queued_running_test(struct kunit *test)
{
	check_resume_running(test, true, false, false);
}

static void resume_deferred_handoff_test(struct kunit *test)
{
	check_resume_running(test, false, true, false);
}

static void resume_handoff_running_test(struct kunit *test)
{
	check_resume_running(test, false, true, true);
}

static void resume_restart_running_test(struct kunit *test)
{
	check_resume_running(test, false, false, true);
}

static int fixture_nested_leaf(struct musb *musb, void *data)
{
	struct restart_fixture *f = data;

	KUNIT_EXPECT_EQ(f->test, musb->resume_work_count, 2U);
	f->calls++;
	return -EIO;
}

static int fixture_nested(struct musb *musb, void *data)
{
	return musb_queue_resume_work(musb, fixture_nested_leaf, data);
}

static void resume_nested_test(struct kunit *test)
{
	struct restart_fixture *f = test->priv;
	unsigned long flags;

	f->musb->is_runtime_suspended = false;
	spin_lock_irqsave(&f->musb->lock, flags);
	KUNIT_EXPECT_EQ(test, musb_queue_resume_work(f->musb, fixture_nested, f), -EIO);
	KUNIT_EXPECT_EQ(test, f->musb->resume_work_count, 0U);
	spin_unlock_irqrestore(&f->musb->lock, flags);
	KUNIT_EXPECT_EQ(test, f->calls, 1U);
	musb_restart_test_stop(f->musb);
}

static void resume_fresh_instance_test(struct kunit *test)
{
	struct restart_fixture *f = test->priv;
	struct musb *fresh = kunit_kzalloc(test, sizeof(*fresh), GFP_KERNEL);
	unsigned long flags;

	KUNIT_ASSERT_NOT_NULL(test, fresh);
	fresh->controller = f->device;
	spin_lock_init(&fresh->lock);
	spin_lock_init(&fresh->list_lock);
	init_waitqueue_head(&fresh->resume_work_wait);
	INIT_LIST_HEAD(&fresh->pending_list);
	musb_restart_test_stop(f->musb);
	spin_lock_irqsave(&fresh->lock, flags);
	KUNIT_EXPECT_EQ(test, musb_queue_resume_work(fresh, fixture_late, f), 0);
	spin_unlock_irqrestore(&fresh->lock, flags);
	KUNIT_EXPECT_EQ(test, f->late_calls, 1U);
	musb_restart_test_stop(fresh);
}

static struct kunit_case restart_cases[] = {
	KUNIT_CASE(restart_busy_giveback_test),
	KUNIT_CASE(restart_empty_requeue_test),
	KUNIT_CASE(restart_same_endpoint_test),
	KUNIT_CASE(restart_other_endpoint_test),
	KUNIT_CASE(restart_follower_test),
	KUNIT_CASE(restart_nuke_test),
	KUNIT_CASE(restart_first_error_test),
	KUNIT_CASE(resume_cancel_test),
	KUNIT_CASE(resume_active_gate_test),
	KUNIT_CASE(resume_suspended_gate_test),
	KUNIT_CASE(resume_immediate_running_test),
	KUNIT_CASE(resume_queued_running_test),
	KUNIT_CASE(resume_deferred_handoff_test),
	KUNIT_CASE(resume_restart_running_test),
	KUNIT_CASE(resume_handoff_running_test),
	KUNIT_CASE(resume_nested_test),
	KUNIT_CASE(resume_fresh_instance_test),
	{}
};

static struct kunit_suite restart_suite = {
	.name = "musb-restart",
	.init = fixture_init,
	.exit = fixture_exit,
	.test_cases = restart_cases,
};

kunit_test_suite(restart_suite);
