/* SPDX-License-Identifier: ISC */
/* Additional hardware/kernel seams for the actual-source PM tests. */
#include <stdarg.h>
#define rmb() atomic_thread_fence(memory_order_seq_cst)
#undef wmb
#define wmb() do { if (role == TXCONTROL) assert(host_claimed); \
 atomic_thread_fence(memory_order_seq_cst); } while (0)
#define min(a, b) ((a) < (b) ? (a) : (b))
#define WARN(condition, ...) assert(!(condition))
#define IRQ_HANDLED 1
#define TASK_INTERRUPTIBLE 1
#define TASK_RUNNING 0
#define ERESTARTSYS 512
#define BRCMF_BUS_DOWN 0
#define BRCMF_BUS_UP 1
typedef int irqreturn_t;
struct sk_buff { unsigned len; void *data; };
struct mmc_data { unsigned sg_len, blocks; int error; };
struct mmc_command { unsigned arg; int error; };
struct mmc_request { int unused; };
struct seq_file { int unused; };
struct sdpcm_shared { unsigned flags, assert_file_addr, assert_exp_addr, assert_line; };
static struct brcmf_sdio_dev *io_dev;
static struct {
 atomic_uint raw, irq_release, irq_mask, irq_free, queue, ctrl_wake, resp_wake;
 unsigned addr, size, ram_reads;
 unsigned ram_fail_at;
} pm_seen;

static void raw_io(void)
{
 assert(host_claimed);
 pm_seen.raw++;
 assert(!io_dev->pm_failed);
}
static u8 sdio_readb(struct sdio_func *f, unsigned addr, int *ret)
{ (void)f; raw_io(); pm_seen.addr = addr; if (ret) *ret = 0; return 0x55; }
static u8 sdio_f0_readb(struct sdio_func *f, unsigned addr, int *ret)
{ return sdio_readb(f, addr, ret); }
static void sdio_writeb(struct sdio_func *f, u8 value, unsigned addr, int *ret)
{ (void)value; (void)sdio_readb(f, addr, ret); }
static void sdio_f0_writeb(struct sdio_func *f, u8 value, unsigned addr, int *ret)
{ sdio_writeb(f, value, addr, ret); }
static u32 sdio_readl(struct sdio_func *f, unsigned addr, int *ret)
{ (void)sdio_readb(f, addr, ret); return 0x12345678; }
static void sdio_writel(struct sdio_func *f, u32 value, unsigned addr, int *ret)
{ (void)value; (void)sdio_readl(f, addr, ret); }
static int sdio_memcpy_fromio(struct sdio_func *f, void *data, unsigned addr, unsigned size)
{ (void)f; (void)data; raw_io(); pm_seen.addr = addr; pm_seen.size = size; return 0; }
static int sdio_readsb(struct sdio_func *f, void *data, unsigned addr, unsigned size)
{ return sdio_memcpy_fromio(f, data, addr, size); }
static int sdio_memcpy_toio(struct sdio_func *f, unsigned addr, void *data, unsigned size)
{ return sdio_memcpy_fromio(f, data, addr, size); }
static void mmc_set_data_timeout(struct mmc_data *data, struct mmc_card *card)
{ (void)data; (void)card; }
static void mmc_wait_for_req(struct mmc_host *host, struct mmc_request *request)
{ (void)host; (void)request; raw_io(); }
static int mmc_hw_reset(struct mmc_card *card) { (void)card; raw_io(); return 0; }
static mmc_pm_flag_t sdio_get_host_pm_caps(struct sdio_func *f)
{ return f->card->host->pm_caps; }
static int sdio_release_irq(struct sdio_func *f)
{ (void)f; assert(host_claimed); pm_seen.irq_release++; return faults.release_irq; }
static void disable_irq_nosync(int irq) { (void)irq; assert(lock_depth == 1); pm_seen.irq_mask++; }
static void free_irq(int irq, void *dev) { (void)irq; (void)dev; pm_seen.irq_free++; }
static void brcmf_bus_change_state(struct brcmf_bus *b, int state)
{ (void)b; if (state == BRCMF_BUS_UP) seen.up++; else seen.down++; }
static void brcmf_sdio_wait_event_wakeup(struct brcmf_sdio *b)
{ pm_seen.ctrl_wake++; wake_up(&b->ctrl_wait); }
static void wake_up_interruptible(wait_queue_head_t *q)
{ pm_seen.resp_wake++; wake_up(q); }
static bool queue_work(void *queue, struct work_struct *work)
{ (void)queue; (void)work; seen.trigger++; pm_seen.queue++; return true; }
static int brcmf_sdio_intr_rstatus(struct brcmf_sdio *b)
{ (void)b; raw_io(); return 0; }
static void brcmf_sdio_trigger_dpc(struct brcmf_sdio *bus);
static void seq_printf(struct seq_file *seq, const char *format, ...)
{ (void)seq; (void)format; }
static int brcmf_sdiod_ramrw(struct brcmf_sdio_dev *d, bool write, u32 addr, u8 *data, unsigned size)
{
 (void)d; (void)write; (void)addr; (void)data; (void)size;
 assert(host_claimed);
 pm_seen.ram_reads++;
 return pm_seen.ram_reads == pm_seen.ram_fail_at ? -EHOSTDOWN : 0;
}
static int brcmf_sdio_checkdied(struct brcmf_sdio *b)
{ (void)b; assert(false); return 0; } /* Must not start firmware diagnostics after a PM fault. */
#define spin_lock_bh(lock) do { assert(!pthread_mutex_lock(lock)); lock_depth++; } while (0)
#define spin_unlock_bh(lock) do { lock_depth--; assert(!pthread_mutex_unlock(lock)); } while (0)
#define vfree(ptr) free(ptr)
/* Expiry isn't measured here: exercise publication/completion under real locks. */
#define wait_event_interruptible_timeout(q, condition, duration) \
 ((void)(duration), wait_event_timeout(q, condition, 5000))

static _Thread_local wait_queue_head_t *response_queue;
static _Thread_local unsigned response_sequence;
#define current NULL
#define DECLARE_WAITQUEUE(name, task) int name
static bool signal_pending(void *task) { (void)task; return false; }
static void add_wait_queue(wait_queue_head_t *q, int *wait)
{ (void)wait; response_queue = q; }
static void remove_wait_queue(wait_queue_head_t *q, int *wait)
{ (void)q; (void)wait; response_queue = NULL; }
static void set_current_state(int state)
{
 if (state != TASK_INTERRUPTIBLE) return;
 assert(!pthread_mutex_lock(&response_queue->lock));
 response_sequence = response_queue->sequence;
 assert(!pthread_mutex_unlock(&response_queue->lock));
}
static int schedule_timeout(int timeout)
{
 wait_queue_head_t *q = response_queue;
 struct timespec limit = deadline(2000);
 assert(!pthread_mutex_lock(&q->lock));
 if (response_sequence == q->sequence) {
  q->sleepers++;
  assert(!pthread_cond_timedwait(&q->cond, &q->lock, &limit));
  q->sleepers--;
 }
 response_sequence = q->sequence;
 assert(!pthread_mutex_unlock(&q->lock));
 return timeout;
}
