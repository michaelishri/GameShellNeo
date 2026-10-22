// SPDX-License-Identifier: GPL-2.0
/* Test-only append to musb_core.c: Linux owns the complete device-PM walk. */
#include <kunit/test.h>
#include <linux/gfp.h>
#include <linux/irq.h>
#include <linux/irqdesc.h>
#include <linux/string.h>
#include <linux/suspend.h>
#include <linux/unaligned.h>

struct wake_dpm_calls {
	unsigned int prepare, suspend, late, noirq, resume_noirq, early, resume;
	unsigned int complete, runtime_resume;
};

struct wake_dpm_state {
	int usage, runtime_status, runtime_error;
	unsigned int runtime_depth, references, irq_depth;
	bool prepared, suspended, late, noirq, wake, armed, disabled;
	gfp_t gfp_mask;
};

struct wake_dpm_fixture {
	struct musb musb;
	struct musb_hdrc_config config;
	struct device device;
	struct kunit *test;
	struct wake_dpm_calls calls;
	int irq, arm_error, disarm_error, runtime_error;
	int prepare_error, late_error, noirq_error, suspend_result, resume_result;
	int prepare_usage, complete_usage;
	unsigned int arms, disarms, disables, enables, mmio;
	unsigned int owner_calls, peer_calls;
	bool initialized, added, released, owner_action, peer_action, peer_wake;
	bool accessors_changed;
	u8 registers[256];
	u8 (*old_readb)(void __iomem *, u32);
	u8 (*old_clearb)(void __iomem *, u32);
	void (*old_writeb)(void __iomem *, u32, u8);
	u16 (*old_readw)(void __iomem *, u32);
	u16 (*old_clearw)(void __iomem *, u32);
	void (*old_writew)(void __iomem *, u32, u16);
};

struct wake_dpm_walk {
	struct wake_dpm_state before, after_start, after_end, after;
	int start_result, end_result;
	bool end_called, resume_start_called;
};

static struct wake_dpm_fixture *wake_dpm_from_device(struct device *dev)
{
	return container_of(dev, struct wake_dpm_fixture, device);
}

static struct wake_dpm_fixture *wake_dpm_registers(void __iomem *base)
{
	return container_of((u8 __force *)base, struct wake_dpm_fixture, registers[0]);
}

/* Register reads/writes and the irqchip are the simulated hardware boundary. */
static u8 wake_dpm_readb(void __iomem *base, u32 offset)
{
	wake_dpm_registers(base)->mmio++;
	return ((u8 __force *)base)[offset];
}

static void wake_dpm_writeb(void __iomem *base, u32 offset, u8 value)
{
	wake_dpm_registers(base)->mmio++;
	((u8 __force *)base)[offset] = value;
}

static u16 wake_dpm_readw(void __iomem *base, u32 offset)
{
	wake_dpm_registers(base)->mmio++;
	return get_unaligned_le16((u8 __force *)base + offset);
}

static void wake_dpm_writew(void __iomem *base, u32 offset, u16 value)
{
	wake_dpm_registers(base)->mmio++;
	put_unaligned_le16(value, (u8 __force *)base + offset);
}

static int wake_dpm_chip_set_wake(struct irq_data *data, unsigned int on)
{
	struct wake_dpm_fixture *f = irq_data_get_irq_chip_data(data);

	if (on) {
		f->arms++;
		return f->arm_error;
	}
	f->disarms++;
	return f->disarm_error;
}

static void wake_dpm_chip_mask(struct irq_data *data) { }
static void wake_dpm_chip_unmask(struct irq_data *data) { }

static struct irq_chip wake_dpm_chip = {
	.name = "musb-wake-dpm-kunit",
	.irq_mask = wake_dpm_chip_mask,
	.irq_unmask = wake_dpm_chip_unmask,
	.irq_set_wake = wake_dpm_chip_set_wake,
};

static irqreturn_t wake_dpm_owner_handler(int irq, void *data)
{
	struct wake_dpm_fixture *f = data;

	f->owner_calls++;
	return IRQ_HANDLED;
}

