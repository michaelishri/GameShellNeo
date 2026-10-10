/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef NEO_CLOCK_DIAG_H
#define NEO_CLOCK_DIAG_H
#include <linux/time64.h>
struct timekeeper;
struct tk_read_base;
struct neo_clock_call;
/* Writer kind is a source-site identifier, not a claim about wall-time order. */
enum neo_clock_writer { NEO_FORWARD = 1, NEO_ADVANCE, NEO_RESUME, NEO_SETUP };
#ifdef CONFIG_NEO_CLOCK_DIAG
struct neo_clock_call *neo_clock_begin(int clock, int abi);
void neo_clock_end(struct neo_clock_call *call, const struct timespec64 *ts,
		   bool valid, int error);
bool neo_clock_target(int clock);
u64 neo_clock_read(const struct timekeeper *tk, const struct tk_read_base *tkr,
		   unsigned int seq, u64 (*read)(const struct tk_read_base *),
		   u64 (*convert)(const struct tk_read_base *, u64));
void neo_clock_accepted(int clock);
void neo_clock_writer_read(const struct timekeeper *tk, u64 cycles, int kind,
			   u64 delta, bool delta_valid);
void neo_clock_publish(const struct timekeeper *old, const struct timekeeper *new,
		       unsigned int seq, unsigned int action);
#else
static inline struct neo_clock_call *neo_clock_begin(int clock, int abi) { return NULL; }
static inline void neo_clock_end(struct neo_clock_call *call, const struct timespec64 *ts,
				bool valid, int error) { }
static inline void neo_clock_accepted(int clock) { }
static inline void neo_clock_writer_read(const struct timekeeper *tk, u64 cycles, int kind,
					 u64 delta, bool delta_valid) { }
/* Do not evaluate the raw sequence load when diagnostics are compiled out. */
#define neo_clock_publish(...) do { } while (0)
#endif
#ifdef CONFIG_NEO_CLOCK_DIAG_KUNIT_TEST
u64 neo_clock_test_read(const struct timekeeper *tk, unsigned int seq, int clock);
#endif
#endif
