/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual power-supply producer/worker; deterministic queue/freezer/IRQ shims.
 * This checks their API contract, not Linux scheduler concurrency or PMIC I/O.
 */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define likely(value) (value)
#define unlikely(value) (value)
#define dev_dbg(...) ((void)0)
#define dev_warn(...) ((void)0)
#define ERR_PTR(value) (value)
#define PSY_EVENT_PROP_CHANGED 1
#define KOBJ_CHANGE 1
struct workqueue_struct { bool freezable; };
struct work_struct {
	struct workqueue_struct *queue;
	bool pending, active, running;
};
struct spinlock { bool held; };
struct kobject { int unused; };
struct device { struct kobject kobj; bool wake_enabled, awake; };
struct power_supply {
	struct work_struct changed_work;
	struct spinlock changed_lock;
	struct device dev;
	bool changed, update_groups;
};
static struct { void *groups; } power_supply_dev_type;
static int power_supply_notifier;
static struct workqueue_struct normal_queue, frozen_queue = { .freezable = true };
struct workqueue_struct *system_freezable_wq = &frozen_queue;
static struct power_supply psy;
static bool freezing, suppliers_ready;
static unsigned delivered[4], group_updates, input_state, output_state[4];
static unsigned scenarios, wake_events, relax_calls;
static bool inject_freeze, inject_change;
static int inject_site, group_result;
enum { PRODUCER_UNLOCK, GROUP_UPDATE, CONSUMER, LED, NOTIFIER, UEVENT, WORKER_UNLOCK };
static bool in_producer;
void power_supply_changed(struct power_supply *supply);
static void hook(int site);

static void lock(struct spinlock *value)
{
	assert(!value->held);
	value->held = true;
}
static void unlock(struct spinlock *value)
{
	assert(value->held);
	value->held = false;
	hook(in_producer ? PRODUCER_UNLOCK : WORKER_UNLOCK);
}
#define spin_lock_irqsave(value, flags) do { (flags) = 0; lock(value); } while (0)
#define spin_unlock_irqrestore(value, flags) do { (void)(flags); unlock(value); } while (0)

void pm_stay_awake(struct device *dev)
{
	assert(dev == &psy.dev && psy.changed_lock.held);
	if (dev->wake_enabled) {
		dev->awake = true;
		wake_events++;
	}
}
void pm_relax(struct device *dev)
{
	assert(dev == &psy.dev && psy.changed_lock.held);
	dev->awake = false;
	relax_calls++;
}

bool queue_work(struct workqueue_struct *queue, struct work_struct *work)
{
	assert(!psy.changed_lock.held && work == &psy.changed_work);
	if (work->pending)
		return false;
	work->queue = queue;
	work->pending = true;
	/* Active means counted in nr_active, including queued-but-not-running. */
	work->active = !(freezing && queue->freezable);
	return true;
}
bool schedule_work(struct work_struct *work) { return queue_work(&normal_queue, work); }

static bool freezer_busy(void)
{
	struct work_struct *work = &psy.changed_work;
	return work->queue && work->queue->freezable &&
		(work->active || work->running);
}
static void announce_change(void)
{
	bool previous = in_producer;
	in_producer = true;
	input_state++;
	power_supply_changed(&psy);
	in_producer = previous;
	assert(psy.changed && psy.changed_work.pending);
	assert(psy.dev.awake == psy.dev.wake_enabled);
}
static void hook(int site)
{
	if (inject_site != site)
		return;
	inject_site = -1; /* One arrival; avoid recursive producer hooks. */
	if (inject_freeze) {
		freezing = true;
		if (psy.changed_work.running)
			assert(freezer_busy());
	}
	if (inject_change)
		announce_change();
}
static void notify(unsigned kind, int site)
{
	assert(suppliers_ready && !psy.changed_lock.held);
	hook(site);
	delivered[kind]++;
	output_state[kind] = input_state;
}
int sysfs_update_groups(struct kobject *object, void *groups)
{
	assert(object == &psy.dev.kobj && groups == power_supply_dev_type.groups);
	assert(!psy.changed_lock.held && suppliers_ready);
	group_updates++;
	hook(GROUP_UPDATE);
	return group_result;
}
/* The linked-consumer callback may itself read a supply property. */
static int __power_supply_changed_work(struct power_supply *supply, void *data)
{
	assert(supply == &psy && data == &psy);
	notify(0, CONSUMER);
	return 0;
}
void power_supply_for_each_psy(void *data, int (*fn)(struct power_supply *, void *))
{
	assert(fn(&psy, data) == 0);
}
void power_supply_update_leds(struct power_supply *supply)
{
	assert(supply == &psy);
	notify(1, LED);
}
int blocking_notifier_call_chain(int *chain, unsigned long event, void *data)
{
	assert(chain == &power_supply_notifier && event == PSY_EVENT_PROP_CHANGED && data == &psy);
	notify(2, NOTIFIER);
	return 0;
}
int kobject_uevent(struct kobject *object, int event)
{
	assert(object == &psy.dev.kobj && event == KOBJ_CHANGE);
	notify(3, UEVENT);
	return 0;
}

