/* Actual extcon/notifier functions; modeled SRCU, IRQ, allocation and sysfs.
 * This tests consumer ordering, not the Linux SRCU implementation/scheduler.
 */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define BIT(n) (1U << (n))
#define GFP_KERNEL 0
#define GFP_ATOMIC 0
#define KOBJ_CHANGE 0
#define NOTIFY_DONE 0
#define NOTIFY_STOP_MASK 0x8000
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define IS_ERR(p) ((uintptr_t)(p) > (uintptr_t)-4096)
#define PTR_ERR(p) ((intptr_t)(p))
#define unlikely(x) (x)
#define WARN(...) ((void)0)
#define trace_notifier_register(p) ((void)(p))
#define trace_notifier_unregister(p) ((void)(p))
#define rcu_assign_pointer(p, v) __atomic_store_n(&(p), (v), __ATOMIC_RELEASE)
#define rcu_dereference_raw(p) __atomic_load_n(&(p), __ATOMIC_ACQUIRE)

struct notifier_block {
    int (*notifier_call)(struct notifier_block *, unsigned long, void *);
    struct notifier_block *next;
    int priority;
};
struct raw_notifier_head { struct notifier_block *head; };
struct srcu_struct { pthread_mutex_t lock; pthread_cond_t idle; unsigned readers; };
struct device { int kobj; };
struct extcon_dev {
    struct device dev;
    unsigned state;
    pthread_mutex_t lock;
    int max_supported;
    const unsigned *supported_cable;
    struct raw_notifier_head *nh, nh_all;
    struct srcu_struct notifier_srcu;
};

static _Thread_local unsigned lock_depth, reader_depth, callback_depth;
static _Thread_local bool irq_context;
static unsigned allocations, inits, cleanups, frees, calls, syncs, max_depth;
static bool allocation_fails, init_fails, page_fails, nesting;
static struct notifier_block *target;
static void *pause_function;
static pthread_mutex_t gate = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static bool selected, release_callback, sync_entered, remove_returned;
static bool pause_after_entry;

static void wait_event(bool *value)
{
    struct timespec deadline;
    assert(clock_gettime(CLOCK_REALTIME, &deadline) == 0);
    deadline.tv_sec += 5;
    while (!*value)
        assert(pthread_cond_timedwait(&changed, &gate, &deadline) == 0);
}

static void *kzalloc(size_t size, int flags)
{
    (void)flags;
    if (allocation_fails) return NULL;
    allocations++;
    return calloc(1, size);
}
static void kfree(void *p) { if (p) { frees++; free(p); } }
static int init_srcu_struct(struct srcu_struct *s)
{
    if (init_fails) return -ENOMEM;
    assert(!pthread_mutex_init(&s->lock, NULL));
    assert(!pthread_cond_init(&s->idle, NULL));
    inits++;
    return 0;
}
static void cleanup_srcu_struct(struct srcu_struct *s)
{
    assert(!s->readers);
    assert(!pthread_cond_destroy(&s->idle));
    assert(!pthread_mutex_destroy(&s->lock));
    cleanups++;
}
static int srcu_read_lock(struct srcu_struct *s)
{
    assert(!lock_depth);
    assert(!pthread_mutex_lock(&s->lock));
    s->readers++;
    reader_depth++;
    if (reader_depth > max_depth) max_depth = reader_depth;
    assert(!pthread_mutex_unlock(&s->lock));
    return (int)reader_depth;
}
static void srcu_read_unlock(struct srcu_struct *s, int index)
{
    assert(!pthread_mutex_lock(&s->lock));
    assert(s->readers && reader_depth == (unsigned)index);
    s->readers--;
    reader_depth--;
    assert(!pthread_cond_broadcast(&s->idle));
    assert(!pthread_mutex_unlock(&s->lock));
}
static void might_sleep(void) { assert(!irq_context && !lock_depth && !callback_depth); }
static void synchronize_srcu(struct srcu_struct *s)
{
    might_sleep();
    assert(!pthread_mutex_lock(&s->lock));
    assert(!pthread_mutex_lock(&gate));
    syncs++;
    sync_entered = true;
    assert(!pthread_cond_broadcast(&changed));
    assert(!pthread_mutex_unlock(&gate));
    while (s->readers) assert(!pthread_cond_wait(&s->idle, &s->lock));
    assert(!pthread_mutex_unlock(&s->lock));
}
#define spin_lock_irqsave(p, flags) do { \
    (flags) = irq_context; assert(!pthread_mutex_lock(p)); lock_depth++; \
} while (0)
#define spin_unlock_irqrestore(p, flags) do { \
    assert(lock_depth && (flags) == irq_context); lock_depth--; \
    assert(!pthread_mutex_unlock(p)); \
} while (0)
static uintptr_t get_zeroed_page(int flags)
{
    (void)flags;
    return page_fails ? 0 : (uintptr_t)calloc(1, 4096);
}
static void free_page(unsigned long p) { free((void *)p); }
#define dev_err(...) ((void)0)
static int name_show(struct device *d, void *a, char *buf)
{ (void)d; (void)a; strcpy(buf, "fixture\n"); return 8; }
static int state_show(struct device *d, void *a, char *buf)
{ (void)d; (void)a; strcpy(buf, "1\n"); return 2; }
static void kobject_uevent(int *obj, int type)
{ (void)obj; (void)type; assert(!lock_depth && reader_depth == callback_depth); }
static void kobject_uevent_env(int *obj, int type, char **env)
{ (void)env; kobject_uevent(obj, type); }

