// SPDX-License-Identifier: GPL-2.0
/* Included only by the isolated OMAP mailbox qualification kernel. */
#undef dev_get_drvdata
#undef musb_readl
#undef musb_writel
#undef devm_phy_get
#undef devm_usb_get_phy_by_phandle

#include <kunit/test.h>
#include <linux/completion.h>
#include <linux/irq_work.h>
#include <linux/kthread.h>
#include <linux/unaligned.h>

struct omap_mailbox_fixture {
	struct omap2430_glue glue;
	struct platform_device *parent;
	struct platform_device *child;
	struct device *provider;
	struct phy *phy;
	struct usb_phy xceiv;
	struct usb_otg otg;
	struct musb *musb;
	struct musb *previous;
	struct notifier_block notifier;
	struct musb_hdrc_platform_data pdata;
	struct omap_musb_board_data board_data;
	struct musb_hdrc_config config;
	u8 registers[0x1000];
	u8 (*saved_readb)(void __iomem *, u32);
	void (*saved_writeb)(void __iomem *, u32, u8);
	u8 (*saved_clearb)(void __iomem *, u32);
	u16 (*saved_clearw)(void __iomem *, u32);
	struct task_struct *dispatch_task;
	struct task_struct *remove_task;
	struct task_struct *pm_task;
	struct completion entered;
	struct completion release;
	struct completion dispatch_done;
	struct completion remove_done;
	struct completion pm_done;
	bool parent_driver;
	bool child_driver;
	bool srcu_initialized;
	bool parent_hold;
	bool child_hold;
	bool hold_dispatch;
	bool hold_work;
	bool hold_suspend;
	bool hold_resume;
	bool do_resume;
	bool resources_gone;
	bool inject_probe_error;
	int probe_result;
	int dispatch_result;
	int pm_result;
	unsigned int generation;
	unsigned int last_generation;
	atomic_t initialized;
	atomic_t powered;
	atomic_t notifications;
	atomic_t bad_access;
	atomic_t pause_timeout;
	atomic_t mmio;
	unsigned long last_event;
	struct irq_work irq;
	int irq_result;
	bool irq_atomic;
	bool irq_initialized;
	bool cleaned;
};

static struct omap_mailbox_fixture *omap_fixture;

static void omap_pause(struct omap_mailbox_fixture *f)
{
	complete(&f->entered);
	if (!wait_for_completion_timeout(&f->release, 5 * HZ))
		atomic_inc(&f->pause_timeout);
}

static void *omap_test_drvdata(const struct device *dev)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);
	void *data = dev_get_drvdata(dev);

	if (f && f->parent && dev == &f->parent->dev && READ_ONCE(f->hold_dispatch) &&
	    current == READ_ONCE(f->dispatch_task))
		omap_pause(f);
	return data;
}

static void omap_observe_mmio(struct omap_mailbox_fixture *f)
{
	atomic_inc(&f->mmio);
	if (READ_ONCE(f->resources_gone))
		atomic_inc(&f->bad_access);
}

static u32 omap_test_readl(void __iomem *addr, u32 offset)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);

	if (f && addr == (void __iomem *)f->registers && offset + sizeof(u32) <= sizeof(f->registers)) {
		omap_observe_mmio(f);
		return get_unaligned((u32 *)(f->registers + offset));
	}
	return musb_readl(addr, offset);
}

static void omap_test_writel(void __iomem *addr, u32 offset, u32 value)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);

	if (f && addr == (void __iomem *)f->registers && offset + sizeof(u32) <= sizeof(f->registers)) {
		omap_observe_mmio(f);
		put_unaligned(value, (u32 *)(f->registers + offset));
		return;
	}
	musb_writel(addr, offset, value);
}