static irqreturn_t wake_dpm_peer_handler(int irq, void *data)
{
	struct wake_dpm_fixture *f = container_of(data, struct wake_dpm_fixture, peer_calls);

	f->peer_calls++;
	return IRQ_HANDLED;
}

static void wake_dpm_platform_disable(struct musb *musb)
{
	container_of(musb, struct wake_dpm_fixture, musb)->disables++;
}

static void wake_dpm_platform_enable(struct musb *musb)
{
	container_of(musb, struct wake_dpm_fixture, musb)->enables++;
}

static const struct musb_platform_ops wake_dpm_platform_ops = {
	.quirks = MUSB_NO_ULPI_BUSCONTROL,
	.disable = wake_dpm_platform_disable,
	.enable = wake_dpm_platform_enable,
};

static int wake_dpm_prepare(struct device *dev)
{
	struct wake_dpm_fixture *f = wake_dpm_from_device(dev);

	f->calls.prepare++;
	f->prepare_usage = atomic_read(&dev->power.usage_count);
	return f->prepare_error;
}

static int wake_dpm_suspend(struct device *dev)
{
	struct wake_dpm_fixture *f = wake_dpm_from_device(dev);

	f->calls.suspend++;
	f->suspend_result = musb_suspend(dev);
	return f->suspend_result;
}

static int wake_dpm_late(struct device *dev)
{
	struct wake_dpm_fixture *f = wake_dpm_from_device(dev);

	f->calls.late++;
	return f->late_error;
}

static int wake_dpm_noirq(struct device *dev)
{
	struct wake_dpm_fixture *f = wake_dpm_from_device(dev);

	f->calls.noirq++;
	return f->noirq_error;
}

static int wake_dpm_resume_noirq(struct device *dev)
{
	wake_dpm_from_device(dev)->calls.resume_noirq++;
	return 0;
}

static int wake_dpm_early(struct device *dev)
{
	wake_dpm_from_device(dev)->calls.early++;
	return 0;
}

static int wake_dpm_resume(struct device *dev)
{
	struct wake_dpm_fixture *f = wake_dpm_from_device(dev);

	f->calls.resume++;
	f->resume_result = musb_resume(dev);
	return f->resume_result;
}

static void wake_dpm_complete(struct device *dev)
{
	struct wake_dpm_fixture *f = wake_dpm_from_device(dev);

	f->calls.complete++;
	f->complete_usage = atomic_read(&dev->power.usage_count);
}

static int wake_dpm_runtime_resume(struct device *dev)
{
	struct wake_dpm_fixture *f = wake_dpm_from_device(dev);

	f->calls.runtime_resume++;
	return f->runtime_error;
}

static const struct dev_pm_ops wake_dpm_ops = {
	.prepare = wake_dpm_prepare,
	.complete = wake_dpm_complete,
	.suspend = wake_dpm_suspend,
	.resume = wake_dpm_resume,
	.suspend_late = wake_dpm_late,
	.resume_early = wake_dpm_early,
	.suspend_noirq = wake_dpm_noirq,
	.resume_noirq = wake_dpm_resume_noirq,
	.runtime_resume = wake_dpm_runtime_resume,
};

static const struct device_type wake_dpm_device_type = {
	.name = "musb-wake-dpm-test",
	.pm = &wake_dpm_ops,
};

static struct wake_dpm_state wake_dpm_snapshot(struct wake_dpm_fixture *f)
{
	struct irq_desc *desc = irq_to_desc(f->irq);
	struct device *dev = &f->device;
	struct wake_dpm_state state;
	unsigned long flags;

	state.usage = atomic_read(&dev->power.usage_count);
	state.runtime_status = dev->power.runtime_status;
	state.runtime_error = dev->power.runtime_error;
	state.runtime_depth = dev->power.disable_depth;
	state.prepared = dev->power.is_prepared;
	state.suspended = dev->power.is_suspended;
	state.late = dev->power.is_late_suspended;
	state.noirq = dev->power.is_noirq_suspended;
	state.gfp_mask = gfp_allowed_mask;
	raw_spin_lock_irqsave(&desc->lock, flags);
	state.references = desc->wake_depth;
	state.irq_depth = desc->depth;
	state.wake = irqd_is_wakeup_set(&desc->irq_data);
	state.armed = irqd_is_wakeup_armed(&desc->irq_data);
	state.disabled = irqd_irq_disabled(&desc->irq_data);
	raw_spin_unlock_irqrestore(&desc->lock, flags);
	return state;
}

