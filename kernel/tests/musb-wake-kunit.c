// SPDX-License-Identifier: GPL-2.0
/* Included with unchanged production functions in a disposable UML guest. */
#include <kunit/test.h>
#include <linux/irq.h>
#include <linux/irqdesc.h>
#include <linux/suspend.h>
#include <linux/unaligned.h>

struct wake_fixture {
	struct musb musb;
	struct musb_hdrc_config config;
	struct device *device;
	struct kunit *test;
	int irq, arm_error, disarm_error, runtime_error;
	unsigned int arms, disarms, disables, enables, mmio, runtime_resumes;
	unsigned int owner_calls, peer_calls;
	bool owner_action, peer_action, peer_wake, accessors_changed;
	u8 registers[256];
	u8 (*old_readb)(void __iomem *, u32);
	u8 (*old_clearb)(void __iomem *, u32);
	void (*old_writeb)(void __iomem *, u32, u8);
	u16 (*old_readw)(void __iomem *, u32);
	u16 (*old_clearw)(void __iomem *, u32);
	void (*old_writew)(void __iomem *, u32, u16);
};

struct wake_irq_state {
	unsigned int references, disable_depth, owner_calls, peer_calls;
	bool wake, armed, disabled;
};

static struct wake_fixture *wake_registers(void __iomem *base)
{
	return container_of((u8 __force *)base, struct wake_fixture, registers[0]);
}

/* Only the unmodelled controller registers are substituted. */
static u8 wake_readb(void __iomem *base, u32 offset)
{
	wake_registers(base)->mmio++;
	return ((u8 __force *)base)[offset];
}

static void wake_writeb(void __iomem *base, u32 offset, u8 value)
{
	wake_registers(base)->mmio++;
	((u8 __force *)base)[offset] = value;
}

static u16 wake_readw(void __iomem *base, u32 offset)
{
	wake_registers(base)->mmio++;
	return get_unaligned_le16((u8 __force *)base + offset);
}

static void wake_writew(void __iomem *base, u32 offset, u16 value)
{
	wake_registers(base)->mmio++;
	put_unaligned_le16(value, (u8 __force *)base + offset);
}

static int wake_chip_set_wake(struct irq_data *data, unsigned int on)
{
	struct wake_fixture *f = irq_data_get_irq_chip_data(data);

	if (on) {
		f->arms++;
		return f->arm_error;
	}
	f->disarms++;
	return f->disarm_error;
}

static void wake_chip_mask(struct irq_data *data) { }
static void wake_chip_unmask(struct irq_data *data) { }

static struct irq_chip wake_chip = {
	.name = "musb-wake-kunit",
	.irq_mask = wake_chip_mask,
	.irq_unmask = wake_chip_unmask,
	.irq_set_wake = wake_chip_set_wake,
};

static irqreturn_t wake_owner_handler(int irq, void *data)
{
	struct wake_fixture *f = data;

	f->owner_calls++;
	return IRQ_HANDLED;
}

static irqreturn_t wake_peer_handler(int irq, void *data)
{
	struct wake_fixture *f = container_of(data, struct wake_fixture, peer_calls);

	f->peer_calls++;
	return IRQ_HANDLED;
}

static void wake_platform_disable(struct musb *musb)
{
	container_of(musb, struct wake_fixture, musb)->disables++;
}

static void wake_platform_enable(struct musb *musb)
{
	container_of(musb, struct wake_fixture, musb)->enables++;
}

static const struct musb_platform_ops wake_platform_ops = {
	.quirks = MUSB_NO_ULPI_BUSCONTROL,
	.disable = wake_platform_disable,
	.enable = wake_platform_enable,
};

static int wake_runtime_resume(struct device *dev)
{
	struct wake_fixture *f = container_of(dev_to_musb(dev), struct wake_fixture, musb);

	f->runtime_resumes++;
	return f->runtime_error;
}

static const struct dev_pm_ops wake_runtime_ops = {
	.runtime_resume = wake_runtime_resume,
};

static const struct device_type wake_device_type = {
	.name = "musb-wake-test",
	.pm = &wake_runtime_ops,
};

static void wake_unused_work(struct work_struct *work) { }

