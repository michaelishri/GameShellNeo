/* NEO-192 diagnostic reader. Exactly one clock operation per accepted request;
 * no retry, timestamp, allocation, affinity change or clock correction here. */
#define _GNU_SOURCE
#define _TIME_BITS 64
#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/syscall.h>

enum { TIME64 = 0, TIME32 = 1, LIBC64 = 2 };
struct kernel64 { int64_t sec, nsec; };
struct kernel32 { int32_t sec, nsec; };
union value {
    struct kernel64 k64;
    struct kernel32 k32;
    struct timespec libc;
    unsigned char bytes[16];
};
struct observation {
    int32_t rc, error, size, converted;
    int64_t sec, nsec, native_ns;
    unsigned char bytes[16];
};
_Static_assert(sizeof(struct observation) == 56, "observation ABI");
_Static_assert(offsetof(struct observation, sec) == 16, "seconds offset");
_Static_assert(offsetof(struct observation, bytes) == 40, "bytes offset");
_Static_assert(sizeof(struct kernel64) == 16 && sizeof(struct kernel32) == 8, "kernel ABI");

#ifndef NEO_CLOCK_TEST
#if !defined(__arm__) || !defined(__ARM_EABI__) || !defined(__ARM_PCS_VFP)
#error Production reader requires ARM EABI hard float
#endif
_Static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "little endian required");
_Static_assert(__NR_clock_gettime64 == 403 && __NR_clock_gettime == 263, "ARM syscall numbers");
_Static_assert(sizeof(void *) == 4 && sizeof(long) == 4 && sizeof(int) == 4, "ARM word sizes");
_Static_assert(sizeof(struct timespec) == 16 && sizeof(time_t) == 8, "libc time64 ABI");
_Static_assert(sizeof(((struct timespec *)0)->tv_nsec) == 4, "libc long nanoseconds");
_Static_assert(offsetof(struct timespec, tv_sec) == 0 &&
               offsetof(struct timespec, tv_nsec) == 8, "libc timespec offsets");
_Static_assert(CLOCK_MONOTONIC == 1 && CLOCK_MONOTONIC_RAW == 4 && CLOCK_BOOTTIME == 7,
               "clock identifiers");
#else
static int fake_operation(int route, int clock, union value *v);
#endif

/* ctypes verifies this before opening the kernel recorder. */
int neo_clock_layout(uint32_t *out, uint32_t count)
{
    const uint32_t values[] = {1, sizeof(struct observation),
        offsetof(struct observation, sec), offsetof(struct observation, bytes),
        sizeof(struct timespec), offsetof(struct timespec, tv_nsec),
        sizeof(((struct timespec *)0)->tv_nsec), sizeof(void *), sizeof(long)};
    if (!out || count != sizeof(values) / sizeof(values[0])) return EINVAL;
    memcpy(out, values, sizeof(values));
    return 0;
}

int neo_clock_read(int route, int clock, struct observation *out)
{
    union value v;
    if (!out || route < TIME64 || route > LIBC64 ||
        (clock != 1 && clock != 4 && clock != 7)) return EINVAL;
    memset(&v, 0xa5, sizeof(v));
    memset(out, 0, sizeof(*out));
    out->size = route == TIME32 ? 8 : 16;
    out->native_ns = -1;
    errno = 0;
#ifdef NEO_CLOCK_TEST
    out->rc = fake_operation(route, clock, &v);
#else
    if (route == TIME64) out->rc = syscall(__NR_clock_gettime64, clock, &v.k64);
    else if (route == TIME32) out->rc = syscall(__NR_clock_gettime, clock, &v.k32);
    else out->rc = clock_gettime(clock, &v.libc);
#endif
    out->error = errno;
    /* Save the entire initialized buffer, including untouched/padding bytes. */
    memcpy(out->bytes, v.bytes, sizeof(out->bytes));
    if (route == TIME64) { out->sec = v.k64.sec; out->nsec = v.k64.nsec; }
    else if (route == TIME32) { out->sec = v.k32.sec; out->nsec = v.k32.nsec; }
    else { out->sec = v.libc.tv_sec; out->nsec = v.libc.tv_nsec; }
    if (!out->rc && out->sec >= 0 && out->nsec >= 0 && out->nsec < 1000000000 &&
        out->sec <= (INT64_MAX - out->nsec) / 1000000000) {
        out->native_ns = out->sec * INT64_C(1000000000) + out->nsec;
        out->converted = 1;
    }
    return 0;
}

