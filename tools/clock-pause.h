/* Separate diagnostic pause ABI; not part of the immutable clock reader. */
#ifndef NEO_CLOCK_PAUSE_H
#define NEO_CLOCK_PAUSE_H
#include <stdint.h>

struct pause_observation {
	int32_t rc, error, clock;
	uint32_t syscall, flags, calls;
	unsigned char request_before[16], request_after[16], remaining[16];
};
enum { PAUSE_SYSCALL = 407, PAUSE_NS = 100000000 };
int neo_clock_pause_layout(uint32_t *out, uint32_t count);
int neo_clock_pause(struct pause_observation *out);
#endif
