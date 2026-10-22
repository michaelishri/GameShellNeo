/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual scan/exit/publication source; deterministic supplier and queue APIs. */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define to_sun4i_usb_phy_data(phy) container_of(phy, struct sun4i_usb_phy_data, phys[(phy)->index])
#define EXTCON_USB_HOST 0
#define EXTCON_USB 1
#define USB_DR_MODE_OTG 0
#define DEBOUNCE_TIME 50
#define POLL_TIME 250
#define PHY_CTL_SIDDQ 8
#define ISCR_DPDM_PULLUP_EN 1
#define ISCR_ID_PULLUP_EN 2
#define IRQ_HANDLED 1
#define NOTIFY_OK 1
#define PSY_EVENT_PROP_CHANGED 1
#define __iomem
typedef uint64_t u64;
typedef int irqreturn_t;
struct mutex { bool held; };
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; bool pending; unsigned delay; };
struct notifier_block { int unused; };
struct power_supply { int unused; };
struct phy { struct mutex mutex; void *data; };
struct sun4i_usb_phy_cfg { bool siddq_in_base, needs_phy2_siddq, phy0_dual_route; int phyctl_offset; };
struct sun4i_usb_phy {
	struct phy *phy;
	void *clk, *clk2, *reset;
	int index;
};
struct sun4i_usb_phy_data {
	struct sun4i_usb_phy phys[4];
	struct sun4i_usb_phy_cfg *cfg;
	void *base, *extcon;
	bool phy0_init, force_session_end;
	u64 phy0_generation;
	int dr_mode, id_det, vbus_det;
	struct delayed_work detect;
	struct notifier_block vbus_power_nb;
	struct power_supply *vbus_power_supply;
};
static struct sun4i_usb_phy_data data;
static struct sun4i_usb_phy_cfg cfg;
static struct phy phy0;
static struct power_supply supply;
static void *system_wq;
static bool powered, polling, retired, tail, rebind;
static unsigned action_cable, scenarios, reads, writes, notified[2];
static int cable_id, cable_vbus;

static void access(void)
{
	assert(powered && phy0.mutex.held);
	assert(!(tail && retired));
	writes++;
}
static void *phy_get_drvdata(struct phy *phy) { return phy->data; }
static void mutex_lock(struct mutex *lock) { assert(!lock->held); lock->held = true; }
static void mutex_unlock(struct mutex *lock) { assert(lock->held); lock->held = false; }
static int sun4i_usb_phy0_get_id_det(struct sun4i_usb_phy_data *d)
{
	assert(d == &data && powered && phy0.mutex.held && d->phy0_init);
	reads++;
	return cable_id;
}
static int sun4i_usb_phy0_get_vbus_det(struct sun4i_usb_phy_data *d)
{
	assert(d == &data && powered && phy0.mutex.held && d->phy0_init);
	reads++;
	return cable_vbus;
}
static bool sun4i_usb_phy0_have_vbus_det(struct sun4i_usb_phy_data *d) { (void)d; return true; }
static void sun4i_usb_phy0_update_iscr(struct phy *phy, unsigned clr, unsigned set)
{ (void)phy; (void)clr; (void)set; access(); }
static void sun4i_usb_phy0_set_vbus_detect(struct phy *phy, int value)
{ assert(phy == &phy0 && (value == 0 || value == 1)); access(); }
static void sun4i_usb_phy0_set_id_detect(struct phy *phy, int value)
{ assert(phy == &phy0 && (value == 0 || value == 1)); access(); }
static void sun4i_usb_phy_passby(struct sun4i_usb_phy *phy, int value)
{ (void)value; assert(phy == &data.phys[0]); access(); }
static void sun4i_usb_phy0_reroute(struct sun4i_usb_phy_data *d, int value)
{ (void)value; assert(d == &data); access(); }
static unsigned readl(void *p) { (void)p; access(); return 0; }
static void writel(unsigned v, void *p) { (void)v; (void)p; access(); }
static void reset_control_assert(void *p) { (void)p; assert(phy0.mutex.held && powered); }
static void clk_disable_unprepare(void *p)
{
	assert(phy0.mutex.held);
	if (p == data.phys[0].clk)
		powered = false;
}
static void msleep(unsigned ms) { assert(ms == 200 || ms == 1000); }
static bool sun4i_usb_phy0_poll(struct sun4i_usb_phy_data *d)
{
	assert(d == &data && powered && phy0.mutex.held && d->phy0_init);
	assert(!(tail && retired));
	return polling;
}
static bool queue_delayed_work(void *queue, struct delayed_work *work, unsigned delay)
{
	assert(queue == system_wq && work == &data.detect);
	if (work->pending)
		return false;
	work->pending = true;
	work->delay = delay;
	return true;
}
static bool mod_delayed_work(void *queue, struct delayed_work *work, unsigned delay)
{
	work->pending = false;
	return queue_delayed_work(queue, work, delay);
}
static int sun4i_usb_phy_exit(struct phy *phy);
static void detector_publish(struct sun4i_usb_phy_data *d);
static void extcon_set_state_sync(void *extcon, unsigned cable, int value)
{
	(void)value;
	assert(extcon == data.extcon && !phy0.mutex.held);
	notified[cable]++;
	if (action_cable == cable + 1) {
		mutex_lock(&phy0.mutex);
		assert(sun4i_usb_phy_exit(&phy0) == 0);
		if (rebind) {
			powered = true;
			detector_publish(&data);
			/* A new init owns its immediate rescan, not the old poll. */
			queue_delayed_work(system_wq, &data.detect, 0);
		}
		mutex_unlock(&phy0.mutex);
		retired = true;
	}
	tail = true;
}

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#include "phy_detector_functions.h"
#pragma GCC diagnostic pop

