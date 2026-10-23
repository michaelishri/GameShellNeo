// SPDX-License-Identifier: GPL-2.0-only
/* Appended to complete musb_core.c; controllers begin after synthetic mapping. */
#include <linux/gfp.h>
#include <linux/irq.h>
#include <linux/irqdesc.h>
#include <linux/irq_sim.h>
#include <linux/kthread.h>
#include <linux/suspend.h>
#include "musb-combined-lifecycle-kunit.h"

struct neo_joined_snapshot {
	int usage, irq;
	bool source, capable, wakeup_initialized, debt, pm_enabled;
};

struct neo_joined_walk {
	int start, end, suspend_result, resume_result;
	int usage_before, usage_after;
	unsigned int wake_depth;
	unsigned int disable_before, disable_after;
	bool armed, disabled, resume_start;
	gfp_t gfp_before, gfp_after;
};

struct neo_joined_globals {
	typeof(musb_readb) readb;
	typeof(musb_writeb) writeb;
	typeof(musb_clearb) clearb;
	typeof(musb_readw) readw;
	typeof(musb_writew) writew;
	typeof(musb_clearw) clearw;
	ushort fifo;
};

enum neo_init_fault {
	NEO_INIT_NO_FAULT,
	NEO_INIT_REGISTER_MEMORY,
	NEO_INIT_IRQ_MAPPING,
	NEO_INIT_CHILD_DRIVER,
};

enum neo_fixture_resource {
	NEO_PARENT = BIT(0),
	NEO_DOMAIN = BIT(1),
	NEO_IRQ = BIT(2),
	NEO_PHY = BIT(3),
	NEO_SUNXI = BIT(4),
	NEO_DRIVER = BIT(5),
};

struct neo_joined_fixture {
	struct neo_joined_lifetime life;
	struct platform_device *children[2];
	unsigned int children_count;
	struct irq_domain *domain;
	struct irq_chip chip;
	struct irq_chip *original_chip;
	unsigned int irq;
	struct usb_gadget_driver gadget;
	struct neo_joined_snapshot last;
	struct neo_joined_walk walk;
	struct neo_joined_globals globals;
	struct neo_joined_gate irq_gate;
	struct completion remove_done;
	struct task_struct *remove_task;
	atomic_t owner_calls, peer_calls, bind_calls, unbind_calls;
	unsigned int arm_calls, disarm_calls;
	unsigned int prepare_calls, suspend_calls, resume_calls, complete_calls;
	unsigned int late_calls, noirq_calls, early_calls, resume_noirq_calls;
	int probe_result;
	bool driver_registered, gadget_registered, peer_action, peer_wake;
	bool fail_initial_get, fail_arm, fail_disarm, fail_late;
	bool foreign_source, terminal_cleanup_control;
	bool last_late_queue;
	bool globals_changed;
	unsigned int acquired, released, cleanup_runs;
};

struct neo_joined_lifetime *neo_joined_current;

static void neo_save_globals(struct neo_joined_globals *saved)
{
	saved->readb = musb_readb;
	saved->writeb = musb_writeb;
	saved->clearb = musb_clearb;
	saved->readw = musb_readw;
	saved->writew = musb_writew;
	saved->clearw = musb_clearw;
	saved->fifo = fifo_mode;
}

static bool neo_globals_equal(const struct neo_joined_globals *saved)
{
	return musb_readb == saved->readb && musb_writeb == saved->writeb &&
		musb_clearb == saved->clearb && musb_readw == saved->readw &&
		musb_writew == saved->writew && musb_clearw == saved->clearw &&
		fifo_mode == saved->fifo;
}

static void neo_restore_globals(const struct neo_joined_globals *saved)
{
	musb_readb = saved->readb;
	musb_writeb = saved->writeb;
	musb_clearb = saved->clearb;
	musb_readw = saved->readw;
	musb_writew = saved->writew;
	musb_clearw = saved->clearw;
	fifo_mode = saved->fifo;
}

static struct neo_joined_fixture *neo_fixture(struct device *dev)
{
	struct neo_joined_lifetime *life = dev_get_platdata(dev->parent);

	return container_of(life, struct neo_joined_fixture, life);
}

void neo_joined_gate_wait(struct neo_joined_gate *gate)
{
	if (!atomic_xchg(&gate->armed, 0))
		return;
	might_sleep();
	complete(&gate->entered);
	wait_for_completion(&gate->release);
}

static void neo_gate_init(struct neo_joined_gate *gate)
{
	init_completion(&gate->entered);
	init_completion(&gate->release);
	atomic_set(&gate->armed, 0);
}

static bool neo_wait(struct completion *completion)
{
	return wait_for_completion_timeout(completion, 3 * HZ) != 0;
}

static int neo_chip_wake(struct irq_data *data, unsigned int on)
{
	struct neo_joined_fixture *f = container_of(data->chip, struct neo_joined_fixture, chip);

	if (on) {
		f->arm_calls++;
		return READ_ONCE(f->fail_arm) ? -EIO : 0;
	}
	f->disarm_calls++;
	return READ_ONCE(f->fail_disarm) ? -EIO : 0;
}

