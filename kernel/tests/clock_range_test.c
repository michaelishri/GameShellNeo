/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Actual extracted search/comparator/boundary code; no hardware operations. */
#include <assert.h>
#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef uint64_t u64;
#define BIT(n) (1UL << (n))
#define do_div(n, base) do { (n) /= (uint32_t)(base); } while (0)
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define max(a, b) ((a) > (b) ? (a) : (b))
#define min(a, b) ((a) < (b) ? (a) : (b))
#define lockdep_assert_held(lock) assert(*(lock))
#define hlist_for_each_entry(pos, head, member) \
	for ((pos) = (head)->first; (pos); (pos) = (pos)->next)

struct clk { unsigned long min_rate, max_rate; struct clk *next; };
struct hlist_head { struct clk *first; };
struct clk_core { unsigned long min_rate, max_rate; struct hlist_head clks; };
struct clk_hw { struct clk_core *core; };
struct ccu_common { struct clk_hw hw; unsigned long features; };
struct ccu_nkm { struct ccu_common common; unsigned long max_m_n_ratio, min_parent_m_ratio; };
static int prepare_lock = 1;
static unsigned long range_queries, nm_cases, nkm_cases, comparator_cases;

#include "clock_range_functions.h"

static struct clk users[2];
static struct clk_core core;
static struct ccu_nkm context;

static void limits(unsigned long low, unsigned long high, unsigned int mode)
{
	/* Exercise both consumer-list walks, not just core constraints. */
	users[0] = (struct clk){ .min_rate = low, .max_rate = ULONG_MAX, .next = &users[1] };
	users[1] = (struct clk){ .min_rate = 0, .max_rate = high };
	core = (struct clk_core){ .min_rate = 0, .max_rate = ULONG_MAX, .clks = { users } };
	context.common.hw.core = &core;
	context.common.features = mode ? CCU_FEATURE_CLOSEST_RATE : 0;
}

static void check_nm(unsigned long parent, unsigned long rate, struct _ccu_nm shape)
{
	struct _ccu_nm before = shape, after = shape;
	unsigned long old_rate, new_rate, old_queries;

	range_queries = 0;
	old_rate = reference_nm_find_best(&context.common, parent, rate, &before);
	old_queries = range_queries;
	range_queries = 0;
	new_rate = candidate_nm_find_best(&context.common, parent, rate, &after);
	assert(old_rate == new_rate && before.n == after.n && before.m == after.m);
	assert(range_queries == 1);
	assert(old_queries == (shape.max_n >= shape.min_n && shape.max_m >= shape.min_m ?
		(shape.max_n - shape.min_n + 1) * (shape.max_m - shape.min_m + 1) : 0));
	nm_cases++;
}

static void check_nkm(unsigned long parent, unsigned long rate, struct _ccu_nkm shape)
{
	struct _ccu_nkm before = shape, after = shape;
	unsigned long old_rate, new_rate, old_queries, expected = 0;

	range_queries = 0;
	old_rate = reference_nkm_find_best(parent, rate, &before, &context.common);
	old_queries = range_queries;
	range_queries = 0;
	new_rate = candidate_nkm_find_best(parent, rate, &after, &context.common);
	assert(old_rate == new_rate && before.n == after.n && before.k == after.k && before.m == after.m);
	assert(range_queries == 1);
	for (unsigned long k = shape.min_k; k <= shape.max_k; k++)
		for (unsigned long n = shape.min_n; n <= shape.max_n; n++)
			for (unsigned long m = shape.min_m; m <= shape.max_m; m++)
				if (ccu_nkm_is_valid_rate(&context.common, parent, n, m))
					expected++;
	assert(old_queries == expected);
	nkm_cases++;
}

static int compare(const void *a, const void *b)
{
	unsigned long x = *(const unsigned long *)a, y = *(const unsigned long *)b;
	return (x > y) - (x < y);
}

static void output_boundaries(bool nkm)
{
	struct _ccu_nm nm = { .min_n = 1, .max_n = 128, .min_m = 1, .max_m = 16 };
	struct _ccu_nkm nkm_shape = { .min_n = 1, .max_n = 32, .min_k = 1, .max_k = 4,
		.min_m = 1, .max_m = 4 };
	unsigned long rates[2048], parent = 24000000;
	size_t count = 0;

	if (nkm) {
		for (unsigned long k = 1; k <= 4; k++)
			for (unsigned long n = 1; n <= 32; n++)
				for (unsigned long m = 1; m <= 4; m++)
					rates[count++] = parent * n * k / m;
	} else {
		for (unsigned long n = 1; n <= 128; n++)
			for (unsigned long m = 1; m <= 16; m++)
				rates[count++] = reference_nm_calc_rate(parent, n, m);
	}
	qsort(rates, count, sizeof(*rates), compare);
	for (unsigned int mode = 0; mode < 2; mode++) {
		limits(0, ULONG_MAX, mode);
		for (size_t i = 0; i < count; i++) {
			if (i && rates[i] == rates[i - 1])
				continue;
			unsigned long requests[] = { rates[i], rates[i] - 1, rates[i] + 1,
				i ? rates[i - 1] + (rates[i] - rates[i - 1]) / 2 : 0 };
			for (size_t j = 0; j < sizeof(requests) / sizeof(*requests); j++) {
				if (nkm)
					check_nkm(parent, requests[j], nkm_shape);
				else
					check_nm(parent, requests[j], nm);
			}
		}
	}
}