static void reset(void)
{
	memset(&data, 0, sizeof(data));
	memset(&phy0, 0, sizeof(phy0));
	memset(&cfg, 0, sizeof(cfg));
	data.cfg = &cfg;
	data.phys[0].phy = &phy0;
	data.phys[0].clk = &cfg;
	data.vbus_power_supply = &supply;
	phy0.data = &data.phys[0];
	data.id_det = data.vbus_det = -1;
	powered = true;
	polling = retired = tail = rebind = false;
	reads = writes = action_cable = 0;
	notified[0] = notified[1] = 0;
	mutex_lock(&phy0.mutex);
	detector_publish(&data);
	mutex_unlock(&phy0.mutex);
}

int main(void)
{
	for (unsigned id = 0; id < 2; id++)
	for (unsigned vbus = 0; vbus < 2; vbus++)
	for (unsigned force = 0; force < 2; force++)
	for (unsigned dual = 0; dual < 2; dual++)
	for (unsigned poll = 0; poll < 2; poll++)
	for (unsigned retire = 0; retire < 5; retire++) {
		reset();
		cable_id = id;
		cable_vbus = vbus;
		data.force_session_end = force;
		cfg.phy0_dual_route = dual;
		polling = poll;
		action_cable = retire ? (retire <= 2 ? 1 : 2) : 0;
		rebind = retire == 2 || retire == 4;
		sun4i_usb_phy0_id_vbus_det_scan(&data.detect.work);
		assert(!phy0.mutex.held && reads == 2);
		assert(notified[0] == 1);
		assert(notified[1] == (retire == 1 || retire == 2 ? 0U : 1U));
		assert(data.detect.pending == (rebind || (!retire && poll)));
		if (rebind)
			assert(data.detect.delay == 0 && data.phy0_generation == 2);
		scenarios++;
	}
	reset();
	data.phy0_init = false;
	powered = false;
	sun4i_usb_phy0_id_vbus_det_scan(&data.detect.work);
	assert(!reads && !writes && !data.detect.pending);
	scenarios++;
	reset();
	sun4i_usb_phy0_id_vbus_det_irq(1, &data);
	assert(data.detect.pending && data.detect.delay == DEBOUNCE_TIME);
	data.detect.pending = false;
	sun4i_usb_phy0_vbus_notify(&data.vbus_power_nb, PSY_EVENT_PROP_CHANGED, &supply);
	assert(data.detect.pending && data.detect.delay == DEBOUNCE_TIME);
	scenarios++;
	printf("Sun4i PHY detector: %u generation/resource/poll scenarios passed\n", scenarios);
	return 0;
}
