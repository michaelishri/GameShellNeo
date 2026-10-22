// SPDX-License-Identifier: GPL-2.0
/* Appended to actual wakeup.c in an isolated UML test source only. */
#include <linux/delay.h>
#include <linux/kernfs.h>
#include "../../../fs/kernfs/kernfs-internal.h"

enum wakeup_sysfs_operation {
	WAKEUP_SYSFS_WRITE,
	WAKEUP_SYSFS_UNREGISTER,
	WAKEUP_SYSFS_OBSERVE_SOURCE,
	WAKEUP_SYSFS_FOREIGN_SOURCE,
	WAKEUP_SYSFS_DRAIN_CONTEXT,
};

struct wakeup_sysfs_worker {
	struct wakeup_sysfs_fixture *fixture;
	struct file *file;
	struct task_struct *task;
	struct completion finished;
	const char *request;
	struct wakeup_source *source;
	ssize_t result;
	enum wakeup_sysfs_operation operation;
};

static atomic_t wakeup_sysfs_sequence = ATOMIC_INIT(0);

static void wakeup_sysfs_device_release(struct device *dev)
{
	struct wakeup_sysfs_fixture *f = container_of(dev, struct wakeup_sysfs_fixture, dev);

	atomic_inc(&f->release_count);
}

static void wakeup_sysfs_unpublish_context(struct wakeup_sysfs_fixture *f)
{
	rcu_assign_pointer(wakeup_sysfs_active, NULL);
	complete(&f->context_unpublished);
	/* Every admitted hook reader must finish before KUnit frees this context. */
	synchronize_srcu(&wakeup_sysfs_context_srcu);
}

static void wakeup_sysfs_cleanup(struct wakeup_sysfs_fixture *f)
{
	complete_all(&f->gate_release);
	complete_all(&f->observer_release);
	complete_all(&f->foreign_release);
	if (f->registered) {
		device_unregister(&f->dev);
		f->registered = false;
		f->initialized = false;
	} else if (f->initialized) {
		put_device(&f->dev);
		f->initialized = false;
	}
	if (f->mount) {
		kern_unmount(f->mount);
		f->mount = NULL;
	}
	if (f->fs) {
		put_filesystem(f->fs);
		f->fs = NULL;
	}
	wakeup_sysfs_unpublish_context(f);
}

static int wakeup_sysfs_init(struct kunit *test)
{
	struct wakeup_sysfs_fixture *f;
	int ret;

	f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	if (!f)
		return -ENOMEM;
	f->name = kunit_kmalloc(test, 64, GFP_KERNEL);
	if (!f->name)
		return -ENOMEM;
	snprintf(f->name, 64, "neo-wakeup-sysfs-%u", atomic_inc_return(&wakeup_sysfs_sequence));
	snprintf(f->foreign_name, sizeof(f->foreign_name), "%s-unrelated", f->name);
	spin_lock_init(&f->lock);
	init_completion(&f->gate_entered[0]);
	init_completion(&f->gate_entered[1]);
	init_completion(&f->gate_release);
	init_completion(&f->srcu_entered);
	init_completion(&f->observer_entered);
	init_completion(&f->observer_release);
	init_completion(&f->foreign_entered);
	init_completion(&f->foreign_release);
	init_completion(&f->context_unpublished);
	atomic_set(&f->fault, WAKEUP_SYSFS_NO_FAULT);
	atomic_set(&f->fault_hits, 0);
	atomic_set(&f->attach_entries, 0);
	atomic_set(&f->duplicate_attaches, 0);
	atomic_set(&f->release_count, 0);
	test->priv = f;
	device_initialize(&f->dev);
	f->initialized = true;
	f->dev.release = wakeup_sysfs_device_release;
	ret = dev_set_name(&f->dev, "%s", f->name);
	if (ret)
		goto failed;
	device_set_wakeup_capable(&f->dev, true);
	rcu_assign_pointer(wakeup_sysfs_active, f);
	ret = device_add(&f->dev);
	if (ret)
		goto failed;
	f->registered = true;
	f->fs = get_fs_type("sysfs");
	if (!f->fs) {
		ret = -ENODEV;
		goto failed;
	}
	f->mount = vfs_kern_mount(f->fs, SB_KERNMOUNT, "sysfs", NULL);
	if (IS_ERR(f->mount)) {
		ret = PTR_ERR(f->mount);
		f->mount = NULL;
		goto failed;
	}
	return 0;
failed:
	wakeup_sysfs_cleanup(f);
	return ret;
}

