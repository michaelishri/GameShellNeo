/* Actual locked driver functions, with controlled pthread interleavings.
 * These shims exercise lifecycle contracts, not the Linux scheduler or SDIO.
 */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#ifndef CONFIG_PM_SLEEP
#define CONFIG_PM_SLEEP 1
#endif
#define IS_ENABLED(option) (option)
#define GFP_KERNEL 0
#define WARN_ON(condition) assert(!(condition))
#define brcmf_dbg(level, ...) do { if (0) fprintf(stderr, __VA_ARGS__); } while (0)
#define brcmf_err(...) do { if (0) fprintf(stderr, __VA_ARGS__); } while (0)
#define READ_ONCE(value) (value)
#define WRITE_ONCE(value, new_value) ((value) = (new_value))
#define unlikely(value) (value)
#define atomic_set(ptr, value) atomic_store(ptr, value)
#define wmb() atomic_thread_fence(memory_order_seq_cst)
#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define msecs_to_jiffies(ms) (ms)
typedef uint32_t u32;
typedef unsigned char u8;
typedef unsigned int mmc_pm_flag_t;
typedef pthread_mutex_t spinlock_t;
static _Thread_local unsigned lock_depth;
#define spin_lock_init(lock) assert(!pthread_mutex_init(lock, NULL))
#define spin_lock_irqsave(lock, flags) do { (flags) = 0; \
 assert(!pthread_mutex_lock(lock)); lock_depth++; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); \
 assert(lock_depth == 1); lock_depth--; assert(!pthread_mutex_unlock(lock)); } while (0)

static struct timespec deadline(unsigned ms)
{
 struct timespec t;
 assert(!clock_gettime(CLOCK_REALTIME, &t));
 t.tv_sec += ms / 1000;
 t.tv_nsec += (long)(ms % 1000) * 1000000;
 if (t.tv_nsec >= 1000000000) { t.tv_sec++; t.tv_nsec -= 1000000000; }
 return t;
}

#define UNTIL(condition) do { unsigned tries = 0; \
 while (!(condition) && tries++ < 2000) usleep(1000); \
 assert(condition); } while (0)

struct gate {
 pthread_mutex_t lock;
 pthread_cond_t cond;
 bool armed, reached, released;
};
static struct gate entry_gate, return_gate, watchdog_gate;
enum role { CONTROL, DATAWORK, WATCHDOG, TXCONTROL };
static _Thread_local enum role role;
static enum role gated_role;
static void gate_init(struct gate *g)
{
 *g = (struct gate){0};
 assert(!pthread_mutex_init(&g->lock, NULL));
 assert(!pthread_cond_init(&g->cond, NULL));
}
static void gate_pass(struct gate *g)
{
 assert(!lock_depth);
 assert(!pthread_mutex_lock(&g->lock));
 if (g->armed) {
  g->reached = true;
  assert(!pthread_cond_broadcast(&g->cond));
  struct timespec limit = deadline(10000);
  while (!g->released)
   assert(!pthread_cond_timedwait(&g->cond, &g->lock, &limit));
 }
 assert(!pthread_mutex_unlock(&g->lock));
}
static void gate_wait(struct gate *g)
{
 assert(!pthread_mutex_lock(&g->lock));
 struct timespec limit = deadline(2000);
 while (!g->reached)
  assert(!pthread_cond_timedwait(&g->cond, &g->lock, &limit));
 assert(!pthread_mutex_unlock(&g->lock));
}
static void gate_release(struct gate *g)
{
 assert(!pthread_mutex_lock(&g->lock));
 g->released = true;
 assert(!pthread_cond_broadcast(&g->cond));
 assert(!pthread_mutex_unlock(&g->lock));
}
static void gate_destroy(struct gate *g)
{
 assert(!pthread_cond_destroy(&g->cond));
 assert(!pthread_mutex_destroy(&g->lock));
}

