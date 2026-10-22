/* Pure NEO-221 synthetic arithmetic only: no MMIO, counter or timing calls. */
#include <assert.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#define HALF UINT32_C(0x80000000)
#define ALL_GATES UINT32_C(0x7f)
struct record { uint64_t counter; uint32_t before, after; };
struct fixture {
	const char *name, *family;
	struct record first, second;
	uint32_t gates;
	unsigned expected;
};
struct result {
	int64_t delta, lower, upper;
	uint32_t first_span, second_span, gap;
	uint64_t uncertainty;
	unsigned code;
	bool has_intervals, resolution;
};
#define REC(c, b, a) {c, UINT32_MAX ^ (uint32_t)(b), UINT32_MAX ^ (uint32_t)(a)}
#define CASE(n, f, c1, b1, a1, c2, b2, a2, g, e) \
	{n, f, REC(c1, b1, a1), REC(c2, b2, a2), g, e}

static const struct fixture fixtures[] = {
	CASE("forward-short", "forward", 1000,100,102, 1050,150,152, ALL_GATES,1),
	CASE("forward-stalled-architectural", "forward", 1000,100,102, 1000,150,152, ALL_GATES,5),
	CASE("forward-rate-offset", "forward", 1000,100,102, 1100,150,152, ALL_GATES,5),
	CASE("architectural-minus18", "architectural-minus18", 1000,100,102, 982,150,152, ALL_GATES,2),
	CASE("mmio-only-reversal", "mmio-only-reversal", 1000,200,202, 1050,150,152, ALL_GATES,3),
	CASE("wrap-normal", "wrap", 1000,UINT32_MAX-3,UINT32_MAX-1, 1009,3,5, ALL_GATES,1),
	CASE("wrap-half-bracket", "wrap", 1000,100,100+HALF, 1050,150,152, ALL_GATES,3),
	CASE("wrap-half-gap", "wrap", 1000,100,102, 1050,102+HALF,104+HALF, ALL_GATES,3),
	CASE("wrap-unproven-window", "wrap", 1000,UINT32_MAX-3,UINT32_MAX-1, 1009,3,5, ALL_GATES^(1u<<6),0),
	CASE("bracket-touch", "brackets", 1000,100,102, 982,102,104, ALL_GATES,4),
	CASE("bracket-quantization", "brackets", 1000,100,102, 982,103,105, ALL_GATES,4),
	CASE("bracket-wide-minus18", "brackets", 1000,100,130, 982,150,180, ALL_GATES,2),
	CASE("bracket-resolution-boundary", "brackets", 1000,100,108, 982,150,156, ALL_GATES,2),
	CASE("premise-ready", "premises", 1000,100,102, 982,150,152, ALL_GATES^(1u<<0),0),
	CASE("premise-controls_stable", "premises", 1000,100,102, 982,150,152, ALL_GATES^(1u<<1),0),
	CASE("premise-sequence_accepted", "premises", 1000,100,102, 982,150,152, ALL_GATES^(1u<<2),0),
	CASE("premise-same_cpu_in_brackets", "premises", 1000,100,102, 982,150,152, ALL_GATES^(1u<<3),0),
	CASE("premise-no_loss", "premises", 1000,100,102, 982,150,152, ALL_GATES^(1u<<4),0),
	CASE("premise-ordering_proven", "premises", 1000,100,102, 982,150,152, ALL_GATES^(1u<<5),0),
};

static struct result analyze(const struct fixture *value)
{
	struct result out = {0};
	const struct record *first = &value->first, *second = &value->second;
	assert(first->counter <= INT64_MAX && second->counter <= INT64_MAX);
	out.delta = (int64_t)second->counter - (int64_t)first->counter;
	if (value->gates != ALL_GATES)
		return out;
	out.first_span = first->before - first->after;
	out.second_span = second->before - second->after;
	out.gap = first->after - second->before;
	if (out.first_span >= HALF || out.second_span >= HALF || out.gap >= HALF) {
		out.code = 3;
		return out;
	}
	out.has_intervals = true;
	out.uncertainty = (uint64_t)out.first_span + out.second_span + 4;
	out.lower = (int64_t)out.gap - 2;
	out.upper = (int64_t)out.first_span + out.second_span + out.gap + 2;
	out.resolution = out.uncertainty < 18;
	if (out.gap <= 1)
		out.code = 4;
	else if (out.delta < 0)
		out.code = 2;
	else if (out.delta < out.lower || out.delta > out.upper)
		out.code = 5;
	else
		out.code = 1;
	return out;
}

int main(void)
{
	_Static_assert(sizeof(uint32_t) == 4 && sizeof(uint64_t) == 8, "fixed analysis ABI");
	_Static_assert(sizeof(fixtures) / sizeof(fixtures[0]) == 19, "fixed case count");
	for (unsigned i = 0; i < 19; i++) {
		const struct fixture *f = &fixtures[i];
		struct result result = analyze(f);
		assert(result.code == f->expected);
		printf("NEO_REFERENCE_FIXTURE {\"name\":\"%s\",\"family\":\"%s\",\"first\":{\"counter\":%" PRIu64 ",\"before\":%" PRIu32 ",\"after\":%" PRIu32 "},\"second\":{\"counter\":%" PRIu64 ",\"before\":%" PRIu32 ",\"after\":%" PRIu32 "},\"gates\":%" PRIu32 ",\"code\":%u,\"delta\":%" PRId64 ",\"has_intervals\":%u,\"first_span\":%" PRIu32 ",\"second_span\":%" PRIu32 ",\"gap\":%" PRIu32 ",\"lower\":%" PRId64 ",\"upper\":%" PRId64 ",\"uncertainty\":%" PRIu64 ",\"resolution\":%u}\n",
		       f->name, f->family, f->first.counter, f->first.before, f->first.after,
		       f->second.counter, f->second.before, f->second.after, f->gates,
		       result.code, result.delta, result.has_intervals, result.first_span,
		       result.second_span, result.gap, result.lower, result.upper,
		       result.uncertainty, result.resolution);
	}
	puts("19 synthetic cases in six families passed; no MMIO or counter instruction executed");
	return 0;
}
