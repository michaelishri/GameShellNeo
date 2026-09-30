/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual PHY scan/IRQ/notifier/PM functions with deterministic API shims.
 * This models workqueue and mutex contracts, not kernel concurrency or MMIO.
 */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define msecs_to_jiffies(ms) (ms)
#define IRQ_HANDLED 1
#define NOTIFY_OK 1
#define PSY_EVENT_PROP_CHANGED 1
#define EXTCON_USB_HOST 0
#define EXTCON_USB 1
#define USB_DR_MODE_OTG 0
#define USB_DR_MODE_PERIPHERAL 1
typedef int irqreturn_t;
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; unsigned disabled; bool pending, running; unsigned delay; };
struct mutex { bool held; };
struct phy { struct mutex mutex; void *data; };
struct device { void *data; };
struct notifier_block { int unused; };
struct power_supply { int unused; };
struct sun4i_usb_phy { struct phy *phy; };
struct sun4i_usb_phy_cfg { bool phy0_dual_route; };
struct sun4i_usb_phy_data {
	struct sun4i_usb_phy phys[1];
	struct delayed_work detect;
	struct notifier_block vbus_power_nb;
	struct power_supply *vbus_power_supply;
	struct sun4i_usb_phy_cfg *cfg;
	bool phy0_init, force_session_end;
	int dr_mode, id_det, vbus_det;
	void *extcon;
};
static struct sun4i_usb_phy_data data;
static struct sun4i_usb_phy_cfg cfg;
static struct phy phy0;
static struct device dev;
static struct power_supply supply, unrelated_supply;
static void *system_wq;
static unsigned reads, writes, notifications[2], scenarios, injections;
static int cable_id, cable_vbus;
static bool bus_available, poll_enabled, force_exit_at_lock;
static int published[2];

void *dev_get_drvdata(struct device *device) { return device->data; }
void *phy_get_drvdata(struct phy *phy) { return phy->data; }
void mutex_lock(struct mutex *mutex)
{
	assert(!mutex->held);
	/* Model phy_exit completing under this same mutex before scan acquires it. */
	if (force_exit_at_lock) {
		data.phy0_init = false;
		force_exit_at_lock = false;
	}
	mutex->held = true;
}
void mutex_unlock(struct mutex *mutex) { assert(mutex->held); mutex->held = false; }
int sun4i_usb_phy0_get_id_det(struct sun4i_usb_phy_data *value)
{
	assert(value == &data && phy0.mutex.held && data.phy0_init && bus_available);
	reads++;
	return cable_id;
}
int sun4i_usb_phy0_get_vbus_det(struct sun4i_usb_phy_data *value)
{
	assert(value == &data && phy0.mutex.held && data.phy0_init && bus_available);
	reads++;
	return cable_vbus;
}
bool sun4i_usb_phy0_have_vbus_det(struct sun4i_usb_phy_data *value) { assert(value == &data); return true; }
bool sun4i_usb_phy0_poll(struct sun4i_usb_phy_data *value) { assert(value == &data); return poll_enabled; }
void sun4i_usb_phy0_set_vbus_detect(struct phy *phy, int value)
{
	assert(phy == &phy0 && phy0.mutex.held && bus_available);
	assert(value == 0 || value == 1);
	writes++;
}
void sun4i_usb_phy0_set_id_detect(struct phy *phy, int value)
{
	assert(phy == &phy0 && phy0.mutex.held && bus_available);
	assert(value == 0 || value == 1);
	writes++;
}
void sun4i_usb_phy_passby(struct sun4i_usb_phy *phy, int value)
{
	assert(phy == &data.phys[0] && bus_available);
	assert(value == 0 || value == 1);
}
void sun4i_usb_phy0_reroute(struct sun4i_usb_phy_data *value, int id)
{
	assert(value == &data && bus_available && (id == 0 || id == 1));
}
void extcon_set_state_sync(void *extcon, unsigned cable, int value)
{
	assert(extcon == data.extcon && cable < 2 && !phy0.mutex.held && bus_available);
	notifications[cable]++;
	published[cable] = value;
}
void msleep(unsigned ms) { assert(ms == 200 || ms == 1000); }
bool mod_delayed_work(void *queue, struct delayed_work *work, unsigned delay)
{
	assert(queue == system_wq && work == &data.detect);
	bool pending = work->pending;
	if (work->disabled)
		return false;
	work->pending = true;
	work->delay = delay;
	return pending;
}
bool queue_delayed_work(void *queue, struct delayed_work *work, unsigned delay)
{
	if (work->pending || work->disabled)
		return false;
	mod_delayed_work(queue, work, delay);
	return true;
}

