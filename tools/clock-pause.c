/* NEO-217 diagnostic pause only; no clock read, retry or policy change. */
#define _GNU_SOURCE
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
#include "clock-pause.h"

struct kernel64 { int64_t sec, nsec; };
_Static_assert(sizeof(struct kernel64) == 16, "kernel time64 ABI");
_Static_assert(sizeof(struct pause_observation) == 72, "pause observation ABI");
_Static_assert(offsetof(struct pause_observation, request_before) == 24, "request offset");
_Static_assert(offsetof(struct pause_observation, remaining) == 56, "remaining offset");

#ifndef NEO_PAUSE_TEST
#if !defined(__arm__) || !defined(__ARM_EABI__) || !defined(__ARM_PCS_VFP)
#error Production pause requires ARM EABI hard float
#endif
_Static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "little endian");
_Static_assert(sizeof(void *) == 4 && sizeof(long) == 4, "ARM word sizes");
_Static_assert(__NR_clock_nanosleep_time64 == PAUSE_SYSCALL, "ARM sleep syscall");
_Static_assert(CLOCK_MONOTONIC == 1, "clock ID");
#else
static long fake_pause(const struct kernel64 *request, struct kernel64 *remaining);
#endif

int neo_clock_pause_layout(uint32_t *out, uint32_t count)
{
	const uint32_t fields[] = {1, 72, 24, 40, 56, 16, PAUSE_SYSCALL, 1, 0, PAUSE_NS,
				   sizeof(void *), sizeof(long)};
	if (!out || count != sizeof(fields) / sizeof(fields[0]))
		return EINVAL;
	memcpy(out, fields, sizeof(fields));
	return 0;
}

int neo_clock_pause(struct pause_observation *out)
{
	struct kernel64 request = {0, PAUSE_NS}, remaining;
	long rc;
	int error;

	if (!out)
		return EINVAL;
	memset(out, 0, sizeof(*out));
	memset(&remaining, 0xa5, sizeof(remaining));
	out->clock = CLOCK_MONOTONIC;
	out->syscall = PAUSE_SYSCALL;
	memcpy(out->request_before, &request, sizeof(request));
	out->calls = 1;
	errno = 0;
#ifdef NEO_PAUSE_TEST
	rc = fake_pause(&request, &remaining);
#else
	rc = syscall(PAUSE_SYSCALL, CLOCK_MONOTONIC, 0, &request, &remaining);
#endif
	error = errno;
	/* Finish the preallocated result before Python can raise a pending signal. */
	out->rc = rc;
	out->error = rc < 0 ? error : 0;
	memcpy(out->request_after, &request, sizeof(request));
	memcpy(out->remaining, &remaining, sizeof(remaining));
	return 0;
}

#ifdef NEO_PAUSE_TEST
#include <assert.h>
static unsigned scenario, invocations;
static long fake_pause(const struct kernel64 *request, struct kernel64 *remaining)
{
	assert(request->sec == 0 && request->nsec == PAUSE_NS);
	invocations++;
	if (scenario == 1) {
		remaining->sec = 0;
		remaining->nsec = 30000000;
		errno = EINTR;
		return -1;
	}
	if (scenario == 2) {
		errno = EFAULT;
		return -1;
	}
	if (scenario == 3)
		((struct kernel64 *)request)->nsec = 1; /* Deliberate fixture corruption. */
	return 0;
}
static void hex(const unsigned char *p)
{
	for (unsigned i = 0; i < 16; i++)
		printf("%02x", p[i]);
}
int main(void)
{
	uint32_t layout[12];
	assert(neo_clock_pause(NULL) == EINVAL && invocations == 0);
	assert(neo_clock_pause_layout(NULL, 12) == EINVAL);
	assert(neo_clock_pause_layout(layout, 11) == EINVAL);
	assert(neo_clock_pause_layout(layout, 12) == 0 && layout[6] == 407);
	for (scenario = 0; scenario < 4; scenario++) {
		struct pause_observation out;
		unsigned before = invocations;
		assert(neo_clock_pause(&out) == 0 && invocations == before + 1);
		assert(out.calls == 1 && out.clock == 1 && out.syscall == 407 && !out.flags);
		assert(out.rc == (scenario == 1 || scenario == 2 ? -1 : 0));
		assert(out.error == (scenario == 1 ? EINTR : scenario == 2 ? EFAULT : 0));
		printf("NEO_PAUSE_FIXTURE {\"scenario\":%u,\"rc\":%d,\"errno\":%d,\"clock\":%d,\"syscall\":%u,\"flags\":%u,\"calls\":%u,\"request_before\":\"",
		       scenario, out.rc, out.error, out.clock, out.syscall, out.flags, out.calls);
		hex(out.request_before);
		printf("\",\"request_after\":\""); hex(out.request_after);
		printf("\",\"remaining\":\""); hex(out.remaining);
		puts("\"}");
	}
	puts("pause fixtures passed: success, EINTR, EFAULT, changed request, no retries");
	return 0;
}
#endif