typedef struct {
 pthread_mutex_t lock;
 pthread_cond_t cond;
 unsigned sequence, wait_sequence;
 atomic_uint sleepers;
} wait_queue_head_t;
static atomic_bool expire_wait;
static void init_waitqueue_head(wait_queue_head_t *q)
{
 assert(!pthread_mutex_init(&q->lock, NULL));
 assert(!pthread_cond_init(&q->cond, NULL));
}
static void wake_up(wait_queue_head_t *q)
{
 assert(!pthread_mutex_lock(&q->lock));
 q->sequence++;
 assert(!pthread_cond_broadcast(&q->cond));
 assert(!pthread_mutex_unlock(&q->lock));
}
/* Condition is evaluated outside the queue lock. Sequence checking preserves
 * a notification between the predicate test and going to sleep. Tests inject
 * expiry explicitly; the host deadline only bounds a broken test/harness.
 */
#define wait_event_timeout(queue, condition, duration) ({ \
 assert(!lock_depth && (duration) == 5000); \
 wait_queue_head_t *q_ = &(queue); \
 struct timespec limit_ = deadline(10000); \
 long result_ = 0; \
 for (;;) { \
  assert(!pthread_mutex_lock(&q_->lock)); \
  unsigned sequence_ = q_->sequence; \
  assert(!pthread_mutex_unlock(&q_->lock)); \
  if (condition) { result_ = 1; break; } \
  if (atomic_load(&expire_wait)) break; \
  assert(!pthread_mutex_lock(&q_->lock)); \
  if (sequence_ == q_->sequence && !atomic_load(&expire_wait)) { \
   q_->wait_sequence = sequence_; \
   atomic_fetch_add(&q_->sleepers, 1); \
   assert(!pthread_cond_timedwait(&q_->cond, &q_->lock, &limit_)); \
   atomic_fetch_sub(&q_->sleepers, 1); \
  } \
  assert(!pthread_mutex_unlock(&q_->lock)); \
 } \
 result_; \
})

struct completion {
 pthread_mutex_t lock;
 pthread_cond_t cond;
 bool done;
 unsigned waiters;
};
static void init_completion(struct completion *c)
{
 assert(!pthread_mutex_init(&c->lock, NULL));
 assert(!pthread_cond_init(&c->cond, NULL));
}
static void reinit_completion(struct completion *c)
{
 assert(!pthread_mutex_lock(&c->lock));
 assert(!c->waiters);
 c->done = false;
 assert(!pthread_mutex_unlock(&c->lock));
}
static void complete_all(struct completion *c)
{
 assert(!pthread_mutex_lock(&c->lock));
 c->done = true;
 assert(!pthread_cond_broadcast(&c->cond));
 assert(!pthread_mutex_unlock(&c->lock));
}
static void wait_for_completion(struct completion *c)
{
 assert(!lock_depth);
 assert(!pthread_mutex_lock(&c->lock));
 c->waiters++;
 assert(!pthread_mutex_unlock(&c->lock));
 if (role == gated_role) gate_pass(&entry_gate);
 assert(!pthread_mutex_lock(&c->lock));
 struct timespec limit = deadline(10000);
 while (!c->done)
  assert(!pthread_cond_timedwait(&c->cond, &c->lock, &limit));
 assert(!pthread_mutex_unlock(&c->lock));
 if (role == gated_role) gate_pass(&return_gate);
 assert(!pthread_mutex_lock(&c->lock));
 c->waiters--;
 assert(!pthread_mutex_unlock(&c->lock));
}
static void completion_destroy(struct completion *c)
{
 assert(!c->waiters);
 assert(!pthread_cond_destroy(&c->cond));
 assert(!pthread_mutex_destroy(&c->lock));
}

#include "brcmfmac_freezer_types.h"

