/* NEO-192: fixed awake clock comparison. No clock, affinity or PM writes. */
#define _GNU_SOURCE
#define _TIME_BITS 64
#define _FILE_OFFSET_BITS 64
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { LIBC, KERNEL, VDSO, NREADS = 9, NCLOCKS = 3, BATCHES = 300, PER_BATCH = 50 };
static const int routes[NREADS] = {LIBC, KERNEL, VDSO, LIBC, VDSO, KERNEL, VDSO, KERNEL, LIBC};
static const int clocks[NCLOCKS] = {1, 4, 7};
struct raw { int rc, error; int64_t sec, nsec; };
struct family { int before, after, valid; int64_t ns[NREADS]; };
struct sequence { struct family clock[NCLOCKS]; };
struct failure { int present, sequence, clock, position, stage; struct raw raw; };
typedef struct raw (*reader_fn)(void *, int, int);
typedef int (*cpu_fn)(void *);
typedef int (*pause_fn)(void *);

static int convert(struct raw raw, int64_t *ns)
{
    if (raw.rc || raw.sec < 0 || raw.nsec < 0 || raw.nsec >= 1000000000 ||
        raw.sec > (INT64_MAX - raw.nsec) / 1000000000)
        return -1;
    *ns = raw.sec * INT64_C(1000000000) + raw.nsec;
    return 0;
}

/* Only test fixtures supply alternate callbacks/bounds. Production is fixed. */
static int capture(struct sequence *data, int count, int batch, reader_fn read_clock,
                   cpu_fn cpu, pause_fn pause, void *ctx, struct failure *failure)
{
    int i, c, p;
    for (i = 0; i < count; ++i) {
        for (c = 0; c < NCLOCKS; ++c) {
            struct family *f = &data[i].clock[c];
            f->before = cpu(ctx);
            f->after = -1;
            if (f->before < 0 || f->before > 3) {
                *failure = (struct failure){1, i, c, -1, 1, {0}};
                return i;
            }
            for (p = 0; p < NREADS; ++p) {
                struct raw raw = read_clock(ctx, routes[p], clocks[c]);
                if (convert(raw, &f->ns[p])) {
                    *failure = (struct failure){1, i, c, p, 2, raw};
                    return i;
                }
                ++f->valid;
            }
            f->after = cpu(ctx);
            if (f->after < 0 || f->after > 3) {
                *failure = (struct failure){1, i, c, NREADS, 3, {0}};
                return i;
            }
        }
        if ((i + 1) % batch == 0 && pause(ctx)) {
            *failure = (struct failure){1, i, -1, -1, 4, {0}};
            return i + 1;
        }
    }
    return count;
}

