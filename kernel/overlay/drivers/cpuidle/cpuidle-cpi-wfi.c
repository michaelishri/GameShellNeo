// SPDX-License-Identifier: GPL-2.0-only
/* Architectural WFI for ClockworkPi; tick suspension belongs to the core. */
#include <linux/cpuidle.h>
#include <linux/init.h>
#include <linux/module.h>
#include <linux/of.h>

#include <asm/cpuidle.h>

static struct cpuidle_driver cpi_wfi_driver = {
	.name = "cpi_wfi",
	.owner = THIS_MODULE,
	.states = {
		{
			.enter = arm_cpuidle_simple_enter,
			.enter_s2idle = arm_cpuidle_simple_enter,
			.exit_latency = 1,
			.target_residency = 1,
			.name = "WFI",
			.desc = "ARM WFI",
		},
	},
	.safe_state_index = 0,
	.state_count = 1,
};

static int __init cpi_wfi_init(void)
{
	if (!of_machine_is_compatible("clockwork,clockworkpi-cpi3"))
		return -ENODEV;

	return cpuidle_register(&cpi_wfi_driver, NULL);
}
device_initcall(cpi_wfi_init);