static unsigned int wakeup_sysfs_sources_named(const char *name)
{
	struct wakeup_source *ws;
	unsigned int count = 0;
	int index = wakeup_sources_read_lock();

	for (ws = wakeup_sources_walk_start(); ws; ws = wakeup_sources_walk_next(ws))
		if (!strcmp(ws->name, name))
			count++;
	wakeup_sources_read_unlock(index);
	return count;
}

static struct wakeup_source *wakeup_sysfs_attached(struct wakeup_sysfs_fixture *f)
{
	struct wakeup_source *ws;
	unsigned long flags;

	spin_lock_irqsave(&f->dev.power.lock, flags);
	ws = f->dev.power.wakeup;
	spin_unlock_irqrestore(&f->dev.power.lock, flags);
	return ws;
}

static void wakeup_sysfs_expect_owned(struct kunit *test, unsigned int owned)
{
	struct wakeup_sysfs_fixture *f = test->priv;
	unsigned int i, live_ids = 0;

	/* Call only after owned workers finish (or before any workers start). */
	KUNIT_EXPECT_EQ(test, f->objects_allocated - f->objects_freed, owned);
	KUNIT_EXPECT_EQ(test, f->names_allocated - f->names_freed, owned);
	KUNIT_EXPECT_EQ(test, f->ids_allocated - f->ids_freed, owned);
	KUNIT_EXPECT_EQ(test, f->ownership_errors, 0U);
	KUNIT_EXPECT_EQ(test, wakeup_sysfs_sources_named(f->name), owned);
	for (i = 0; i < f->slots_used; i++)
		if (f->slots[i].id_live) {
			live_ids++;
			KUNIT_EXPECT_TRUE(test, ida_exists(&wakeup_ida, f->slots[i].id));
		}
	KUNIT_EXPECT_EQ(test, live_ids, owned);
}

static void wakeup_sysfs_exit(struct kunit *test)
{
	struct wakeup_sysfs_fixture *f = test->priv;

	wakeup_sysfs_cleanup(f);
	wakeup_sysfs_expect_owned(test, 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->release_count), 1);
}

static struct file *wakeup_sysfs_open(struct wakeup_sysfs_fixture *f, const char *name, int flags)
{
	char path[128];

	snprintf(path, sizeof(path), "devices/%s/power/wakeup", name);
	return file_open_root_mnt(f->mount, path, flags, 0);
}

static ssize_t wakeup_sysfs_write(struct wakeup_sysfs_fixture *f, const char *request)
{
	struct file *file = wakeup_sysfs_open(f, f->name, O_WRONLY);
	loff_t pos = 0;
	ssize_t result;

	if (IS_ERR(file))
		return PTR_ERR(file);
	result = kernel_write(file, request, strlen(request), &pos);
	__fput_sync(file);
	return result;
}

static bool wakeup_sysfs_readback(struct wakeup_sysfs_fixture *f, bool enabled)
{
	struct file *file = wakeup_sysfs_open(f, f->name, O_RDONLY);
	char buffer[16] = { };
	loff_t pos = 0;
	ssize_t result;

	if (IS_ERR(file))
		return false;
	result = kernel_read(file, buffer, sizeof(buffer) - 1, &pos);
	__fput_sync(file);
	return result > 0 && !strcmp(buffer, enabled ? "enabled\n" : "disabled\n");
}

