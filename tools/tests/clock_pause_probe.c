/* Offline ARM production-library probe. Two declared calls, never a retry. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include "../clock-pause.h"

static volatile sig_atomic_t interrupted;
static void alarm_received(int signal_number)
{
	(void)signal_number;
	interrupted++;
}
static void hex(const unsigned char *bytes)
{
	for (unsigned i = 0; i < 16; i++)
		printf("%02x", bytes[i]);
}
static void emit(const char *mode, const struct pause_observation *out)
{
	printf("NEO_PAUSE_REAL {\"mode\":\"%s\",\"rc\":%d,\"errno\":%d,\"clock\":%d,\"syscall\":%u,\"flags\":%u,\"calls\":%u,\"request_before\":\"",
	       mode, out->rc, out->error, out->clock, out->syscall, out->flags, out->calls);
	hex(out->request_before);
	printf("\",\"request_after\":\""); hex(out->request_after);
	printf("\",\"remaining\":\""); hex(out->remaining);
	puts("\"}");
}
int main(void)
{
	uint32_t layout[12];
	const uint32_t expected[] = {1, 72, 24, 40, 56, 16, 407, 1, 0, 100000000, 4, 4};
	const int64_t request[] = {0, PAUSE_NS};
	struct pause_observation out;
	struct sigaction action = {.sa_handler = alarm_received};
	struct itimerval timer = {.it_value = {.tv_usec = 50000}};
	struct timespec before, after;
	int64_t remaining[2];

	assert(neo_clock_pause_layout(layout, 12) == 0 && !memcmp(layout, expected, sizeof(expected)));
	assert(clock_gettime(CLOCK_MONOTONIC, &before) == 0);
	assert(neo_clock_pause(&out) == 0 && out.rc == 0 && out.error == 0 && out.calls == 1);
	assert(clock_gettime(CLOCK_MONOTONIC, &after) == 0);
	assert((int64_t)(after.tv_sec - before.tv_sec) * 1000000000 + after.tv_nsec - before.tv_nsec >= PAUSE_NS);
	assert(!memcmp(out.request_before, request, 16) && !memcmp(out.request_after, request, 16));
	emit("success", &out);

	assert(sigemptyset(&action.sa_mask) == 0 && sigaction(SIGALRM, &action, NULL) == 0);
	assert(setitimer(ITIMER_REAL, &timer, NULL) == 0);
	assert(neo_clock_pause(&out) == 0);
	assert(interrupted == 1 && out.rc == -1 && out.error == EINTR && out.calls == 1);
	assert(!memcmp(out.request_before, request, 16) && !memcmp(out.request_after, request, 16));
	memcpy(remaining, out.remaining, 16);
	assert(remaining[0] == 0 && remaining[1] > 0 && remaining[1] <= PAUSE_NS);
	emit("interrupted", &out);
	puts("ARM production pause library passed: one success, one signal, no retry");
	return 0;
}