enum brcmf_sdiod_state { BRCMF_SDIOD_DOWN, BRCMF_SDIOD_DATA, BRCMF_SDIOD_NOMEDIUM };
enum { MMC_CAP_POWER_OFF_CARD = 1, MMC_PM_KEEP_POWER = 2, MMC_PM_WAKE_SDIO_IRQ = 4 };
struct device { void *data; pthread_mutex_t mutex; };
struct mmc_host { unsigned caps, pm_caps; };
struct mmc_card { struct mmc_host *host; };
struct sdio_func { struct device dev; unsigned num, vendor, device; struct mmc_card *card; };
struct work_struct { int unused; };
struct brcmf_sdio_dev;
struct brcmf_bus { struct { struct brcmf_sdio_dev *sdio; } bus_priv; };
struct brcmfmac_sdio_pd {
 bool oob_irq_supported; int oob_irq_nr;
};
struct settings { struct { struct brcmfmac_sdio_pd sdio; } bus; };
struct brcmf_sdio {
 struct brcmf_sdio_dev *sdiodev;
 struct work_struct datawork;
 atomic_bool dpc_running, dpc_triggered;
 unsigned idlecount;
 struct completion watchdog_wait;
 wait_queue_head_t ctrl_wait, dcmd_resp_wait;
 unsigned char *ctrl_frame_buf, *rxctl, *rxctl_orig;
 unsigned ctrl_frame_len, rxlen;
 atomic_bool ctrl_frame_stat;
 int ctrl_frame_err;
 spinlock_t rxctl_lock;
 atomic_int intstatus, ipend;
 bool intr;
 void *brcmf_wq;
 struct { unsigned tickcnt, intrcount, tx_ctlerrs, tx_ctlpkts, rx_ctlerrs, rx_ctlpkts; } sdcnt;
};
struct brcmf_sdio_dev {
 struct brcmf_sdiod_freezer *freezer;
 struct brcmf_sdio *bus;
 struct sdio_func *func1;
 struct sdio_func *func2;
 struct brcmf_bus *bus_if;
 struct settings *settings;
 bool wowl_enabled;
 bool pm_suspended, pm_oob_irq_wake;
 bool pm_powered_off;
 atomic_bool pm_irq_blocked;
 atomic_bool pm_failed;
 bool oob_irq_requested, sd_irq_requested, irq_en;
 spinlock_t irq_en_lock;
 u32 sbwad;
 _Atomic enum brcmf_sdiod_state state;
};
struct counters {
 atomic_uint trigger, claims, releases, sleep, wake, down, up, wd_stop, wd_start;
 atomic_uint flags, irq_on, irq_off, dpc, wd_io, remove, probe, cancel, allow;
};
static struct counters seen;
static unsigned pm_flags;
static _Thread_local unsigned host_depth;
#define host_claimed (host_depth != 0)
static pthread_mutex_t host_lock;
static pthread_once_t host_once = PTHREAD_ONCE_INIT;
static void host_init(void)
{
 pthread_mutexattr_t attr;
 assert(!pthread_mutexattr_init(&attr));
 assert(!pthread_mutexattr_settype(&attr, PTHREAD_MUTEX_RECURSIVE));
 assert(!pthread_mutex_init(&host_lock, &attr));
 assert(!pthread_mutexattr_destroy(&attr));
}
static struct { int sleep, wake, enable, disable, flags, release_irq; } faults;
static bool allocation_fails;
static unsigned watchdog_mode, watchdog_loops;
static void *kzalloc(size_t size, int flags)
{ (void)flags; return allocation_fails ? NULL : calloc(1, size); }
static void kfree(void *ptr)
{
#ifdef NEO_SDIO_LIFECYCLE
 extern bool lifecycle_free(void *ptr);
 if (lifecycle_free(ptr)) return;
#endif
 struct brcmf_sdiod_freezer *f = ptr;
 completion_destroy(&f->resumed);
 assert(!pthread_cond_destroy(&f->thread_freeze.cond));
 assert(!pthread_mutex_destroy(&f->thread_freeze.lock));
 assert(!pthread_mutex_destroy(&f->lock));
 free(f);
}
static void *dev_get_drvdata(struct device *d) { return d->data; }
static void sdio_claim_host(struct sdio_func *f)
{
 (void)f; assert(!lock_depth);
 assert(!pthread_once(&host_once, host_init));
 assert(!pthread_mutex_lock(&host_lock)); host_depth++; seen.claims++;
}
static void sdio_release_host(struct sdio_func *f)
{
 (void)f; assert(!lock_depth && host_claimed);
 host_depth--; seen.releases++; assert(!pthread_mutex_unlock(&host_lock));
}
#ifndef NEO_PM_TRANSACTION
static void brcmf_sdio_trigger_dpc(struct brcmf_sdio *b)
{ assert(!lock_depth); b->dpc_triggered = true; seen.trigger++; }
static void brcmf_sdiod_change_state(struct brcmf_sdio_dev *d, int state)
{
 assert(!lock_depth);
 if (state == BRCMF_SDIOD_DATA) seen.up++; else seen.down++;
 d->state = state;
}
#endif
static int brcmf_sdio_sleep(struct brcmf_sdio *b, bool sleep)
{
 assert(!lock_depth && host_claimed && b->sdiodev->state == BRCMF_SDIOD_DOWN);
 if (sleep) seen.sleep++; else seen.wake++;
 return sleep ? faults.sleep : faults.wake;
}
static void brcmf_sdio_wd_timer(struct brcmf_sdio *b, bool active)
{
 assert(!lock_depth);
 if (active) { assert(b->sdiodev->state == BRCMF_SDIOD_DATA); seen.wd_start++; }
 else seen.wd_stop++;
}
static int enable_irq_wake(int irq) { (void)irq; seen.irq_on++; return faults.enable; }
static int disable_irq_wake(int irq) { (void)irq; seen.irq_off++; return faults.disable; }
static int sdio_set_host_pm_flags(struct sdio_func *f, mmc_pm_flag_t flags)
{ (void)f; seen.flags++; if (!faults.flags) pm_flags |= flags; return faults.flags; }
static void brcmf_sdiod_intr_unregister(struct brcmf_sdio_dev *d) { (void)d; seen.cancel++; }
#ifdef NEO_SDIO_LIFECYCLE
static void lifecycle_drain(struct brcmf_sdio *b);
static void lifecycle_cancel_reset(struct brcmf_bus *b);
static void lifecycle_remove(struct brcmf_sdio_dev *d);
#endif
static void brcmf_sdio_cancel_datawork(struct brcmf_sdio *b)
{
 (void)b; seen.cancel++;
#ifdef NEO_SDIO_LIFECYCLE
 lifecycle_drain(b);
#endif
}
static void brcmf_bus_cancel_reset_work(struct brcmf_bus *b)
{
 (void)b; seen.cancel++;
#ifdef NEO_SDIO_LIFECYCLE
 lifecycle_cancel_reset(b);
#endif
}
static void brcmf_bus_allow_reset_work(struct brcmf_bus *b) { (void)b; seen.allow++; }
static int brcmf_sdiod_remove(struct brcmf_sdio_dev *d)
{
 (void)d; seen.remove++;
#ifdef NEO_SDIO_LIFECYCLE
 lifecycle_remove(d);
#endif
 return 0;
}
static int brcmf_sdiod_probe(struct brcmf_sdio_dev *d) { (void)d; seen.probe++; return 0; }
static void brcmf_sdio_dpc(struct brcmf_sdio *b)
{ assert(!lock_depth && b->sdiodev->state == BRCMF_SDIOD_DATA); seen.dpc++; }
static void brcmf_sdio_bus_watchdog(struct brcmf_sdio *b)
{ assert(!lock_depth && b->sdiodev->state == BRCMF_SDIOD_DATA); seen.wd_io++; }
static void allow_signal(int sig) { assert(sig == SIGTERM); }
static bool kthread_should_stop(void) { return !watchdog_mode || watchdog_loops++ > 0; }
static int wait_for_completion_interruptible(struct completion *c)
{ (void)c; gate_pass(&watchdog_gate); return watchdog_mode == 1 ? -EINTR : 0; }