static void sysfs_enable_test(struct kunit *test)
{
	struct wakeup_sysfs_fixture *f = test->priv;

	KUNIT_EXPECT_EQ(test, wakeup_sysfs_write(f, "enabled\n"), 8);
	KUNIT_EXPECT_TRUE(test, wakeup_sysfs_readback(f, true));
	wakeup_sysfs_expect_owned(test, 1);
}

static void sysfs_disable_test(struct kunit *test)
{
	struct wakeup_sysfs_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, wakeup_sysfs_write(f, "enabled\n"), 8);
	KUNIT_EXPECT_EQ(test, wakeup_sysfs_write(f, "disabled\n"), 9);
	KUNIT_EXPECT_TRUE(test, wakeup_sysfs_readback(f, false));
	wakeup_sysfs_expect_owned(test, 0);
	KUNIT_EXPECT_EQ(test, f->objects_allocated, 1U);
}

static void sysfs_enabled_idempotent_test(struct kunit *test)
{
	struct wakeup_sysfs_fixture *f = test->priv;
	struct wakeup_source *before;

	KUNIT_ASSERT_EQ(test, wakeup_sysfs_write(f, "enabled\n"), 8);
	before = wakeup_sysfs_attached(f);
	atomic_set(&f->fault, WAKEUP_SYSFS_OBJECT_FAULT);
	KUNIT_EXPECT_EQ(test, wakeup_sysfs_write(f, "enabled\n"), 8);
	KUNIT_EXPECT_PTR_EQ(test, wakeup_sysfs_attached(f), before);
	KUNIT_EXPECT_TRUE(test, wakeup_sysfs_readback(f, true));
	wakeup_sysfs_expect_owned(test, 1);
}

static void sysfs_disabled_idempotent_test(struct kunit *test)
{
	struct wakeup_sysfs_fixture *f = test->priv;

	KUNIT_EXPECT_EQ(test, wakeup_sysfs_write(f, "disabled\n"), 9);
	KUNIT_EXPECT_EQ(test, wakeup_sysfs_write(f, "disabled\n"), 9);
	KUNIT_EXPECT_TRUE(test, wakeup_sysfs_readback(f, false));
	wakeup_sysfs_expect_owned(test, 0);
}

struct wakeup_sysfs_incapable {
	struct device dev;
	atomic_t releases;
};

static void wakeup_sysfs_incapable_release(struct device *dev)
{
	struct wakeup_sysfs_incapable *d = container_of(dev, struct wakeup_sysfs_incapable, dev);

	atomic_inc(&d->releases);
}

static void sysfs_invalid_request_test(struct kunit *test)
{
	struct wakeup_sysfs_fixture *f = test->priv;
	struct wakeup_sysfs_incapable d = { };
	struct file *file = NULL;
	ssize_t result = 0;
	int ret, missing = 0;
	bool added = false;

	KUNIT_EXPECT_EQ(test, wakeup_sysfs_write(f, "Enabled\n"), -EINVAL);
	KUNIT_EXPECT_TRUE(test, wakeup_sysfs_readback(f, false));
	device_initialize(&d.dev);
	d.dev.release = wakeup_sysfs_incapable_release;
	atomic_set(&d.releases, 0);
	ret = dev_set_name(&d.dev, "%s-incapable", f->name);
	if (!ret)
		ret = device_add(&d.dev);
	if (!ret) {
		added = true;
		file = wakeup_sysfs_open(f, dev_name(&d.dev), O_WRONLY);
		missing = IS_ERR(file) ? PTR_ERR(file) : 0;
		if (!IS_ERR(file))
			__fput_sync(file);
		/* No real attribute exists: exercise the actual unchanged frontend. */
		result = wakeup_sysfs_kunit_store(&d.dev, "enabled\n", 8);
	}
	if (added)
		device_unregister(&d.dev);
	else
		put_device(&d.dev);
	KUNIT_EXPECT_EQ(test, ret, 0);
	KUNIT_EXPECT_EQ(test, missing, -ENOENT);
	KUNIT_EXPECT_EQ(test, result, -EINVAL);
	KUNIT_EXPECT_EQ(test, atomic_read(&d.releases), 1);
	wakeup_sysfs_expect_owned(test, 0);
}

