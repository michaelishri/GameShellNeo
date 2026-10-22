/* SPDX-License-Identifier: GPL-2.0-only */
/* Deliberately naive composition controls, not a shipping/installed defect. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#define IRQCHIP_SKIP_SET_WAKE 1
#define IRQ_GET_DESC_CHECK_GLOBAL 0
#define IRQD_WAKEUP_STATE 1
struct device { int unused; };
struct musb { struct device *controller; int nIrq; bool irq_wake, wakeup_initialized; };
struct irq_chip { unsigned flags; int (*irq_set_wake)(void *, unsigned); };
struct irq_data { struct irq_chip *chip; unsigned flags; };
struct irq_desc { struct irq_data irq_data; unsigned wake_depth; };
static struct irq_desc desc;
static unsigned valid_disarms, invalid_disarms, warnings, frees, errors;
static bool fail_disarm;
static struct irq_desc *irq_to_desc(unsigned irq) { assert(irq == 164); return &desc; }
static struct irq_chip *irq_desc_get_chip(struct irq_desc *d) { return d->irq_data.chip; }
static bool irq_is_nmi(struct irq_desc *d) { (void)d; return false; }
static void irqd_set(struct irq_data *d, unsigned flag) { d->flags |= flag; }
static void irqd_clear(struct irq_data *d, unsigned flag) { d->flags &= ~flag; }
static struct irq_desc *get_desc(unsigned irq) { return irq == 164 ? &desc : NULL; }
#define scoped_irqdesc_get_and_buslock(irq, check) \
	for (struct irq_desc *scoped_irqdesc = get_desc(irq); scoped_irqdesc; scoped_irqdesc = NULL)
#define WARN(value, ...) do { if (value) warnings++; } while (0)
#define dev_err(...) do { errors++; } while (0)
int irq_set_irq_wake(unsigned irq, unsigned on);
static int disable_irq_wake(unsigned irq)
{
	if (irq == 164) valid_disarms++; else invalid_disarms++;
	return irq_set_irq_wake(irq, 0);
}
static int chip_wake(void *data, unsigned on)
{ assert(data == &desc.irq_data && !on); return fail_disarm ? -EIO : 0; }
static void free_irq(int irq, struct musb *m) { assert(irq == 164 && m); frees++; }
static int device_init_wakeup(struct device *dev, bool enabled)
{ assert(dev && !enabled); return 0; }

#include "musb_terminal_wake_reference_functions.h"

static struct musb reset(struct device *dev)
{
	static struct irq_chip chip = {.irq_set_wake = chip_wake};
	desc = (struct irq_desc){.irq_data = {.chip = &chip, .flags = IRQD_WAKEUP_STATE}, .wake_depth = 1};
	valid_disarms = invalid_disarms = warnings = frees = errors = 0; fail_disarm = false;
	return (struct musb){.controller = dev, .nIrq = 164, .irq_wake = true};
}

int main(void)
{
	struct device dev;
	struct musb m = reset(&dev);
	/* A single owned cleanup before action release retains correct identity. */
	musb_cleanup_wakeup(&m); reference_free_irq(&m);
	assert(valid_disarms == 1 && !invalid_disarms && !warnings && !errors);
	assert(!desc.wake_depth && !m.irq_wake && frees == 1 && m.nIrq == -ENODEV);

	/* Keeping the number alone permits a second disable of an unowned depth. */
	m = reset(&dev); reference_free_irq_keeps_number(&m); musb_cleanup_wakeup(&m);
	assert(valid_disarms == 2 && !invalid_disarms && warnings == 1 && frees == 1);
	assert(!desc.wake_depth && !m.irq_wake);

	/* Unchanged retirement invalidates the number but leaves the flag set. */
	m = reset(&dev); reference_free_irq(&m); musb_cleanup_wakeup(&m);
	assert(valid_disarms == 1 && invalid_disarms == 1 && errors == 1 && !warnings);
	assert(!desc.wake_depth && m.irq_wake && frees == 1 && m.nIrq == -ENODEV);

	/* A failed final disable is retained by the actual IRQ-core function. */
	m = reset(&dev); fail_disarm = true;
	reference_free_irq(&m); musb_cleanup_wakeup(&m);
	assert(valid_disarms == 1 && invalid_disarms == 1 && errors == 2 && !warnings);
	assert(desc.wake_depth == 1 && m.irq_wake && frees == 1 && m.nIrq == -ENODEV);
	puts("MUSB naive terminal composition: 4 actual-source references reproduced");
	return 0;
}