#ifdef NEO_PM_TRANSACTION
#include "brcmfmac_pm_shims.h"
#endif
#ifdef NEO_SDIO_LIFECYCLE
#include "brcmfmac_lifecycle_shims.h"
#endif
#include "brcmfmac_freezer_functions.h"
#ifdef NEO_SDIO_LIFECYCLE
/* Model the driver core's per-callback device locking, outside actual bodies. */
static int brcmf_ops_sdio_suspend(struct device *dev)
{
 device_lock(dev); int ret = callback_suspend(dev); device_unlock(dev); return ret;
}
static int brcmf_ops_sdio_resume(struct device *dev)
{
 device_lock(dev); int ret = callback_resume(dev); device_unlock(dev); return ret;
}
#endif

static struct {
 struct mmc_host host;
 struct mmc_card card;
 struct sdio_func f1, f2;
 struct settings settings;
 struct brcmf_bus interface;
 struct brcmf_sdio bus;
 struct brcmf_sdio_dev dev;
} fixture;
static atomic_bool pm_done;
static int pm_result;
static unsigned scenarios;
static void setup(void)
{
 fixture = (typeof(fixture)){0};
 seen = (struct counters){0};
 faults = (typeof(faults)){0};
 expire_wait = false;
 allocation_fails = false;
 pm_done = false;
 pm_result = 999;
 pm_flags = 0;
 watchdog_mode = watchdog_loops = 0;
 gate_init(&entry_gate); gate_init(&return_gate); gate_init(&watchdog_gate);
 gated_role = DATAWORK;
 fixture.card.host = &fixture.host;
 fixture.host.pm_caps = MMC_PM_KEEP_POWER | MMC_PM_WAKE_SDIO_IRQ;
 fixture.f1 = (struct sdio_func){ .num = 1, .card = &fixture.card, .dev.data = &fixture.interface };
 fixture.f2 = (struct sdio_func){ .num = 2, .card = &fixture.card, .dev.data = &fixture.interface };
#ifdef NEO_SDIO_LIFECYCLE
 lifecycle_setup(&fixture.f1.dev, &fixture.f2.dev);
#endif
 fixture.interface.bus_priv.sdio = &fixture.dev;
 fixture.dev = (struct brcmf_sdio_dev){ .bus = &fixture.bus, .func1 = &fixture.f1,
  .func2 = &fixture.f2, .bus_if = &fixture.interface,
  .settings = &fixture.settings, .state = BRCMF_SDIOD_DATA };
 fixture.bus.sdiodev = &fixture.dev;
 init_completion(&fixture.bus.watchdog_wait);
 init_waitqueue_head(&fixture.bus.ctrl_wait);
 init_waitqueue_head(&fixture.bus.dcmd_resp_wait);
 spin_lock_init(&fixture.bus.rxctl_lock);
 spin_lock_init(&fixture.dev.irq_en_lock);
 assert(!brcmf_sdiod_freezer_attach(&fixture.dev));
 brcmf_sdiod_freezer_count(&fixture.dev); /* Persistent datawork registration. */
}
static unsigned frozen(void)
{
 unsigned long flags;
 struct brcmf_sdiod_freezer *f = fixture.dev.freezer;
 spin_lock_irqsave(&f->lock, flags);
 unsigned result = f->frozen_count;
 spin_unlock_irqrestore(&f->lock, flags);
 return result;
}
static void teardown(void)
{
#ifdef NEO_SDIO_LIFECYCLE
 lifecycle_teardown(&fixture.f1.dev, &fixture.f2.dev);
#endif
 if (IS_ENABLED(CONFIG_PM_SLEEP)) {
  assert(!brcmf_sdiod_freezing(&fixture.dev));
  assert(!frozen());
  assert(fixture.dev.freezer->thread_count == 1);
 }
 assert(seen.claims == seen.releases && !host_claimed && !lock_depth);
 brcmf_sdiod_freezer_detach(&fixture.dev);
 completion_destroy(&fixture.bus.watchdog_wait);
 assert(!pthread_cond_destroy(&fixture.bus.ctrl_wait.cond));
 assert(!pthread_mutex_destroy(&fixture.bus.ctrl_wait.lock));
 assert(!pthread_cond_destroy(&fixture.bus.dcmd_resp_wait.cond));
 assert(!pthread_mutex_destroy(&fixture.bus.dcmd_resp_wait.lock));
 assert(!pthread_mutex_destroy(&fixture.bus.rxctl_lock));
 assert(!pthread_mutex_destroy(&fixture.dev.irq_en_lock));
 gate_destroy(&entry_gate); gate_destroy(&return_gate); gate_destroy(&watchdog_gate);
 scenarios++;
}
static void *suspend_thread(void *unused)
{
 (void)unused;
 pm_result = brcmf_ops_sdio_suspend(&fixture.f1.dev);
 pm_done = true;
 return NULL;
}
static void *data_thread(void *unused)
{
 (void)unused; role = DATAWORK;
 brcmf_sdio_dataworker(&fixture.bus.datawork);
 return NULL;
}
static void *watchdog_thread(void *unused)
{
 (void)unused; role = WATCHDOG;
 assert(!brcmf_sdio_watchdog_thread(&fixture.bus));
 return NULL;
}
static pthread_t start(void *(*entry)(void *))
{
 pthread_t thread;
 assert(!pthread_create(&thread, NULL, entry, NULL));
 return thread;
}
static void join(pthread_t thread) { assert(!pthread_join(thread, NULL)); }
static pthread_t start_suspend(void)
{
 pm_done = false;
#ifndef NEO_PM_TRANSACTION
 unsigned count = seen.trigger;
#endif
 pthread_t t = start(suspend_thread);
#ifdef NEO_PM_TRANSACTION
 UNTIL(brcmf_sdiod_freezing(&fixture.dev) || pm_done);
#else
 UNTIL(seen.trigger == count + 1);
#endif
 return t;
}
static void collect_result(pthread_t pm, int expected)
{ UNTIL(pm_done); join(pm); assert(pm_result == expected); }
static void force_expiry(void)
{ expire_wait = true; wake_up(&fixture.dev.freezer->thread_freeze); }
static void no_power_changes(void)
{
 assert(!seen.claims && !seen.releases && !seen.sleep && !seen.wake);
 assert(!seen.down && !seen.up && !seen.wd_stop && !seen.wd_start);
 assert(!seen.flags && !seen.irq_on && !seen.irq_off);
 assert(fixture.dev.state == BRCMF_SDIOD_DATA);
}
static void resume(void) { assert(!brcmf_ops_sdio_resume(&fixture.f2.dev)); }

