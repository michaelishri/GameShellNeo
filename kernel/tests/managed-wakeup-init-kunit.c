// SPDX-License-Identifier: GPL-2.0
/* Included by wakeup.c in a disposable test kernel, after the real IDA/APIs. */
#include <kunit/test.h>
#include <linux/sched.h>
#include <linux/sched/task.h>
#include "../base.h"

struct managed_wakeup_fixture {
	struct device dev;
	struct task_struct *owner;
	void (*action)(void *);
	char name[64];
	bool registered;
	bool fail_source;
	bool fail_action;
	unsigned int source_hits;
	unsigned int action_hits;
	unsigned int created;
	unsigned int freed;
	int last_id;
	atomic_t releases;
};

/* Observers never retain a fixture pointer after unlocking. Removal waits for
 * every short observer before KUnit can release its context. No sleep, wait,
 * allocation or production callback occurs while this lock is held.
 */
static DEFINE_SPINLOCK(managed_wakeup_hook_lock);
static struct managed_wakeup_fixture *managed_wakeup_active;
static atomic_t managed_wakeup_sequence = ATOMIC_INIT(0);

static bool managed_wakeup_matches(struct managed_wakeup_fixture *f,
				   const char *name)
{
	return f && current == f->owner && name && !strcmp(name, f->name);
}

bool neo_managed_wakeup_source_fail(const char *name)
{
	struct managed_wakeup_fixture *f;
	unsigned long flags;
	bool fail = false;

	spin_lock_irqsave(&managed_wakeup_hook_lock, flags);
	f = managed_wakeup_active;
	if (managed_wakeup_matches(f, name) && f->fail_source) {
		f->source_hits++;
		f->fail_source = false;
		fail = true;
	}
	spin_unlock_irqrestore(&managed_wakeup_hook_lock, flags);
	return fail;
}

void neo_managed_wakeup_created(struct wakeup_source *ws)
{
	struct managed_wakeup_fixture *f;
	unsigned long flags;

	spin_lock_irqsave(&managed_wakeup_hook_lock, flags);
	f = managed_wakeup_active;
	if (managed_wakeup_matches(f, ws->name)) {
		f->created++;
		f->last_id = ws->id;
	}
	spin_unlock_irqrestore(&managed_wakeup_hook_lock, flags);
}

void neo_managed_wakeup_freeing(struct wakeup_source *ws)
{
	struct managed_wakeup_fixture *f;
	unsigned long flags;

	spin_lock_irqsave(&managed_wakeup_hook_lock, flags);
	f = managed_wakeup_active;
	if (managed_wakeup_matches(f, ws->name))
		f->freed++;
	spin_unlock_irqrestore(&managed_wakeup_hook_lock, flags);
}

bool neo_managed_wakeup_action_fail(struct device *dev,
				  void (*action)(void *), void *data)
{
	struct managed_wakeup_fixture *f;
	unsigned long flags;
	bool fail = false;

	spin_lock_irqsave(&managed_wakeup_hook_lock, flags);
	f = managed_wakeup_active;
	if (f && current == f->owner && dev == &f->dev && data == dev &&
	    action == f->action && f->fail_action) {
		f->action_hits++;
		f->fail_action = false;
		fail = true;
	}
	spin_unlock_irqrestore(&managed_wakeup_hook_lock, flags);
	return fail;
}

static void managed_wakeup_release(struct device *dev)
{
	struct managed_wakeup_fixture *f;

	f = container_of(dev, struct managed_wakeup_fixture, dev);
	atomic_inc(&f->releases);
}

static unsigned int managed_wakeup_sources(struct managed_wakeup_fixture *f)
{
	struct wakeup_source *ws;
	unsigned int count = 0;
	int idx = wakeup_sources_read_lock();

	for_each_wakeup_source(ws)
		if (!strcmp(ws->name, f->name))
			count++;
	wakeup_sources_read_unlock(idx);
	return count;
}

/* Use the allocator's locked public range query, not an assumed ID count. */
static bool managed_wakeup_id_owned(int id)
{
	return id >= 0 && ida_find_first_range(&wakeup_ida, id, id) == id;
}