static void wake_dpm_release(struct device *dev)
{
	wake_dpm_from_device(dev)->released = true;
}

static void wake_dpm_unused_work(struct work_struct *work) { }

static void wake_dpm_cleanup(void *data)
{
	struct wake_dpm_fixture *f = data;

	/* Observe original errors/debt in the test before clearing artificial errors
	 * to release this disposable fixture. This is no driver recovery policy.
	 */
	f->arm_error = 0;
	f->disarm_error = 0;
	f->runtime_error = 0;
	if (f->initialized) {
		musb_cleanup_wakeup(&f->musb);
		if (f->peer_wake)
			KUNIT_EXPECT_EQ(f->test, disable_irq_wake(f->irq), 0);
		if (f->irq >= 0)
			KUNIT_EXPECT_EQ(f->test, wake_dpm_snapshot(f).references, 0U);
		device_init_wakeup(&f->device, false);
		pm_runtime_disable(&f->device);
		pm_runtime_dont_use_autosuspend(&f->device);
		while (atomic_read(&f->device.power.usage_count) > 0)
			pm_runtime_put_noidle(&f->device);
	}
	if (f->peer_action)
		free_irq(f->irq, &f->peer_calls);
	if (f->owner_action)
		free_irq(f->irq, f);
	if (f->irq >= 0) {
		irq_set_chip_and_handler(f->irq, NULL, NULL);
		irq_set_chip_data(f->irq, NULL);
		irq_free_descs(f->irq, 1);
	}
	cancel_delayed_work_sync(&f->musb.irq_work);
	cancel_delayed_work_sync(&f->musb.gadget_work);
	if (f->accessors_changed) {
		musb_readb = f->old_readb;
		musb_writeb = f->old_writeb;
		musb_clearb = f->old_clearb;
		musb_readw = f->old_readw;
		musb_writew = f->old_writew;
		musb_clearw = f->old_clearw;
	}
	if (f->added)
		device_unregister(&f->device);
	else if (f->initialized)
		put_device(&f->device);
	if (f->initialized)
		KUNIT_EXPECT_TRUE(f->test, f->released);
}

