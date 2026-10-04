/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual regmap functions; W1C hardware and nested IRQ delivery are shims. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include "power_irq_mask_defs.h"
typedef uint32_t u32;
struct regmap { void *dev; unsigned reg_stride; };
struct regmap_irq { unsigned reg_offset, mask; struct { unsigned types_supported; } type; };
struct regmap_irq_chip {
	bool runtime_pm, init_ack_masked, use_ack, ack_invert, clear_ack, wake_invert, type_in_mask, clear_on_unmask;
	int num_regs, num_config_bases, num_config_regs;
	unsigned mask_base, unmask_base, status_base, ack_base, wake_base, *config_base;
	void (*handle_mask_sync)(int, unsigned, unsigned, void *);
	void *irq_drv_data;
};
struct regmap_irq_chip_data {
	struct regmap *map; struct regmap_irq_chip *chip;
	unsigned mask_buf[5], mask_buf_def[5], *wake_buf, **config_buf, *type_buf;
	bool clear_status; int lock, wake_count, irq;
	u32 (*get_irq_reg)(struct regmap_irq_chip_data *, unsigned, int);
};
struct irq_data { unsigned hwirq; };
static struct regmap_irq_chip_data data;
static struct regmap_irq irqs[4];
static unsigned status[5], enabled[5], delivered[4], acks;
#define dev_err(...) assert(false)
static void *irq_data_get_irq_chip_data(struct irq_data *d) { (void)d; return &data; }
static const struct regmap_irq *irq_to_regmap_irq(struct regmap_irq_chip_data *d, int n)
{ assert(d == &data && n >= 0 && n < 4); return &irqs[n]; }
static u32 address(struct regmap_irq_chip_data *d, unsigned base, int n)
{ assert(d == &data && n >= 0 && n < 5); return base + n; }
static int regmap_read(struct regmap *m, unsigned r, u32 *v)
{ assert(m == data.map && r >= 0x48 && r < 0x4d); *v = status[r - 0x48]; return 0; }
static int regmap_write(struct regmap *m, unsigned r, u32 v)
{ assert(m == data.map && r >= 0x48 && r < 0x4d); status[r - 0x48] &= ~v; acks++; return 0; }
static int regmap_update_bits(struct regmap *m, unsigned r, u32 mask, u32 v)
{ assert(m == data.map && r >= 0x40 && r < 0x45); enabled[r - 0x40] = (enabled[r - 0x40] & ~mask) | (v & mask); return 0; }
static int pm_runtime_get_sync(void *d) { (void)d; assert(false); return 0; }
static void pm_runtime_put(void *d) { (void)d; assert(false); }
static void enable_irq_wake(int n) { (void)n; assert(false); }
static void disable_irq_wake(int n) { (void)n; assert(false); }
static void mutex_unlock(int *l) { assert(*l); *l = 0; }
#include "power_irq_mask_functions.h"
static void change(unsigned n, bool on)
{
	struct irq_data irq = {.hwirq = n}; data.lock = 1;
	if (on) regmap_irq_enable(&irq); else regmap_irq_disable(&irq);
	regmap_irq_sync_unlock(&irq);
}
static void dispatch(void)
{
	for (unsigned i = 0; i < 4; i++)
		if (status[0] & enabled[0] & irqs[i].mask) {
			delivered[i]++; status[0] &= ~irqs[i].mask;
		}
}
static void init(struct regmap *map, struct regmap_irq_chip *chip)
{
	memset(&data, 0, sizeof(data)); memset(status, 0, sizeof(status));
	memset(enabled, 0, sizeof(enabled)); memset(delivered, 0, sizeof(delivered));
	*map = (struct regmap){.reg_stride = 1};
	*chip = (struct regmap_irq_chip){.num_regs = 5, .unmask_base = 0x40,
		.status_base = 0x48, .ack_base = 0x48, .init_ack_masked = true};
	data.map = map; data.chip = chip; data.get_irq_reg = address;
	unsigned masks[] = {ACIN_PLUGIN, ACIN_REMOVAL, VBUS_PLUGIN, VBUS_REMOVAL};
	for (unsigned i = 0; i < 4; i++) { irqs[i].mask = masks[i]; data.mask_buf_def[0] |= masks[i]; }
	enabled[0] = data.mask_buf_def[0]; acks = 0;
}
int main(void)
{
	struct regmap map; struct regmap_irq_chip chip; unsigned cases = 0;
	/* Either supply may resume first. Removal is masked even with plugin wake. */
	for (unsigned plugin_wake = 0; plugin_wake < 2; plugin_wake++)
	for (unsigned first = 0; first < 2; first++) {
		init(&map, &chip);
		for (unsigned i = 0; i < 4; i++) if (!plugin_wake || (i & 1)) change(i, false);
		assert(!(enabled[0] & (ACIN_REMOVAL | VBUS_REMOVAL)));
		status[0] = ACIN_REMOVAL | VBUS_REMOVAL; dispatch();
		assert(!delivered[1] && !delivered[3]);
		/* A bus sync before unmasking the removals acknowledges both. */
		change(first ? 2 : 0, true);
		assert(!status[0] && acks);
		for (unsigned i = 0; i < 4; i++) change(i, true);
		dispatch(); assert(!delivered[1] && !delivered[3]);
		/* A later awake insertion still dispatches normally. */
		status[0] = ACIN_PLUGIN | VBUS_PLUGIN; dispatch();
		assert(delivered[0] == 1 && delivered[2] == 1); cases++;
	}
	/* Unmasked removal is observable; do not generalize the loss to awake edges. */
	init(&map, &chip); status[0] = ACIN_REMOVAL | VBUS_REMOVAL; dispatch();
	assert(delivered[1] == 1 && delivered[3] == 1); cases++;
	/* Masked acknowledgement disabled: the pending edge survives this ordering. */
	init(&map, &chip); chip.init_ack_masked = false;
	change(1, false); status[0] = ACIN_REMOVAL; change(0, true); change(1, true); dispatch();
	assert(delivered[1] == 1); cases++;
	printf("AXP223 masked IRQ: %u source-function scenarios passed\n", cases);
}