static u8 omap_fixture_readb(void __iomem *addr, u32 offset)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);

	if (addr == (void __iomem *)f->registers && offset < sizeof(f->registers)) {
		if (READ_ONCE(f->hold_work) && current_work() == &f->glue.omap_musb_mailbox_work)
			omap_pause(f);
		omap_observe_mmio(f);
		return READ_ONCE(f->registers[offset]);
	}
	return f->saved_readb(addr, offset);
}

static void omap_fixture_writeb(void __iomem *addr, u32 offset, u8 value)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);

	if (addr == (void __iomem *)f->registers && offset < sizeof(f->registers)) {
		omap_observe_mmio(f);
		/* Synthetic hardware resolves the requested role immediately. */
		if (offset == MUSB_DEVCTL) {
			if (value & MUSB_DEVCTL_SESSION)
				value &= ~MUSB_DEVCTL_BDEVICE;
			else
				value |= MUSB_DEVCTL_BDEVICE;
		}
		WRITE_ONCE(f->registers[offset], value);
		return;
	}
	f->saved_writeb(addr, offset, value);
}

static struct phy *omap_test_get_phy(struct device *dev, const char *name)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);

	if (f && f->parent && dev == &f->parent->dev)
		return f->phy;
	return devm_phy_get(dev, name);
}

static struct usb_phy *omap_test_get_usb_phy(struct device *dev, const char *name, u8 index)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);

	if (f && f->parent && dev == &f->parent->dev)
		return &f->xceiv;
	return devm_usb_get_phy_by_phandle(dev, name, index);
}

static int omap_phy_init(struct phy *phy)
{
	struct omap_mailbox_fixture *f = phy_get_drvdata(phy);

	if (f->parent)
		lockdep_assert_not_held(&f->parent->dev.power.lock);
	if (READ_ONCE(f->hold_resume) && current == READ_ONCE(f->pm_task))
		omap_pause(f);
	atomic_inc(&f->initialized);
	return 0;
}

static int omap_phy_exit(struct phy *phy)
{
	struct omap_mailbox_fixture *f = phy_get_drvdata(phy);

	atomic_dec(&f->initialized);
	return 0;
}

static int omap_phy_power_on(struct phy *phy)
{
	struct omap_mailbox_fixture *f = phy_get_drvdata(phy);

	atomic_inc(&f->powered);
	return 0;
}

static int omap_phy_power_off(struct phy *phy)
{
	struct omap_mailbox_fixture *f = phy_get_drvdata(phy);

	if (f->parent)
		lockdep_assert_not_held(&f->parent->dev.power.lock);
	if (READ_ONCE(f->hold_suspend) && current == READ_ONCE(f->pm_task))
		omap_pause(f);
	atomic_dec(&f->powered);
	return 0;
}

static const struct phy_ops omap_fixture_phy_ops = {
	.init = omap_phy_init,
	.exit = omap_phy_exit,
	.power_on = omap_phy_power_on,
	.power_off = omap_phy_power_off,
	.owner = THIS_MODULE,
};

static int omap_notified(struct notifier_block *nb, unsigned long event, void *data)
{
	struct omap_mailbox_fixture *f = container_of(nb, struct omap_mailbox_fixture, notifier);

	if (READ_ONCE(f->resources_gone))
		atomic_inc(&f->bad_access);
	f->last_event = event;
	f->last_generation = f->generation;
	atomic_inc(&f->notifications);
	return NOTIFY_OK;
}

static int omap_probe_backend(struct musb *musb)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);
	unsigned long flags;
	int ret;

	ret = omap2430_musb_init(musb);
	if (!ret && f->inject_probe_error) {
		spin_lock_irqsave(&musb->controller->power.lock, flags);
		musb->controller->power.runtime_error = -EIO;
		spin_unlock_irqrestore(&musb->controller->power.lock, flags);
	}
	return ret;
}

static const struct musb_platform_ops omap_probe_ops = {
	.init = omap_probe_backend,
	.exit = omap2430_musb_exit,
	.phy_callback = omap2430_musb_mailbox,
	.phy_callback_quiesce = omap2430_musb_quiesce,
};

