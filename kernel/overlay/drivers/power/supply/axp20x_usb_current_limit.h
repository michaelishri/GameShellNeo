/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef AXP20X_USB_CURRENT_LIMIT_H
#define AXP20X_USB_CURRENT_LIMIT_H

#include <linux/errno.h>

/* Tables are register-indexed, not necessarily sorted; -1 is not finite. */
static inline int axp20x_usb_current_limit_select(const int *table,
		unsigned int count, int requested, unsigned int maximum)
{
	int best = -EINVAL;
	unsigned int i;

	if (requested <= 0)
		return -EINVAL;
	if (maximum && (unsigned int)requested > maximum)
		requested = maximum;

	for (i = 0; i < count; i++) {
		if (table[i] <= 0 || table[i] > requested)
			continue;
		if (best < 0 || table[i] > table[best])
			best = i;
	}
	return best;
}

#endif