static void comparator_edges(void)
{
	unsigned long values[] = { 0, 1, LONG_MAX - 1UL, LONG_MAX, LONG_MAX + 1UL,
		ULONG_MAX - 1, ULONG_MAX };
	unsigned long bounds[][2] = { {0, ULONG_MAX}, {1, ULONG_MAX - 1},
		{24000000, 24000000}, {ULONG_MAX, 0} };

	for (unsigned int mode = 0; mode < 2; mode++)
		for (size_t r = 0; r < sizeof(bounds) / sizeof(*bounds); r++) {
			limits(bounds[r][0], bounds[r][1], mode);
			for (size_t i = 0; i < sizeof(values) / sizeof(*values); i++)
				for (size_t j = 0; j < sizeof(values) / sizeof(*values); j++)
					for (size_t k = 0; k < sizeof(values) / sizeof(*values); k++) {
						range_queries = 0;
						bool a = reference_compare(&context.common, values[i], values[j], values[k]);
						bool b = candidate_compare(&context.common, values[i], values[j], values[k]);
						assert(a == b && range_queries == 2);
						comparator_cases++;
					}
		}
}

static void constraints_and_extremes(void)
{
	unsigned long parents[] = { 0, 1, 32768, 24000000, 297000000, UINT32_MAX, ULONG_MAX };
	unsigned long rates[] = { 0, 1, 24000000, 270000000, 297000000, 432000000,
		LONG_MAX, LONG_MAX + 1UL, ULONG_MAX };
	unsigned long bounds[][2] = { {0, ULONG_MAX}, {1, ULONG_MAX}, {24000000, 24000000},
		{23999999, 24000001}, {270000000, 432000000}, {ULONG_MAX, 0} };
	struct _ccu_nm nm_shapes[] = {
		{ .min_n = 1, .max_n = 128, .min_m = 1, .max_m = 32 }, /* A33 audio integer path */
		{ .min_n = 3, .max_n = 7, .min_m = 2, .max_m = 5 },
		{ .min_n = 1, .max_n = 1, .min_m = 1, .max_m = 1 },
		{ .min_n = 2, .max_n = 1, .min_m = 1, .max_m = 1 },
	};
	struct _ccu_nkm nkm_shape = { .min_n = 1, .max_n = 16, .min_k = 1, .max_k = 4,
		.min_m = 1, .max_m = 16 }; /* A33 MIPI limits, fixed parent only. */

	for (unsigned int mode = 0; mode < 2; mode++)
		for (size_t b = 0; b < sizeof(bounds) / sizeof(*bounds); b++) {
			/* Reuse the same object while changing constraints each iteration. */
			limits(bounds[b][0], bounds[b][1], mode);
			for (size_t p = 0; p < sizeof(parents) / sizeof(*parents); p++)
				for (size_t r = 0; r < sizeof(rates) / sizeof(*rates); r++) {
					for (size_t s = 0; s < sizeof(nm_shapes) / sizeof(*nm_shapes); s++)
						check_nm(parents[p], rates[r], nm_shapes[s]);
					for (unsigned int restriction = 0; restriction < 3; restriction++) {
						context.max_m_n_ratio = restriction ? 1 : 0;
						context.min_parent_m_ratio = restriction == 2 ? ULONG_MAX : 0;
						check_nkm(parents[p], rates[r], nkm_shape);
					}
				}
		}
	context.max_m_n_ratio = context.min_parent_m_ratio = 0;
	nkm_shape.min_k = nkm_shape.max_k + 1;
	check_nkm(24000000, 24000000, nkm_shape); /* Empty search: old0/new1 lookup. */
	limits(0, ULONG_MAX, 0);
	core.min_rate = 300000000;
	core.max_rate = 500000000;
	check_nm(24000000, 432000000, nm_shapes[0]); /* Core and consumer intersection. */
}

int main(void)
{
	struct _ccu_nm nm = { .min_n = 1, .max_n = 128, .min_m = 1, .max_m = 16 };
	struct _ccu_nkm nkm = { .min_n = 1, .max_n = 32, .min_k = 1, .max_k = 4,
		.min_m = 1, .max_m = 4 };
	comparator_edges();
	output_boundaries(false);
	output_boundaries(true);
	constraints_and_extremes();
	limits(0, ULONG_MAX, 0);
	range_queries = 0;
	reference_nm_find_best(&context.common, 24000000, 432000000, &nm);
	assert(range_queries == 2048);
	range_queries = 0;
	candidate_nm_find_best(&context.common, 24000000, 432000000, &nm);
	assert(range_queries == 1);
	range_queries = 0;
	reference_nkm_find_best(24000000, 432000000, &nkm, &context.common);
	assert(range_queries == 512);
	range_queries = 0;
	candidate_nkm_find_best(24000000, 432000000, &nkm, &context.common);
	assert(range_queries == 1);
	printf("Clock ranges: %lu NM, %lu NKM, %lu comparator cases passed; unsigned long=%zu bits\n",
		nm_cases, nkm_cases, comparator_cases, sizeof(unsigned long) * CHAR_BIT);
	puts("Range lookups: A33 video 2048 -> 1; A33 DDR0 512 -> 1 (search work, not hardware timing)");
	return 0;
}