static int omap_child_probe(struct platform_device *pdev)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);
	struct musb *musb;
	int ret;

	if (f->inject_probe_error) {
		f->probe_result = musb_omap_test_probe(&pdev->dev, (void __iomem *)f->registers);
		return f->probe_result;
	}
	musb = devm_kzalloc(&pdev->dev, sizeof(*musb), GFP_KERNEL);
	if (!musb)
		return -ENOMEM;
	musb->controller = &pdev->dev;
	musb->mregs = (void __iomem *)f->registers;
	musb->ops = &omap2430_ops;
	spin_lock_init(&musb->lock);
	f->musb = musb;
	f->generation++;
	WRITE_ONCE(f->resources_gone, false);
	platform_set_drvdata(pdev, musb);
	ret = omap2430_musb_init(musb);
	if (ret)
		return ret;
	ret = musb_omap_test_register(musb);
	if (ret) {
		omap2430_musb_exit(musb);
		return ret;
	}
	pm_runtime_set_active(&pdev->dev);
	pm_runtime_get_noresume(&pdev->dev);
	f->child_hold = true;
	pm_runtime_enable(&pdev->dev);
	return 0;
}

static void omap_child_remove(struct platform_device *pdev)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);
	struct musb *musb = platform_get_drvdata(pdev);

	musb_omap_test_quiesce(musb);
	pm_runtime_disable(&pdev->dev);
	if (f->child_hold) {
		pm_runtime_put_noidle(&pdev->dev);
		f->child_hold = false;
	}
	/* Parent-PM unit cases can already own the zero PHY references. */
	if (atomic_read(&f->initialized) && atomic_read(&f->powered))
		omap2430_musb_exit(musb);
	WRITE_ONCE(f->resources_gone, true);
	f->previous = musb;
	f->musb = NULL;
	complete(&f->remove_done);
}

static struct platform_driver omap_child_driver = {
	.probe = omap_child_probe,
	.remove = omap_child_remove,
	.driver = { .name = "omap-mailbox-child-fixture" },
};

static int omap_parent_probe(struct platform_device *pdev)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);
	int ret;

	f->glue.dev = &pdev->dev;
	f->glue.status = MUSB_UNKNOWN;
	f->glue.control_otghs = ERR_PTR(-ENODEV);
	ret = init_srcu_struct(&f->glue.child_srcu);
	if (ret)
		return ret;
	f->srcu_initialized = true;
	spin_lock_init(&f->glue.status_lock);
	INIT_WORK(&f->glue.omap_musb_mailbox_work, omap_musb_mailbox_work);
	disable_work_sync(&f->glue.omap_musb_mailbox_work);
	platform_set_drvdata(pdev, &f->glue);
	pm_runtime_set_active(&pdev->dev);
	pm_runtime_get_noresume(&pdev->dev);
	f->parent_hold = true;
	pm_runtime_enable(&pdev->dev);
	return 0;
}

static void omap_parent_remove(struct platform_device *pdev)
{
	struct omap_mailbox_fixture *f = READ_ONCE(omap_fixture);

	if (f->child) {
		omap2430_remove(pdev);
		f->child = NULL;
	} else {
		pm_runtime_disable(&pdev->dev);
	}
	if (f->parent_hold) {
		pm_runtime_put_noidle(&pdev->dev);
		f->parent_hold = false;
	}
	cleanup_srcu_struct(&f->glue.child_srcu);
	f->srcu_initialized = false;
}

static const struct dev_pm_ops omap_fixture_pm_ops = {
	.runtime_suspend = omap2430_runtime_suspend,
	.runtime_resume = omap2430_runtime_resume,
};

static struct platform_driver omap_parent_driver = {
	.probe = omap_parent_probe,
	.remove = omap_parent_remove,
	.driver = { .name = "omap-mailbox-parent-fixture", .pm = &omap_fixture_pm_ops },
};