static irqreturn_t neo_owner_thread(int irq, void *data)
{
	struct musb *musb = data;
	struct neo_joined_fixture *f = neo_fixture(musb->controller);

	atomic_inc(&f->owner_calls);
	neo_joined_gate_wait(&f->irq_gate);
	if (!atomic_read(&f->life.backend_clock))
		atomic_inc(&f->life.bad_access);
	/* The physical ISR is the delivery seam; Linux still owns this action. */
	return IRQ_HANDLED;
}

static irqreturn_t neo_peer_thread(int irq, void *data)
{
	struct neo_joined_fixture *f = data;

	atomic_inc(&f->peer_calls);
	return IRQ_HANDLED;
}

static int neo_joined_request_irq(unsigned int irq, irq_handler_t handler,
				 unsigned long flags, const char *name, void *data)
{
	struct musb *musb = data;

	if (neo_joined_current && musb->controller == neo_joined_current->controller)
		return request_threaded_irq(irq, NULL, neo_owner_thread,
					    flags | IRQF_ONESHOT, name, data);
	return request_irq(irq, handler, flags, name, data);
}

static void neo_joined_irq_retiring(struct musb *musb)
{
	struct neo_joined_lifetime *life = neo_joined_current;

	if (life && life->controller == musb->controller) {
		lockdep_assert_not_held(&musb->lock);
		might_sleep();
		complete(&life->irq_retiring);
	}
}

static void neo_snapshot(struct neo_joined_fixture *f, struct musb *musb)
{
	struct device *dev = musb->controller;

	f->last.usage = atomic_read(&dev->power.usage_count);
	f->last.irq = musb->nIrq;
	f->last.source = dev->power.wakeup != NULL;
	f->last.capable = device_can_wakeup(dev);
	f->last.wakeup_initialized = musb->wakeup_initialized;
	f->last.debt = musb->irq_wake;
	f->last.pm_enabled = pm_runtime_enabled(dev);
}

/* Named source-derived copies change only the declared cleanup omission. */
NEO_JOINED_CORE_CONTROL_BODIES

static int neo_child_probe(struct platform_device *pdev)
{
	struct neo_joined_fixture *f = neo_fixture(&pdev->dev);
	struct musb *musb;

	f->life.controller = &pdev->dev;
	if (f->foreign_source) {
		f->probe_result = device_init_wakeup(&pdev->dev, true);
		if (f->probe_result)
			return f->probe_result;
	}
	f->probe_result = musb_init_controller(&pdev->dev, f->irq, f->life.registers);
	f->globals_changed |= !neo_globals_equal(&f->globals);
	musb = dev_get_drvdata(&pdev->dev);
	if (musb)
		neo_snapshot(f, musb);
	f->life.musb = f->probe_result ? NULL : musb;
	return f->probe_result;
}

static void neo_child_remove(struct platform_device *pdev)
{
	struct neo_joined_fixture *f = neo_fixture(&pdev->dev);
	struct musb *musb = dev_get_drvdata(&pdev->dev);

	if (f->terminal_cleanup_control)
		control_musb_remove(pdev);
	else
		musb_remove(pdev);
	/* Capture original state before the driver core releases devm allocation. */
	neo_snapshot(f, musb);
	if (f->terminal_cleanup_control) {
		/* The control has no wake debt after its successful resume. */
		device_init_wakeup(&pdev->dev, false);
		musb->wakeup_initialized = false;
	}
	f->life.musb = NULL;
}

static int neo_prepare(struct device *dev)
{
	neo_fixture(dev)->prepare_calls++;
	return 0;
}

static int neo_suspend(struct device *dev)
{
	struct neo_joined_fixture *f = neo_fixture(dev);

	f->suspend_calls++;
	f->walk.suspend_result = musb_suspend(dev);
	return f->walk.suspend_result;
}

static int neo_late(struct device *dev)
{
	struct neo_joined_fixture *f = neo_fixture(dev);

	f->late_calls++;
	return f->fail_late ? -EIO : 0;
}

static int neo_noirq(struct device *dev)
{
	neo_fixture(dev)->noirq_calls++;
	return 0;
}

static int neo_resume_noirq(struct device *dev)
{
	neo_fixture(dev)->resume_noirq_calls++;
	return 0;
}

static int neo_early(struct device *dev)
{
	neo_fixture(dev)->early_calls++;
	return 0;
}

static int neo_resume(struct device *dev)
{
	struct neo_joined_fixture *f = neo_fixture(dev);

	f->resume_calls++;
	f->walk.resume_result = musb_resume(dev);
	return f->walk.resume_result;
}

static void neo_complete(struct device *dev)
{
	neo_fixture(dev)->complete_calls++;
}

static int neo_runtime_resume(struct device *dev)
{
	struct neo_joined_fixture *f = neo_fixture(dev);

	if (f->fail_initial_get && !dev_to_musb(dev)->is_initialized)
		return -EIO;
	return musb_runtime_resume(dev);
}

static const struct dev_pm_ops neo_pm_ops = {
	.prepare = neo_prepare,
	.suspend = neo_suspend,
	.suspend_late = neo_late,
	.suspend_noirq = neo_noirq,
	.resume_noirq = neo_resume_noirq,
	.resume_early = neo_early,
	.resume = neo_resume,
	.complete = neo_complete,
	.runtime_suspend = musb_runtime_suspend,
	.runtime_resume = neo_runtime_resume,
};

static struct platform_driver neo_child_driver = {
	.probe = neo_child_probe,
	.remove = neo_child_remove,
	.driver = {
		.name = "musb-combined-child",
		.pm = &neo_pm_ops,
	},
};

