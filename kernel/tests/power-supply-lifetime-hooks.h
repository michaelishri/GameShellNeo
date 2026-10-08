/* SPDX-License-Identifier: GPL-2.0-only */
/* Included only in the isolated KUnit build, never the board patch queue. */
#include <kunit/test.h>
#include <linux/completion.h>
#include <linux/kthread.h>

enum psy_test_point {
	PSY_DEFER_ENTER,
	PSY_PARENT_BLOCKED,
	PSY_DEFER_NOTIFY,
	PSY_DEFER_QUEUED,
	PSY_CHANGED_ENTER,
	PSY_CANCEL_DEFER_BEGIN,
	PSY_CANCEL_CHANGED_BEGIN,
	PSY_CANCEL_CHANGED_DONE,
	PSY_TEST_POINTS,
};

struct psy_lifetime_context {
	struct device *parent;
	struct power_supply *psy;
	struct task_struct *remover;
	struct completion point[PSY_TEST_POINTS];
	struct completion release_deferred;
	struct completion release_changed;
	struct completion removal_done;
	wait_queue_head_t stop_wait;
	bool hold_deferred;
	bool hold_changed;
	bool parent_locked;
	bool removed;
};

static const struct power_supply_desc psy_lifetime_desc;

static void psy_lifetime_hook(struct power_supply *psy, enum psy_test_point point)
{
	struct psy_lifetime_context *ctx;

	if (psy->desc != &psy_lifetime_desc)
		return;
	ctx = power_supply_get_drvdata(psy);
	complete_all(&ctx->point[point]);
	if (point == PSY_DEFER_NOTIFY && ctx->hold_deferred)
		wait_for_completion(&ctx->release_deferred);
	if (point == PSY_CHANGED_ENTER && ctx->hold_changed)
		wait_for_completion(&ctx->release_changed);
	/* Ensure the notification is running before the deferred producer exits. */
	if (point == PSY_DEFER_QUEUED && ctx->hold_deferred)
		wait_for_completion(&ctx->point[PSY_CHANGED_ENTER]);
}