#ifdef NEO_CLOCK_TEST
#include <assert.h>
#include <inttypes.h>
#include <stdio.h>
static int operations, wanted_route, wanted_clock, failure;
static int64_t fixture_sec, fixture_nsec;
static int fake_operation(int route, int clock, union value *v)
{
    ++operations;
    assert(route == wanted_route && clock == wanted_clock);
    if (failure) { errno = failure; return -1; }
    if (route == TIME64) { v->k64.sec = fixture_sec; v->k64.nsec = fixture_nsec; }
    else if (route == TIME32) { v->k32.sec = fixture_sec; v->k32.nsec = fixture_nsec; }
    else { v->libc.tv_sec = fixture_sec; v->libc.tv_nsec = fixture_nsec; }
    return 0;
}

/* Host replay checks actual ARM-produced buffers independently of the C
 * decoder. This is fixture output only, never part of a live clock window. */
static void emit(const struct observation *o)
{
    const char *routes[] = {"syscall64", "syscall32", "libc64"};
    printf("NEO_BOUNDARY_FIXTURE {\"route\":\"%s\",\"clock\":%d,\"rc\":%d,\"errno\":%d,"
           "\"size\":%d,\"converted\":%d,\"sec\":%" PRId64 ",\"nsec\":%" PRId64
           ",\"native_ns\":%" PRId64 ",\"raw\":\"", routes[wanted_route], wanted_clock,
           o->rc, o->error, o->size, o->converted, o->sec, o->nsec, o->native_ns);
    for (unsigned i = 0; i < sizeof(o->bytes); ++i) printf("%02x", o->bytes[i]);
    puts("\"}");
}

int main(void)
{
    struct observation o;
    int clocks[] = {1, 4, 7};
    uint32_t layout[9];
    assert(!neo_clock_layout(layout, 9) && layout[0] == 1 && layout[1] == 56);
    assert(neo_clock_layout(layout, 8) == EINVAL);
    for (wanted_route = 0; wanted_route < 3; ++wanted_route) {
        for (int i = 0; i < 3; ++i) {
            wanted_clock = clocks[i];
            fixture_sec = 7; fixture_nsec = 6350; failure = 0; operations = 0;
            assert(!neo_clock_read(wanted_route, wanted_clock, &o));
            assert(operations == 1 && o.rc == 0 && o.error == 0 && o.converted);
            assert(o.sec == 7 && o.nsec == 6350 && o.native_ns == INT64_C(7000006350));
            assert(o.size == (wanted_route == TIME32 ? 8 : 16));
            emit(&o);
            int64_t previous = o.native_ns;
            fixture_nsec -= 750;
            assert(!neo_clock_read(wanted_route, wanted_clock, &o));
            assert(operations == 2 && o.native_ns == previous - 750);
            emit(&o);
            failure = EFAULT;
            assert(!neo_clock_read(wanted_route, wanted_clock, &o));
            assert(operations == 3 && o.rc == -1 && o.error == EFAULT && !o.converted);
            assert(o.native_ns == -1);
            for (unsigned k = 0; k < sizeof(o.bytes); ++k) assert(o.bytes[k] == 0xa5);
            emit(&o);
            failure = 0;
            fixture_nsec = 1000000000;
            assert(!neo_clock_read(wanted_route, wanted_clock, &o) && !o.converted);
            fixture_sec = -1; fixture_nsec = 1;
            assert(!neo_clock_read(wanted_route, wanted_clock, &o) && !o.converted);
            fixture_sec = wanted_route == TIME32 ? INT32_MAX : INT64_MAX;
            assert(!neo_clock_read(wanted_route, wanted_clock, &o));
            assert(o.converted == (wanted_route == TIME32));
            if (wanted_route != TIME32) {
                fixture_sec = INT64_MAX / 1000000000;
                fixture_nsec = INT64_MAX % 1000000000;
                assert(!neo_clock_read(wanted_route, wanted_clock, &o) && o.converted);
                assert(o.native_ns == INT64_MAX);
                ++fixture_nsec;
                assert(!neo_clock_read(wanted_route, wanted_clock, &o) && !o.converted);
            }
        }
    }
    operations = 0;
    assert(neo_clock_read(3, 1, &o) == EINVAL);
    assert(neo_clock_read(0, 0, &o) == EINVAL);
    assert(neo_clock_read(0, 1, NULL) == EINVAL);
    assert(!operations);
    puts("clock-boundary fixtures passed: three routes, three clocks, raw errors, regression, overflow");
    return 0;
}
#endif