static int omap_bind_child(struct omap_mailbox_fixture *f)
{
	struct platform_device *child;
	int ret;

	child = platform_device_alloc("omap-mailbox-child-fixture", PLATFORM_DEVID_AUTO);
	if (!child)
		return -ENOMEM;
	child->dev.parent = &f->parent->dev;
	f->child = child;
	f->glue.musb = child;
	f->pdata.platform_ops = f->inject_probe_error ? &omap_probe_ops : &omap2430_ops;
	ret = platform_device_add_data(child, &f->pdata, sizeof(f->pdata));
	if (!ret)
		ret = platform_device_add(child);
	if (ret) {
		platform_device_put(child);
		f->child = NULL;
	}
	return ret;
}

static void omap_child_suspended(struct omap_mailbox_fixture *f)
{
	pm_runtime_disable(&f->child->dev);
	if (f->child_hold) {
		pm_runtime_put_noidle(&f->child->dev);
		f->child_hold = false;
	}
	pm_runtime_set_suspended(&f->child->dev);
}

static void omap_fixture_exit(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;

	if (!f || f->cleaned)
		return;
	f->cleaned = true;
	complete_all(&f->release);
	if (f->irq_initialized)
		irq_work_sync(&f->irq);
	if (!IS_ERR_OR_NULL(f->dispatch_task))
		kthread_stop(f->dispatch_task);
	if (!IS_ERR_OR_NULL(f->pm_task))
		kthread_stop(f->pm_task);
	if (!IS_ERR_OR_NULL(f->remove_task))
		kthread_stop(f->remove_task);
	if (f->parent) {
		platform_device_unregister(f->parent);
		f->parent = NULL;
	}
	if (f->child_driver)
		platform_driver_unregister(&omap_child_driver);
	if (f->parent_driver)
		platform_driver_unregister(&omap_parent_driver);
	if (f->srcu_initialized)
		cleanup_srcu_struct(&f->glue.child_srcu);
	if (!IS_ERR_OR_NULL(f->phy)) {
		for (int i = 0; i < 8 && atomic_read(&f->powered) > 0; i++)
			phy_power_off(f->phy);
		for (int i = 0; i < 8 && atomic_read(&f->initialized) > 0; i++)
			phy_exit(f->phy);
		KUNIT_EXPECT_EQ(test, atomic_read(&f->powered), 0);
		KUNIT_EXPECT_EQ(test, atomic_read(&f->initialized), 0);
		phy_destroy(f->phy);
	}
	if (!IS_ERR_OR_NULL(f->provider))
		root_device_unregister(f->provider);
	musb_readb = f->saved_readb;
	musb_writeb = f->saved_writeb;
	musb_clearb = f->saved_clearb;
	musb_clearw = f->saved_clearw;
	WRITE_ONCE(omap_fixture, NULL);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bad_access), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->pause_timeout), 0);
}