static irqreturn_t sun4i_usb_phy0_id_vbus_det_irq(int irq, void *dev_id);
static int sun4i_usb_phy0_vbus_notify(struct notifier_block *nb, unsigned long val, void *v);
static void arrivals(void)
{
	if (injections & 1)
		sun4i_usb_phy0_id_vbus_det_irq(0, &data);
	if (injections & 2)
		sun4i_usb_phy0_vbus_notify(&data.vbus_power_nb, PSY_EVENT_PROP_CHANGED, &supply);
}
bool disable_delayed_work_sync(struct delayed_work *work)
{
	assert(!phy0.mutex.held && work == &data.detect);
	bool pending = work->pending;
	work->disabled++;
	work->pending = false;
	if (work->running) {
		/* An in-flight poll's retry is rejected while being drained. */
		mod_delayed_work(system_wq, work, 250);
		work->running = false;
	}
	arrivals();
	return pending;
}
bool cancel_delayed_work_sync(struct delayed_work *work)
{
	bool pending = work->pending;
	work->pending = work->running = false;
	arrivals(); /* Unlike disabling, cancellation permits a new arrival. */
	return pending;
}
bool enable_delayed_work(struct delayed_work *work)
{
	assert(work->disabled == 1);
	work->disabled--;
	arrivals();
	return true;
}

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#include "usb_phy_suspend_functions.h"
#pragma GCC diagnostic pop

static void reset(void)
{
	memset(&data, 0, sizeof(data));
	memset(&cfg, 0, sizeof(cfg));
	memset(&phy0, 0, sizeof(phy0));
	memset(notifications, 0, sizeof(notifications));
	data.phys[0].phy = &phy0;
	data.phy0_init = true;
	data.vbus_power_supply = &supply;
	data.cfg = &cfg;
	data.dr_mode = USB_DR_MODE_PERIPHERAL;
	data.id_det = data.vbus_det = -1;
	phy0.data = &data.phys[0];
	dev.data = &data;
	reads = writes = injections = 0;
	published[0] = published[1] = -1;
	bus_available = true;
	poll_enabled = force_exit_at_lock = false;
	cable_id = cable_vbus = 1;
}

static void run_scan(void)
{
	assert(!data.detect.disabled && !data.detect.running);
	data.detect.pending = false;
	data.detect.running = true;
	sun4i_usb_phy0_id_vbus_det_scan(&data.detect.work);
	data.detect.running = false;
	assert(!phy0.mutex.held);
}

static void scan_checks(void)
{
	for (unsigned missing = 0; missing < 3; missing++) {
		reset();
		if (missing == 0) data.phys[0].phy = NULL;
		if (missing == 1) data.phy0_init = false;
		if (missing == 2) force_exit_at_lock = true;
		bus_available = false;
		run_scan();
		assert(!reads && !writes && !notifications[0] && !notifications[1]);
		assert(!data.detect.pending);
		scenarios++;
	}
	for (unsigned id = 0; id < 2; id++)
	for (unsigned vbus = 0; vbus < 2; vbus++)
	for (unsigned poll = 0; poll < 2; poll++)
	for (unsigned otg = 0; otg < 2; otg++) {
		reset();
		cable_id = id; cable_vbus = vbus; poll_enabled = poll;
		data.dr_mode = otg ? USB_DR_MODE_OTG : USB_DR_MODE_PERIPHERAL;
		data.force_session_end = true;
		cfg.phy0_dual_route = true;
		run_scan();
		assert(reads == 2 && data.id_det == (int)id && data.vbus_det == (int)vbus);
		assert(published[0] == !id && published[1] == (int)vbus);
		assert(notifications[0] == 1 && notifications[1] == 1);
		assert(data.detect.pending == poll);
		assert(!poll || data.detect.delay == POLL_TIME);
		run_scan();
		assert(reads == 4 && notifications[0] == 1 && notifications[1] == 1);
		scenarios++;
	}
	reset();
	sun4i_usb_phy0_vbus_notify(&data.vbus_power_nb, PSY_EVENT_PROP_CHANGED, &unrelated_supply);
	sun4i_usb_phy0_vbus_notify(&data.vbus_power_nb, 0, &supply);
	assert(!data.detect.pending);
	scenarios++;
}

static void pm_checks(void)
{
	for (unsigned initial = 0; initial < 4; initial++)
	for (unsigned irq = 0; irq < 4; irq++)
	for (unsigned poll = 0; poll < 2; poll++) {
		reset();
		injections = irq; poll_enabled = poll;
		data.detect.pending = initial & 1;
		data.detect.running = initial & 2;
		for (unsigned repeat = 0; repeat < 4; repeat++) {
			assert(sun4i_usb_phy_suspend(&dev) == 0);
			assert(data.detect.disabled == 1 && !data.detect.pending && !data.detect.running);
			bus_available = false;
			arrivals();
			assert(!data.detect.pending && !data.detect.running);
			/* A supplier failure uses the same resume callback to unwind. */
			bus_available = true;
			cable_vbus = !cable_vbus;
			assert(sun4i_usb_phy_resume(&dev) == 0);
			assert(!data.detect.disabled && data.detect.pending && data.detect.delay == DEBOUNCE_TIME);
			run_scan();
			assert(published[1] == cable_vbus);
			scenarios++;
		}
	}
}

int main(void)
{
	scan_checks();
	pm_checks();
	printf("Sun4i PHY suspend: %u scan/notification/drain/requeue/recovery scenarios passed\n", scenarios);
	return 0;
}
