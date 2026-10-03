/* SPDX-License-Identifier: GPL-2.0-only */
/* Execute the actual TP_printk expression with independent printer/record status. */
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

struct endpoint_record {
	const char *name;
	unsigned maxpacket, maxpacket_limit, max_streams, mult, maxburst;
	unsigned address;
	bool claimed, enabled;
	int ret;
};

static void format(char *buffer, size_t size,
		   const struct endpoint_record *record, int printer_status)
{
	const struct endpoint_record *__entry = record;
	int ret = printer_status;
	(void)ret;
#define __get_str(member) (__entry->member)
#define TP_printk(...) snprintf(buffer, size, __VA_ARGS__)
#include "udc_ep_format.h"
#undef TP_printk
#undef __get_str
}

int main(void)
{
	const int results[] = {0, 1, 17, -5, -19, -22, -108};
	const int printer_statuses[] = {0, 1, 2};
	const char *names[] = {"ep0", "ep1out", "ep2in"};
	unsigned scenarios = 0;
	for (unsigned n = 0; n < 3; n++)
	for (unsigned claimed = 0; claimed < 2; claimed++)
	for (unsigned enabled = 0; enabled < 2; enabled++)
	for (unsigned r = 0; r < sizeof(results) / sizeof(*results); r++)
	for (unsigned p = 0; p < 3; p++) {
		struct endpoint_record record = {
			.name = names[n], .maxpacket = 16, .maxpacket_limit = 512,
			.max_streams = 3, .mult = 2, .maxburst = 4,
			.address = 0x80 + n, .claimed = claimed,
			.enabled = enabled, .ret = results[r],
		};
		char actual[256], expected[256];
		format(actual, sizeof(actual), &record, printer_statuses[p]);
		snprintf(expected, sizeof(expected),
			 "%s: mps 16/512 streams 3 mult 2 burst 4 addr %02x %s:%s --> %d",
			 names[n], 0x80 + n, claimed ? "claimed" : "released",
			 enabled ? "enabled" : "disabled", results[r]);
		assert(!strcmp(actual, expected));
		scenarios++;
	}
	printf("UDC trace: %u actual-format scenarios passed\n", scenarios);
	return 0;
}
