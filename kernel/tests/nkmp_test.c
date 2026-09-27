/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Includes the actual original/patched search code extracted by check-nkmp.py. */
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef uint64_t u64;
/* The extracted calc function ignores do_div's remainder; match its u32 divisor. */
#define do_div(n, base) do { (n) /= (uint32_t)(base); } while (0)
static unsigned long reference_calls, candidate_calls, cases, improved;
#include "nkmp_functions.h"

static void check(unsigned long parent, unsigned long rate, struct _ccu_nkmp limits)
{
	struct _ccu_nkmp reference = limits, candidate = limits;
	unsigned long a, b;

	reference_calls = candidate_calls = 0;
	a = reference_find(parent, rate, &reference);
	b = candidate_find(parent, rate, &candidate);
	if (a != b || reference.n != candidate.n || reference.k != candidate.k ||
	    reference.m != candidate.m || reference.p != candidate.p ||
	    candidate_calls > reference_calls) {
		fprintf(stderr, "Mismatch: parent=%lu request=%lu old=%lu new=%lu\n",
			parent, rate, a, b);
		abort();
	}
	/* Non-exact and zero results must retain the old exhaustive behavior. */
	if (a != rate || !a)
		assert(candidate_calls == reference_calls);
	if (candidate_calls < reference_calls)
		improved++;
	cases++;
}

static int order(const void *a, const void *b)
{
	unsigned long x = *(const unsigned long *)a, y = *(const unsigned long *)b;
	return (x > y) - (x < y);
}

static void boundaries(unsigned long parent, struct _ccu_nkmp limits)
{
	unsigned long rates[8192], n, k, m, p;
	size_t count = 0, i;

	/* Every output breakpoint, adjacent integer, and a point in each gap. */
	for (k = limits.min_k; k <= limits.max_k; k++)
		for (n = limits.min_n; n <= limits.max_n; n++)
			for (m = limits.min_m; m <= limits.max_m; m++)
				for (p = limits.min_p; p <= limits.max_p; p <<= 1) {
					assert(count < sizeof(rates) / sizeof(*rates));
					rates[count++] = reference_calc(parent, n, k, m, p);
				}
	qsort(rates, count, sizeof(*rates), order);
	check(parent, 0, limits);
	check(parent, 1, limits);
	check(parent, ULONG_MAX, limits);
	for (i = 0; i < count; i++) {
		unsigned long rate = rates[i];
		if (i && rate == rates[i - 1])
			continue;
		check(parent, rate, limits);
		if (rate)
			check(parent, rate - 1, limits);
		if (rate < ULONG_MAX)
			check(parent, rate + 1, limits);
		if (i && rate - rates[i - 1] > 1)
			check(parent, rates[i - 1] + (rate - rates[i - 1]) / 2, limits);
	}
}

int main(void)
{
	const struct _ccu_nkmp limits[] = {
		/* Actual A33 CPU PLL factors; locked definitions checked by the generator. */
		{ .min_n = 1, .max_n = 32, .min_k = 1, .max_k = 4,
		  .min_m = 1, .max_m = 4, .min_p = 1, .max_p = 4 },
		/* Additional algorithm shapes; these do not assert other boards' support. */
		{ .min_n = 1, .max_n = 32, .min_k = 1, .max_k = 4,
		  .min_m = 1, .max_m = 4, .min_p = 1, .max_p = 128 },
		{ .min_n = 5, .max_n = 13, .min_k = 2, .max_k = 3,
		  .min_m = 1, .max_m = 2, .min_p = 2, .max_p = 8 },
		{ .min_n = 1, .max_n = 1, .min_k = 1, .max_k = 1,
		  .min_m = 1, .max_m = 1, .min_p = 1, .max_p = 1 },
	};
	const unsigned long parents[] = { 0, 1, 32768, 24000000, 25000001, UINT32_MAX };
	size_t i, j;

	for (i = 0; i < sizeof(limits) / sizeof(*limits); i++)
		for (j = 0; j < sizeof(parents) / sizeof(*parents); j++)
			boundaries(parents[j], limits[i]);
	for (i = 0; i < sizeof(a33_opps) / sizeof(*a33_opps); i++) {
		struct _ccu_nkmp value = limits[0];
		unsigned long rate = a33_opps[i];
		check(24000000, rate, limits[0]);
		assert(reference_calls == 1536);
		assert(candidate_calls < reference_calls);
		printf("OPP %lu Hz: evaluations %lu -> %lu; ", rate,
		       reference_calls, candidate_calls);
		assert(candidate_find(24000000, rate, &value) == rate);
		printf("N=%lu K=%lu M=%lu P=%lu\n", value.n, value.k, value.m, value.p);
	}
	assert(improved);
	printf("NKMP equivalence passed: %lu cases, %lu shortened searches, unsigned long=%zu bits\n",
	       cases, improved, sizeof(unsigned long) * CHAR_BIT);
	return 0;
}