static int neo_add_child(struct neo_joined_fixture *f)
{
	struct musb_hdrc_platform_data pdata = {
		.mode = MUSB_PERIPHERAL,
		.config = neo_joined_sunxi_config(),
		.platform_ops = neo_joined_sunxi_ops(&f->life),
	};
	struct platform_device *child;
	int ret;

	if (f->children_count == ARRAY_SIZE(f->children))
		return -E2BIG;
	child = platform_device_alloc("musb-combined-child", f->children_count);
	if (!child)
		return -ENOMEM;
	child->dev.parent = f->life.parent;
	ret = platform_device_add_data(child, &pdata, sizeof(pdata));
	if (ret)
		goto put;
	f->probe_result = -EINPROGRESS;
	ret = platform_device_add(child);
	if (ret)
		goto put;
	f->children[f->children_count++] = child;
	return f->probe_result;
put:
	platform_device_put(child);
	return ret;
}

static int neo_gadget_bind(struct usb_gadget *gadget, struct usb_gadget_driver *driver)
{
	struct neo_joined_fixture *f = container_of(driver, struct neo_joined_fixture, gadget);

	atomic_inc(&f->bind_calls);
	return 0;
}

static void neo_gadget_unbind(struct usb_gadget *gadget)
{
	struct neo_joined_fixture *f = neo_fixture(gadget_to_musb(gadget)->controller);

	atomic_inc(&f->unbind_calls);
}

static int neo_gadget_setup(struct usb_gadget *gadget, const struct usb_ctrlrequest *request)
{
	return -EOPNOTSUPP;
}

static void neo_gadget_disconnect(struct usb_gadget *gadget) { }

static int neo_bind_gadget(struct neo_joined_fixture *f)
{
	int ret;

	f->gadget = (struct usb_gadget_driver) {
		.function = "joined-lifecycle-test",
		.driver.name = "musb-combined-function",
		.max_speed = USB_SPEED_HIGH,
		.bind = neo_gadget_bind,
		.unbind = neo_gadget_unbind,
		.setup = neo_gadget_setup,
		.disconnect = neo_gadget_disconnect,
	};
	ret = usb_gadget_register_driver(&f->gadget);
	if (!ret)
		f->gadget_registered = true;
	return ret;
}

static void neo_dpm(struct neo_joined_fixture *f, bool wake)
{
	struct device *dev = f->life.controller;
	struct irq_desc *desc = irq_to_desc(f->irq);
	struct neo_joined_walk *walk = &f->walk;
	unsigned int flags;

	device_set_wakeup_enable(dev, wake);
	walk->usage_before = atomic_read(&dev->power.usage_count);
	walk->disable_before = dev->power.disable_depth;
	walk->gfp_before = gfp_allowed_mask;
	flags = lock_system_sleep();
	walk->start = dpm_suspend_start(PMSG_SUSPEND);
	if (!walk->start) {
		walk->end = dpm_suspend_end(PMSG_SUSPEND);
		/* No allocation, printk, assertion or sleep while guest IRQs are quiesced. */
		walk->wake_depth = READ_ONCE(desc->wake_depth);
		walk->armed = irqd_is_wakeup_armed(irq_desc_get_irq_data(desc));
		walk->disabled = irqd_irq_disabled(irq_desc_get_irq_data(desc));
		if (!walk->end) {
			dpm_resume_start(PMSG_RESUME);
			walk->resume_start = true;
		}
	}
	dpm_resume_end(PMSG_RESUME);
	unlock_system_sleep(flags);
	walk->usage_after = atomic_read(&dev->power.usage_count);
	walk->disable_after = dev->power.disable_depth;
	walk->gfp_after = gfp_allowed_mask;
}

static void neo_expect_walk(struct kunit *test, struct neo_joined_fixture *f, bool wake,
			    unsigned int peer)
{
	KUNIT_EXPECT_EQ(test, f->walk.start, f->fail_arm ? -EIO : 0);
	if (!f->fail_arm)
		KUNIT_EXPECT_EQ(test, f->walk.end, f->fail_late ? -EIO : 0);
	KUNIT_EXPECT_EQ(test, f->walk.usage_after, f->walk.usage_before);
	KUNIT_EXPECT_EQ(test, f->walk.disable_after, f->walk.disable_before);
	KUNIT_EXPECT_EQ(test, f->walk.gfp_after, f->walk.gfp_before);
	KUNIT_EXPECT_EQ(test, f->prepare_calls, 1U);
	KUNIT_EXPECT_EQ(test, f->suspend_calls, 1U);
	KUNIT_EXPECT_EQ(test, f->complete_calls, 1U);
	if (!f->fail_arm && !f->fail_late) {
		KUNIT_EXPECT_TRUE(test, f->walk.resume_start);
		KUNIT_EXPECT_EQ(test, f->walk.wake_depth, peer + (unsigned int)wake);
		KUNIT_EXPECT_EQ(test, f->walk.armed, wake || peer);
		KUNIT_EXPECT_EQ(test, f->walk.disabled, !(wake || peer));
		KUNIT_EXPECT_EQ(test, f->late_calls, 1U);
		KUNIT_EXPECT_EQ(test, f->noirq_calls, 1U);
		KUNIT_EXPECT_EQ(test, f->resume_noirq_calls, 1U);
		KUNIT_EXPECT_EQ(test, f->early_calls, 1U);
	}
	KUNIT_EXPECT_EQ(test, f->walk.resume_result, f->fail_disarm ? -EIO : 0);
}

