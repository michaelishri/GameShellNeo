// SPDX-License-Identifier: GPL-2.0-only
/* Real regmap/Maple, debugfs, driver removal and PM preparation under UML. */
#include <kunit/test.h>
#include <linux/completion.h>
#include <linux/delay.h>
#include <linux/file.h>
#include <linux/kthread.h>
#include <linux/mount.h>
#include <linux/platform_device.h>
#include <linux/suspend.h>
#include "../base/regmap/internal.h"
#include "axp223-control-diag.h"

struct control_fixture {
	struct kunit *test;
	struct regmap *map;
	struct platform_device *pdev;
	struct axp20x_rsb *chip;
	struct vfsmount *mount;
	unsigned int reads, writes, addresses[16];
	int failed_reg;
	bool block;
	struct completion entered, release;
};

static int control_bus_read(void *context, unsigned int reg, unsigned int *value)
{
	struct control_fixture *f = context;

	KUNIT_EXPECT_TRUE(f->test, reg == 0x33 || reg == 0x34);
	if (f->reads < ARRAY_SIZE(f->addresses))
		f->addresses[f->reads] = reg;
	f->reads++;
	if (READ_ONCE(f->block)) {
		WRITE_ONCE(f->block, false);
		complete(&f->entered);
		if (!wait_for_completion_timeout(&f->release, msecs_to_jiffies(5000)))
			return -ETIMEDOUT;
	}
	/* Poison the output even on failure; the wrapper must suppress it. */
	*value = reg == 0x33 ? 0xc6 : 0x45;
	return f->failed_reg == reg ? -EREMOTEIO : 0;
}

static int control_bus_write(void *context, unsigned int reg, unsigned int value)
{
	struct control_fixture *f = context;

	f->writes++;
	return -EACCES;
}

static const struct regmap_bus control_bus = {
	.reg_read = control_bus_read,
	.reg_write = control_bus_write,
};

static int control_probe(struct platform_device *pdev)
{
	struct control_fixture *f = *(struct control_fixture **)dev_get_platdata(&pdev->dev);

	f->chip = devm_kzalloc(&pdev->dev, sizeof(*f->chip), GFP_KERNEL);
	if (!f->chip)
		return -ENOMEM;
	f->chip->axp.dev = &pdev->dev;
	f->chip->axp.variant = AXP223_ID;
	f->chip->axp.regmap = f->map;
	platform_set_drvdata(pdev, &f->chip->axp);
	return axp223_control_init(f->chip, true);
}

static void control_remove(struct platform_device *pdev)
{
	axp223_control_remove(axp223_controls(&pdev->dev));
}

static struct platform_driver control_driver = {
	.probe = control_probe,
	.remove = control_remove,
	.driver = { .name = "axp223-control-kunit", .pm = &axp223_control_pm_ops },
};

static int control_init(struct kunit *test)
{
	struct control_fixture *f;
	struct file_system_type *fs;
	struct regmap_config config = {
		.reg_bits = 8, .val_bits = 8, .max_register = 0x34,
		.cache_type = REGCACHE_MAPLE,
	};
	int ret;

	f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	if (!f)
		return -ENOMEM;
	f->test = test;
	init_completion(&f->entered);
	init_completion(&f->release);
	f->map = regmap_init(NULL, &control_bus, f, &config);
	if (IS_ERR(f->map))
		return PTR_ERR(f->map);
	/* Prime software cache only, without a bus write. */
	regcache_cache_only(f->map, true);
	ret = regmap_write(f->map, 0x33, 0xa1);
	ret = ret ?: regmap_write(f->map, 0x34, 0xb2);
	regcache_cache_only(f->map, false);
	if (ret)
		goto map_out;
	ret = platform_driver_register(&control_driver);
	if (ret)
		goto map_out;
	f->pdev = platform_device_register_data(NULL, "axp223-control-kunit", -1, &f, sizeof(f));
	if (IS_ERR(f->pdev)) {
		ret = PTR_ERR(f->pdev);
		goto driver_out;
	}
	if (!f->pdev->dev.driver) {
		ret = -ENODEV;
		goto device_out;
	}
	fs = get_fs_type("debugfs");
	if (!fs) {
		ret = -ENODEV;
		goto device_out;
	}
	f->mount = kern_mount(fs);
	put_filesystem(fs);
	if (IS_ERR(f->mount)) {
		ret = PTR_ERR(f->mount);
		goto device_out;
	}
	test->priv = f;
	return 0;
device_out:
	platform_device_unregister(f->pdev);
driver_out:
	platform_driver_unregister(&control_driver);
map_out:
	regmap_exit(f->map);
	return ret;
}