static int managed_wakeup_init(struct kunit *test)
{
	struct managed_wakeup_fixture *f;
	unsigned long flags;
	int ret;

	f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	if (!f)
		return -ENOMEM;
	test->priv = f;
	f->owner = current;
	f->action = device_disable_wakeup;
	f->last_id = -1;
	atomic_set(&f->releases, 0);
	snprintf(f->name, sizeof(f->name), "neo-managed-wakeup-%d",
		 atomic_inc_return(&managed_wakeup_sequence));
	device_initialize(&f->dev);
	f->dev.release = managed_wakeup_release;
	ret = dev_set_name(&f->dev, "%s", f->name);
	if (ret) {
		put_device(&f->dev);
		return ret;
	}
	ret = device_add(&f->dev);
	if (ret) {
		put_device(&f->dev);
		return ret;
	}
	spin_lock_irqsave(&managed_wakeup_hook_lock, flags);
	if (managed_wakeup_active) {
		spin_unlock_irqrestore(&managed_wakeup_hook_lock, flags);
		device_unregister(&f->dev);
		return -EBUSY;
	}
	managed_wakeup_active = f;
	get_task_struct(f->owner);
	f->registered = true;
	spin_unlock_irqrestore(&managed_wakeup_hook_lock, flags);
	return 0;
}

static void managed_wakeup_exit(struct kunit *test)
{
	struct managed_wakeup_fixture *f = test->priv;
	struct task_struct *old_owner;
	unsigned long flags;

	if (!f || !f->registered)
		return;
	/* KUnit runs case cleanup in a second try/catch thread. The case thread
	 * has joined; transfer the retained task identity before normal teardown.
	 */
	get_task_struct(current);
	spin_lock_irqsave(&managed_wakeup_hook_lock, flags);
	old_owner = f->owner;
	f->owner = current;
	spin_unlock_irqrestore(&managed_wakeup_hook_lock, flags);
	put_task_struct(old_owner);
	/* Normal device removal drains any unconsumed action and wakeup source.
	 * The embedded device stays allocated by KUnit through its release callback.
	 */
	device_unregister(&f->dev);
	f->registered = false;
	KUNIT_EXPECT_EQ(test, atomic_read(&f->releases), 1);
	KUNIT_EXPECT_EQ(test, managed_wakeup_sources(f), 0U);
	KUNIT_EXPECT_EQ(test, f->created, f->freed);
	spin_lock_irqsave(&managed_wakeup_hook_lock, flags);
	managed_wakeup_active = NULL;
	f->owner = NULL;
	spin_unlock_irqrestore(&managed_wakeup_hook_lock, flags);
	put_task_struct(current);
}

static void managed_wakeup_balance(struct kunit *test, bool capable_disabled)
{
	struct managed_wakeup_fixture *f = test->priv;
	int id, result;

	if (capable_disabled) {
		device_set_wakeup_capable(&f->dev, true);
		KUNIT_EXPECT_PTR_EQ(test, f->dev.power.wakeup, NULL);
	}
	result = devm_device_init_wakeup(&f->dev);
	KUNIT_EXPECT_EQ(test, result, 0);
	KUNIT_ASSERT_NOT_NULL(test, f->dev.power.wakeup);
	id = f->dev.power.wakeup->id;
	KUNIT_EXPECT_TRUE(test, device_can_wakeup(&f->dev));
	KUNIT_EXPECT_TRUE(test, managed_wakeup_id_owned(id));
	KUNIT_EXPECT_TRUE(test, devm_is_action_added(&f->dev, f->action, &f->dev));
	KUNIT_EXPECT_EQ(test, managed_wakeup_sources(f), 1U);
	devres_release_all(&f->dev);
	KUNIT_EXPECT_PTR_EQ(test, f->dev.power.wakeup, NULL);
	KUNIT_EXPECT_FALSE(test, device_can_wakeup(&f->dev));
	KUNIT_EXPECT_FALSE(test, managed_wakeup_id_owned(id));
	KUNIT_EXPECT_EQ(test, f->freed, 1U);
	devres_release_all(&f->dev);
	KUNIT_EXPECT_EQ(test, f->freed, 1U);
	KUNIT_EXPECT_FALSE(test, devm_is_action_added(&f->dev, f->action, &f->dev));
	kunit_info(test, "ownership result=%d source_hits=%u action_hits=%u created=%u freed=%u\n",
		   result, f->source_hits, f->action_hits, f->created, f->freed);
}

static void managed_wakeup_success_test(struct kunit *test)
{
	managed_wakeup_balance(test, false);
}

static void managed_wakeup_capable_disabled_test(struct kunit *test)
{
	managed_wakeup_balance(test, true);
}