static void successful_cycle(unsigned mode)
{
 setup();
 fixture.dev.wowl_enabled = mode != 0;
 fixture.settings.bus.sdio.oob_irq_supported = mode == 2;
 if (mode) fixture.host.caps = MMC_CAP_POWER_OFF_CARD; /* WOWL still retains. */
 pthread_t pm = start_suspend(), data = start(data_thread);
 collect_result(pm, 0);
#ifdef NEO_PM_TRANSACTION
 assert(fixture.dev.pm_suspended);
#endif
 assert(frozen() == 1 && fixture.dev.state == BRCMF_SDIOD_DOWN);
 assert(seen.down == 1 && seen.sleep == 1 && seen.wd_stop == 1);
 assert(pm_flags == (MMC_PM_KEEP_POWER | (mode == 1 ? MMC_PM_WAKE_SDIO_IRQ : 0)));
 assert(seen.irq_on == (mode == 2));
 /* Wrong function and repeated suspend must not disturb the transaction. */
 assert(!brcmf_ops_sdio_resume(&fixture.f1.dev));
 assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EBUSY);
 assert(seen.sleep == 1 && !seen.wake);
 resume(); join(data);
#ifdef NEO_PM_TRANSACTION
 assert(!fixture.dev.pm_suspended);
#endif
 assert(seen.up == 1 && seen.wake == 1 && seen.wd_start == 1);
 assert(seen.irq_off == (mode == 2));
 resume(); assert(seen.wake == 1);
 teardown();
}