static void wakeup_sysfs_error_test(struct kunit *test, int fault)
{
	struct wakeup_sysfs_fixture *f = test->priv;
	bool disabled;
	ssize_t result;

	atomic_set(&f->fault, fault);
	result = wakeup_sysfs_write(f, "enabled\n");
	disabled = wakeup_sysfs_readback(f, false);
	kunit_info(test, "fault-observation result=%zd disabled=%u hits=%d objects=%u names=%u ids=%u\n",
		   result, disabled, atomic_read(&f->fault_hits),
		   f->objects_allocated - f->objects_freed,
		   f->names_allocated - f->names_freed, f->ids_allocated - f->ids_freed);
	KUNIT_EXPECT_EQ(test, result, -ENOMEM);
	KUNIT_EXPECT_TRUE(test, disabled);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->fault_hits), 1);
	wakeup_sysfs_expect_owned(test, 0);
}

static void sysfs_object_alloc_error_test(struct kunit *test)
{
	wakeup_sysfs_error_test(test, WAKEUP_SYSFS_OBJECT_FAULT);
}

static void sysfs_name_alloc_error_test(struct kunit *test)
{
	wakeup_sysfs_error_test(test, WAKEUP_SYSFS_NAME_FAULT);
}

static void sysfs_id_alloc_error_test(struct kunit *test)
{
	wakeup_sysfs_error_test(test, WAKEUP_SYSFS_ID_FAULT);
}

static void sysfs_registration_error_test(struct kunit *test)
{
	wakeup_sysfs_error_test(test, WAKEUP_SYSFS_REGISTRATION_FAULT);
}

static int wakeup_sysfs_worker_run(void *data)
{
	struct wakeup_sysfs_worker *worker = data;
	struct wakeup_sysfs_fixture *f = worker->fixture;
	loff_t pos = 0;
	int index;

	switch (worker->operation) {
	case WAKEUP_SYSFS_UNREGISTER:
		device_unregister(&f->dev);
		f->registered = false;
		f->initialized = false;
		worker->result = 0;
		break;
	case WAKEUP_SYSFS_OBSERVE_SOURCE:
		/* This task holds the reader; the coordinator performs no I/O under it. */
		index = wakeup_sources_read_lock();
		worker->source = wakeup_sysfs_attached(f);
		complete(&f->observer_entered);
		wait_for_completion(&f->observer_release);
		wakeup_sources_read_unlock(index);
		worker->result = 0;
		break;
	case WAKEUP_SYSFS_FOREIGN_SOURCE:
		worker->source = wakeup_source_register(NULL, f->foreign_name);
		worker->result = worker->source ? 0 : -ENOMEM;
		wakeup_source_unregister(worker->source);
		break;
	case WAKEUP_SYSFS_DRAIN_CONTEXT:
		wakeup_sysfs_unpublish_context(f);
		worker->result = 0;
		break;
	case WAKEUP_SYSFS_WRITE:
		worker->result = kernel_write(worker->file, worker->request,
					      strlen(worker->request), &pos);
		break;
	}
	complete(&worker->finished);
	return 0;
}

static int wakeup_sysfs_start(struct wakeup_sysfs_worker *worker)
{
	init_completion(&worker->finished);
	worker->task = kthread_create(wakeup_sysfs_worker_run, worker, "neo-wakeup-sysfs");
	if (IS_ERR(worker->task)) {
		int ret = PTR_ERR(worker->task);

		worker->task = NULL;
		return ret;
	}
	/* Retain storage even when the operation finishes before the join. */
	get_task_struct(worker->task);
	wake_up_process(worker->task);
	return 0;
}

static void wakeup_sysfs_join(struct wakeup_sysfs_worker *worker)
{
	if (worker->task) {
		kthread_stop_put(worker->task);
		worker->task = NULL;
	}
}

