// SPDX-License-Identifier: GPL-2.0-only
/* Appended to the complete actual Sun4i PHY driver; generic PHY remains real. */
#include <linux/sched.h>
#include "musb-combined-lifecycle-kunit.h"

struct neo_phy_fixture {
	struct sun4i_usb_phy_data data;
	bool registered;
};

static struct sun4i_usb_phy_data *neo_phy_data(void)
{
	struct neo_joined_lifetime *life = neo_joined_current;
	struct neo_phy_fixture *fixture = life ? life->phy_private : NULL;

	return fixture ? &fixture->data : NULL;
}

static void neo_phy_access(struct sun4i_usb_phy_data *data)
{
	struct neo_joined_lifetime *life = neo_joined_current;

	lockdep_assert_held(&data->phys[0].phy->mutex);
	atomic_inc(&life->phy_access);
	if (!atomic_read(&life->phy_clock))
		atomic_inc(&life->bad_access);
	/* A live rebound clock cannot excuse an old admitted scan's access. */
	if (READ_ONCE(life->held_scan_task) == current &&
	    life->held_scan_generation != data->phy0_generation)
		atomic_inc(&life->bad_access);
}

static int neo_phy_clock_on(struct clk *clock)
{
	struct neo_joined_lifetime *life = neo_joined_current;

	if (life && clock == (struct clk *)&life->phy_clock) {
		if (READ_ONCE(life->fail_phy))
			return -EIO;
		atomic_inc(&life->phy_clock);
		return 0;
	}
	return clk_prepare_enable(clock);
}

static void neo_phy_clock_off(struct clk *clock)
{
	struct neo_joined_lifetime *life = neo_joined_current;

	if (life && clock == (struct clk *)&life->phy_clock) {
		if (atomic_read(&life->phy_clock) != 1)
			atomic_inc(&life->bad_access);
		atomic_dec(&life->phy_clock);
		return;
	}
	clk_disable_unprepare(clock);
}

static void neo_phy_after_notification(struct sun4i_usb_phy_data *data, u64 generation)
{
	struct neo_joined_lifetime *life = neo_joined_current;

	if (data != neo_phy_data())
		return;
	if (atomic_read(&life->scan_gate.armed)) {
		life->held_scan_generation = generation;
		WRITE_ONCE(life->held_scan_task, current);
	}
	neo_joined_gate_wait(&life->scan_gate);
}

static void neo_phy_scan_done(struct sun4i_usb_phy_data *data)
{
	struct neo_joined_lifetime *life = neo_joined_current;

	if (data == neo_phy_data() && READ_ONCE(life->held_scan_task) == current)
		WRITE_ONCE(life->held_scan_task, NULL);
}

static void neo_phy_after_mode(struct sun4i_usb_phy_data *data)
{
	if (data == neo_phy_data()) {
		atomic_inc(&neo_joined_current->work_calls);
		neo_joined_gate_wait(&neo_joined_current->work_gate);
	}
}

static int neo_phy_vbus(struct sun4i_usb_phy_data *data)
{
	neo_phy_access(data);
	return READ_ONCE(neo_joined_current->vbus_level);
}

int neo_joined_phy_prepare(struct neo_joined_lifetime *life)
{
	struct neo_phy_fixture *fixture;
	struct sun4i_usb_phy_data *data;
	struct phy *phy;
	int ret;

	fixture = kunit_kzalloc(life->test, sizeof(*fixture), GFP_KERNEL);
	if (!fixture)
		return -ENOMEM;
	life->phy_private = fixture;
	data = &fixture->data;
	data->cfg = &sun8i_a33_cfg;
	data->dr_mode = USB_DR_MODE_PERIPHERAL;
	spin_lock_init(&data->reg_lock);
	INIT_DELAYED_WORK(&data->detect, sun4i_usb_phy0_id_vbus_det_scan);
	phy = phy_create(life->parent, NULL, &sun4i_usb_phy_ops);
	if (IS_ERR(phy))
		return PTR_ERR(phy);
	life->phy = phy;
	data->phys[0].phy = phy;
	data->phys[0].clk = (struct clk *)&life->phy_clock;
	phy_set_drvdata(phy, &data->phys[0]);
	data->extcon = devm_extcon_dev_allocate(life->parent, sun4i_usb_phy0_cable);
	if (IS_ERR(data->extcon))
		return PTR_ERR(data->extcon);
	life->extcon = data->extcon;
	ret = extcon_dev_register(data->extcon);
	if (ret)
		return ret;
	fixture->registered = true;
	return 0;
}

void neo_joined_phy_destroy(struct neo_joined_lifetime *life)
{
	struct neo_phy_fixture *fixture = life->phy_private;

	if (!fixture)
		return;
	complete_all(&life->scan_gate.release);
	complete_all(&life->notifier_gate.release);
	complete_all(&life->work_gate.release);
	cancel_delayed_work_sync(&fixture->data.detect);
	if (fixture->registered)
		extcon_dev_unregister(fixture->data.extcon);
	if (!IS_ERR_OR_NULL(fixture->data.extcon))
		devm_extcon_dev_free(life->parent, fixture->data.extcon);
	if (!IS_ERR_OR_NULL(life->phy))
		phy_destroy(life->phy);
}

void neo_joined_phy_flush(struct neo_joined_lifetime *life)
{
	struct neo_phy_fixture *fixture = life->phy_private;

	flush_delayed_work(&fixture->data.detect);
}

void neo_joined_phy_irq(struct neo_joined_lifetime *life)
{
	struct neo_phy_fixture *fixture = life->phy_private;

	sun4i_usb_phy0_id_vbus_det_irq(0, &fixture->data);
}

u64 neo_joined_phy_generation(struct neo_joined_lifetime *life)
{
	struct neo_phy_fixture *fixture = life->phy_private;
	u64 generation;

	mutex_lock(&life->phy->mutex);
	generation = fixture->data.phy0_generation;
	mutex_unlock(&life->phy->mutex);
	return generation;
}

bool neo_joined_phy_active(struct neo_joined_lifetime *life)
{
	struct neo_phy_fixture *fixture = life->phy_private;
	bool active;

	mutex_lock(&life->phy->mutex);
	active = fixture->data.phy0_init;
	mutex_unlock(&life->phy->mutex);
	return active;
}

bool neo_joined_phy_current_level(struct neo_joined_lifetime *life)
{
	return extcon_get_state(life->extcon, EXTCON_USB) == READ_ONCE(life->vbus_level);
}

bool neo_joined_phy_scan_drained(struct neo_joined_lifetime *life)
{
	return READ_ONCE(life->held_scan_task) == NULL;
}
