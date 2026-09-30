/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual driver PM/IRQ functions with deterministic work/IRQ API shims.
 * The shims model documented API contracts, not kernel concurrency or timing.
 */
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

#define DEBOUNCE_TIME 50
#define IRQ_HANDLED 1
typedef int irqreturn_t;
struct device { void *data; bool wake; };
struct power_supply { struct device dev; };
struct delayed_work { unsigned disabled; bool pending, running; unsigned delay; };
struct axp20x_usb_power {
	struct power_supply *supply;
	struct delayed_work vbus_detect;
	unsigned num_irqs;
	bool irq_wake_enabled;
	unsigned irqs[4];
};
static struct axp20x_usb_power power;
static struct power_supply supply;
static struct device device;
static void *system_power_efficient_wq;
static unsigned irq_depth[4], wake_depth, notifications, scenarios, injections;
static int enable_error, disable_error;

void *dev_get_drvdata(struct device *dev) { return dev->data; }
bool device_may_wakeup(struct device *dev) { return dev->wake; }
void power_supply_changed(struct power_supply *psy)
{
	assert(psy == &supply);
	notifications++;
}
bool mod_delayed_work(void *queue, struct delayed_work *work, unsigned delay)
{
	bool pending = work->pending;
	(void)queue;
	if (work->disabled)
		return false;
	work->pending = true;
	work->delay = delay;
	return pending;
}

/* Defined by the extracted driver below; used for adversarial wake arrivals. */
static irqreturn_t axp20x_usb_power_irq(int irq, void *devid);

bool disable_delayed_work_sync(struct delayed_work *work)
{
	bool pending = work->pending;
	work->disabled++;
	work->pending = false;
	if (work->running) {
		/* The in-flight poll tries its ordinary retry while being drained. */
		mod_delayed_work(system_power_efficient_wq, work, DEBOUNCE_TIME);
		work->running = false;
	}
	if (injections & 1)
		axp20x_usb_power_irq(0, &power);
	return pending;
}
bool cancel_delayed_work_sync(struct delayed_work *work)
{
	bool pending = work->pending;
	work->pending = work->running = false;
	/* Cancellation alone cannot exclude an IRQ arriving afterwards. */
	if (injections & 1)
		axp20x_usb_power_irq(0, &power);
	return pending;
}
bool enable_delayed_work(struct delayed_work *work)
{
	assert(work->disabled == 1);
	return --work->disabled == 0;
}
int enable_irq_wake(unsigned irq)
{
	assert(irq == 0 && wake_depth == 0);
	if (enable_error)
		return enable_error;
	wake_depth++;
	if (injections & 2)
		axp20x_usb_power_irq(irq, &power);
	return 0;
}
int disable_irq_wake(unsigned irq)
{
	assert(irq == 0 && wake_depth == 1);
	if (disable_error)
		return disable_error;
	wake_depth--;
	if (injections & 4)
		axp20x_usb_power_irq(irq, &power);
	return 0;
}
void disable_irq(unsigned irq)
{
	assert(irq < power.num_irqs && irq_depth[irq] == 0);
	/* Model an already-running handler finishing before masking completes. */
	if (injections & 8)
		axp20x_usb_power_irq(irq, &power);
	irq_depth[irq]++;
}
void enable_irq(unsigned irq)
{
	assert(irq < power.num_irqs && irq_depth[irq] == 1);
	irq_depth[irq]--;
	if (injections & 16)
		axp20x_usb_power_irq(irq, &power);
}

/* Match the kernel's warning policy for the unmodified upstream callbacks. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wsign-compare"
#include "usb_suspend_functions.h"
#pragma GCC diagnostic pop

static void reset(unsigned irqs, bool wake, unsigned arrivals)
{
	memset(&power, 0, sizeof(power));
	memset(irq_depth, 0, sizeof(irq_depth));
	power.supply = &supply;
	power.num_irqs = irqs;
	for (unsigned i = 0; i < irqs; i++)
		power.irqs[i] = i;
	supply.dev.wake = wake;
	device.data = &power;
	wake_depth = notifications = 0;
	enable_error = disable_error = 0;
	injections = arrivals;
}

static void awake(void)
{
	assert(!power.vbus_detect.disabled && !power.vbus_detect.running);
	assert(power.vbus_detect.pending && power.vbus_detect.delay == DEBOUNCE_TIME);
	for (unsigned i = 0; i < power.num_irqs; i++)
		assert(irq_depth[i] == 0);
}

static void cycles(void)
{
	for (unsigned irqs = 2; irqs <= 4; irqs += 2)
	for (unsigned wake = 0; wake < 2; wake++)
	for (unsigned arrivals = 0; arrivals < 32; arrivals++)
	for (unsigned initial = 0; initial < 4; initial++) {
		reset(irqs, wake, arrivals);
		power.vbus_detect.pending = initial & 1;
		power.vbus_detect.running = initial & 2;
		for (unsigned repeat = 0; repeat < 4; repeat++) {
			assert(axp20x_usb_power_suspend(&device) == 0);
			assert(power.vbus_detect.disabled == 1);
			assert(!power.vbus_detect.pending && !power.vbus_detect.running);
			assert(wake_depth == wake);
			for (unsigned i = 0; i < irqs; i++)
				assert(irq_depth[i] == !(wake && i == 0));
			if (wake) {
				axp20x_usb_power_irq(0, &power);
				assert(!power.vbus_detect.pending);
			}
			/* Resume must balance the armed policy, not reread this flag. */
			supply.dev.wake = !wake;
			assert(axp20x_usb_power_resume(&device) == 0);
			awake();
			assert(!wake_depth && !power.irq_wake_enabled);
			supply.dev.wake = wake;
			scenarios++;
		}
	}
}

static void failures(void)
{
	for (unsigned irqs = 2; irqs <= 4; irqs += 2) {
		reset(irqs, true, 31);
		power.vbus_detect.running = power.vbus_detect.pending = true;
		enable_error = -EIO;
		assert(axp20x_usb_power_suspend(&device) == -EIO);
		awake();
		assert(!wake_depth && !power.irq_wake_enabled);
		enable_error = 0;
		assert(axp20x_usb_power_suspend(&device) == 0);
		/* A later driver's failure is unwound via this same resume callback. */
		assert(axp20x_usb_power_resume(&device) == 0);
		awake();
		scenarios++;

		assert(axp20x_usb_power_suspend(&device) == 0);
		disable_error = -EIO;
		assert(axp20x_usb_power_resume(&device) == -EIO);
		awake();
		assert(wake_depth == 1 && power.irq_wake_enabled);
		/* Persistent wake-disable failure rejects sleep but leaves polling on. */
		assert(axp20x_usb_power_suspend(&device) == -EIO);
		awake();
		assert(wake_depth == 1);
		/* Retry balances the old reference even if wake was since disabled. */
		disable_error = 0;
		supply.dev.wake = false;
		assert(axp20x_usb_power_suspend(&device) == 0);
		assert(!wake_depth && !power.irq_wake_enabled);
		for (unsigned i = 0; i < irqs; i++)
			assert(irq_depth[i] == 1);
		assert(axp20x_usb_power_resume(&device) == 0);
		awake();
		scenarios++;
	}
}

int main(void)
{
	cycles();
	failures();
	printf("AXP USB suspend: %u work/IRQ/wake/unwind scenarios passed\n", scenarios);
	return 0;
}