static void sysfs_two_enables_test(struct kunit *test)
{
	struct wakeup_sysfs_fixture *f = test->priv;
	struct wakeup_sysfs_worker workers[2] = { };
	unsigned long entered[2] = { };
	int ret[2] = { -EINVAL, -EINVAL };
	unsigned int i;
	bool opened = true;

	for (i = 0; i < 2; i++) {
		workers[i].fixture = f;
		workers[i].request = "enabled\n";
		workers[i].file = wakeup_sysfs_open(f, f->name, O_WRONLY);
		if (IS_ERR(workers[i].file))
			opened = false;
	}
	if (!opened)
		goto restore;
	f->gate_attachment = true;
	for (i = 0; i < 2; i++)
		ret[i] = wakeup_sysfs_start(&workers[i]);
	for (i = 0; i < 2; i++)
		if (!ret[i])
			entered[i] = wait_for_completion_timeout(&f->gate_entered[i], WAKEUP_SYSFS_TIMEOUT);
restore:
	complete_all(&f->gate_release);
	for (i = 0; i < 2; i++) {
		wakeup_sysfs_join(&workers[i]);
		if (!IS_ERR_OR_NULL(workers[i].file))
			__fput_sync(workers[i].file);
	}
	f->gate_attachment = false;
	/* No assertion can return before every gate and started worker is restored. */
	KUNIT_EXPECT_TRUE(test, opened);
	for (i = 0; i < 2; i++) {
		KUNIT_EXPECT_EQ(test, ret[i], 0);
		KUNIT_EXPECT_NE(test, entered[i], 0UL);
		KUNIT_EXPECT_EQ(test, workers[i].result, 8);
	}
	KUNIT_EXPECT_EQ(test, atomic_read(&f->attach_entries), 2);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->duplicate_attaches), 1);
	KUNIT_EXPECT_EQ(test, f->objects_allocated, 2U);
	KUNIT_EXPECT_EQ(test, f->objects_freed, 1U);
	KUNIT_EXPECT_TRUE(test, wakeup_sysfs_readback(f, true));
	wakeup_sysfs_expect_owned(test, 1);
}

static void sysfs_disable_enable_srcu_test(struct kunit *test)
{
	struct wakeup_sysfs_fixture *f = test->priv;
	struct wakeup_sysfs_worker worker = { .fixture = f, .request = "disabled\n" };
	struct wakeup_sysfs_worker observer = { .fixture = f,
		.operation = WAKEUP_SYSFS_OBSERVE_SOURCE };
	struct wakeup_source *old = NULL, *new = NULL;
	unsigned long observed = 0, entered = 0;
	bool detached = false, blocked = false, old_alive = false;
	ssize_t enabled = -EINVAL;
	int observer_ret, ret = -EINVAL;

	KUNIT_ASSERT_EQ(test, wakeup_sysfs_write(f, "enabled\n"), 8);
	worker.file = wakeup_sysfs_open(f, f->name, O_WRONLY);
	KUNIT_ASSERT_FALSE(test, IS_ERR(worker.file));
	observer_ret = wakeup_sysfs_start(&observer);
	if (observer_ret)
		goto restore;
	observed = wait_for_completion_timeout(&f->observer_entered, WAKEUP_SYSFS_TIMEOUT);
	if (!observed)
		goto restore;
	old = observer.source;
	f->observe_srcu = true;
	ret = wakeup_sysfs_start(&worker);
	if (!ret) {
		entered = wait_for_completion_timeout(&f->srcu_entered, WAKEUP_SYSFS_TIMEOUT);
		if (entered) {
			detached = !wakeup_sysfs_attached(f);
			blocked = !completion_done(&worker.finished);
			old_alive = old && f->slots[0].object_live && ida_exists(&wakeup_ida, old->id);
			enabled = wakeup_sysfs_write(f, "enabled\n");
			new = wakeup_sysfs_attached(f);
		}
	}
restore:
	complete_all(&f->observer_release);
	wakeup_sysfs_join(&observer);
	wakeup_sysfs_join(&worker);
	__fput_sync(worker.file);
	f->observe_srcu = false;
	kunit_info(test, "srcu-observation observer=%lu detached=%u blocked=%u old-alive=%u enabled=%zd\n",
		   observed, detached, blocked, old_alive, enabled);
	KUNIT_EXPECT_EQ(test, observer_ret, 0);
	KUNIT_EXPECT_NE(test, observed, 0UL);
	KUNIT_EXPECT_EQ(test, ret, 0);
	KUNIT_EXPECT_NE(test, entered, 0UL);
	KUNIT_EXPECT_TRUE(test, detached);
	KUNIT_EXPECT_TRUE(test, blocked);
	KUNIT_EXPECT_TRUE(test, old_alive);
	KUNIT_EXPECT_EQ(test, enabled, 8);
	KUNIT_EXPECT_NOT_NULL(test, new);
	KUNIT_EXPECT_PTR_NE(test, new, old);
	KUNIT_EXPECT_PTR_EQ(test, wakeup_sysfs_attached(f), new);
	KUNIT_EXPECT_EQ(test, worker.result, 9);
	KUNIT_EXPECT_EQ(test, f->objects_allocated, 2U);
	KUNIT_EXPECT_EQ(test, f->objects_freed, 1U);
	KUNIT_EXPECT_TRUE(test, wakeup_sysfs_readback(f, true));
	wakeup_sysfs_expect_owned(test, 1);
}