#include "power_supply_suspend_functions.h"

static bool run_one(void)
{
	struct work_struct *work = &psy.changed_work;
	if (!work->pending || !work->active)
		return false;
	assert(!work->running);
	work->pending = work->active = false;
	work->running = true;
	power_supply_changed_work(work);
	work->running = false;
	assert(!psy.changed_lock.held);
	assert(!psy.changed || !psy.dev.wake_enabled || psy.dev.awake);
	return true;
}
static void drain_active(void)
{
	unsigned budget = 8;
	while (run_one())
		assert(--budget);
}
static void restore_and_thaw(void)
{
	/* Actual PM core resumes devices before thawing on success and unwind. */
	suppliers_ready = true;
	freezing = false;
	if (psy.changed_work.pending)
		psy.changed_work.active = true;
	drain_active();
	assert(!psy.changed && !psy.changed_work.pending && !psy.dev.awake);
	for (unsigned i = 0; i < 4; i++) {
		assert(delivered[i] && output_state[i] == input_state);
	}
}
static void reset(bool wake)
{
	memset(&psy, 0, sizeof(psy));
	memset(delivered, 0, sizeof(delivered));
	memset(output_state, 0, sizeof(output_state));
	psy.dev.wake_enabled = wake;
	suppliers_ready = true;
	freezing = in_producer = inject_freeze = inject_change = false;
	inject_site = -1;
	group_result = 0;
	group_updates = input_state = wake_events = relax_calls = 0;
}

static void awake_checks(bool wake)
{
	reset(wake);
	for (unsigned i = 0; i < 4; i++)
		announce_change();
	assert(run_one());
	assert(!run_one() && !psy.dev.awake && relax_calls == 1);
	for (unsigned i = 0; i < 4; i++)
		assert(delivered[i] == 1 && output_state[i] == 4);
	assert(wake_events == (wake ? 4U : 0U));
	scenarios++;
}

static void frozen_arrivals(bool wake)
{
	for (unsigned pending = 0; pending < 2; pending++)
	for (unsigned abort = 0; abort < 2; abort++) {
		reset(wake);
		if (pending)
			announce_change();
		freezing = true;
		assert(freezer_busy() == (bool)pending);
		drain_active();
		assert(!freezer_busy());
		/* No supplier transition on the early abort path. Both paths thaw. */
		suppliers_ready = abort;
		unsigned prior = delivered[3];
		for (unsigned i = 0; i < 4; i++) {
			announce_change();
			assert(!run_one() && !freezer_busy() && delivered[3] == prior);
		}
		restore_and_thaw();
		scenarios++;
	}
}

static void boundary_checks(bool wake)
{
	/* Freeze between producer unlocking changed_lock and its queue_work. */
	reset(wake);
	inject_site = PRODUCER_UNLOCK;
	inject_freeze = true;
	announce_change();
	assert(freezing && !freezer_busy());
	suppliers_ready = false;
	assert(!run_one());
	restore_and_thaw();
	scenarios++;

	for (int site = GROUP_UPDATE; site <= WORKER_UNLOCK; site++)
	for (unsigned freeze = 0; freeze < 2; freeze++)
	for (unsigned group_error = 0; group_error < 2; group_error++) {
		reset(wake);
		psy.update_groups = true;
		group_result = group_error ? -12 : 0;
		announce_change();
		inject_site = site;
		inject_freeze = freeze;
		inject_change = true;
		assert(run_one());
		assert(inject_site == -1 && input_state == 2 && group_updates == 1);
		if (freeze) {
			assert(!freezer_busy());
			suppliers_ready = false;
			assert(!run_one());
		}
		restore_and_thaw();
		scenarios++;
	}
}

static void repeated_cycles(bool wake)
{
	reset(wake);
	for (unsigned cycle = 0; cycle < 4; cycle++) {
		announce_change();
		freezing = true;
		assert(freezer_busy());
		drain_active();
		assert(!freezer_busy());
		suppliers_ready = false;
		announce_change();
		assert(!run_one());
		restore_and_thaw();
		assert(input_state == (cycle + 1) * 2);
		scenarios++;
	}
}

int main(void)
{
	for (unsigned wake = 0; wake < 2; wake++) {
		awake_checks(wake);
		frozen_arrivals(wake);
		boundary_checks(wake);
		repeated_cycles(wake);
	}
	printf("Power-supply suspend: %u notification/freeze/replay/wake scenarios passed\n", scenarios);
	return 0;
}