static struct wake_irq_state wake_snapshot(struct wake_fixture *f)
{
	struct irq_desc *desc = irq_to_desc(f->irq);
	struct wake_irq_state state;
	unsigned long flags;

	raw_spin_lock_irqsave(&desc->lock, flags);
	state.references = desc->wake_depth;
	state.disable_depth = desc->depth;
	state.wake = irqd_is_wakeup_set(&desc->irq_data);
	state.armed = irqd_is_wakeup_armed(&desc->irq_data);
	state.disabled = irqd_irq_disabled(&desc->irq_data);
	state.owner_calls = f->owner_calls;
	state.peer_calls = f->peer_calls;
	raw_spin_unlock_irqrestore(&desc->lock, flags);
	return state;
}

static void wake_fixture_cleanup(void *data)
{
	struct wake_fixture *f = data;

	/* Error results and retained debt are asserted before this fixture-only reset.
	 * This is resource release in a disposable guest, not a driver retry policy.
	 */
	f->arm_error = 0;
	f->disarm_error = 0;
	if (!IS_ERR_OR_NULL(f->device)) {
		musb_cleanup_wakeup(&f->musb);
		if (f->peer_wake)
			KUNIT_EXPECT_EQ(f->test, disable_irq_wake(f->irq), 0);
		if (f->irq >= 0)
			KUNIT_EXPECT_EQ(f->test, wake_snapshot(f).references, 0U);
		device_init_wakeup(f->device, false);
		pm_runtime_disable(f->device);
		pm_runtime_dont_use_autosuspend(f->device);
		while (atomic_read(&f->device->power.usage_count) > 0)
			pm_runtime_put_noidle(f->device);
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
	if (!IS_ERR_OR_NULL(f->device)) {
		f->device->type = NULL;
		root_device_unregister(f->device);
	}
}

static int wake_fixture_init(struct kunit *test)
{
	struct wake_fixture *f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	int ret;

	if (!f)
		return -ENOMEM;
	test->priv = f;
	f->test = test;
	f->irq = -1;
	spin_lock_init(&f->musb.lock);
	spin_lock_init(&f->musb.list_lock);
	INIT_LIST_HEAD(&f->musb.pending_list);
	INIT_DELAYED_WORK(&f->musb.irq_work, wake_unused_work);
	INIT_DELAYED_WORK(&f->musb.gadget_work, wake_unused_work);
	ret = kunit_add_action_or_reset(test, wake_fixture_cleanup, f);
	if (ret)
		return ret;
	f->device = root_device_register("musb-wake-kunit");
	if (IS_ERR(f->device))
		return PTR_ERR(f->device);
	f->musb.controller = f->device;
	f->device->type = &wake_device_type;
	dev_set_drvdata(f->device, &f->musb);
	f->musb.config = &f->config; /* No physical endpoints in the register model. */
	f->musb.ops = &wake_platform_ops;
	f->musb.port_mode = MUSB_PERIPHERAL;
	f->musb.g.speed = USB_SPEED_UNKNOWN;
	f->musb.mregs = (void __iomem *)f->registers;
	pm_runtime_set_active(f->device);
	pm_runtime_set_autosuspend_delay(f->device, 500);
	pm_runtime_use_autosuspend(f->device);
	pm_runtime_get_noresume(f->device); /* Keep the synthetic controller active. */
	pm_runtime_enable(f->device);
	f->irq = irq_alloc_descs(-1, 1, 1, NUMA_NO_NODE);
	if (f->irq < 0)
		return f->irq;
	f->musb.nIrq = f->irq;
	ret = irq_set_chip_data(f->irq, f);
	if (ret)
		return ret;
	irq_set_chip_and_handler(f->irq, &wake_chip, handle_level_irq);
	irq_clear_status_flags(f->irq, IRQ_NOREQUEST | IRQ_NOPROBE);
	irq_set_status_flags(f->irq, IRQ_LEVEL);
	ret = request_irq(f->irq, wake_owner_handler, IRQF_SHARED, "musb-wake-owner", f);
	if (ret)
		return ret;
	f->owner_action = true;
	ret = request_irq(f->irq, wake_peer_handler, IRQF_SHARED, "musb-wake-peer", &f->peer_calls);
	if (ret)
		return ret;
	f->peer_action = true;
	f->old_readb = musb_readb;
	f->old_writeb = musb_writeb;
	f->old_clearb = musb_clearb;
	f->old_readw = musb_readw;
	f->old_writew = musb_writew;
	f->old_clearw = musb_clearw;
	musb_readb = wake_readb;
	musb_writeb = wake_writeb;
	musb_clearb = wake_readb;
	musb_readw = wake_readw;
	musb_writew = wake_writew;
	musb_clearw = wake_readw;
	f->accessors_changed = true;
	return 0;
}

static void wake_initialization_test(struct kunit *test)
{
	struct wake_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	KUNIT_EXPECT_EQ(test, f->arms, 1U);
	KUNIT_EXPECT_EQ(test, f->disarms, 1U);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 0U);
	KUNIT_EXPECT_FALSE(test, wake_snapshot(f).wake);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
	KUNIT_EXPECT_TRUE(test, f->musb.wakeup_initialized);
	KUNIT_EXPECT_TRUE(test, device_may_wakeup(f->device));
	musb_cleanup_wakeup(&f->musb);
	KUNIT_EXPECT_FALSE(test, device_can_wakeup(f->device));
	KUNIT_EXPECT_FALSE(test, f->musb.wakeup_initialized);
	KUNIT_EXPECT_EQ(test, f->disarms, 1U);
}