static int omap_fixture_init(struct kunit *test)
{
	struct omap_mailbox_fixture *f;
	int ret;

	f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	if (!f)
		return -ENOMEM;
	test->priv = f;
	init_completion(&f->entered);
	init_completion(&f->release);
	init_completion(&f->dispatch_done);
	init_completion(&f->remove_done);
	init_completion(&f->pm_done);
	f->saved_readb = musb_readb;
	f->saved_writeb = musb_writeb;
	f->saved_clearb = musb_clearb;
	f->saved_clearw = musb_clearw;
	WRITE_ONCE(omap_fixture, f);
	musb_readb = omap_fixture_readb;
	musb_writeb = omap_fixture_writeb;
	f->provider = root_device_register("omap-mailbox-phy-fixture");
	if (IS_ERR(f->provider)) {
		ret = PTR_ERR(f->provider);
		goto fail;
	}
	f->phy = phy_create(f->provider, NULL, &omap_fixture_phy_ops);
	if (IS_ERR(f->phy)) {
		ret = PTR_ERR(f->phy);
		goto fail;
	}
	phy_set_drvdata(f->phy, f);
	f->xceiv.dev = f->provider;
	f->xceiv.otg = &f->otg;
	f->otg.usb_phy = &f->xceiv;
	ATOMIC_INIT_NOTIFIER_HEAD(&f->xceiv.notifier);
	f->notifier.notifier_call = omap_notified;
	atomic_notifier_chain_register(&f->xceiv.notifier, &f->notifier);
	f->pdata.board_data = &f->board_data;
	f->board_data.interface_type = MUSB_INTERFACE_UTMI;
	f->pdata.mode = MUSB_PERIPHERAL;
	f->pdata.config = &f->config;
	f->config.num_eps = 4;
	f->config.ram_bits = 10;
	f->registers[MUSB_DEVCTL] = MUSB_DEVCTL_BDEVICE;
	ret = platform_driver_register(&omap_parent_driver);
	if (ret)
		goto fail;
	f->parent_driver = true;
	f->parent = platform_device_register_simple("omap-mailbox-parent-fixture", PLATFORM_DEVID_AUTO, NULL, 0);
	if (IS_ERR(f->parent)) {
		ret = PTR_ERR(f->parent);
		f->parent = NULL;
		goto fail;
	}
	ret = platform_driver_register(&omap_child_driver);
	if (ret)
		goto fail;
	f->child_driver = true;
	return 0;
fail:
	omap_fixture_exit(test);
	return ret;
}

static void omap_park(void)
{
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
}

static int omap_dispatch_thread(void *data)
{
	struct omap_mailbox_fixture *f = data;

	f->dispatch_result = musb_mailbox(MUSB_VBUS_OFF);
	complete(&f->dispatch_done);
	omap_park();
	return 0;
}

static int omap_remove_thread(void *data)
{
	struct omap_mailbox_fixture *f = data;

	device_release_driver(&f->child->dev);
	complete(&f->remove_done);
	omap_park();
	return 0;
}

static int omap_pm_thread(void *data)
{
	struct omap_mailbox_fixture *f = data;

	if (f->do_resume) {
		f->pm_result = pm_runtime_resume_and_get(&f->parent->dev);
		f->parent_hold = f->pm_result >= 0;
	} else {
		f->parent_hold = false;
		f->pm_result = pm_runtime_put_sync_suspend(&f->parent->dev);
	}
	complete(&f->pm_done);
	omap_park();
	return 0;
}

static void omap_irq_event(struct irq_work *work)
{
	struct omap_mailbox_fixture *f = container_of(work, struct omap_mailbox_fixture, irq);

	f->irq_atomic = in_interrupt() || irqs_disabled();
	f->irq_result = musb_mailbox(MUSB_VBUS_OFF);
}

static bool omap_owner_closed(struct omap_mailbox_fixture *f)
{
	struct musb *owner = f->musb;
	unsigned long end = jiffies + 2 * HZ;

	while (musb_omap_test_owned(owner)) {
		if (time_after(jiffies, end))
			return false;
		msleep(1);
	}
	return true;
}

static void no_owner_test(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;

	KUNIT_EXPECT_EQ(test, musb_mailbox(MUSB_VBUS_OFF), -ENODEV);
	init_irq_work(&f->irq, omap_irq_event);
	f->irq_initialized = true;
	irq_work_queue(&f->irq);
	irq_work_sync(&f->irq);
	KUNIT_EXPECT_TRUE(test, f->irq_atomic);
	KUNIT_EXPECT_EQ(test, f->irq_result, -ENODEV);
}