static int wake_dpm_fixture_init(struct kunit *test)
{
	struct wake_dpm_fixture *f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	int ret;

	if (!f)
		return -ENOMEM;
	test->priv = f;
	f->test = test;
	f->irq = -1;
	spin_lock_init(&f->musb.lock);
	spin_lock_init(&f->musb.list_lock);
	INIT_LIST_HEAD(&f->musb.pending_list);
	INIT_DELAYED_WORK(&f->musb.irq_work, wake_dpm_unused_work);
	INIT_DELAYED_WORK(&f->musb.gadget_work, wake_dpm_unused_work);
	ret = kunit_add_action_or_reset(test, wake_dpm_cleanup, f);
	if (ret)
		return ret;
	device_initialize(&f->device);
	f->initialized = true;
	f->device.release = wake_dpm_release;
	/* device_pm_add caches no_pm_callbacks during device_add. */
	f->device.type = &wake_dpm_device_type;
	f->musb.controller = &f->device;
	dev_set_drvdata(&f->device, &f->musb);
	ret = dev_set_name(&f->device, "musb-wake-dpm-kunit");
	if (ret)
		return ret;
	ret = device_add(&f->device);
	if (ret)
		return ret;
	f->added = true;
	f->musb.config = &f->config;
	f->musb.ops = &wake_dpm_platform_ops;
	f->musb.port_mode = MUSB_PERIPHERAL;
	f->musb.g.speed = USB_SPEED_UNKNOWN;
	f->musb.mregs = (void __iomem *)f->registers;
	ret = pm_runtime_set_active(&f->device);
	if (ret)
		return ret;
	pm_runtime_set_autosuspend_delay(&f->device, 500);
	pm_runtime_use_autosuspend(&f->device);
	pm_runtime_get_noresume(&f->device); /* Foreign reference held across each walk. */
	pm_runtime_enable(&f->device);
	f->irq = irq_alloc_descs(-1, 1, 1, NUMA_NO_NODE);
	if (f->irq < 0)
		return f->irq;
	f->musb.nIrq = f->irq;
	ret = irq_set_chip_data(f->irq, f);
	if (ret)
		return ret;
	irq_set_chip_and_handler(f->irq, &wake_dpm_chip, handle_level_irq);
	irq_clear_status_flags(f->irq, IRQ_NOREQUEST | IRQ_NOPROBE);
	irq_set_status_flags(f->irq, IRQ_LEVEL);
	ret = request_irq(f->irq, wake_dpm_owner_handler, IRQF_SHARED, "musb-dpm-owner", f);
	if (ret)
		return ret;
	f->owner_action = true;
	ret = request_irq(f->irq, wake_dpm_peer_handler, IRQF_SHARED, "musb-dpm-peer", &f->peer_calls);
	if (ret)
		return ret;
	f->peer_action = true;
	f->old_readb = musb_readb;
	f->old_writeb = musb_writeb;
	f->old_clearb = musb_clearb;
	f->old_readw = musb_readw;
	f->old_writew = musb_writew;
	f->old_clearw = musb_clearw;
	musb_readb = wake_dpm_readb;
	musb_writeb = wake_dpm_writeb;
	musb_clearb = wake_dpm_readb;
	musb_readw = wake_dpm_readw;
	musb_writew = wake_dpm_writew;
	musb_clearw = wake_dpm_readw;
	f->accessors_changed = true;
	ret = musb_init_wakeup(&f->musb);
	if (ret)
		return ret;
	return device_set_wakeup_enable(&f->device, false);
}

static struct wake_dpm_walk wake_dpm_run(struct wake_dpm_fixture *f)
{
	struct wake_dpm_walk walk = {};
	unsigned int flags = lock_system_sleep();

	walk.before = wake_dpm_snapshot(f);
	walk.start_result = dpm_suspend_start(PMSG_SUSPEND);
	walk.after_start = wake_dpm_snapshot(f);
	if (!walk.start_result) {
		walk.end_called = true;
		walk.end_result = dpm_suspend_end(PMSG_SUSPEND);
		walk.after_end = wake_dpm_snapshot(f);
		if (!walk.end_result) {
			walk.resume_start_called = true;
			dpm_resume_start(PMSG_RESUME);
		}
		/* Failed late/noirq paths already perform their matching early unwind. */
	}
	/* Match every started walk, including failed prepare, with complete/GFP restore.
	 * No KUnit assertion or allocation may bypass this restoration.
	 */
	dpm_resume_end(PMSG_RESUME);
	walk.after = wake_dpm_snapshot(f);
	unlock_system_sleep(flags);
	return walk;
}

static void wake_dpm_expect_restored(struct kunit *test, struct wake_dpm_fixture *f,
				    const struct wake_dpm_walk *walk, unsigned int references)
{
	KUNIT_EXPECT_EQ(test, walk->before.usage, 1);
	KUNIT_EXPECT_EQ(test, walk->after.usage, walk->before.usage);
	KUNIT_EXPECT_EQ(test, walk->after.runtime_depth, walk->before.runtime_depth);
	KUNIT_EXPECT_EQ(test, walk->after.runtime_status, walk->before.runtime_status);
	KUNIT_EXPECT_EQ(test, walk->after.gfp_mask, walk->before.gfp_mask);
	KUNIT_EXPECT_FALSE(test, walk->after.prepared);
	KUNIT_EXPECT_FALSE(test, walk->after.suspended);
	KUNIT_EXPECT_FALSE(test, walk->after.late);
	KUNIT_EXPECT_FALSE(test, walk->after.noirq);
	KUNIT_EXPECT_FALSE(test, walk->after.armed);
	KUNIT_EXPECT_EQ(test, walk->after.irq_depth, walk->before.irq_depth);
	KUNIT_EXPECT_EQ(test, walk->after.disabled, walk->before.disabled);
	KUNIT_EXPECT_EQ(test, walk->after.references, references);
	KUNIT_EXPECT_EQ(test, walk->after.wake, references != 0);
	KUNIT_EXPECT_EQ(test, f->calls.prepare, 1U);
	KUNIT_EXPECT_EQ(test, f->prepare_usage, walk->before.usage + 1);
	KUNIT_EXPECT_EQ(test, generic_handle_irq_safe(f->irq), 0);
	KUNIT_EXPECT_EQ(test, f->owner_calls, 1U);
	KUNIT_EXPECT_EQ(test, f->peer_calls, 1U);
}

