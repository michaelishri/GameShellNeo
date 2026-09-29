/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Experimental CPI v3.1 policy; included after struct axp20x_usb_power. */
#ifndef AXP20X_USB_GAMESHELLNEO_H
#define AXP20X_USB_GAMESHELLNEO_H

#define GAMESHELLNEO_ABSENT_POLL msecs_to_jiffies(250)

static bool gameshellneo_slow_poll;
module_param(gameshellneo_slow_poll, bool, 0444);
MODULE_PARM_DESC(gameshellneo_slow_poll,
	"Opt in to guarded CPI v3.1 peripheral USB absent polling (experimental)");

static bool gameshellneo_node_enabled(struct device_node *node)
{
	struct device_node *parent;

	for (parent = of_node_get(node); parent;
	     parent = of_get_next_parent(parent)) {
		if (!of_device_is_available(parent)) {
			of_node_put(parent);
			return false;
		}
	}
	return true;
}

/* The inherited sunxi connector notification must come from this same PHY. */
static bool gameshellneo_usb_extcon(struct device_node *node, struct device_node *phy)
{
	struct device_node *target;
	unsigned int port;
	bool valid;

	if (of_property_count_u32_elems(node, "extcon") != 2 ||
	    of_property_read_u32_index(node, "extcon", 1, &port) || port != 0)
		return false;
	target = of_parse_phandle(node, "extcon", 0);
	valid = target == phy;
	of_node_put(target);
	return valid;
}

/* Count consumers, rather than accepting the first matching phandle. */
static bool gameshellneo_usb_graph(struct device_node *supply)
{
	struct device_node *node, *target, *phy = NULL;
	struct of_phandle_args args;
	const char *mode;
	unsigned int cells, consumers = 0;
	int count, i;
	bool valid = false;

	for_each_of_allnodes(node) {
		if (!gameshellneo_node_enabled(node) ||
		    !of_property_present(node, "usb0_vbus_power-supply"))
			continue;
		if (of_property_count_u32_elems(node, "usb0_vbus_power-supply") != 1)
			goto out;
		target = of_parse_phandle(node, "usb0_vbus_power-supply", 0);
		if (!target)
			goto out;
		if (target == supply) {
			of_node_put(target);
			if (phy || !of_device_is_compatible(node, "allwinner,sun8i-a33-usb-phy"))
				goto out;
			phy = of_node_get(node);
		} else {
			of_node_put(target);
		}
	}
	if (!phy || of_property_read_u32(phy, "#phy-cells", &cells) || cells != 1 ||
	    of_property_present(phy, "usb0_vbus-supply") ||
	    of_property_present(phy, "usb0_vbus_det-gpios") ||
	    of_property_present(phy, "usb0_vbus_det-gpio") ||
	    of_property_present(phy, "usb0_id_det-gpios") ||
	    of_property_present(phy, "usb0_id_det-gpio"))
		goto out;

	for_each_of_allnodes(node) {
		if (!gameshellneo_node_enabled(node) ||
		    !of_property_present(node, "phys"))
			continue;
		count = of_count_phandle_with_args(node, "phys", "#phy-cells");
		if (count < 0)
			goto out;
		for (i = 0; i < count; i++) {
			if (of_parse_phandle_with_args(node, "phys", "#phy-cells", i, &args))
				goto out;
			if (args.np != phy) {
				of_node_put(args.np);
				continue;
			}
			of_node_put(args.np);
			if (args.args_count != 1 || args.args[0] > 1)
				goto out;
			/* USB1's EHCI/OHCI keypad consumers are separate. */
			if (args.args[0] != 0)
				continue;
			if (++consumers != 1 || count != 1 ||
			    !of_device_is_compatible(node, "allwinner,sun8i-a33-musb") ||
			    of_property_read_string(node, "dr_mode", &mode) ||
			    strcmp(mode, "peripheral") ||
			    of_property_present(node, "usb-role-switch") ||
			    !gameshellneo_usb_extcon(node, phy) ||
			    of_property_present(node, "vbus-supply"))
				goto out;
		}
	}
	valid = consumers == 1;
out:
	of_node_put(node);
	of_node_put(phy);
	return valid;
}

/* Called only after all IRQ registrations succeed. No PMIC writes. */
static const char *gameshellneo_hardware_refusal(struct axp20x_usb_power *power,
					  struct axp20x_dev *pmic)
{
	struct device_node *parent = power->dev->parent->of_node;
	unsigned int input, gpio;

	if (!of_machine_is_compatible("clockwork,clockworkpi-cpi3") ||
	    !of_machine_is_compatible("allwinner,sun8i-a33") ||
	    pmic->variant != AXP223_ID ||
	    !of_device_is_compatible(parent, "x-powers,axp223") ||
	    !of_device_is_compatible(power->dev->of_node, "x-powers,axp223-usb-power-supply"))
		return "board or PMIC mismatch";
	if (!IS_ENABLED(CONFIG_USB_MUSB_GADGET) ||
	    !IS_ENABLED(CONFIG_USB_MUSB_SUNXI) ||
	    IS_ENABLED(CONFIG_USB_MUSB_HOST) || IS_ENABLED(CONFIG_USB_MUSB_DUAL_ROLE) ||
	    IS_ENABLED(CONFIG_PM_SLEEP) || IS_ENABLED(CONFIG_OF_DYNAMIC))
		return "build allows role, sleep or topology changes";
	if (power->num_irqs != 2 ||
	    strcmp(power->axp_data->irq_names[0], "VBUS_PLUGIN") ||
	    strcmp(power->axp_data->irq_names[1], "VBUS_REMOVAL") ||
	    !power->axp_data->vbus_needs_polling)
		return "unexpected interrupt or polling contract";
	if (of_property_present(parent, "x-powers,drive-vbus-en") ||
	    !gameshellneo_usb_graph(power->dev->of_node))
		return "USB topology or VBUS sourcing mismatch";
	if (regmap_read(power->regmap, AXP20X_VBUS_IPSOUT_MGMT, &input) ||
	    regmap_read(power->regmap, AXP20X_OVER_TMP, &gpio))
		return "PMIC configuration read failed";
	/* N_VBUSEN mode and DRIVEVBUS mux; cached reads are not pin measurements. */
	if ((input & (BIT(7) | BIT(2))) || (gpio & BIT(4)))
		return "PMIC VBUS configuration mismatch";
	return NULL;
}

static const char *gameshellneo_poll_refusal(struct axp20x_usb_power *power,
					  struct axp20x_dev *pmic)
{
	if (!gameshellneo_slow_poll)
		return "opt-in disabled";
	return gameshellneo_hardware_refusal(power, pmic);
}

#endif
