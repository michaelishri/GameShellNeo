/* SPDX-License-Identifier: GPL-2.0-only */
/* Run the real probe/IRQ/poll code with deterministic devres/workqueue shims.
 * This checks ownership and adversarial unwind ordering, not kernel timing.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

#define BIT(n) (1U << (n))
#define __counted_by(member)
#define GFP_KERNEL 0
#define IRQ_HANDLED 1
#define DRVNAME "axp20x-usb-power-supply"
#define AXP20X_PWR_INPUT_STATUS 0
#define AXP20X_PWR_STATUS_VBUS_PRESENT BIT(5)
#define AXP20X_PWR_STATUS_VBUS_USED BIT(4)
#define DEBOUNCE_TIME 50
#define IS_ENABLED(option) 0
#define IS_ERR(ptr) ((intptr_t)(ptr) < 0 && (intptr_t)(ptr) > -4096)
#define PTR_ERR(ptr) ((int)(intptr_t)(ptr))
#define ERR_PTR(value) ((void *)(intptr_t)(value))
#define struct_size(ptr, member, count) (sizeof(*(ptr)) + sizeof((ptr)->member[0]) * (count))
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define dev_dbg(...) ((void)0)
#define dev_err(...) ((void)0)

typedef int irqreturn_t;
struct device { struct device *parent; void *of_node, *drvdata; };
struct platform_device { struct device dev; };
struct regmap { int unused; };
struct regmap_field { int unused; };
struct reg_field { unsigned int reg, lsb, msb; };
struct power_supply_desc { int unused; };
struct power_supply { bool live; };
struct power_supply_config { void *fwnode, *drv_data; };
struct iio_channel { int unused; };
struct work_struct { int unused; };
struct delayed_work {
	struct work_struct work;
	void (*callback)(struct work_struct *);
	bool initialized, pending;
};
struct axp20x_dev { struct regmap *regmap; void *regmap_irqc; };

#include "usb_structs.h"

enum resource { MEMORY, SUPPLY, CANCEL, IRQ };
enum failure { NONE, ALLOC, FIELD, OPTIONAL, SUPPLY_REGISTER, CANCEL_REGISTER,
	IRQ_LOOKUP_0, IRQ_LOOKUP_1, IRQ_REQUEST_0, IRQ_REQUEST_1 };
static enum resource resources[16];
static unsigned int resource_count, irq_count, immediate_mask, notifications;
static enum failure fail_at;
static int faults, total_faults, scenarios;
static struct axp20x_usb_power *allocated;
static struct power_supply supply;
static struct regmap_field field;
static struct delayed_work *recorded_work;
static const struct axp_data test_data;
static void *system_power_efficient_wq;

static void fault(const char *message)
{
	faults++;
	fprintf(stderr, "lifetime violation: %s\n", message);
}

static void push(enum resource resource)
{
	if (resource_count == sizeof(resources) / sizeof(resources[0]))
		abort();
	resources[resource_count++] = resource;
}

static void *dev_get_drvdata(struct device *dev) { return dev->drvdata; }
static void platform_set_drvdata(struct platform_device *pdev, void *data) { pdev->dev.drvdata = data; }
static bool of_device_is_available(void *node) { return node != NULL; }
static const void *of_device_get_match_data(struct device *dev) { (void)dev; return &test_data; }
static void *dev_fwnode(struct device *dev) { return dev->of_node; }

static void *devm_kzalloc(struct device *dev, size_t bytes, int flags)
{
	(void)dev; (void)flags;
	if (fail_at == ALLOC)
		return NULL;
	allocated = calloc(1, bytes);
	if (!allocated)
		abort();
	push(MEMORY);
	return allocated;
}

static struct regmap_field *devm_regmap_field_alloc(struct device *dev,
		struct regmap *map, struct reg_field desc)
{
	(void)dev; (void)map; (void)desc;
	return fail_at == FIELD ? ERR_PTR(-ENOMEM) : &field;
}

static int axp20x_regmap_field_alloc_optional(struct device *dev, struct regmap *map,
		struct reg_field desc, struct regmap_field **result)
{
	(void)dev; (void)map; (void)desc;
	*result = NULL; /* The AXP223 path has no optional fields. */
	return fail_at == OPTIONAL ? -ENOMEM : 0;
}

static void axp20x_usb_power_parse_dt(struct device *dev, struct axp20x_usb_power *power)
{
	(void)dev; (void)power;
}

static int regmap_field_write(struct regmap_field *reg, unsigned int value)
{
	(void)reg; (void)value;
	fault("unexpected hardware write on the AXP223 test path");
	return -EINVAL;
}

static int regmap_read(struct regmap *map, unsigned int reg, unsigned int *value)
{
	(void)map; (void)reg;
	/* Force a new status notification if work runs after unregister. */
	*value = AXP20X_PWR_STATUS_VBUS_PRESENT;
	return 0;
}

