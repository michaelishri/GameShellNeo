/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include "axp20x_usb_current_limit.h"

#define PICK(t, v, cap) axp20x_usb_current_limit_select(t, sizeof(t) / sizeof(t[0]), v, cap)

int main(void)
{
	const int axp223[] = { 900000, 500000, 100000, -1 };
	const int axp221[] = { 900000, 500000, -1, -1 };
	const int axp192[] = { -1, -1, 500000, 100000 };
	const int axp813[] = { 100000, 500000, 900000, 1500000, 2000000,
			      2500000, 3000000, 3500000, 4000000 };
	const int ascending[] = { 100000, 500000, 900000, -1 };
	const int scrambled[] = { -1, 500000, 0, 900000, 100000 };
	const int invalid[] = { -1, 0, -1 };

	assert(PICK(axp223, 100000, 0) == 2);
	assert(PICK(axp223, 500000, 0) == 1);
	assert(PICK(axp223, 900000, 0) == 0);
	assert(PICK(axp223, 499999, 0) == 2);
	assert(PICK(axp223, INT_MAX, 0) == 0);
	assert(PICK(axp223, 900000, 500000) == 1);
	assert(PICK(axp223, 900000, 99999) == -EINVAL);
	assert(PICK(axp223, 99999, 0) == -EINVAL);
	assert(PICK(axp223, 0, 0) == -EINVAL);
	assert(PICK(axp223, -1, 0) == -EINVAL);
	assert(PICK(axp223, INT_MIN, 0) == -EINVAL);
	assert(PICK(axp221, 100000, 0) == -EINVAL);
	assert(PICK(axp221, 500000, 0) == 1);
	assert(PICK(axp221, 900000, 0) == 0);
	assert(PICK(axp192, 900000, 0) == 2);
	assert(PICK(axp192, 100000, 0) == 3);
	assert(PICK(axp192, 99999, 0) == -EINVAL);
	assert(PICK(axp813, 1999999, 0) == 3);
	assert(PICK(axp813, INT_MAX, UINT_MAX) == 8);
	assert(PICK(axp813, 4000000, 1200000) == 2);
	assert(PICK(ascending, 700000, 0) == 1);
	assert(PICK(scrambled, 900000, 0) == 3);
	assert(PICK(invalid, 900000, 0) == -EINVAL);
	assert(axp20x_usb_current_limit_select(axp223, 0, 900000, 0) == -EINVAL);
	puts("current-limit selection: all regression cases passed");
	return 0;
}