static void control_exit(struct kunit *test)
{
	struct control_fixture *f = test->priv;

	complete_all(&f->release);
	platform_device_unregister(f->pdev);
	platform_driver_unregister(&control_driver);
	kern_unmount(f->mount);
	KUNIT_EXPECT_EQ(test, f->writes, 0);
	regmap_exit(f->map);
}

static struct file *control_open_file(struct control_fixture *f, int flags)
{
	return file_open_root_mnt(f->mount,
		"axp223-controls-axp223-control-kunit/snapshot", flags, 0);
}

static void control_snapshot_test(struct kunit *test)
{
	struct control_fixture *f = test->priv;
	struct axp223_control_snapshot snapshot = {};
	int i;

	KUNIT_ASSERT_EQ(test, axp223_control_capture(&f->chip->controls, &snapshot), 0);
	for (i = 0; i < 4; i++) {
		struct axp223_control_read *r = &snapshot.reads[i];

		KUNIT_EXPECT_EQ(test, r->reg, i < 2 ? 0x33 : 0x34);
		KUNIT_EXPECT_EQ(test, r->bypass, !!(i & 1));
		KUNIT_EXPECT_EQ(test, r->error, 0);
		KUNIT_EXPECT_EQ(test, r->value, ((unsigned int[]){0xa1, 0xc6, 0xb2, 0x45})[i]);
		KUNIT_EXPECT_LE(test, r->start_ns, r->end_ns);
		if (i)
			KUNIT_EXPECT_LE(test, snapshot.reads[i - 1].end_ns, r->start_ns);
	}
	KUNIT_EXPECT_EQ(test, f->reads, 2);
	KUNIT_EXPECT_EQ(test, f->addresses[0], 0x33);
	KUNIT_EXPECT_EQ(test, f->addresses[1], 0x34);
}

static void control_error_flags_test(struct kunit *test)
{
	struct control_fixture *f = test->priv;
	struct axp223_control_snapshot snapshot;
	unsigned int value;
	int mode, failure, i;

	/* Cache-only and bypass are mutually exclusive public API modes. */
	for (mode = 0; mode < 3; mode++)
	for (failure = 0; failure < 3; failure++) {
		bool only = mode == 1, bypass = mode == 2;

		regcache_cache_only(f->map, false);
		regcache_cache_bypass(f->map, false);
		regcache_cache_only(f->map, only);
		regcache_cache_bypass(f->map, bypass);
		f->failed_reg = failure ? 0x32 + failure : 0;
		f->reads = 0;
		KUNIT_ASSERT_EQ(test, axp223_control_capture(&f->chip->controls, &snapshot), 0);
		KUNIT_EXPECT_EQ(test, f->map->cache_only, !!only);
		KUNIT_EXPECT_EQ(test, f->map->cache_bypass, !!bypass);
		KUNIT_EXPECT_EQ(test, f->reads, bypass ? 4 : 2);
		for (i = 0; i < 4; i++) {
			bool bus_read = (i & 1) || bypass;
			int err = bus_read && f->failed_reg == snapshot.reads[i].reg ? -EREMOTEIO : 0;

			KUNIT_EXPECT_EQ(test, snapshot.reads[i].error, err);
			if (err)
				KUNIT_EXPECT_EQ(test, snapshot.reads[i].value, 0);
		}
		KUNIT_ASSERT_EQ(test, regcache_read(f->map, 0x33, &value), 0);
		KUNIT_EXPECT_EQ(test, value, 0xa1);
		KUNIT_ASSERT_EQ(test, regcache_read(f->map, 0x34, &value), 0);
		KUNIT_EXPECT_EQ(test, value, 0xb2);
	}
}