static void held_dispatch_test(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, omap_bind_child(f), 0);
	WRITE_ONCE(f->hold_dispatch, true);
	f->dispatch_task = kthread_create(omap_dispatch_thread, f, "omap-dispatch");
	KUNIT_ASSERT_FALSE(test, IS_ERR(f->dispatch_task));
	wake_up_process(f->dispatch_task);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->entered, 2 * HZ), 0UL);
	f->remove_task = kthread_run(omap_remove_thread, f, "omap-remove");
	KUNIT_ASSERT_FALSE(test, IS_ERR(f->remove_task));
	KUNIT_ASSERT_TRUE(test, omap_owner_closed(f));
	KUNIT_EXPECT_FALSE(test, completion_done(&f->remove_done));
	KUNIT_EXPECT_FALSE(test, f->resources_gone);
	complete_all(&f->release);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->remove_done, 3 * HZ), 0UL);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->dispatch_done, 3 * HZ), 0UL);
	KUNIT_EXPECT_EQ(test, f->dispatch_result, 0);
	KUNIT_EXPECT_EQ(test, musb_mailbox(MUSB_VBUS_OFF), -ENODEV);
}

static void held_work_test(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, omap_bind_child(f), 0);
	/* The worker must be able to resume its real parent inside child SRCU. */
	f->child_hold = false;
	KUNIT_ASSERT_GE(test, pm_runtime_put_sync_suspend(&f->child->dev), 0);
	f->parent_hold = false;
	KUNIT_ASSERT_GE(test, pm_runtime_put_sync_suspend(&f->parent->dev), 0);
	KUNIT_ASSERT_TRUE(test, pm_runtime_suspended(&f->parent->dev));
	WRITE_ONCE(f->hold_work, true);
	KUNIT_ASSERT_EQ(test, musb_mailbox(MUSB_VBUS_OFF), 0);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->entered, 2 * HZ), 0UL);
	f->remove_task = kthread_run(omap_remove_thread, f, "omap-work-remove");
	KUNIT_ASSERT_FALSE(test, IS_ERR(f->remove_task));
	KUNIT_ASSERT_TRUE(test, omap_owner_closed(f));
	KUNIT_EXPECT_FALSE(test, completion_done(&f->remove_done));
	KUNIT_EXPECT_PTR_EQ(test, rcu_access_pointer(f->glue.active_musb), f->musb);
	complete_all(&f->release);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->remove_done, 3 * HZ), 0UL);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->initialized), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->powered), 0);
}

static void coalesced_status_test(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, omap_bind_child(f), 0);
	KUNIT_ASSERT_EQ(test, musb_mailbox(MUSB_VBUS_VALID), 0);
	KUNIT_ASSERT_EQ(test, musb_mailbox(MUSB_VBUS_OFF), 0);
	flush_work(&f->glue.omap_musb_mailbox_work);
	KUNIT_EXPECT_EQ(test, f->last_event, (unsigned long)USB_EVENT_NONE);
	init_irq_work(&f->irq, omap_irq_event);
	f->irq_initialized = true;
	irq_work_queue(&f->irq);
	irq_work_sync(&f->irq);
	KUNIT_EXPECT_TRUE(test, f->irq_atomic);
	KUNIT_EXPECT_EQ(test, f->irq_result, 0);
	flush_work(&f->glue.omap_musb_mailbox_work);
}

static void owner_identity_test(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;
	struct musb *other;

	KUNIT_ASSERT_EQ(test, omap_bind_child(f), 0);
	other = kunit_kzalloc(test, sizeof(*other), GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, other);
	other->controller = &f->child->dev;
	other->ops = &omap2430_ops;
	KUNIT_EXPECT_EQ(test, musb_omap_test_register(other), -EBUSY);
	musb_omap_test_quiesce(other);
	KUNIT_EXPECT_TRUE(test, musb_omap_test_owned(f->musb));
	KUNIT_EXPECT_EQ(test, musb_mailbox(MUSB_VBUS_OFF), 0);
	flush_work(&f->glue.omap_musb_mailbox_work);
}