static int neo_remove_thread(void *data)
{
	struct neo_joined_fixture *f = data;

	device_release_driver(f->life.controller);
	complete(&f->remove_done);
	while (!kthread_should_stop())
		schedule_timeout_interruptible(HZ);
	return 0;
}

static void neo_expect_settled(struct kunit *test, struct neo_joined_fixture *f,
			      bool foreign, unsigned int peer, bool debt)
{
	KUNIT_EXPECT_EQ(test, f->last.irq, -ENODEV);
	KUNIT_EXPECT_EQ(test, f->last.usage, 0);
	KUNIT_EXPECT_FALSE(test, f->last.pm_enabled);
	if (!foreign) {
		KUNIT_EXPECT_FALSE(test, f->last.wakeup_initialized);
		KUNIT_EXPECT_FALSE(test, f->last.capable);
		KUNIT_EXPECT_FALSE(test, f->last.source);
	}
	KUNIT_EXPECT_FALSE(test, neo_joined_sunxi_notifier_linked(&f->life));
	KUNIT_EXPECT_FALSE(test, neo_joined_phy_active(&f->life));
	KUNIT_EXPECT_EQ(test, atomic_read(&f->life.backend_clock), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->life.phy_clock), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->life.bad_access), 0);
	KUNIT_EXPECT_EQ(test, irq_to_desc(f->irq)->wake_depth, peer + (unsigned int)debt);
	KUNIT_EXPECT_EQ(test, f->last.debt, debt);
	f->last_late_queue = neo_joined_sunxi_late_queue(&f->life);
	KUNIT_EXPECT_FALSE(test, f->last_late_queue);
	if (f->last_late_queue)
		neo_joined_sunxi_control_cleanup(&f->life);
}

static void neo_owned_line(struct kunit *test, struct neo_joined_fixture *f)
{
	kunit_info(test, "owned core=%d source=%d cap=%d late=%d refs=%d debt=%d bad=%d",
		   f->last.wakeup_initialized, f->last.source, f->last.capable,
		   f->last_late_queue, f->last.usage, f->last.debt,
		   atomic_read(&f->life.bad_access));
}

static void neo_joined_exit(struct kunit *test)
{
	struct neo_joined_fixture *f = test->priv;
	unsigned int i;

	if (!f)
		return;
	/* KUnit invokes .exit even after .init fails. Consume its one claim first. */
	test->priv = NULL;
	f->cleanup_runs++;
	complete_all(&f->life.notifier_gate.release);
	complete_all(&f->life.work_gate.release);
	complete_all(&f->life.scan_gate.release);
	complete_all(&f->irq_gate.release);
	if (!IS_ERR_OR_NULL(f->remove_task)) {
		kthread_stop(f->remove_task);
		f->remove_task = NULL;
	}
	WRITE_ONCE(f->fail_disarm, false);
	WRITE_ONCE(f->fail_arm, false);
	if (f->gadget_registered) {
		usb_gadget_unregister_driver(&f->gadget);
		f->gadget_registered = false;
	}
	for (i = 0; i < f->children_count; i++) {
		device_release_driver(&f->children[i]->dev);
		device_init_wakeup(&f->children[i]->dev, false);
		platform_device_unregister(f->children[i]);
		f->children[i] = NULL;
	}
	f->children_count = 0;
	f->life.controller = NULL;
	f->life.musb = NULL;
	/* Only fixture debt recovery, using the still-owned original descriptor. */
	if (f->irq && irq_to_desc(f->irq)->wake_depth > (unsigned int)f->peer_wake)
		KUNIT_EXPECT_EQ(test, disable_irq_wake(f->irq), 0);
	if (f->peer_wake) {
		KUNIT_EXPECT_EQ(test, disable_irq_wake(f->irq), 0);
		f->peer_wake = false;
	}
	if (f->peer_action) {
		free_irq(f->irq, f);
		f->peer_action = false;
	}
	neo_joined_sunxi_destroy(&f->life);
	f->released |= f->acquired & NEO_SUNXI;
	neo_joined_phy_destroy(&f->life);
	f->released |= f->acquired & NEO_PHY;
	if (f->driver_registered) {
		platform_driver_unregister(&neo_child_driver);
		f->driver_registered = false;
		f->released |= NEO_DRIVER;
	}
	if (f->irq) {
		if (f->original_chip)
			irq_set_chip(f->irq, f->original_chip);
		irq_dispose_mapping(f->irq);
		f->irq = 0;
		f->original_chip = NULL;
		f->released |= NEO_IRQ;
	}
	if (!IS_ERR_OR_NULL(f->domain)) {
		irq_domain_remove_sim(f->domain);
		f->released |= NEO_DOMAIN;
	}
	f->domain = NULL;
	if (!IS_ERR_OR_NULL(f->life.parent)) {
		root_device_unregister(f->life.parent);
		f->released |= NEO_PARENT;
	}
	f->life.parent = NULL;
	/* All child, IRQ, work and detector users have retired before this handoff. */
	neo_restore_globals(&f->globals);
	neo_joined_sunxi_restore_globals(&f->life);
	KUNIT_EXPECT_TRUE(test, neo_globals_equal(&f->globals));
	if (f->acquired & NEO_DRIVER)
		KUNIT_EXPECT_TRUE(test, f->globals_changed);
	KUNIT_EXPECT_EQ(test, f->cleanup_runs, 1U);
	KUNIT_EXPECT_EQ(test, f->released, f->acquired);
	neo_joined_current = NULL;
	kunit_info(test, "globals restored changed=%d", f->globals_changed);
	kunit_info(test, "joined cleanup complete");
}