static void absent_worker_timeout(void)
{
 setup();
 pthread_t pm = start_suspend();
 force_expiry(); collect_result(pm, -ETIMEDOUT);
 assert(!brcmf_sdiod_freezing(&fixture.dev));
 no_power_changes(); resume(); no_power_changes();
 /* Work queued by the failed collection must still be usable afterward. */
 join(start(data_thread));
 assert(seen.dpc == 1); no_power_changes();
 teardown();
}

static void late_worker_after_timeout(void)
{
 setup();
 pthread_t pm = start_suspend();
 force_expiry(); collect_result(pm, -ETIMEDOUT);
 resume(); no_power_changes();
 expire_wait = false;
 /* The previously queued work has not run yet; one execution can collect
  * for the new request without joining the already abandoned generation. */
 pm = start_suspend();
 pthread_t data = start(data_thread);
 collect_result(pm, 0); resume(); join(data);
#ifdef NEO_PM_TRANSACTION
 assert(seen.trigger == 1); /* The real trigger coalesces the already queued work. */
#else
 assert(seen.trigger == 2);
#endif
 assert(seen.dpc == 1 && seen.sleep == 1 && seen.up == 1);
 teardown();
}

static void partial_timeout(bool before_wait)
{
 setup();
 brcmf_sdiod_freezer_count(&fixture.dev); /* Second participant never arrives. */
 if (before_wait) entry_gate.armed = true;
 return_gate.armed = true;
 pthread_t pm = start_suspend(), data = start(data_thread);
 UNTIL(frozen() == 1);
 if (before_wait) gate_wait(&entry_gate);
 force_expiry(); collect_result(pm, -ETIMEDOUT);
 no_power_changes();
 assert(!brcmf_sdiod_freezing(&fixture.dev));
 assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EBUSY);
 resume(); no_power_changes();
 if (before_wait) gate_release(&entry_gate);
 gate_wait(&return_gate); /* Signaled but not yet retired. */
 assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EBUSY);
 gate_release(&return_gate); join(data);
 brcmf_sdiod_freezer_uncount(&fixture.dev);
 assert(!frozen());
 expire_wait = false;
 pm = start_suspend(); data = start(data_thread);
 collect_result(pm, 0); resume(); join(data);
 assert(seen.sleep == 1 && seen.wake == 1 && seen.down == 1 && seen.up == 1);
 teardown();
}

