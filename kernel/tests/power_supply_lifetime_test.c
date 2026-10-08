/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual core functions with deterministic workqueue/device API shims.
 * A RUNNING deferred callback is paused before its body, then completed by
 * cancel_delayed_work_sync(). This models a permitted join interleaving,
 * not Linux scheduler concurrency or a physical AXP teardown.
 */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define dev_dbg(...) ((void)0)
#define WARN_ON(value) assert(!(value))
#define spin_lock_irqsave(lock, flags) do { (void)(lock); (flags) = 0; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(lock); (void)(flags); } while (0)

enum deferred_state { PENDING, RUNNING, DONE };
struct work_struct { bool pending; };
struct delayed_work { struct work_struct work; enum deferred_state state; };
struct device { struct device *parent; int kobj; bool locked, released, awake, wake_enabled; };
struct power_supply {
	struct device dev;
	struct work_struct changed_work;
	struct delayed_work deferred_register_work;
	int use_cnt, changed_lock;
	bool changed, removing;
};
static struct power_supply psy;
static struct device parent;
static int system_freezable_wq;
static unsigned queues, joined, cancelled, scenarios;
static bool external_arrival;
void power_supply_changed(struct power_supply *supply);
static void power_supply_deferred_register_work(struct work_struct *work);

static int atomic_dec_return(int *value) { return --*value; }
static void pm_stay_awake(struct device *dev)
{
	assert(!dev->released);
	if (dev->wake_enabled)
		dev->awake = true;
}
static bool queue_work(int queue, struct work_struct *work)
{
	bool already = work->pending;
	(void)queue;
	assert(work == &psy.changed_work && !psy.dev.released);
	work->pending = true;
	queues++;
	return !already;
}
static bool device_trylock(struct device *dev)
{
	if (dev->locked)
		return false;
	dev->locked = true;
	return true;
}
static void device_unlock(struct device *dev)
{
	assert(dev->locked);
	dev->locked = false;
}
static void msleep(int milliseconds)
{
	(void)milliseconds;
	/* Teardown has set removing before joining; a held parent must abort. */
	assert(false);
}
static void cancel_work_sync(struct work_struct *work)
{
	assert(work == &psy.changed_work);
	work->pending = false;
	cancelled++;
}
static void cancel_delayed_work_sync(struct delayed_work *work)
{
	assert(work == &psy.deferred_register_work);
	if (work->state == RUNNING)
		power_supply_deferred_register_work(&work->work);
	/* A pending callback is cancelled, never started by this API. */
	work->state = DONE;
	joined++;
}
static void sysfs_remove_link(int *kobj, const char *name)
{
	(void)name;
	assert(kobj == &psy.dev.kobj);
}
static void power_supply_remove_hwmon_sysfs(struct power_supply *supply) { assert(supply == &psy); }
static void power_supply_remove_triggers(struct power_supply *supply) { assert(supply == &psy); }
static void psy_unregister_thermal(struct power_supply *supply) { assert(supply == &psy); }
static void device_init_wakeup(struct device *dev, bool enabled)
{
	assert(dev == &psy.dev && !enabled);
	dev->wake_enabled = false;
	dev->awake = false;
	/* Separate boundary: a caller that has not stopped external producers. */
	if (external_arrival)
		power_supply_changed(&psy);
}
static void device_unregister(struct device *dev)
{
	assert(dev == &psy.dev && joined == 1 && cancelled == 1);
	dev->released = true;
}

#include "power_supply_lifetime_functions.h"

static void reset(int parent_mode, enum deferred_state state, bool changed)
{
	memset(&psy, 0, sizeof(psy));
	memset(&parent, 0, sizeof(parent));
	queues = joined = cancelled = 0;
	external_arrival = false;
	psy.use_cnt = 1;
	psy.dev.wake_enabled = true;
	psy.dev.parent = parent_mode ? &parent : NULL;
	parent.locked = parent_mode == 2;
	psy.deferred_register_work.state = state;
	if (changed)
		power_supply_changed(&psy);
}

int main(void)
{
	for (int parent_mode = 0; parent_mode < 3; parent_mode++) {
		for (int state = PENDING; state <= DONE; state++) {
			for (int changed = 0; changed < 2; changed++) {
				reset(parent_mode, state, changed);
				power_supply_unregister(&psy);
				bool late = state == RUNNING && parent_mode != 2;
				assert(queues == (unsigned)changed + late);
				assert(psy.changed_work.pending == (late && !EXPECT_REORDERED));
				assert(psy.dev.released && psy.removing && psy.use_cnt == 0);
				assert(parent.locked == (parent_mode == 2));
				scenarios++;
			}
		}
	}
	/* Ordinary deferred registration still emits its first notification. */
	for (int parent_mode = 0; parent_mode < 2; parent_mode++) {
		reset(parent_mode, RUNNING, false);
		power_supply_deferred_register_work(&psy.deferred_register_work.work);
		assert(queues == 1 && psy.changed_work.pending && psy.dev.awake);
		assert(!parent.locked);
		psy.deferred_register_work.state = DONE;
		power_supply_unregister(&psy);
		assert(!psy.changed_work.pending);
		scenarios++;
	}
	/* Reordering only drains the core's deferred producer, not arbitrary IRQs. */
	reset(2, DONE, false);
	external_arrival = true;
	power_supply_unregister(&psy);
	assert(psy.changed_work.pending && psy.dev.released);
	scenarios++;
	printf("%u scenarios: %s order, parent-lock and external-producer boundaries verified\n",
	       scenarios, EXPECT_REORDERED ? "candidate reordered" : "pinned original");
	return 0;
}