static void control_admission_test(struct kunit *test)
{
	struct control_fixture *f = test->priv;
	struct axp20x_rsb other = { .axp = { .variant = AXP221_ID } };
	struct axp223_control_snapshot snapshot;

	KUNIT_ASSERT_EQ(test, axp223_control_init(&other, true), 0);
	KUNIT_EXPECT_EQ(test, axp223_control_capture(&other.controls, &snapshot), -EOPNOTSUPP);
	other.axp.variant = AXP223_ID;
	KUNIT_ASSERT_EQ(test, axp223_control_init(&other, false), 0);
	KUNIT_EXPECT_EQ(test, axp223_control_capture(&other.controls, &snapshot), -EOPNOTSUPP);
	KUNIT_ASSERT_EQ(test, axp223_control_prepare(&f->pdev->dev), 0);
	KUNIT_EXPECT_EQ(test, axp223_control_capture(&f->chip->controls, &snapshot), -EBUSY);
	axp223_control_remove(&f->chip->controls);
	axp223_control_complete(&f->pdev->dev);
	KUNIT_EXPECT_EQ(test, axp223_control_capture(&f->chip->controls, &snapshot), -ENODEV);
	KUNIT_EXPECT_EQ(test, f->reads, 0);
}

struct control_job {
	struct control_fixture *f;
	struct completion started, done;
	struct axp223_control_snapshot snapshot;
	struct file *file;
	unsigned int value;
	int action, ret;
};

static int control_thread(void *arg)
{
	struct control_job *job = arg;
	unsigned int flags;

	complete(&job->started);
	switch (job->action) {
	case 0:
		job->ret = axp223_control_capture(&job->f->chip->controls, &job->snapshot);
		break;
	case 1:
		job->ret = regmap_read(job->f->map, 0x33, &job->value);
		break;
	case 2:
		flags = lock_system_sleep();
		job->ret = dpm_prepare(PMSG_SUSPEND);
		unlock_system_sleep(flags);
		break;
	case 3:
		job->file = control_open_file(job->f, O_RDONLY);
		job->ret = PTR_ERR_OR_ZERO(job->file);
		break;
	case 4:
		device_release_driver(&job->f->pdev->dev);
		break;
	}
	complete(&job->done);
	/* Keep task storage alive until the fixture joins with kthread_stop(). */
	for (;;) {
		set_current_state(TASK_INTERRUPTIBLE);
		if (kthread_should_stop())
			break;
		schedule();
	}
	__set_current_state(TASK_RUNNING);
	return 0;
}

static struct task_struct *control_start(struct control_job *job,
					 struct control_fixture *f, int action)
{
	job->f = f;
	job->action = action;
	init_completion(&job->started);
	init_completion(&job->done);
	return kthread_run(control_thread, job, "axp223-controls-test");
}