static void wakeup_sysfs_expect_context_drain(struct kunit *test)
{
	struct wakeup_sysfs_fixture *f = test->priv;
	struct wakeup_sysfs_worker foreign = { .fixture = f,
		.operation = WAKEUP_SYSFS_FOREIGN_SOURCE };
	struct wakeup_sysfs_worker drain = { .fixture = f,
		.operation = WAKEUP_SYSFS_DRAIN_CONTEXT };
	unsigned long entered = 0, unpublished = 0, finished_early = 1;
	int foreign_ret, drain_ret = -EINVAL;

	/* The device and its tracked source have already been removed. */
	WRITE_ONCE(f->gate_foreign_allocation, true);
	foreign_ret = wakeup_sysfs_start(&foreign);
	if (!foreign_ret) {
		entered = wait_for_completion_timeout(&f->foreign_entered, WAKEUP_SYSFS_TIMEOUT);
		if (entered) {
			drain_ret = wakeup_sysfs_start(&drain);
			if (!drain_ret) {
				unpublished = wait_for_completion_timeout(&f->context_unpublished,
								 WAKEUP_SYSFS_TIMEOUT);
				if (unpublished)
					finished_early = wait_for_completion_timeout(&drain.finished,
									msecs_to_jiffies(20));
			}
		}
	}
	complete_all(&f->foreign_release);
	wakeup_sysfs_join(&foreign);
	wakeup_sysfs_join(&drain);
	WRITE_ONCE(f->gate_foreign_allocation, false);
	kunit_info(test, "context-observation entered=%lu unpublished=%lu finished-early=%lu foreign-result=%zd\n",
		   entered, unpublished, finished_early, foreign.result);
	/* Restore and join even on setup failure before reporting any expectation. */
	KUNIT_EXPECT_EQ(test, foreign_ret, 0);
	KUNIT_EXPECT_NE(test, entered, 0UL);
	KUNIT_EXPECT_EQ(test, drain_ret, 0);
	KUNIT_EXPECT_NE(test, unpublished, 0UL);
	KUNIT_EXPECT_EQ(test, finished_early, 0UL);
	KUNIT_EXPECT_EQ(test, foreign.result, 0);
	KUNIT_EXPECT_EQ(test, drain.result, 0);
	KUNIT_EXPECT_EQ(test, wakeup_sysfs_sources_named(f->foreign_name), 0U);
}