static bool collector_parked(wait_queue_head_t *q)
{
 assert(!pthread_mutex_lock(&q->lock));
 bool parked = atomic_load(&q->sleepers) && q->wait_sequence == q->sequence;
 assert(!pthread_mutex_unlock(&q->lock));
 return parked;
}

static void participant_withdrawal(void)
{
 setup(); brcmf_sdiod_freezer_count(&fixture.dev);
 entry_gate.armed = true;
 pthread_t pm = start_suspend(), data = start(data_thread);
 gate_wait(&entry_gate); /* Admission's notification has already been sent. */
 wait_queue_head_t *q = &fixture.dev.freezer->thread_freeze;
 UNTIL(collector_parked(q)); /* Slept on false after consuming that notification. */
 brcmf_sdiod_freezer_uncount(&fixture.dev);
 collect_result(pm, 0); resume(); gate_release(&entry_gate); join(data);
 teardown();
}

static void watchdog_arrival(bool late)
{
 setup(); watchdog_mode = 2; watchdog_gate.armed = true;
 pthread_t wd = start(watchdog_thread);
 gate_wait(&watchdog_gate); /* Watchdog is uncounted while waiting. */
 return_gate.armed = true; gated_role = WATCHDOG;
 if (!late) {
  /* Let its count/admission overlap the data worker collection. */
  entry_gate.armed = true;
 }
 pthread_t pm = start_suspend();
 if (!late) { gate_release(&watchdog_gate); gate_wait(&entry_gate); }
 pthread_t data = start(data_thread);
 collect_result(pm, 0);
 if (late) gate_release(&watchdog_gate);
 UNTIL(frozen() == 2);
 if (!late) gate_wait(&entry_gate);
 assert(!seen.wd_io); /* Newly counted watchdog must park before any I/O. */
 resume(); join(data);
 if (!late) gate_release(&entry_gate);
 gate_wait(&return_gate);
 assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EBUSY);
 gate_release(&return_gate); join(wd);
 assert(seen.wd_io == 1 && fixture.bus.sdcnt.tickcnt == 1);
 assert(seen.down == 1 && seen.up == 1);
 teardown();
}