static void control_race(struct kunit *test, int action)
{
	struct control_fixture *f = test->priv;
	struct control_job *first, *second;
	struct task_struct *reader, *contender;
	struct axp223_control_snapshot snapshot;
	struct file *file;
	unsigned int flags, count;

	first = kunit_kzalloc(test, sizeof(*first), GFP_KERNEL);
	second = kunit_kzalloc(test, sizeof(*second), GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, first);
	KUNIT_ASSERT_NOT_NULL(test, second);
	f->block = true;
	reader = control_start(first, f, action == 4 ? 3 : 0);
	KUNIT_ASSERT_FALSE(test, IS_ERR(reader));
	if (!wait_for_completion_timeout(&f->entered, msecs_to_jiffies(1000))) {
		KUNIT_FAIL(test, "reader did not enter bus");
		goto reader_out;
	}
	contender = control_start(second, f, action);
	if (IS_ERR(contender)) {
		KUNIT_FAIL(test, "contender could not start");
		goto reader_out;
	}
	KUNIT_EXPECT_NE(test, wait_for_completion_timeout(&second->started, HZ), 0);
	KUNIT_EXPECT_EQ(test, wait_for_completion_timeout(&second->done, msecs_to_jiffies(20)), 0);
	complete_all(&f->release);
	KUNIT_EXPECT_EQ(test, kthread_stop(reader), 0);
	KUNIT_EXPECT_EQ(test, kthread_stop(contender), 0);
	KUNIT_EXPECT_EQ(test, first->ret, 0);
	KUNIT_EXPECT_EQ(test, second->ret, 0);
	count = f->reads;
	if (action == 1) {
		KUNIT_EXPECT_EQ(test, second->value, 0xa1);
		KUNIT_EXPECT_EQ(test, count, 2);
	} else if (action == 2) {
		KUNIT_EXPECT_EQ(test, axp223_control_capture(&f->chip->controls, &snapshot), -EBUSY);
		file = control_open_file(f, O_RDONLY);
		KUNIT_EXPECT_EQ(test, PTR_ERR_OR_ZERO(file), -EBUSY);
		if (!IS_ERR(file))
			__fput_sync(file);
		KUNIT_EXPECT_EQ(test, f->reads, count);
		flags = lock_system_sleep();
		dpm_complete(PMSG_RESUME);
		unlock_system_sleep(flags);
		KUNIT_EXPECT_EQ(test, axp223_control_capture(&f->chip->controls, &snapshot), 0);
	} else {
		/* Devres has freed chip: release may touch only the per-open record. */
		if (!IS_ERR_OR_NULL(first->file))
			__fput_sync(first->file);
		file = control_open_file(f, O_RDONLY);
		KUNIT_EXPECT_EQ(test, PTR_ERR_OR_ZERO(file), -ENOENT);
		if (!IS_ERR(file))
			__fput_sync(file);
		KUNIT_EXPECT_EQ(test, f->reads, count);
	}
	return;
reader_out:
	complete_all(&f->release);
	kthread_stop(reader);
	if (action == 4 && !IS_ERR_OR_NULL(first->file))
		__fput_sync(first->file);
}

static void control_map_lock_test(struct kunit *test) { control_race(test, 1); }
static void control_pm_core_test(struct kunit *test) { control_race(test, 2); }
static void control_remove_test(struct kunit *test) { control_race(test, 4); }

static void control_file_test(struct kunit *test)
{
	struct control_fixture *f = test->priv;
	struct axp223_control_snapshot *snapshot;
	struct file *file = control_open_file(f, O_WRONLY);

	KUNIT_EXPECT_EQ(test, PTR_ERR_OR_ZERO(file), -EACCES);
	if (!IS_ERR(file))
		__fput_sync(file);
	KUNIT_EXPECT_EQ(test, f->reads, 0);
	f->failed_reg = 0x34;
	file = control_open_file(f, O_RDONLY);
	KUNIT_ASSERT_FALSE(test, IS_ERR(file));
	snapshot = file->private_data;
	KUNIT_EXPECT_NOT_NULL(test, strstr(snapshot->text, "\"mode\":\"normal\""));
	KUNIT_EXPECT_NOT_NULL(test, strstr(snapshot->text, "\"mode\":\"bypass\""));
	KUNIT_EXPECT_NOT_NULL(test, strstr(snapshot->text, "\"value\":null"));
	KUNIT_EXPECT_LT(test, snapshot->length, sizeof(snapshot->text));
	KUNIT_EXPECT_EQ(test, f->reads, 2);
	__fput_sync(file);
}

static struct kunit_case control_cases[] = {
	KUNIT_CASE(control_snapshot_test),
	KUNIT_CASE(control_error_flags_test),
	KUNIT_CASE(control_admission_test),
	KUNIT_CASE(control_map_lock_test),
	KUNIT_CASE(control_pm_core_test),
	KUNIT_CASE(control_remove_test),
	KUNIT_CASE(control_file_test),
	{}
};

static struct kunit_suite control_suite = {
	.name = "axp223-controls", .init = control_init, .exit = control_exit,
	.test_cases = control_cases,
};
kunit_test_suite(control_suite);
MODULE_LICENSE("GPL");