/* The real notifier loop calls this after prefetching next_nb. Holding here
 * models a block selected before entering its callback, including a next block
 * removed while the preceding callback has not yet entered.
 */
static void hold_callback(void)
{
    assert(reader_depth);
    assert(!pthread_mutex_lock(&gate));
    selected = true;
    assert(!pthread_cond_broadcast(&changed));
    wait_event(&release_callback);
    assert(!pthread_mutex_unlock(&gate));
}
static void trace_notifier_run(void *fn)
{
    assert(reader_depth);
    if (fn == pause_function && !pause_after_entry) hold_callback();
}

#include "extcon_notifier_functions.h"

static int callback(struct notifier_block *nb, unsigned long state, void *value)
{
    (void)nb; (void)state;
    assert(reader_depth && !lock_depth);
    callback_depth++;
    if (pause_after_entry && nb == target) hold_callback();
    calls++;
    if (nesting && callback_depth == 1)
        assert(extcon_sync(value, 2) == 0);
    callback_depth--;
    return NOTIFY_DONE;
}
static int predecessor(struct notifier_block *nb, unsigned long state, void *value)
{ return callback(nb, state, value); }

static const unsigned cables[] = {1, 2, 0};
static struct extcon_dev *make_device(void)
{
    struct extcon_dev *d = extcon_dev_allocate(cables);
    assert(!IS_ERR(d));
    assert(d->supported_cable == cables && d->max_supported == 0);
    assert(!pthread_mutex_init(&d->lock, NULL));
    d->max_supported = 2;
    d->nh = calloc(2, sizeof(*d->nh));
    assert(d->nh);
    return d;
}
static void destroy_device(struct extcon_dev *d)
{
    assert(!d->nh[0].head && !d->nh[1].head && !d->nh_all.head);
    assert(!pthread_mutex_destroy(&d->lock));
    free(d->nh);
    extcon_dev_free(d);
}
static struct extcon_dev *current;
static bool dispatch_irq, ordinary;
static int removal_result;
static void *dispatch(void *unused)
{
    (void)unused;
    irq_context = dispatch_irq;
    assert(extcon_sync(current, 1) == 0);
    assert(!reader_depth);
    return NULL;
}
static void *remove_target(void *unused)
{
    (void)unused;
    removal_result = ordinary ? extcon_unregister_notifier(current, 1, target) :
        extcon_unregister_notifier_sync(current, 1, target);
    assert(!pthread_mutex_lock(&gate));
    remove_returned = true;
    assert(!pthread_cond_broadcast(&changed));
    assert(!pthread_mutex_unlock(&gate));
    return NULL;
}

