/* Actual wakeup_store frontend with bounded API/lock boundary observations.
 * Real allocation, sysfs, SRCU and worker lifetime are qualified in KUnit.
 */
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>

struct device_attribute { int unused; };
struct device {
	struct {
		bool can_wakeup;
		void *wakeup;
		int lock;
	} power;
	int next_error;
	unsigned int calls;
};

static int existing_source, attached_source;

static bool device_can_wakeup(struct device *dev)
{
	return dev->power.can_wakeup;
}

static inline void spin_lock_irq(int *lock)
{
	assert(!*lock);
	*lock = 1;
}

static inline void spin_unlock_irq(int *lock)
{
	assert(*lock == 1);
	*lock = 0;
}

static bool sysfs_streq(const char *value, const char *expected)
{
	size_t length = strlen(expected);

	return !strncmp(value, expected, length) &&
		(!value[length] || (value[length] == '\n' && !value[length + 1]));
}

static int device_set_wakeup_enable(struct device *dev, bool enable)
{
	int error = dev->next_error;

	/* The real API may allocate and sleep; the frontend must release its lock. */
	assert(!dev->power.lock);
	dev->calls++;
	dev->next_error = 0;
	if (!enable) {
		dev->power.wakeup = NULL;
		return 0;
	}
	if (error == -EEXIST)
		dev->power.wakeup = &attached_source;
	if (error)
		return error;
	if (dev->power.wakeup)
		return -EEXIST;
	dev->power.wakeup = &attached_source;
	return 0;
}

#include "wakeup-sysfs-functions.h"

static struct device initial(bool enabled)
{
	struct device dev = { .power.can_wakeup = true };

	if (enabled)
		dev.power.wakeup = &existing_source;
	return dev;
}

static int observation(const char *name, struct device *dev, ssize_t result,
		       ssize_t expected, bool policy, bool additional)
{
	bool passed = result == expected && !!dev->power.wakeup == policy &&
		!dev->power.lock && additional;

	printf("%s %s result=%zd expected=%zd policy=%u calls=%u\n",
	       passed ? "PASS" : "FAIL", name, result, expected,
	       !!dev->power.wakeup, dev->calls);
	return !passed;
}

int main(void)
{
	static const char * const errors[] = {
		"object_alloc_error", "name_alloc_error", "id_alloc_error", "registration_error"
	};
	struct device dev;
	ssize_t result, malformed;
	unsigned int i;
	int failures = 0;

	dev = initial(false);
	result = wakeup_store(&dev, NULL, "enabled\n", 8);
	failures += observation("enable", &dev, result, 8, true, true);

	dev = initial(true);
	result = wakeup_store(&dev, NULL, "disabled\n", 9);
	failures += observation("disable", &dev, result, 9, false, true);

	dev = initial(true);
	dev.next_error = -ENOMEM;
	result = wakeup_store(&dev, NULL, "enabled\n", 8);
	failures += observation("enabled_idempotent", &dev, result, 8, true,
				dev.power.wakeup == &existing_source);

	dev = initial(false);
	result = wakeup_store(&dev, NULL, "disabled\n", 9);
	failures += observation("disabled_idempotent", &dev, result, 9, false, true);

	dev = initial(false);
	malformed = wakeup_store(&dev, NULL, "Enabled\n", 8);
	dev.power.can_wakeup = false;
	result = wakeup_store(&dev, NULL, "enabled\n", 8);
	failures += observation("invalid_request", &dev, result, -EINVAL, false,
				malformed == -EINVAL && !dev.calls);

	for (i = 0; i < sizeof(errors) / sizeof(errors[0]); i++) {
		dev = initial(false);
		/* Public API collapses each lower registration/allocation failure. */
		dev.next_error = -ENOMEM;
		result = wakeup_store(&dev, NULL, "enabled\n", 8);
		failures += observation(errors[i], &dev, result, -ENOMEM, false, dev.calls == 1);
	}

	dev = initial(false);
	/* Another writer attaches after the initial disabled observation. */
	dev.next_error = -EEXIST;
	result = wakeup_store(&dev, NULL, "enabled\n", 8);
	failures += observation("concurrent_enable", &dev, result, 8, true, true);
	return failures ? 1 : 0;
}