static void wake_unsupported_irq_test(struct kunit *test)
{
	struct wake_fixture *f = test->priv;

	f->arm_error = -ENXIO;
	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	KUNIT_EXPECT_FALSE(test, device_can_wakeup(f->device));
	KUNIT_EXPECT_FALSE(test, f->musb.wakeup_initialized);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 0U);
	KUNIT_EXPECT_EQ(test, f->disarms, 0U);
	KUNIT_ASSERT_EQ(test, musb_suspend(f->device), 0);
	KUNIT_EXPECT_EQ(test, f->arms, 1U);
	KUNIT_EXPECT_EQ(test, musb_resume(f->device), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
}

static void wake_foreign_capability_test(struct kunit *test)
{
	struct wake_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, device_init_wakeup(f->device, true), 0);
	KUNIT_EXPECT_EQ(test, musb_init_wakeup(&f->musb), -EEXIST);
	KUNIT_EXPECT_EQ(test, f->arms, 0U);
	KUNIT_EXPECT_FALSE(test, f->musb.wakeup_initialized);
	musb_cleanup_wakeup(&f->musb);
	KUNIT_EXPECT_TRUE(test, device_may_wakeup(f->device));
}

static void wake_probe_disarm_error_test(struct kunit *test)
{
	struct wake_fixture *f = test->priv;

	f->disarm_error = -EIO;
	KUNIT_EXPECT_EQ(test, musb_init_wakeup(&f->musb), -EIO);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 1U);
	KUNIT_EXPECT_TRUE(test, wake_snapshot(f).wake);
	KUNIT_EXPECT_TRUE(test, f->musb.irq_wake);
	KUNIT_EXPECT_FALSE(test, device_can_wakeup(f->device));
	KUNIT_EXPECT_FALSE(test, f->musb.wakeup_initialized);
	KUNIT_EXPECT_EQ(test, f->arms, 1U);
	KUNIT_EXPECT_EQ(test, f->disarms, 1U);
}