static void wake_dpm_expect_suspended(struct kunit *test, struct wake_dpm_fixture *f,
				     const struct wake_dpm_walk *walk)
{
	KUNIT_EXPECT_EQ(test, walk->start_result, 0);
	KUNIT_EXPECT_TRUE(test, walk->end_called);
	KUNIT_EXPECT_EQ(test, f->calls.suspend, 1U);
	KUNIT_EXPECT_EQ(test, f->suspend_result, 0);
	KUNIT_EXPECT_EQ(test, walk->after_start.usage, walk->before.usage + 2);
	KUNIT_EXPECT_TRUE(test, walk->after_start.prepared);
	KUNIT_EXPECT_TRUE(test, walk->after_start.suspended);
	/* This observes precisely dpm_suspend_start's restriction, not platform sleep. */
	KUNIT_EXPECT_EQ(test, walk->after_start.gfp_mask,
		       walk->before.gfp_mask & ~(__GFP_IO | __GFP_FS));
	KUNIT_EXPECT_EQ(test, f->calls.resume, 1U);
	KUNIT_EXPECT_EQ(test, f->calls.complete, 1U);
	KUNIT_EXPECT_EQ(test, f->complete_usage, walk->before.usage + 1);
}

static void wake_dpm_expect_full_cycle(struct kunit *test, struct wake_dpm_fixture *f,
				      const struct wake_dpm_walk *walk, bool wake)
{
	wake_dpm_expect_suspended(test, f, walk);
	KUNIT_EXPECT_EQ(test, walk->end_result, 0);
	KUNIT_EXPECT_TRUE(test, walk->resume_start_called);
	KUNIT_EXPECT_EQ(test, f->calls.late, 1U);
	KUNIT_EXPECT_EQ(test, f->calls.noirq, 1U);
	KUNIT_EXPECT_EQ(test, f->calls.resume_noirq, 1U);
	KUNIT_EXPECT_EQ(test, f->calls.early, 1U);
	KUNIT_EXPECT_TRUE(test, walk->after_end.late);
	KUNIT_EXPECT_TRUE(test, walk->after_end.noirq);
	KUNIT_EXPECT_EQ(test, walk->after_end.runtime_depth, walk->before.runtime_depth + 1);
	KUNIT_EXPECT_EQ(test, walk->after_end.armed, wake);
	KUNIT_EXPECT_EQ(test, walk->after_end.disabled, !wake);
	KUNIT_EXPECT_EQ(test, walk->after_end.references, wake ? 1U : 0U);
}

static void dpm_policy_disabled_test(struct kunit *test)
{
	struct wake_dpm_fixture *f = test->priv;
	struct wake_dpm_walk walk = wake_dpm_run(f);

	wake_dpm_expect_restored(test, f, &walk, 0);
	wake_dpm_expect_full_cycle(test, f, &walk, false);
	KUNIT_EXPECT_EQ(test, f->resume_result, 0);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
}

static void dpm_policy_enabled_test(struct kunit *test)
{
	struct wake_dpm_fixture *f = test->priv;
	struct wake_dpm_walk walk;

	KUNIT_ASSERT_EQ(test, device_set_wakeup_enable(&f->device, true), 0);
	walk = wake_dpm_run(f);
	wake_dpm_expect_restored(test, f, &walk, 0);
	wake_dpm_expect_full_cycle(test, f, &walk, true);
	KUNIT_EXPECT_EQ(test, f->resume_result, 0);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
}