static void probe_unwind_test(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;

	f->inject_probe_error = true;
	KUNIT_ASSERT_EQ(test, omap_bind_child(f), 0);
	KUNIT_EXPECT_EQ(test, f->probe_result, -EINVAL);
	KUNIT_EXPECT_PTR_EQ(test, f->child->dev.driver, NULL);
	KUNIT_EXPECT_PTR_EQ(test, platform_get_drvdata(f->child), NULL);
	KUNIT_EXPECT_PTR_EQ(test, rcu_access_pointer(f->glue.active_musb), NULL);
	KUNIT_EXPECT_EQ(test, musb_mailbox(MUSB_VBUS_OFF), -ENODEV);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->initialized), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->powered), 0);
}

static void child_rebind_test(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;
	int events;

	KUNIT_ASSERT_EQ(test, omap_bind_child(f), 0);
	KUNIT_ASSERT_EQ(test, musb_mailbox(MUSB_VBUS_VALID), 0);
	flush_work(&f->glue.omap_musb_mailbox_work);
	device_release_driver(&f->child->dev);
	events = atomic_read(&f->notifications);
	KUNIT_ASSERT_EQ(test, device_driver_attach(&omap_child_driver.driver, &f->child->dev), 0);
	KUNIT_ASSERT_NOT_NULL(test, f->musb);
	KUNIT_EXPECT_EQ(test, f->generation, 2U);
	flush_work(&f->glue.omap_musb_mailbox_work);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->notifications), events);
	/* Explicit cached initialization is a new operation on the new child. */
	omap2430_musb_enable(f->musb);
	KUNIT_EXPECT_EQ(test, f->last_event, (unsigned long)USB_EVENT_VBUS);
	KUNIT_EXPECT_EQ(test, f->last_generation, 2U);
}

static void parent_remove_test(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, omap_bind_child(f), 0);
	platform_device_unregister(f->parent);
	f->parent = NULL;
	KUNIT_EXPECT_PTR_EQ(test, f->child, NULL);
	KUNIT_EXPECT_FALSE(test, f->srcu_initialized);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->initialized), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->powered), 0);
	KUNIT_EXPECT_EQ(test, musb_mailbox(MUSB_VBUS_OFF), -ENODEV);
}

static void omap_held_pm(struct kunit *test, bool resume)
{
	struct omap_mailbox_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, omap_bind_child(f), 0);
	omap_child_suspended(f);
	if (resume) {
		f->parent_hold = false;
		KUNIT_ASSERT_GE(test, pm_runtime_put_sync_suspend(&f->parent->dev), 0);
		KUNIT_ASSERT_TRUE(test, pm_runtime_suspended(&f->parent->dev));
	}
	f->hold_suspend = !resume;
	f->hold_resume = resume;
	f->do_resume = resume;
	f->pm_task = kthread_create(omap_pm_thread, f, "omap-parent-pm");
	KUNIT_ASSERT_FALSE(test, IS_ERR(f->pm_task));
	wake_up_process(f->pm_task);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->entered, 2 * HZ), 0UL);
	f->remove_task = kthread_run(omap_remove_thread, f, "omap-parent-pm-remove");
	KUNIT_ASSERT_FALSE(test, IS_ERR(f->remove_task));
	KUNIT_ASSERT_TRUE(test, omap_owner_closed(f));
	KUNIT_EXPECT_FALSE(test, completion_done(&f->remove_done));
	KUNIT_EXPECT_FALSE(test, f->resources_gone);
	complete_all(&f->release);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->pm_done, 3 * HZ), 0UL);
	KUNIT_ASSERT_NE(test, wait_for_completion_timeout(&f->remove_done, 3 * HZ), 0UL);
	KUNIT_EXPECT_GE(test, f->pm_result, 0);
	KUNIT_EXPECT_EQ(test, pm_runtime_suspended(&f->parent->dev), !resume);
	KUNIT_EXPECT_EQ(test, (unsigned int)f->glue.is_runtime_suspended, (unsigned int)!resume);
}

static void held_parent_suspend_test(struct kunit *test) { omap_held_pm(test, false); }
static void held_parent_resume_test(struct kunit *test) { omap_held_pm(test, true); }