static void wake_policy_test(struct kunit *test, bool enabled)
{
	struct wake_fixture *f = test->priv;
	struct wake_irq_state before, event, after;
	unsigned int wake_irq;
	int handled;

	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	KUNIT_ASSERT_EQ(test, device_set_wakeup_enable(f->device, enabled), 0);
	KUNIT_ASSERT_EQ(test, musb_suspend(f->device), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 2);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, enabled ? 1U : 0U);
	/* Walk the actual global descriptor set. Do not sleep, allocate or assert
	 * while guest device IRQs are suspended; always restore before checking.
	 */
	suspend_device_irqs();
	before = wake_snapshot(f);
	handled = generic_handle_irq_safe(f->irq);
	event = wake_snapshot(f);
	resume_device_irqs();
	after = wake_snapshot(f);
	wake_irq = pm_wakeup_irq();
	if (wake_irq == f->irq) {
		pm_wakeup_clear(f->irq);
		pm_system_cancel_wakeup();
	}
	KUNIT_EXPECT_EQ(test, handled, 0);
	KUNIT_EXPECT_EQ(test, before.armed, enabled);
	KUNIT_EXPECT_EQ(test, before.wake, enabled);
	KUNIT_EXPECT_EQ(test, before.disabled, !enabled);
	KUNIT_EXPECT_EQ(test, before.disable_depth, enabled ? 0U : 1U);
	KUNIT_EXPECT_FALSE(test, event.armed);
	KUNIT_EXPECT_TRUE(test, event.disabled);
	KUNIT_EXPECT_EQ(test, event.disable_depth, 1U);
	KUNIT_EXPECT_EQ(test, event.owner_calls, 0U);
	KUNIT_EXPECT_EQ(test, event.peer_calls, 0U);
	KUNIT_EXPECT_FALSE(test, after.armed);
	KUNIT_EXPECT_FALSE(test, after.disabled);
	KUNIT_EXPECT_EQ(test, after.disable_depth, 0U);
	KUNIT_EXPECT_EQ(test, after.references, enabled ? 1U : 0U);
	if (enabled)
		KUNIT_EXPECT_EQ(test, wake_irq, (unsigned int)f->irq);
	/* A level source is explicitly reasserted after resume; this does not
	 * claim physical pending replay from the substituted irqchip.
	 */
	KUNIT_ASSERT_EQ(test, generic_handle_irq_safe(f->irq), 0);
	KUNIT_EXPECT_EQ(test, f->owner_calls, 1U);
	KUNIT_EXPECT_EQ(test, f->peer_calls, 1U);
	KUNIT_EXPECT_EQ(test, musb_resume(f->device), 0);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 0U);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
}

static void wake_policy_disabled_test(struct kunit *test) { wake_policy_test(test, false); }
static void wake_policy_enabled_test(struct kunit *test) { wake_policy_test(test, true); }

static void wake_peer_test(struct kunit *test, bool first)
{
	struct wake_fixture *f = test->priv;
	struct wake_irq_state state;

	if (first) {
		KUNIT_ASSERT_EQ(test, enable_irq_wake(f->irq), 0);
		f->peer_wake = true;
	}
	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	KUNIT_ASSERT_EQ(test, musb_suspend(f->device), 0);
	if (!first) {
		KUNIT_ASSERT_EQ(test, enable_irq_wake(f->irq), 0);
		f->peer_wake = true;
	}
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 2U);
	KUNIT_EXPECT_EQ(test, musb_resume(f->device), 0);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 1U);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
	KUNIT_ASSERT_EQ(test, device_set_wakeup_enable(f->device, false), 0);
	KUNIT_ASSERT_EQ(test, musb_suspend(f->device), 0);
	suspend_device_irqs();
	state = wake_snapshot(f);
	resume_device_irqs();
	KUNIT_EXPECT_TRUE(test, state.armed); /* The peer owns this wake source. */
	KUNIT_EXPECT_EQ(test, state.references, 1U);
	KUNIT_EXPECT_FALSE(test, state.disabled);
	KUNIT_EXPECT_EQ(test, musb_resume(f->device), 0);
	musb_cleanup_wakeup(&f->musb);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 1U);
	KUNIT_EXPECT_TRUE(test, wake_snapshot(f).wake);
	KUNIT_ASSERT_EQ(test, disable_irq_wake(f->irq), 0);
	f->peer_wake = false;
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 0U);
	KUNIT_EXPECT_EQ(test, f->arms, first ? 1U : 2U);
	KUNIT_EXPECT_EQ(test, f->disarms, first ? 1U : 2U);
}

static void wake_peer_first_test(struct kunit *test) { wake_peer_test(test, true); }
static void wake_peer_last_test(struct kunit *test) { wake_peer_test(test, false); }

