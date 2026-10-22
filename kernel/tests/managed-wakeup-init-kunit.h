/* SPDX-License-Identifier: GPL-2.0 */
#ifndef NEO_MANAGED_WAKEUP_INIT_KUNIT_H
#define NEO_MANAGED_WAKEUP_INIT_KUNIT_H

#include <linux/types.h>

struct device;
struct wakeup_source;

#ifdef CONFIG_NEO_MANAGED_WAKEUP_INIT_KUNIT_TEST
bool neo_managed_wakeup_source_fail(const char *name);
void neo_managed_wakeup_created(struct wakeup_source *ws);
void neo_managed_wakeup_freeing(struct wakeup_source *ws);
bool neo_managed_wakeup_action_fail(struct device *dev,
				  void (*action)(void *), void *data);
#else
static inline bool neo_managed_wakeup_source_fail(const char *name)
{
	return false;
}

static inline void neo_managed_wakeup_created(struct wakeup_source *ws) { }
static inline void neo_managed_wakeup_freeing(struct wakeup_source *ws) { }

static inline bool neo_managed_wakeup_action_fail(struct device *dev,
					       void (*action)(void *), void *data)
{
	return false;
}
#endif
#endif
