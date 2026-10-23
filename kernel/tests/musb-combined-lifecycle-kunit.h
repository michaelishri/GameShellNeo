/* SPDX-License-Identifier: GPL-2.0-only */
/* Inlined only into the three translation units in the disposable test view. */
#ifndef NEO_COMBINED_LIFECYCLE_KUNIT_H
#define NEO_COMBINED_LIFECYCLE_KUNIT_H

#include <kunit/test.h>
#include <linux/atomic.h>
#include <linux/completion.h>
#include <linux/device.h>
#include <linux/phy/phy.h>

struct musb;
struct musb_hdrc_config;
struct musb_platform_ops;
struct extcon_dev;

struct neo_joined_gate {
	atomic_t armed;
	struct completion entered;
	struct completion release;
};

struct neo_joined_lifetime {
	struct kunit *test;
	struct device *parent;
	struct device *controller;
	struct phy *phy;
	struct extcon_dev *extcon;
	struct musb *musb;
	void *sunxi_private;
	void *phy_private;
	void __iomem *registers;
	size_t register_bytes;
	atomic_t backend_clock;
	atomic_t phy_clock;
	atomic_t bad_access;
	atomic_t phy_access;
	atomic_t notification_calls;
	atomic_t work_calls;
	bool fail_phy;
	bool work_disable_control;
	bool vbus_level;
	bool notifier_linked;
	struct neo_joined_gate notifier_gate;
	struct neo_joined_gate work_gate;
	struct neo_joined_gate scan_gate;
	struct completion notifier_retiring;
	struct completion work_retiring;
	struct completion irq_retiring;
};

extern struct neo_joined_lifetime *neo_joined_current;
void neo_joined_gate_wait(struct neo_joined_gate *gate);
int neo_joined_phy_prepare(struct neo_joined_lifetime *life);
void neo_joined_phy_destroy(struct neo_joined_lifetime *life);
void neo_joined_phy_flush(struct neo_joined_lifetime *life);
void neo_joined_phy_irq(struct neo_joined_lifetime *life);
u64 neo_joined_phy_generation(struct neo_joined_lifetime *life);
bool neo_joined_phy_active(struct neo_joined_lifetime *life);
bool neo_joined_phy_current_level(struct neo_joined_lifetime *life);
int neo_joined_sunxi_prepare(struct neo_joined_lifetime *life);
void neo_joined_sunxi_destroy(struct neo_joined_lifetime *life);
const struct musb_platform_ops *neo_joined_sunxi_ops(struct neo_joined_lifetime *life);
const struct musb_hdrc_config *neo_joined_sunxi_config(void);
void neo_joined_sunxi_flush(struct neo_joined_lifetime *life);
void neo_joined_sunxi_recover(struct neo_joined_lifetime *life);
bool neo_joined_sunxi_late_queue(struct neo_joined_lifetime *life);
bool neo_joined_sunxi_notifier_linked(struct neo_joined_lifetime *life);
void neo_joined_sunxi_control_cleanup(struct neo_joined_lifetime *life);

#endif