static void race(unsigned kind, bool irq, bool asynchronous, bool active)
{
    struct notifier_block removed = {.notifier_call = callback};
    struct notifier_block other = {.notifier_call = predecessor, .priority = 1};
    pthread_t reader, remover;
    current = make_device();
    unsigned initial_calls = calls;
    target = &removed;
    dispatch_irq = irq;
    ordinary = asynchronous;
    pause_after_entry = active;
    selected = release_callback = sync_entered = remove_returned = false;
    pause_function = kind ? predecessor : callback;
    assert(!extcon_register_notifier(current, 1, target));
    if (kind == 1) assert(!extcon_register_notifier(current, 1, &other));
    if (kind == 2) assert(!extcon_register_notifier_all(current, &other));
    assert(!pthread_create(&reader, NULL, dispatch, NULL));
    assert(!pthread_mutex_lock(&gate));
    wait_event(&selected);
    assert(!pthread_create(&remover, NULL, remove_target, NULL));
    if (asynchronous) wait_event(&remove_returned);
    else {
        /* Either milestone wakes us; a lost grace period must fail promptly. */
        struct timespec deadline;
        assert(!clock_gettime(CLOCK_REALTIME, &deadline)); deadline.tv_sec += 5;
        while (!sync_entered && !remove_returned)
            assert(!pthread_cond_timedwait(&changed, &gate, &deadline));
        assert(sync_entered && !remove_returned);
    }
    assert(!pthread_mutex_unlock(&gate));
    /* Unlink occurred under the extcon lock; a new dispatch must not select
     * the removed block. Read the head with that same lock here. */
    assert(!pthread_mutex_lock(&current->lock));
    assert(current->nh[0].head != target);
    assert(!pthread_mutex_unlock(&current->lock));
    assert(!pthread_mutex_lock(&gate));
    release_callback = true;
    assert(!pthread_cond_broadcast(&changed));
    assert(!pthread_mutex_unlock(&gate));
    assert(!pthread_join(reader, NULL));
    assert(!pthread_join(remover, NULL));
    assert(removal_result == 0 && remove_returned);
    assert(calls == initial_calls + (kind ? 2 : 1));
    if (kind == 1) assert(!extcon_unregister_notifier_sync(current, 1, &other));
    if (kind == 2) assert(!extcon_unregister_notifier_all(current, &other));
    unsigned before = calls;
    pause_function = NULL;
    pause_after_entry = false;
    assert(!extcon_sync(current, 1));
    assert(calls == before);
    /* Same child block can register again after completed retirement. */
    assert(!extcon_register_notifier(current, 1, target));
    assert(!extcon_sync(current, 1) && calls == before + 1);
    assert(!extcon_unregister_notifier_sync(current, 1, target));
    destroy_device(current);
}

int main(void)
{
    unsigned cases = 0;
    assert(PTR_ERR(extcon_dev_allocate(NULL)) == -EINVAL);
    allocation_fails = true;
    assert(PTR_ERR(extcon_dev_allocate(cables)) == -ENOMEM);
    allocation_fails = false; init_fails = true;
    assert(PTR_ERR(extcon_dev_allocate(cables)) == -ENOMEM);
    assert(allocations == frees && inits == cleanups);
    init_fails = false;
    extcon_dev_free(NULL);
    extcon_dev_free(extcon_dev_allocate(cables)); /* Never registered. */
    assert(allocations == frees && inits == cleanups);
    cases += 5;
    struct extcon_dev *d = make_device();
    struct notifier_block nb = {.notifier_call = callback};
    assert(extcon_unregister_notifier_sync(NULL, 1, &nb) == -EINVAL);
    assert(extcon_unregister_notifier_sync(d, 1, NULL) == -EINVAL);
    assert(extcon_unregister_notifier_sync(d, 99, &nb) == -EINVAL);
    assert(extcon_unregister_notifier_sync(d, 1, &nb) == -ENOENT);
    assert(!syncs);
    assert(!extcon_register_notifier(d, 1, &nb));
    assert(extcon_register_notifier(d, 1, &nb) == -EEXIST);
    assert(!extcon_unregister_notifier_sync(d, 1, &nb) && syncs == 1);
    assert(extcon_sync(NULL, 1) == -EINVAL);
    assert(extcon_sync(d, 99) == -EINVAL);
    page_fails = true;
    assert(extcon_sync(d, 1) == -ENOMEM && !d->notifier_srcu.readers);
    page_fails = false;
    destroy_device(d);
    cases += 8;
    /* Reader nesting in both original process and simulated IRQ contexts. */
    for (unsigned irq = 0; irq < 2; irq++) {
        struct notifier_block first = {.notifier_call = callback};
        struct notifier_block second = {.notifier_call = callback};
        d = make_device();
        assert(!extcon_register_notifier(d, 1, &first));
        assert(!extcon_register_notifier(d, 2, &second));
        nesting = true; irq_context = irq;
        assert(!extcon_sync(d, 1) && max_depth == 2);
        nesting = irq_context = false;
        assert(!extcon_unregister_notifier_sync(d, 1, &first));
        assert(!extcon_unregister_notifier_sync(d, 2, &second));
        destroy_device(d);
        cases++;
    }
    for (unsigned kind = 0; kind < 3; kind++)
        for (unsigned irq = 0; irq < 2; irq++)
            for (unsigned asynchronous = 0; asynchronous < 2; asynchronous++) {
                race(kind, irq, asynchronous, false);
                cases++;
            }
    for (unsigned irq = 0; irq < 2; irq++) {
        race(0, irq, false, true);
        cases++;
    }
    assert(allocations == frees && inits == cleanups && !reader_depth && !lock_depth);
    printf("%u extcon scenarios passed (modeled SRCU/IRQ boundaries)\n", cases);
    return 0;
}