static void dpm_shared_peer_test(struct kunit *test)
{
	struct wake_dpm_fixture *f = test->priv;
	struct wake_dpm_walk walk;

	KUNIT_ASSERT_EQ(test, enable_irq_wake(f->irq), 0);
	f->peer_wake = true;
	walk = wake_dpm_run(f);
	wake_dpm_expect_restored(test, f, &walk, 1);
	wake_dpm_expect_full_cycle(test, f, &walk, true);
	KUNIT_EXPECT_EQ(test, f->resume_result, 0);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
}

static void dpm_prepare_error_test(struct kunit *test)
{
	struct wake_dpm_fixture *f = test->priv;
	struct wake_dpm_walk walk;

	f->prepare_error = -EIO;
	walk = wake_dpm_run(f);
	wake_dpm_expect_restored(test, f, &walk, 0);
	KUNIT_EXPECT_EQ(test, walk.start_result, -EIO);
	KUNIT_EXPECT_FALSE(test, walk.end_called);
	KUNIT_EXPECT_FALSE(test, walk.resume_start_called);
	KUNIT_EXPECT_EQ(test, walk.after_start.usage, walk.before.usage);
	KUNIT_EXPECT_EQ(test, walk.after_start.gfp_mask, walk.before.gfp_mask);
	KUNIT_EXPECT_EQ(test, f->calls.suspend, 0U);
	KUNIT_EXPECT_EQ(test, f->calls.resume, 0U);
	KUNIT_EXPECT_EQ(test, f->calls.complete, 0U);
}

static void wake_dpm_expect_start_error(struct kunit *test, struct wake_dpm_fixture *f,
				       const struct wake_dpm_walk *walk)
{
	wake_dpm_expect_restored(test, f, walk, 0);
	KUNIT_EXPECT_EQ(test, walk->start_result, -EIO);
	KUNIT_EXPECT_FALSE(test, walk->end_called);
	KUNIT_EXPECT_FALSE(test, walk->resume_start_called);
	KUNIT_EXPECT_EQ(test, f->suspend_result, -EIO);
	KUNIT_EXPECT_EQ(test, f->calls.suspend, 1U);
	KUNIT_EXPECT_EQ(test, f->calls.late, 0U);
	KUNIT_EXPECT_EQ(test, f->calls.noirq, 0U);
	KUNIT_EXPECT_EQ(test, f->calls.resume, 0U);
	KUNIT_EXPECT_EQ(test, f->calls.complete, 1U);
	KUNIT_EXPECT_EQ(test, walk->after_start.usage, walk->before.usage + 1);
	KUNIT_EXPECT_EQ(test, f->complete_usage, walk->before.usage + 1);
	KUNIT_EXPECT_EQ(test, f->disables, 0U);
	KUNIT_EXPECT_EQ(test, f->mmio, 0U);
}

static void dpm_arm_error_test(struct kunit *test)
{
	struct wake_dpm_fixture *f = test->priv;
	struct wake_dpm_walk walk;

	KUNIT_ASSERT_EQ(test, device_set_wakeup_enable(&f->device, true), 0);
	f->arm_error = -EIO;
	walk = wake_dpm_run(f);
	wake_dpm_expect_start_error(test, f, &walk);
	KUNIT_EXPECT_EQ(test, f->arms, 2U);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
}

static void dpm_runtime_resume_error_test(struct kunit *test)
{
	struct wake_dpm_fixture *f = test->priv;
	struct wake_dpm_walk walk;

	pm_runtime_disable(&f->device);
	KUNIT_ASSERT_EQ(test, pm_runtime_set_suspended(&f->device), 0);
	f->runtime_error = -EIO;
	pm_runtime_enable(&f->device);
	walk = wake_dpm_run(f);
	wake_dpm_expect_start_error(test, f, &walk);
	KUNIT_EXPECT_EQ(test, f->calls.runtime_resume, 1U);
	KUNIT_EXPECT_EQ(test, walk.after.runtime_error, -EIO);
	KUNIT_EXPECT_EQ(test, f->arms, 1U);
}

