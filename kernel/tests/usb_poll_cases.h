/* SPDX-License-Identifier: GPL-2.0-only */
static unsigned int policy_cases;

static void no_refs(void)
{
	for (unsigned int i = 0; i < node_count; i++)
		assert(nodes[i].refs == 0);
}

static void gate_tests(void)
{
	struct axp20x_dev pmic = { .variant = AXP223_ID };
	struct device parent = { .of_node = &nodes[1] };
	struct device dev = { .parent = &parent, .of_node = &nodes[2] };
	struct axp20x_usb_power power = { .dev = &dev, .num_irqs = 2, .axp_data = &test_data };

	for (unsigned int test = 0; test < 47; test++) {
		reset_graph();
		gameshellneo_slow_poll = true;
		pmic.variant = AXP223_ID;
		power.num_irqs = 2;
		switch (test) {
		case 0: break; /* Intended graph includes both USB1 keypad consumers. */
		case 1: gameshellneo_slow_poll = false; break;
		case 2: board_match = false; break;
		case 3: soc_match = false; break;
		case 4: pmic.variant++; break;
		case 5: nodes[1].compatible = "other"; break;
		case 6: nodes[2].compatible = "other"; break;
		case 7: config_gadget = false; break;
		case 8: config_sunxi = false; break;
		case 9: config_host = true; break;
		case 10: config_dual = true; break;
		case 11: config_sleep = true; break;
		case 12: config_dynamic = true; break;
		case 13: power.num_irqs = 1; break;
		case 14: nodes[1].property_bits = 1U << 8; break;
		case 15: nodes[3].supply_property = false; break;
		case 16: nodes[3].supply_cells = 2; break;
		case 17: nodes[3].supply = NULL; break;
		case 18: nodes[3].supply = &nodes[1]; break;
		case 19: nodes[3].compatible = "other"; break;
		case 20: nodes[3].enabled = false; break;
		case 21: nodes[3].phy_cells = 99; break;
		case 22: nodes[3].phy_cells = 2; break;
		case 23: case 24: case 25: case 26: case 27:
			nodes[3].property_bits = 1U << (test - 23); break;
		case 28: nodes[4].enabled = false; break;
		case 29: nodes[4].phys_property = false; break;
		case 30: nodes[4].phys_count = -EINVAL; break;
		case 31: nodes[4].parse_error = 0; break;
		case 32: nodes[4].phys[0].args_count = 0; break;
		case 33: nodes[4].phys[0].args[0] = 2; break;
		case 34: nodes[4].compatible = "other"; break;
		case 35: nodes[4].mode = NULL; break;
		case 36: nodes[4].mode = "otg"; break;
		case 37: case 39:
			nodes[4].property_bits = 1U << (test - 32); break;
		case 38: nodes[4].extcon = &nodes[1]; break;
		case 40: error_register = 0x30; break;
		case 41: error_register = 0x8f; break;
		case 42: nodes[0].enabled = false; break;
		case 43: nodes[4].extcon = NULL; break;
		case 44: nodes[4].extcon_cells = 1; break;
		case 45: nodes[4].extcon_port = 1; break;
		case 46: nodes[4].extcon_port = -1; break;
		}
		assert((gameshellneo_poll_refusal(&power, &pmic) == NULL) == (test == 0));
		no_refs();
		policy_cases++;
	}
	/* Duplicate consumers and duplicate supplies, including disabled copies. */
	for (unsigned int source = 3; source <= 4; source++) {
		for (unsigned int enabled = 0; enabled <= 1; enabled++) {
			reset_graph();
			gameshellneo_slow_poll = true;
			node_count = 8;
			nodes[7] = nodes[source];
			nodes[7].enabled = enabled;
			assert((gameshellneo_poll_refusal(&power, &pmic) == NULL) == !enabled);
			no_refs();
			policy_cases++;
		}
	}
	/* Every disallowed PMIC control bit; permitted bits remain tolerated. */
	for (unsigned int reg = 0; reg < 2; reg++) {
		for (unsigned int value = 0; value < 256; value++) {
			reset_graph();
			gameshellneo_slow_poll = true;
			if (reg) gpio_config = value; else input_config = value;
			bool allowed = reg ? !(value & 16) : !(value & 132);
			assert((gameshellneo_poll_refusal(&power, &pmic) == NULL) == allowed);
			no_refs();
			policy_cases++;
		}
	}
}

static void rearm_irq(struct delayed_work *work)
{
	struct axp20x_usb_power *power = container_of(work, struct axp20x_usb_power, vbus_detect);
	axp20x_usb_power_irq(0, power);
}

static void state_tests(void)
{
	reset_graph();
	supply.live = true;
	for (unsigned int enabled = 0; enabled <= 1; enabled++)
	for (unsigned int error = 0; error <= 1; error++)
	for (unsigned int old = 0; old <= 48; old += 16)
	for (unsigned int value = 0; value < 256; value++) {
		struct axp20x_usb_power power = {
			.supply = &supply, .axp_data = &test_data, .old_status = old,
			.online = old & 16, .gameshellneo_slow_poll = enabled,
			.vbus_detect = { .initialized = true },
		};
		unsigned int status = value & 48;
		input_status = value;
		error_register = error ? 0 : -1;
		notifications = 0;
		axp20x_usb_power_poll_vbus(&power.vbus_detect.work);
		assert(power.old_status == (error ? old : status));
		assert(power.online == (error ? old & 16 : status & 16));
		assert(notifications == (!error && old != status));
		bool pending = enabled ? error || status != 48 : !(power.online);
		assert(power.vbus_detect.pending == pending);
		if (pending)
			assert(power.vbus_detect.delay == (enabled && !error && !status ? 250 : 50));
		policy_cases++;
	}
	/* IRQ before and after recurring rearm; old mod-rearm would fail case 1. */
	for (unsigned int position = 1; position <= 2; position++) {
		struct axp20x_usb_power power = {
			.supply = &supply, .axp_data = &test_data, .gameshellneo_slow_poll = true,
			.vbus_detect = { .initialized = true },
		};
		input_status = 0;
		error_register = -1;
		race_position = position;
		axp20x_usb_power_poll_vbus(&power.vbus_detect.work);
		assert(power.vbus_detect.pending && power.vbus_detect.delay == 50);
		assert(race_position == 0);
		policy_cases++;
	}
	/* An IRQ already queued 50 ms before this worker finishes its read. */
	{
		struct axp20x_usb_power power = {
			.supply = &supply, .axp_data = &test_data, .gameshellneo_slow_poll = true,
			.vbus_detect = { .initialized = true },
		};
		axp20x_usb_power_irq(0, &power);
		axp20x_usb_power_poll_vbus(&power.vbus_detect.work);
		assert(power.vbus_detect.pending && power.vbus_detect.delay == 50);
		policy_cases++;
	}
	supply.live = false;
}

#ifdef NEO_USB_BOARD_TEST
#include "usb_board_fixture.h"
#endif

int main(void)
{
	gate_tests();
	state_tests();
#ifdef NEO_USB_BOARD_TEST
	board_tests();
#endif
	for (unsigned int early = 0; early <= 1; early++)
	for (unsigned int enabled = 0; enabled <= 1; enabled++) {
		reset_graph();
		gameshellneo_slow_poll = enabled;
		run_early_work = early;
		if (early)
			input_status = 0;
		assert(lifetime_tests() == 0);
		no_refs();
	}
	assert(total_faults == 0);
	printf("USB policy: %u gate/state/race cases and %d probe/unwind cases passed\n",
	       policy_cases, scenarios);
	return 0;
}