static void sysfs_unregister_active_write_test(struct kunit *test)
{
	struct wakeup_sysfs_fixture *f = test->priv;
	struct wakeup_sysfs_worker writer = { .fixture = f, .request = "enabled\n" };
	struct wakeup_sysfs_worker remover = { .fixture = f,
		.operation = WAKEUP_SYSFS_UNREGISTER };
	struct kernfs_node *node;
	unsigned long entered = 0, deadline;
	bool blocked = false;
	int writer_ret, remove_ret = -EINVAL, active = 0, released = -1;
	loff_t pos = 0;
	ssize_t after;

	writer.file = wakeup_sysfs_open(f, f->name, O_WRONLY);
	KUNIT_ASSERT_FALSE(test, IS_ERR(writer.file));
	node = kernfs_walk_and_get(f->dev.kobj.sd, "power/wakeup");
	if (!node) {
		__fput_sync(writer.file);
		KUNIT_FAIL(test, "Actual wakeup kernfs node absent");
		return;
	}
	f->gate_allocation = true;
	writer_ret = wakeup_sysfs_start(&writer);
	if (!writer_ret) {
		entered = wait_for_completion_timeout(&f->gate_entered[0], WAKEUP_SYSFS_TIMEOUT);
		if (entered) {
			remove_ret = wakeup_sysfs_start(&remover);
			deadline = jiffies + WAKEUP_SYSFS_TIMEOUT;
			while (!remove_ret && atomic_read(&node->active) >= 0 && time_before(jiffies, deadline))
				schedule_timeout_uninterruptible(1);
			active = atomic_read(&node->active);
			blocked = !completion_done(&remover.finished);
			released = atomic_read(&f->release_count);
		}
	}
	complete_all(&f->gate_release);
	wakeup_sysfs_join(&writer);
	wakeup_sysfs_join(&remover);
	f->gate_allocation = false;
	after = kernel_write(writer.file, "enabled\n", 8, &pos);
	__fput_sync(writer.file);
	kernfs_put(node);
	/* Include unrelated admitted hooks in the context-free boundary. */
	wakeup_sysfs_expect_context_drain(test);
	KUNIT_EXPECT_EQ(test, writer_ret, 0);
	KUNIT_EXPECT_NE(test, entered, 0UL);
	KUNIT_EXPECT_EQ(test, remove_ret, 0);
	KUNIT_EXPECT_EQ(test, active, KN_DEACTIVATED_BIAS + 1);
	KUNIT_EXPECT_TRUE(test, blocked);
	KUNIT_EXPECT_EQ(test, released, 0);
	KUNIT_EXPECT_EQ(test, writer.result, 8);
	KUNIT_EXPECT_EQ(test, remover.result, 0);
	KUNIT_EXPECT_EQ(test, after, -ENODEV);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->release_count), 1);
	wakeup_sysfs_expect_owned(test, 0);
}

static struct kunit_case wakeup_sysfs_cases[] = {
	KUNIT_CASE(sysfs_enable_test),
	KUNIT_CASE(sysfs_disable_test),
	KUNIT_CASE(sysfs_enabled_idempotent_test),
	KUNIT_CASE(sysfs_disabled_idempotent_test),
	KUNIT_CASE(sysfs_invalid_request_test),
	KUNIT_CASE(sysfs_object_alloc_error_test),
	KUNIT_CASE(sysfs_name_alloc_error_test),
	KUNIT_CASE(sysfs_id_alloc_error_test),
	KUNIT_CASE(sysfs_registration_error_test),
	KUNIT_CASE(sysfs_two_enables_test),
	KUNIT_CASE(sysfs_disable_enable_srcu_test),
	KUNIT_CASE(sysfs_unregister_active_write_test),
	{ }
};

static struct kunit_suite wakeup_sysfs_suite = {
	.name = "wakeup-sysfs",
	.init = wakeup_sysfs_init,
	.exit = wakeup_sysfs_exit,
	.test_cases = wakeup_sysfs_cases,
};
kunit_test_suite(wakeup_sysfs_suite);