static void repeated_success(void)
{
 setup(); return_gate.armed = true;
 pthread_t pm = start_suspend(), data = start(data_thread);
 collect_result(pm, 0); resume(); gate_wait(&return_gate);
 assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EBUSY);
 assert(seen.trigger == 1);
 gate_release(&return_gate); join(data);
 for (unsigned i = 0; i < 32; i++) {
  pm = start_suspend(); data = start(data_thread);
  collect_result(pm, 0); resume(); join(data);
 }
 assert(seen.sleep == 33 && seen.wake == 33 && seen.up == 33 && seen.down == 33);
 teardown();
}

int main(void)
{
 alarm(45);
 if (!IS_ENABLED(CONFIG_PM_SLEEP)) {
  setup(); assert(!fixture.dev.freezer);
  brcmf_sdiod_try_freeze(&fixture.dev);
  brcmf_sdiod_freezer_uncount(&fixture.dev);
  join(start(data_thread)); join(start(watchdog_thread));
  teardown(); puts("PM disabled: no freezer allocation or access"); return 0;
 }
 setup();
 assert(!brcmf_ops_sdio_suspend(&fixture.f2.dev));
 resume(); no_power_changes(); teardown();
 for (unsigned mode = 0; mode < 3; mode++) successful_cycle(mode);
 absent_worker_timeout();
 late_worker_after_timeout();
 for (unsigned i = 0; i < 8; i++) { partial_timeout(false); partial_timeout(true); }
 participant_withdrawal();
 for (unsigned i = 0; i < 8; i++) { watchdog_arrival(false); watchdog_arrival(true); }
 repeated_success();
 for (watchdog_mode = 0; watchdog_mode < 3;) {
  unsigned mode = watchdog_mode;
  setup(); watchdog_mode = mode;
  join(start(watchdog_thread)); teardown(); watchdog_mode = mode + 1;
 }
 setup(); fixture.host.caps = MMC_CAP_POWER_OFF_CARD;
 assert(!brcmf_ops_sdio_suspend(&fixture.f1.dev)); resume();
 assert(seen.remove == 1 && seen.probe == 1 && seen.cancel == 3 && seen.allow == 1);
 assert(!seen.trigger); no_power_changes(); teardown();
 struct brcmf_sdio_dev empty = {0};
 allocation_fails = true;
 assert(brcmf_sdiod_freezer_attach(&empty) == -ENOMEM);
 brcmf_sdiod_freezer_detach(&empty);
 printf("%u lifecycle scenarios passed (including repeated abort/reuse and 33-cycle reuse)\n", scenarios);
 return 0;
}