static void managed_wakeup_source_error_test(struct kunit *test)
{
	struct managed_wakeup_fixture *f = test->priv;
	bool action_present, capable_after_release;
	int result;

	f->fail_source = true;
	result = devm_device_init_wakeup(&f->dev);
	action_present = devm_is_action_added(&f->dev, f->action, &f->dev);
	KUNIT_EXPECT_EQ(test, result, -ENOMEM);
	KUNIT_EXPECT_FALSE(test, action_present);
	KUNIT_EXPECT_PTR_EQ(test, f->dev.power.wakeup, NULL);
	KUNIT_EXPECT_EQ(test, f->source_hits, 1U);
	KUNIT_EXPECT_EQ(test, f->created, 0U);
	KUNIT_EXPECT_EQ(test, f->freed, 0U);
	KUNIT_EXPECT_TRUE(test, device_can_wakeup(&f->dev));
	devres_release_all(&f->dev);
	capable_after_release = device_can_wakeup(&f->dev);
	KUNIT_EXPECT_TRUE(test, capable_after_release);
	KUNIT_EXPECT_EQ(test, managed_wakeup_sources(f), 0U);
	kunit_info(test, "ownership result=%d action=%d capable=%d source_hits=%u action_hits=%u created=%u freed=%u\n",
		   result, action_present, capable_after_release, f->source_hits,
		   f->action_hits, f->created, f->freed);
}

static void managed_wakeup_existing_source_test(struct kunit *test)
{
	struct managed_wakeup_fixture *f = test->priv;
	unsigned long identity;
	bool action_present, source_preserved, id_preserved, capable_after_release;
	int id, result;

	KUNIT_ASSERT_EQ(test, device_init_wakeup(&f->dev, true), 0);
	KUNIT_ASSERT_NOT_NULL(test, f->dev.power.wakeup);
	/* Numeric identity is safe even when the original control frees the source. */
	identity = (unsigned long)f->dev.power.wakeup;
	id = f->dev.power.wakeup->id;
	result = devm_device_init_wakeup(&f->dev);
	action_present = devm_is_action_added(&f->dev, f->action, &f->dev);
	KUNIT_EXPECT_EQ(test, result, -EEXIST);
	KUNIT_EXPECT_FALSE(test, action_present);
	KUNIT_EXPECT_EQ(test, (unsigned long)f->dev.power.wakeup, identity);
	KUNIT_EXPECT_EQ(test, f->created, 2U);
	KUNIT_EXPECT_EQ(test, f->freed, 1U);
	devres_release_all(&f->dev);
	source_preserved = (unsigned long)f->dev.power.wakeup == identity;
	id_preserved = managed_wakeup_id_owned(id);
	capable_after_release = device_can_wakeup(&f->dev);
	KUNIT_EXPECT_TRUE(test, source_preserved);
	KUNIT_EXPECT_TRUE(test, id_preserved);
	KUNIT_EXPECT_TRUE(test, capable_after_release);
	kunit_info(test, "ownership result=%d action=%d source=%d id=%d capable=%d source_hits=%u action_hits=%u created=%u freed=%u\n",
		   result, action_present, source_preserved, id_preserved,
		   capable_after_release, f->source_hits, f->action_hits, f->created, f->freed);
	/* The ordinary source belongs to this case, not to the failed managed call. */
	device_init_wakeup(&f->dev, false);
	KUNIT_EXPECT_EQ(test, f->freed, 2U);
	KUNIT_EXPECT_FALSE(test, managed_wakeup_id_owned(id));
}

static void managed_wakeup_action_error_test(struct kunit *test)
{
	struct managed_wakeup_fixture *f = test->priv;
	int result;

	f->fail_action = true;
	result = devm_device_init_wakeup(&f->dev);
	KUNIT_EXPECT_EQ(test, result, -ENOMEM);
	KUNIT_EXPECT_EQ(test, f->action_hits, 1U);
	KUNIT_EXPECT_EQ(test, f->created, 1U);
	KUNIT_EXPECT_EQ(test, f->freed, 1U);
	KUNIT_EXPECT_PTR_EQ(test, f->dev.power.wakeup, NULL);
	KUNIT_EXPECT_FALSE(test, device_can_wakeup(&f->dev));
	KUNIT_EXPECT_FALSE(test, managed_wakeup_id_owned(f->last_id));
	KUNIT_EXPECT_FALSE(test, devm_is_action_added(&f->dev, f->action, &f->dev));
	devres_release_all(&f->dev);
	KUNIT_EXPECT_EQ(test, f->freed, 1U);
	kunit_info(test, "ownership result=%d source_hits=%u action_hits=%u created=%u freed=%u\n",
		   result, f->source_hits, f->action_hits, f->created, f->freed);
}

static struct kunit_case managed_wakeup_cases[] = {
	KUNIT_CASE(managed_wakeup_success_test),
	KUNIT_CASE(managed_wakeup_source_error_test),
	KUNIT_CASE(managed_wakeup_existing_source_test),
	KUNIT_CASE(managed_wakeup_action_error_test),
	KUNIT_CASE(managed_wakeup_capable_disabled_test),
	{}
};

static struct kunit_suite managed_wakeup_suite = {
	.name = "managed-wakeup-init",
	.init = managed_wakeup_init,
	.exit = managed_wakeup_exit,
	.test_cases = managed_wakeup_cases,
};
kunit_test_suite(managed_wakeup_suite);