static int neo_joined_init_stage(struct kunit *test, enum neo_init_fault fault)
{
	struct neo_joined_fixture *f;
	int ret;

	if (neo_joined_current)
		return -EBUSY;
	kunit_info(test, "begin joined lifecycle");
	f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	if (!f)
		return -ENOMEM;
	f->life.test = test;
	f->life.vbus_level = true;
	f->life.register_bytes = 4096;
	neo_gate_init(&f->life.notifier_gate);
	neo_gate_init(&f->life.work_gate);
	neo_gate_init(&f->life.scan_gate);
	neo_gate_init(&f->irq_gate);
	init_completion(&f->remove_done);
	init_completion(&f->life.notifier_retiring);
	init_completion(&f->life.work_retiring);
	init_completion(&f->life.irq_retiring);
	neo_save_globals(&f->globals);
	/* From this point, every possible .exit has initialized cleanup state. */
	test->priv = f;
	neo_joined_current = &f->life;
	if (fault == NEO_INIT_REGISTER_MEMORY)
		return -ENOMEM;
	f->life.registers = (void __iomem *)kunit_kzalloc(test, f->life.register_bytes, GFP_KERNEL);
	if (!f->life.registers)
		return -ENOMEM;
	f->life.parent = root_device_register("musb-combined-parent");
	if (IS_ERR(f->life.parent)) {
		ret = PTR_ERR(f->life.parent);
		goto fail;
	}
	f->acquired |= NEO_PARENT;
	f->life.parent->platform_data = &f->life;
	f->domain = irq_domain_create_sim(NULL, 1);
	if (IS_ERR(f->domain)) {
		ret = PTR_ERR(f->domain);
		goto fail;
	}
	f->acquired |= NEO_DOMAIN;
	/* Only these fixture acquisition results are injected, not Linux helpers. */
	f->irq = fault == NEO_INIT_IRQ_MAPPING ? 0 : irq_create_mapping(f->domain, 0);
	if (!f->irq) {
		ret = -EINVAL;
		goto fail;
	}
	f->acquired |= NEO_IRQ;
	f->original_chip = irq_get_chip(f->irq);
	f->chip = *f->original_chip;
	f->chip.name = "musb-combined-lifecycle";
	f->chip.flags &= ~IRQCHIP_SKIP_SET_WAKE;
	f->chip.irq_set_wake = neo_chip_wake;
	irq_set_chip(f->irq, &f->chip);
	ret = neo_joined_phy_prepare(&f->life);
	if (ret)
		goto fail;
	f->acquired |= NEO_PHY;
	ret = neo_joined_sunxi_prepare(&f->life);
	if (ret)
		goto fail;
	f->acquired |= NEO_SUNXI;
	ret = fault == NEO_INIT_CHILD_DRIVER ? -EIO : platform_driver_register(&neo_child_driver);
	if (ret)
		goto fail;
	f->driver_registered = true;
	f->acquired |= NEO_DRIVER;
	return 0;
fail:
	/* The framework owns cleanup, including this failed initialization. */
	return ret;
}

static int neo_joined_init(struct kunit *test)
{
	return neo_joined_init_stage(test, NEO_INIT_NO_FAULT);
}

struct neo_init_probe {
	const char *name;
	enum neo_init_fault fault;
	int error;
	unsigned int acquired;
};

static const struct neo_init_probe neo_init_probes[] = {
	{ "combined_init_register_memory_error_test", NEO_INIT_REGISTER_MEMORY, -ENOMEM, 0 },
	{ "combined_init_irq_mapping_error_test", NEO_INIT_IRQ_MAPPING, -EINVAL,
	  NEO_PARENT | NEO_DOMAIN },
	{ "combined_init_child_driver_error_test", NEO_INIT_CHILD_DRIVER, -EIO,
	  NEO_PARENT | NEO_DOMAIN | NEO_IRQ | NEO_PHY | NEO_SUNXI },
};

static const struct neo_init_probe *neo_init_probe(struct kunit *test)
{
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(neo_init_probes); i++)
		if (!strcmp(test->name, neo_init_probes[i].name))
			return &neo_init_probes[i];
	return NULL;
}

static int neo_init_probe_init(struct kunit *test)
{
	const struct neo_init_probe *probe = neo_init_probe(test);
	int ret;

	if (!probe)
		return -EINVAL;
	ret = neo_joined_init_stage(test, probe->fault);
	KUNIT_EXPECT_EQ(test, ret, probe->error);
	/* The pinned framework, not this wrapper, now invokes the real .exit. */
	kunit_info(test, "fixture init probe error=%d", ret);
	return ret;
}