#ifdef NEO_CLOCK_TEST
struct fixture { int calls, cpus, pauses, fail_at, bad_cpu, fail_pause; int64_t tick; };
static struct raw fake_read(void *ctx, int route, int clock)
{
    struct fixture *f = ctx;
    assert(route == routes[f->calls % NREADS]);
    assert(clock == clocks[(f->calls / NREADS) % NCLOCKS]);
    ++f->calls;
    if (f->calls == f->fail_at) return (struct raw){-1, ENOSYS, -1, -1};
    /* Deliberately decreasing values must survive, never be clamped/retried. */
    return (struct raw){0, 0, 100, --f->tick};
}
static int fake_cpu(void *ctx) { struct fixture *f = ctx; ++f->cpus; return f->bad_cpu ? -1 : 2; }
static int fake_pause(void *ctx) { struct fixture *f = ctx; ++f->pauses; return f->fail_pause; }
int main(void)
{
    struct sequence data[4] = {0}; struct failure error = {0};
    struct fixture f = {.tick = 10000};
    assert(capture(data, 4, 2, fake_read, fake_cpu, fake_pause, &f, &error) == 4);
    assert(!error.present && f.calls == 108 && f.cpus == 24 && f.pauses == 2);
    assert(data[0].clock[0].ns[1] == data[0].clock[0].ns[0] - 1);
    memset(data, 0, sizeof(data)); f = (struct fixture){.tick = 10000, .fail_at = 14};
    assert(capture(data, 4, 2, fake_read, fake_cpu, fake_pause, &f, &error) == 0);
    assert(f.calls == 14 && f.pauses == 0 && error.clock == 1 && error.position == 4);
    assert(error.raw.rc == -1 && error.raw.error == ENOSYS && error.raw.sec == -1);
    assert(data[0].clock[0].valid == 9 && data[0].clock[1].valid == 4);
    memset(data, 0, sizeof(data)); f = (struct fixture){.bad_cpu = 1};
    assert(capture(data, 4, 2, fake_read, fake_cpu, fake_pause, &f, &error) == 0 && f.calls == 0);
    memset(data, 0, sizeof(data)); f = (struct fixture){.tick = 10000, .fail_pause = 1};
    assert(capture(data, 4, 2, fake_read, fake_cpu, fake_pause, &f, &error) == 2 && f.pauses == 1);
    int64_t ns;
    assert(!convert((struct raw){0, 0, INT64_C(1) << 33, 123}, &ns));
    assert(ns == (INT64_C(1) << 33)*1000000000 + 123);
    assert(convert((struct raw){0, 0, INT64_MAX, 0}, &ns));
    assert(convert((struct raw){0, 0, 0, 1000000000}, &ns));
    assert(convert((struct raw){0, 0, -1, 0}, &ns));
    assert(!convert((struct raw){0, 0, 0, 0}, &ns) && ns == 0);
    puts("Native clock capture: fixed bounds, ordering, raw failures and overflow checks passed.");
    return 0;
}
#else
#if !defined(__arm__) || !defined(__ARM_EABI__) || __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error Production clock comparison requires little-endian ARM EABI
#endif
#include <asm/unistd.h>
#include <dlfcn.h>
#include <gnu/libc-version.h>
#include <link.h>
#include <linux/time_types.h>
#include <sched.h>
#include <sys/auxv.h>
#include <unistd.h>
_Static_assert(sizeof(void *) == 4 && sizeof(long) == 4 && sizeof(clockid_t) == 4, "ARM32 ABI");
_Static_assert(sizeof(time_t) == 8 && sizeof(struct timespec) == 16 &&
               offsetof(struct timespec, tv_nsec) == 8 && sizeof(((struct timespec *)0)->tv_nsec) == 4,
               "libc time64 is seconds64, nanoseconds32 plus padding");
_Static_assert(sizeof(struct __kernel_timespec) == 16 && _Alignof(struct __kernel_timespec) == 8 &&
               offsetof(struct __kernel_timespec, tv_nsec) == 8 &&
               sizeof(((struct __kernel_timespec *)0)->tv_nsec) == 8, "kernel time64 layout");
_Static_assert(__NR_clock_gettime64 == 403 && CLOCK_MONOTONIC == 1 && CLOCK_MONOTONIC_RAW == 4 &&
               CLOCK_BOOTTIME == 7, "clock IDs and syscall number");