static void power_supply_changed(struct power_supply *psy)
{
	if (!psy || !psy->live)
		fault("poll/IRQ accessed an unregistered supply");
	notifications++;
}

static bool queue_delayed_work(void *queue, struct delayed_work *work, unsigned long delay)
{
	bool pending = work->pending;
	(void)queue; (void)delay;
	if (!work->initialized)
		fault("IRQ queued work before initialization");
	work->pending = true;
	return !pending;
}

static bool mod_delayed_work(void *queue, struct delayed_work *work, unsigned long delay)
{
	return !queue_delayed_work(queue, work, delay);
}

static int devm_delayed_work_autocancel(struct device *dev, struct delayed_work *work,
		void (*callback)(struct work_struct *))
{
	(void)dev;
	work->initialized = true;
	work->callback = callback;
	recorded_work = work;
	if (fail_at == CANCEL_REGISTER)
		return -ENOMEM;
	push(CANCEL);
	return 0;
}

static struct power_supply *devm_power_supply_register(struct device *dev,
		const struct power_supply_desc *desc, struct power_supply_config *config)
{
	(void)dev; (void)desc; (void)config;
	if (fail_at == SUPPLY_REGISTER)
		return ERR_PTR(-ENOMEM);
	supply.live = true;
	push(SUPPLY);
	return &supply;
}

static int platform_get_irq_byname(struct platform_device *pdev, const char *name)
{
	unsigned int index = !strcmp(name, "VBUS_REMOVAL");
	(void)pdev;
	if (fail_at == (index ? IRQ_LOOKUP_1 : IRQ_LOOKUP_0))
		return -ENXIO;
	return (int)index;
}

static int regmap_irq_get_virq(void *data, unsigned int irq) { (void)data; return (int)irq; }

static int devm_request_any_context_irq(struct device *dev, unsigned int irq,
		irqreturn_t (*handler)(int, void *), unsigned long flags, const char *name, void *data)
{
	(void)dev; (void)flags; (void)name;
	if (fail_at == (irq ? IRQ_REQUEST_1 : IRQ_REQUEST_0))
		return -EBUSY;
	push(IRQ);
	irq_count++;
	if (immediate_mask & BIT(irq))
		handler((int)irq, data);
	return 0;
}

/* Match the kernel's treatment of these existing upstream warnings while
 * retaining -Wextra/-Werror for the harness itself. */
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wsign-compare"
#include "usb_callbacks.h"
#include "usb_probe.h"
#pragma GCC diagnostic pop

static const char * const irq_names[] = { "VBUS_PLUGIN", "VBUS_REMOVAL" };
static const struct axp_data test_data = {
	.irq_names = irq_names,
	.num_irq_names = 2,
	.vbus_needs_polling = true,
	.axp20x_read_vbus = axp20x_usb_power_poll_vbus,
};

static void unwind(void)
{
	while (resource_count) {
		switch (resources[--resource_count]) {
		case IRQ:
			irq_count--;
			break;
		case CANCEL:
			if (irq_count)
				fault("IRQ source still active during final work cancellation");
			recorded_work->pending = false;
			break;
		case SUPPLY:
			supply.live = false;
			/* Legal adversarial schedule: the timer expires immediately
			 * after unregister, before the next devres action runs. */
			if (recorded_work && recorded_work->pending) {
				recorded_work->pending = false;
				recorded_work->callback(&recorded_work->work);
			}
			break;
		case MEMORY:
			if (recorded_work && recorded_work->pending)
				fault("work remains pending when driver memory is released");
			free(allocated);
			allocated = NULL;
			recorded_work = NULL;
			break;
		}
	}
}

int main(void)
{
	struct regmap regmap = { 0 };
	struct axp20x_dev pmic = { .regmap = &regmap };
	struct device parent = { .drvdata = &pmic };
	struct platform_device pdev = { .dev = { .parent = &parent, .of_node = &pdev } };

	for (unsigned int failure = NONE; failure <= IRQ_REQUEST_1; failure++) {
		for (unsigned int mask = 0; mask < 4; mask++) {
			fail_at = (enum failure)failure;
			immediate_mask = mask;
			faults = 0;
			notifications = 0;
			int result = axp20x_usb_power_probe(&pdev);
			if ((failure == NONE) != (result == 0))
				fault("probe result did not match the injected failure");
			if (result == 0 && (!recorded_work || !recorded_work->pending))
				fault("initial offline read was not queued");
			if (result == 0 && notifications != (unsigned int)__builtin_popcount(mask))
				fault("immediate IRQ notification was lost");
			unwind();
			if (irq_count || allocated || supply.live)
				fault("owned resources leaked after unwind");
			total_faults += faults;
			scenarios++;
		}
	}
	printf("USB lifetime: %d probe/unwind scenarios, %d violations\n", scenarios, total_faults);
	return total_faults ? EXIT_FAILURE : EXIT_SUCCESS;
}