static void neo_init_probe_exit(struct kunit *test)
{
	const struct neo_init_probe *probe = neo_init_probe(test);
	struct neo_joined_fixture *f = test->priv;
	unsigned int irq;

	KUNIT_ASSERT_NOT_NULL(test, probe);
	KUNIT_ASSERT_NOT_NULL(test, f);
	irq = f->irq;
	KUNIT_EXPECT_EQ(test, f->acquired, probe->acquired);
	neo_joined_exit(test);
	KUNIT_EXPECT_PTR_EQ(test, test->priv, NULL);
	KUNIT_EXPECT_PTR_EQ(test, neo_joined_current, NULL);
	KUNIT_EXPECT_PTR_EQ(test, f->life.parent, NULL);
	KUNIT_EXPECT_PTR_EQ(test, f->domain, NULL);
	KUNIT_EXPECT_EQ(test, f->irq, 0U);
	if (irq)
		KUNIT_EXPECT_PTR_EQ(test, irq_to_desc(irq), NULL);
	KUNIT_EXPECT_PTR_EQ(test, f->life.phy, NULL);
	KUNIT_EXPECT_PTR_EQ(test, f->life.extcon, NULL);
	KUNIT_EXPECT_PTR_EQ(test, f->life.phy_private, NULL);
	KUNIT_EXPECT_PTR_EQ(test, f->life.sunxi_private, NULL);
	KUNIT_EXPECT_FALSE(test, f->driver_registered);
	KUNIT_EXPECT_TRUE(test, completion_done(&f->life.notifier_gate.release));
	KUNIT_EXPECT_TRUE(test, completion_done(&f->life.work_gate.release));
	KUNIT_EXPECT_TRUE(test, completion_done(&f->life.scan_gate.release));
	KUNIT_EXPECT_TRUE(test, completion_done(&f->irq_gate.release));
	KUNIT_EXPECT_EQ(test, f->released, probe->acquired);
	KUNIT_EXPECT_EQ(test, f->cleanup_runs, 1U);
	KUNIT_EXPECT_TRUE(test, neo_globals_equal(&f->globals));
	/* This deliberately repeated request cannot touch released Linux objects. */
	neo_joined_exit(test);
	KUNIT_EXPECT_EQ(test, f->cleanup_runs, 1U);
	KUNIT_EXPECT_TRUE(test, neo_globals_equal(&f->globals));
	kunit_info(test, "failed init cleanup once acquired=%u released=%u second=noop",
		   f->acquired, f->released);
}

static void combined_init_register_memory_error_test(struct kunit *test)
{
	KUNIT_FAIL(test, "failed-init probe body must not execute");
}

static void combined_init_irq_mapping_error_test(struct kunit *test)
{
	KUNIT_FAIL(test, "failed-init probe body must not execute");
}

static void combined_init_child_driver_error_test(struct kunit *test)
{
	KUNIT_FAIL(test, "failed-init probe body must not execute");
}

static int neo_terminal_control_init(struct kunit *test)
{
	int ret = neo_joined_init(test);

	if (!ret)
		((struct neo_joined_fixture *)test->priv)->terminal_cleanup_control = true;
	return ret;
}

static int neo_work_control_init(struct kunit *test)
{
	int ret = neo_joined_init(test);

	if (!ret)
		((struct neo_joined_fixture *)test->priv)->life.work_disable_control = true;
	return ret;
}

static int neo_probe(struct kunit *test, struct neo_joined_fixture *f)
{
	int ret = neo_add_child(f);

	if (ret)
		return ret;
	if (!f->life.musb)
		return -ENODEV;
	KUNIT_EXPECT_EQ(test, atomic_read(&f->life.controller->power.usage_count), 1);
	return 0;
}

static void neo_policy_case(struct kunit *test, bool wake)
{
	struct neo_joined_fixture *f = test->priv;

	KUNIT_ASSERT_EQ(test, neo_probe(test, f), 0);
	KUNIT_ASSERT_EQ(test, neo_bind_gadget(f), 0);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->bind_calls), 1);
	neo_joined_sunxi_flush(&f->life);
	neo_dpm(f, wake);
	neo_expect_walk(test, f, wake, 0);
	neo_joined_sunxi_flush(&f->life);
	device_release_driver(f->life.controller);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->unbind_calls), 1);
	neo_expect_settled(test, f, false, 0, false);
	neo_owned_line(test, f);
}

static void combined_policy_disabled_remove_test(struct kunit *test) { neo_policy_case(test, false); }
static void combined_policy_enabled_remove_test(struct kunit *test) { neo_policy_case(test, true); }

static void combined_shared_peer_rebind_test(struct kunit *test)
{
	struct neo_joined_fixture *f = test->priv;
	struct device *first;

	KUNIT_ASSERT_EQ(test, request_threaded_irq(f->irq, NULL, neo_peer_thread,
						 IRQF_SHARED | IRQF_ONESHOT, "joined-peer", f), 0);
	f->peer_action = true;
	KUNIT_ASSERT_EQ(test, enable_irq_wake(f->irq), 0);
	f->peer_wake = true;
	KUNIT_ASSERT_EQ(test, neo_probe(test, f), 0);
	first = f->life.controller;
	neo_dpm(f, true);
	neo_expect_walk(test, f, true, 1);
	device_release_driver(first);
	neo_expect_settled(test, f, false, 1, false);
	KUNIT_ASSERT_EQ(test, neo_probe(test, f), 0);
	KUNIT_EXPECT_PTR_NE(test, f->life.controller, first);
	KUNIT_ASSERT_EQ(test, neo_bind_gadget(f), 0);
	neo_joined_sunxi_flush(&f->life);
	neo_joined_phy_flush(&f->life);
	KUNIT_EXPECT_TRUE(test, neo_joined_phy_current_level(&f->life));
	device_release_driver(f->life.controller);
	neo_expect_settled(test, f, false, 1, false);
	neo_owned_line(test, f);
}