static void omap_closed_pm(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;
	int before = atomic_read(&f->mmio);
	unsigned int suspended = f->glue.is_runtime_suspended;

	f->parent_hold = false;
	KUNIT_ASSERT_GE(test, pm_runtime_put_sync_suspend(&f->parent->dev), 0);
	KUNIT_EXPECT_TRUE(test, pm_runtime_suspended(&f->parent->dev));
	KUNIT_EXPECT_EQ(test, (unsigned int)f->glue.is_runtime_suspended, suspended);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->mmio), before);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->powered), 0);
	KUNIT_ASSERT_GE(test, pm_runtime_resume_and_get(&f->parent->dev), 0);
	f->parent_hold = true;
	KUNIT_EXPECT_TRUE(test, pm_runtime_active(&f->parent->dev));
	KUNIT_EXPECT_EQ(test, (unsigned int)f->glue.is_runtime_suspended, suspended);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->mmio), before);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->initialized), 0);
}

static void closed_parent_pm_test(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;

	omap_closed_pm(test); /* Real parent status changes, original no-child no-op. */
	KUNIT_ASSERT_EQ(test, omap_bind_child(f), 0);
	device_release_driver(&f->child->dev);
	omap_closed_pm(test);
}

static void rebound_parent_pm_test(struct kunit *test)
{
	struct omap_mailbox_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, omap_bind_child(f), 0);
	device_release_driver(&f->child->dev);
	omap_closed_pm(test);
	KUNIT_ASSERT_EQ(test, device_driver_attach(&omap_child_driver.driver, &f->child->dev), 0);
	KUNIT_ASSERT_NOT_NULL(test, f->musb);
	KUNIT_EXPECT_TRUE(test, pm_runtime_active(&f->parent->dev));
	KUNIT_EXPECT_EQ(test, (unsigned int)f->glue.is_runtime_suspended, 0U);
	KUNIT_EXPECT_EQ(test, (unsigned int)f->glue.phy_suspended, 0U);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->initialized), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->powered), 1);
	omap_child_suspended(f);
	f->parent_hold = false;
	KUNIT_ASSERT_GE(test, pm_runtime_put_sync_suspend(&f->parent->dev), 0);
	KUNIT_EXPECT_TRUE(test, pm_runtime_suspended(&f->parent->dev));
	KUNIT_EXPECT_EQ(test, (unsigned int)f->glue.is_runtime_suspended, 1U);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->powered), 0);
	KUNIT_ASSERT_GE(test, pm_runtime_resume_and_get(&f->parent->dev), 0);
	f->parent_hold = true;
	KUNIT_EXPECT_TRUE(test, pm_runtime_active(&f->parent->dev));
	KUNIT_EXPECT_EQ(test, (unsigned int)f->glue.is_runtime_suspended, 0U);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->initialized), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->powered), 1);
}

static struct kunit_case omap_mailbox_cases[] = {
	KUNIT_CASE(no_owner_test),
	KUNIT_CASE(held_dispatch_test),
	KUNIT_CASE(held_work_test),
	KUNIT_CASE(coalesced_status_test),
	KUNIT_CASE(owner_identity_test),
	KUNIT_CASE(probe_unwind_test),
	KUNIT_CASE(child_rebind_test),
	KUNIT_CASE(parent_remove_test),
	KUNIT_CASE(held_parent_suspend_test),
	KUNIT_CASE(held_parent_resume_test),
	KUNIT_CASE(closed_parent_pm_test),
	KUNIT_CASE(rebound_parent_pm_test),
	{}
};

static struct kunit_suite omap_mailbox_suite = {
	.name = "omap-musb-mailbox",
	.init = omap_fixture_init,
	.exit = omap_fixture_exit,
	.test_cases = omap_mailbox_cases,
};
kunit_test_suite(omap_mailbox_suite);