static void wake_arm_error_test(struct kunit *test)
{
	struct wake_fixture *f = test->priv;
	unsigned int mmio;

	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	mmio = f->mmio;
	f->arm_error = -EIO;
	KUNIT_EXPECT_EQ(test, musb_suspend(f->device), -EIO);
	KUNIT_EXPECT_EQ(test, f->arms, 2U);
	KUNIT_EXPECT_EQ(test, f->disarms, 1U);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 0U);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
	KUNIT_EXPECT_EQ(test, f->mmio, mmio);
	KUNIT_EXPECT_EQ(test, f->disables, 0U);
	KUNIT_EXPECT_EQ(test, f->enables, 0U);
	KUNIT_EXPECT_FALSE(test, f->musb.gadget_suspended);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
}

static void wake_disarm_error_test(struct kunit *test)
{
	struct wake_fixture *f = test->priv;
	unsigned int arms, mmio;

	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	KUNIT_ASSERT_EQ(test, musb_suspend(f->device), 0);
	f->disarm_error = -EIO;
	KUNIT_EXPECT_EQ(test, musb_resume(f->device), -EIO);
	KUNIT_EXPECT_EQ(test, f->disarms, 2U);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 1U);
	KUNIT_EXPECT_TRUE(test, wake_snapshot(f).wake);
	KUNIT_EXPECT_TRUE(test, f->musb.irq_wake);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
	arms = f->arms;
	mmio = f->mmio;
	/* A later transition must report the debt, never stack another reference. */
	KUNIT_EXPECT_EQ(test, musb_suspend(f->device), -EIO);
	KUNIT_EXPECT_EQ(test, f->disarms, 3U);
	KUNIT_EXPECT_EQ(test, f->arms, arms);
	KUNIT_EXPECT_EQ(test, f->mmio, mmio);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 1U);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
	f->disarm_error = 0;
	KUNIT_ASSERT_EQ(test, device_set_wakeup_enable(f->device, false), 0);
	KUNIT_ASSERT_EQ(test, musb_suspend(f->device), 0);
	KUNIT_EXPECT_EQ(test, f->disarms, 4U);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 0U);
	KUNIT_EXPECT_EQ(test, f->arms, arms);
	KUNIT_EXPECT_FALSE(test, f->musb.irq_wake);
	KUNIT_EXPECT_EQ(test, musb_resume(f->device), 0);
	KUNIT_EXPECT_EQ(test, f->disarms, 4U);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
}

static void wake_runtime_resume_error_test(struct kunit *test)
{
	struct wake_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, musb_init_wakeup(&f->musb), 0);
	pm_runtime_disable(f->device);
	KUNIT_ASSERT_EQ(test, pm_runtime_set_suspended(f->device), 0);
	f->runtime_error = -EIO;
	pm_runtime_enable(f->device);
	KUNIT_EXPECT_EQ(test, musb_suspend(f->device), -EIO);
	KUNIT_EXPECT_EQ(test, f->runtime_resumes, 1U);
	KUNIT_EXPECT_EQ(test, f->arms, 1U);
	KUNIT_EXPECT_EQ(test, f->mmio, 0U);
	KUNIT_EXPECT_EQ(test, f->disables, 0U);
	KUNIT_EXPECT_EQ(test, wake_snapshot(f).references, 0U);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->device->power.usage_count), 1);
}

static struct kunit_case musb_wake_cases[] = {
	KUNIT_CASE(wake_initialization_test),
	KUNIT_CASE(wake_unsupported_irq_test),
	KUNIT_CASE(wake_foreign_capability_test),
	KUNIT_CASE(wake_probe_disarm_error_test),
	KUNIT_CASE(wake_policy_disabled_test),
	KUNIT_CASE(wake_policy_enabled_test),
	KUNIT_CASE(wake_peer_first_test),
	KUNIT_CASE(wake_peer_last_test),
	KUNIT_CASE(wake_arm_error_test),
	KUNIT_CASE(wake_disarm_error_test),
	KUNIT_CASE(wake_runtime_resume_error_test),
	{}
};

static struct kunit_suite musb_wake_suite = {
	.name = "musb-wake",
	.init = wake_fixture_init,
	.test_cases = musb_wake_cases,
};
kunit_test_suite(musb_wake_suite);