static void neo_probe_error_case(struct kunit *test, unsigned int kind)
{
	struct neo_joined_fixture *f = test->priv;

	f->fail_initial_get = kind == 0;
	f->life.fail_phy = kind == 1;
	f->foreign_source = kind == 2;
	KUNIT_ASSERT_EQ(test, neo_add_child(f), kind == 2 ? -EEXIST : -EIO);
	KUNIT_EXPECT_PTR_EQ(test, f->life.controller->driver, NULL);
	neo_expect_settled(test, f, kind == 2, 0, false);
	if (kind == 2) {
		KUNIT_EXPECT_TRUE(test, f->last.source);
		KUNIT_EXPECT_TRUE(test, f->last.capable);
	}
	neo_owned_line(test, f);
}

static void combined_startup_pm_error_test(struct kunit *test) { neo_probe_error_case(test, 0); }
static void combined_phy_init_error_test(struct kunit *test) { neo_probe_error_case(test, 1); }
static void combined_foreign_wakeup_probe_error_test(struct kunit *test) { neo_probe_error_case(test, 2); }

static void neo_dpm_error_case(struct kunit *test, unsigned int kind)
{
	struct neo_joined_fixture *f = test->priv;
	unsigned int attempts;

	KUNIT_ASSERT_EQ(test, neo_probe(test, f), 0);
	f->fail_arm = kind == 0;
	f->fail_late = kind == 1;
	f->fail_disarm = kind == 2;
	neo_dpm(f, true);
	neo_expect_walk(test, f, true, 0);
	neo_joined_sunxi_flush(&f->life);
	attempts = f->disarm_calls;
	device_release_driver(f->life.controller);
	neo_expect_settled(test, f, false, 0, kind == 2);
	if (kind == 2)
		KUNIT_EXPECT_EQ(test, f->disarm_calls, attempts + 1);
	neo_owned_line(test, f);
}

static void combined_dpm_arm_error_remove_test(struct kunit *test) { neo_dpm_error_case(test, 0); }
static void combined_dpm_late_error_remove_test(struct kunit *test) { neo_dpm_error_case(test, 1); }
static void combined_resume_debt_remove_test(struct kunit *test) { neo_dpm_error_case(test, 2); }

static void neo_held_case(struct kunit *test, unsigned int kind)
{
	struct neo_joined_fixture *f = test->priv;
	struct neo_joined_gate *gate;

	gate = kind == 0 ? &f->life.notifier_gate :
		kind == 1 ? &f->life.work_gate : &f->irq_gate;
	if (!kind)
		atomic_set(&gate->armed, 1); /* The initial real PHY notification is admitted. */
	KUNIT_ASSERT_EQ(test, neo_probe(test, f), 0);
	if (!kind)
		KUNIT_ASSERT_TRUE(test, neo_wait(&gate->entered));
	neo_dpm(f, true);
	neo_expect_walk(test, f, true, 0);
	if (kind == 1) {
		neo_joined_sunxi_flush(&f->life);
		atomic_set(&gate->armed, 1);
		neo_joined_sunxi_recover(&f->life);
	} else if (kind == 2) {
		atomic_set(&gate->armed, 1);
		KUNIT_ASSERT_EQ(test, irq_set_irqchip_state(f->irq, IRQCHIP_STATE_PENDING, true), 0);
	}
	if (kind)
		KUNIT_ASSERT_TRUE(test, neo_wait(&gate->entered));
	f->remove_task = kthread_run(neo_remove_thread, f, "musb-joined-remove");
	KUNIT_ASSERT_FALSE(test, IS_ERR(f->remove_task));
	/* Observe entry into the actual blocking API, not merely a started task. */
	KUNIT_ASSERT_TRUE(test, neo_wait(kind == 0 ? &f->life.notifier_retiring :
				       kind == 1 ? &f->life.work_retiring : &f->life.irq_retiring));
	KUNIT_EXPECT_FALSE(test, completion_done(&f->remove_done));
	KUNIT_EXPECT_EQ(test, atomic_read(&f->life.backend_clock), 1);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->life.phy_clock), 1);
	complete_all(&gate->release);
	KUNIT_ASSERT_TRUE(test, neo_wait(&f->remove_done));
	kthread_stop(f->remove_task);
	f->remove_task = NULL;
	neo_expect_settled(test, f, false, 0, false);
	neo_owned_line(test, f);
}

static void combined_held_notifier_remove_test(struct kunit *test) { neo_held_case(test, 0); }
static void combined_held_work_remove_test(struct kunit *test) { neo_held_case(test, 1); }
static void combined_held_irq_remove_test(struct kunit *test) { neo_held_case(test, 2); }