static void dpm_late_error_test(struct kunit *test)
{
	struct wake_dpm_fixture *f = test->priv;
	struct wake_dpm_walk walk;

	KUNIT_ASSERT_EQ(test, device_set_wakeup_enable(&f->device, true), 0);
	f->late_error = -EIO;
	walk = wake_dpm_run(f);
	wake_dpm_expect_restored(test, f, &walk, 0);
	wake_dpm_expect_suspended(test, f, &walk);
	KUNIT_EXPECT_EQ(test, walk.end_result, -EIO);
	KUNIT_EXPECT_FALSE(test, walk.resume_start_called);
	KUNIT_EXPECT_EQ(test, f->calls.late, 1U);
	KUNIT_EXPECT_EQ(test, f->calls.noirq, 0U);
	KUNIT_EXPECT_EQ(test, f->calls.resume_noirq, 0U);
	KUNIT_EXPECT_EQ(test, f->calls.early, 0U);
	KUNIT_EXPECT_EQ(test, f->resume_result, 0);
}

static void dpm_noirq_error_test(struct kunit *test)
{
	struct wake_dpm_fixture *f = test->priv;
	struct wake_dpm_walk walk;

	KUNIT_ASSERT_EQ(test, device_set_wakeup_enable(&f->device, true), 0);
	f->noirq_error = -EIO;
	walk = wake_dpm_run(f);
	wake_dpm_expect_restored(test, f, &walk, 0);
	wake_dpm_expect_suspended(test, f, &walk);
	KUNIT_EXPECT_EQ(test, walk.end_result, -EIO);
	KUNIT_EXPECT_FALSE(test, walk.resume_start_called);
	KUNIT_EXPECT_EQ(test, f->calls.late, 1U);
	KUNIT_EXPECT_EQ(test, f->calls.noirq, 1U);
	KUNIT_EXPECT_EQ(test, f->calls.resume_noirq, 0U);
	KUNIT_EXPECT_EQ(test, f->calls.early, 1U);
	KUNIT_EXPECT_FALSE(test, walk.after_end.armed);
	KUNIT_EXPECT_EQ(test, walk.after_end.runtime_depth, walk.before.runtime_depth);
	KUNIT_EXPECT_EQ(test, f->resume_result, 0);
}

static void dpm_resume_disarm_error_test(struct kunit *test)
{
	struct wake_dpm_fixture *f = test->priv;
	struct wake_dpm_walk walk;

	KUNIT_ASSERT_EQ(test, device_set_wakeup_enable(&f->device, true), 0);
	f->disarm_error = -EIO;
	walk = wake_dpm_run(f);
	wake_dpm_expect_restored(test, f, &walk, 1);
	wake_dpm_expect_full_cycle(test, f, &walk, true);
	/* dpm_resume_end is void; capture the actual callback error and retained debt. */
	KUNIT_EXPECT_EQ(test, f->resume_result, -EIO);
	KUNIT_EXPECT_TRUE(test, f->musb.irq_wake);
	KUNIT_EXPECT_EQ(test, f->disarms, 2U);
}

static struct kunit_case wake_dpm_cases[] = {
	KUNIT_CASE(dpm_policy_disabled_test),
	KUNIT_CASE(dpm_policy_enabled_test),
	KUNIT_CASE(dpm_shared_peer_test),
	KUNIT_CASE(dpm_prepare_error_test),
	KUNIT_CASE(dpm_arm_error_test),
	KUNIT_CASE(dpm_runtime_resume_error_test),
	KUNIT_CASE(dpm_late_error_test),
	KUNIT_CASE(dpm_noirq_error_test),
	KUNIT_CASE(dpm_resume_disarm_error_test),
	{}
};

static struct kunit_suite wake_dpm_suite = {
	.name = "musb-wake-dpm",
	.init = wake_dpm_fixture_init,
	.test_cases = wake_dpm_cases,
};
kunit_test_suite(wake_dpm_suite);