static int (*vdso_clock)(clockid_t, struct __kernel_timespec *);
static uintptr_t vdso_base;
static char vdso_name[128];
static int find_vdso(struct dl_phdr_info *info, size_t size, void *unused)
{
    (void)size; (void)unused;
    if ((uintptr_t)info->dlpi_addr != vdso_base) return 0;
    if (!info->dlpi_name || strlen(info->dlpi_name) >= sizeof(vdso_name)) return 1;
    strcpy(vdso_name, info->dlpi_name);
    return 1;
}
static struct raw real_read(void *unused, int route, int clock)
{
    (void)unused;
    struct raw r;
    errno = 0;
    if (route == LIBC) {
        struct timespec ts = {.tv_sec = -1, .tv_nsec = -1};
        r.rc = clock_gettime(clock, &ts); r.error = errno; r.sec = ts.tv_sec; r.nsec = ts.tv_nsec;
    } else {
        struct __kernel_timespec ts = {.tv_sec = -1, .tv_nsec = -1};
        r.rc = route == KERNEL ? syscall(__NR_clock_gettime64, clock, &ts) : vdso_clock(clock, &ts);
        r.error = errno; r.sec = ts.tv_sec; r.nsec = ts.tv_nsec;
    }
    return r;
}
static int real_cpu(void *unused) { (void)unused; return sched_getcpu(); }
static int real_pause(void *unused)
{
    (void)unused; struct timespec delay = {.tv_sec = 0, .tv_nsec = 100000000};
    return nanosleep(&delay, NULL); /* Interrupted pauses stop; no hidden retry. */
}
struct metadata { char boot[64], clocksource[64]; unsigned affinity; };
static int text_file(const char *path, char *text, size_t size)
{
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    int ok = fgets(text, size, f) != NULL && !ferror(f);
    fclose(f);
    if (!ok) return -1;
    text[strcspn(text, "\n")] = 0;
    return !*text || strspn(text, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-. ") != strlen(text) ? -1 : 0;
}
static int metadata(struct metadata *m)
{
    cpu_set_t cpus; CPU_ZERO(&cpus); m->affinity = 0;
    if (sched_getaffinity(0, sizeof(cpus), &cpus)) return -1;
    for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) if (CPU_ISSET(cpu, &cpus)) {
        if (cpu > 3) return -1;
        m->affinity |= 1u << cpu;
    }
    return !m->affinity || text_file("/proc/sys/kernel/random/boot_id", m->boot, sizeof(m->boot)) ||
        text_file("/sys/devices/system/clocksource/clocksource0/current_clocksource", m->clocksource, sizeof(m->clocksource));
}
static void print_meta(struct metadata *m)
{
    printf("{\"boot_id\":\"%s\",\"clocksource\":\"%s\",\"affinity\":%u}", m->boot, m->clocksource, m->affinity);
}
int main(int argc, char **argv)
{
    int inspect_only = argc == 2 && !strcmp(argv[1], "--inspect-vdso");
    if (argc != 1 && !inspect_only) return 2;
    if (getenv("LD_PRELOAD") || getenv("LD_AUDIT") || getenv("LD_LIBRARY_PATH")) {
        fputs("Loader environment is outside this comparison's attribution.\n", stderr); return 1;
    }
    vdso_base = getauxval(AT_SYSINFO_EHDR);
    if (!vdso_base) { fputs("Missing vDSO auxiliary-vector identity.\n", stderr); return 1; }
    dl_iterate_phdr(find_vdso, NULL);
    void *handle = *vdso_name ? dlopen(vdso_name, RTLD_NOW | RTLD_LOCAL | RTLD_NOLOAD) : NULL;
    struct link_map *map = NULL;
    int handle_verified = handle && !dlinfo(handle, RTLD_DI_LINKMAP, &map) &&
                          map && (uintptr_t)map->l_addr == vdso_base;
    if (inspect_only) {
        struct metadata before = {0}, after = {0};
        if (metadata(&before)) return 1;
        const char *names[] = {"__vdso_clock_gettime64", "__vdso_clock_gettime",
                              "__vdso_gettimeofday", "__vdso_clock_getres"};
        printf("{\"type\":\"vdso-inventory\",\"schema\":1,\"mapping_found\":%s,"
               "\"handle_base_verified\":%s,\"version\":\"LINUX_2.6\",\"symbols\":{",
               *vdso_name ? "true" : "false", handle_verified ? "true" : "false");
        for (int i = 0; i < 4; ++i) {
            void *versioned = handle_verified ? dlvsym(handle, names[i], "LINUX_2.6") : NULL;
            void *plain = handle_verified ? dlsym(handle, names[i]) : NULL;
            Dl_info info;
            int verified = versioned && dladdr(versioned, &info) && (uintptr_t)info.dli_fbase == vdso_base;
            printf("%s\"%s\":{\"versioned\":%s,\"unversioned\":%s,\"base_verified\":%s}",
                   i ? "," : "", names[i], versioned ? "true" : "false", plain ? "true" : "false",
                   verified ? "true" : "false");
        }
        int ok = !metadata(&after) && handle_verified && before.affinity == after.affinity &&
                 !strcmp(before.boot, after.boot) && !strcmp(before.clocksource, after.clocksource);
        printf("},\"libc\":\"%s\",\"before\":", gnu_get_libc_version());
        print_meta(&before); printf(",\"after\":"); print_meta(&after);
        printf(",\"complete\":%s}\n", ok ? "true" : "false");
        if (handle) dlclose(handle);
        return ok && !fflush(stdout) && !ferror(stdout) ? 0 : 1;
    }
    void *symbol = handle ? dlvsym(handle, "__vdso_clock_gettime64", "LINUX_2.6") : NULL;
    Dl_info info;
    if (!handle_verified || !symbol || !dladdr(symbol, &info) || (uintptr_t)info.dli_fbase != vdso_base) {
        fputs("Cannot establish the mapped, versioned ARM time64 vDSO entry.\n", stderr); return 1;
    }
    vdso_clock = (int (*)(clockid_t, struct __kernel_timespec *))symbol;
    struct metadata before = {0}, after = {0};
    if (metadata(&before)) { fputs("Metadata read failed before capture.\n", stderr); return 1; }
    struct sequence *data = calloc(BATCHES * PER_BATCH, sizeof(*data));
    if (!data) return 1;
    struct failure failure = {0};
    int completed = capture(data, BATCHES * PER_BATCH, PER_BATCH, real_read, real_cpu, real_pause, NULL, &failure);
    int after_ok = metadata(&after) == 0;
    printf("{\"type\":\"header\",\"schema\":1,\"operation\":\"native-clock-comparison\","
           "\"batches\":300,\"per_batch\":50,\"pause_ns\":100000000,\"routes\":[0,1,2,0,2,1,2,1,0],"
           "\"clocks\":[1,4,7],\"vdso_symbol\":\"__vdso_clock_gettime64\",\"vdso_version\":\"LINUX_2.6\","
           "\"vdso_base_verified\":true,\"libc\":\"%s\",\"before\":", gnu_get_libc_version());
    print_meta(&before); puts("}");
    int rows = completed + (failure.present && failure.stage != 4);
    for (int i = 0; i < rows; ++i) {
        printf("{\"type\":\"sample\",\"index\":%d,\"clocks\":[", i + 1);
        for (int c = 0; c < NCLOCKS; ++c) {
            struct family *f = &data[i].clock[c];
            printf("%s{\"cpu_before\":%d,\"cpu_after\":%d,\"ns\":[", c ? "," : "", f->before, f->after);
            for (int p = 0; p < f->valid; ++p) printf("%s%" PRId64, p ? "," : "", f->ns[p]);
            printf("]}");
        }
        puts("]}");
    }
    int complete = !failure.present && after_ok && before.affinity == after.affinity &&
        !strcmp(before.boot, after.boot) && !strcmp(before.clocksource, after.clocksource);
    printf("{\"type\":\"footer\",\"complete\":%s,\"completed\":%d,\"after\":", complete ? "true" : "false", completed);
    print_meta(&after);
    printf(",\"failure\":{\"present\":%s,\"sequence\":%d,\"clock\":%d,\"position\":%d,\"stage\":%d,"
           "\"rc\":%d,\"errno\":%d,\"sec\":%" PRId64 ",\"nsec\":%" PRId64 "}}\n",
           failure.present ? "true" : "false", failure.sequence, failure.clock, failure.position, failure.stage,
           failure.raw.rc, failure.raw.error, failure.raw.sec, failure.raw.nsec);
    int output_error = fflush(stdout) || ferror(stdout);
    free(data); dlclose(handle);
    return complete && !output_error ? 0 : 1;
}
#endif