static void combined_detector_exit_rebind_test(struct kunit *test)
{
	struct neo_joined_fixture *f = test->priv;
	u64 generation;

	atomic_set(&f->life.scan_gate.armed, 1);
	KUNIT_ASSERT_EQ(test, neo_probe(test, f), 0);
	KUNIT_ASSERT_TRUE(test, neo_wait(&f->life.scan_gate.entered));
	generation = neo_joined_phy_generation(&f->life);
	neo_dpm(f, true);
	neo_expect_walk(test, f, true, 0);
	device_release_driver(f->life.controller);
	neo_expect_settled(test, f, false, 0, false);
	f->life.vbus_level = false;
	KUNIT_ASSERT_EQ(test, neo_probe(test, f), 0);
	KUNIT_ASSERT_EQ(test, neo_bind_gadget(f), 0);
	KUNIT_EXPECT_EQ(test, neo_joined_phy_generation(&f->life), generation + 1);
	complete_all(&f->life.scan_gate.release);
	neo_joined_sunxi_flush(&f->life);
	neo_joined_phy_flush(&f->life);
	KUNIT_EXPECT_TRUE(test, neo_joined_phy_current_level(&f->life));
	KUNIT_EXPECT_TRUE(test, neo_joined_phy_scan_drained(&f->life));
	KUNIT_EXPECT_EQ(test, atomic_read(&f->life.bad_access), 0);
	device_release_driver(f->life.controller);
	neo_expect_settled(test, f, false, 0, false);
	neo_owned_line(test, f);
}

static void combined_closed_producer_rebind_test(struct kunit *test)
{
	struct neo_joined_fixture *f = test->priv;
	unsigned int accesses;

	KUNIT_ASSERT_EQ(test, neo_probe(test, f), 0);
	neo_dpm(f, true);
	neo_expect_walk(test, f, true, 0);
	device_release_driver(f->life.controller);
	neo_expect_settled(test, f, false, 0, false);
	accesses = atomic_read(&f->life.phy_access);
	neo_joined_phy_irq(&f->life);
	neo_joined_phy_flush(&f->life);
	KUNIT_EXPECT_EQ(test, atomic_read(&f->life.phy_access), accesses);
	f->life.vbus_level = false;
	KUNIT_ASSERT_EQ(test, neo_probe(test, f), 0);
	KUNIT_ASSERT_EQ(test, neo_bind_gadget(f), 0);
	neo_joined_sunxi_flush(&f->life);
	neo_joined_phy_flush(&f->life);
	KUNIT_EXPECT_TRUE(test, neo_joined_phy_current_level(&f->life));
	device_release_driver(f->life.controller);
	neo_expect_settled(test, f, false, 0, false);
	neo_owned_line(test, f);
}

static struct kunit_case neo_joined_cases[] = {
	KUNIT_CASE_SLOW(combined_policy_disabled_remove_test),
	KUNIT_CASE_SLOW(combined_policy_enabled_remove_test),
	KUNIT_CASE_SLOW(combined_shared_peer_rebind_test),
	KUNIT_CASE_SLOW(combined_startup_pm_error_test),
	KUNIT_CASE_SLOW(combined_phy_init_error_test),
	KUNIT_CASE_SLOW(combined_foreign_wakeup_probe_error_test),
	KUNIT_CASE_SLOW(combined_dpm_arm_error_remove_test),
	KUNIT_CASE_SLOW(combined_dpm_late_error_remove_test),
	KUNIT_CASE_SLOW(combined_resume_debt_remove_test),
	KUNIT_CASE_SLOW(combined_held_notifier_remove_test),
	KUNIT_CASE_SLOW(combined_held_work_remove_test),
	KUNIT_CASE_SLOW(combined_held_irq_remove_test),
	KUNIT_CASE_SLOW(combined_detector_exit_rebind_test),
	KUNIT_CASE_SLOW(combined_closed_producer_rebind_test),
	{ }
};

static struct kunit_case neo_terminal_control_cases[] = {
	KUNIT_CASE_SLOW(combined_policy_enabled_remove_test),
	{ }
};

static struct kunit_case neo_work_control_cases[] = {
	KUNIT_CASE_SLOW(combined_policy_disabled_remove_test),
	{ }
};

static struct kunit_case neo_init_probe_cases[] = {
	KUNIT_CASE_SLOW(combined_init_register_memory_error_test),
	KUNIT_CASE_SLOW(combined_init_irq_mapping_error_test),
	KUNIT_CASE_SLOW(combined_init_child_driver_error_test),
	{ }
};

static struct kunit_suite neo_joined_suite = {
	.name = "musb-combined-lifecycle",
	.init = neo_joined_init,
	.exit = neo_joined_exit,
	.test_cases = neo_joined_cases,
};

static struct kunit_suite neo_terminal_control_suite = {
	.name = "musb-combined-terminal-control",
	.init = neo_terminal_control_init,
	.exit = neo_joined_exit,
	.test_cases = neo_terminal_control_cases,
};

static struct kunit_suite neo_work_control_suite = {
	.name = "musb-combined-work-control",
	.init = neo_work_control_init,
	.exit = neo_joined_exit,
	.test_cases = neo_work_control_cases,
};

static struct kunit_suite neo_init_probe_suite = {
	.name = "musb-combined-init-failure",
	.init = neo_init_probe_init,
	.exit = neo_init_probe_exit,
	.test_cases = neo_init_probe_cases,
};

kunit_test_suites(&neo_joined_suite, &neo_terminal_control_suite,
		 &neo_work_control_suite, &neo_init_probe_suite);
