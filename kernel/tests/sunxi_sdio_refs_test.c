/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Actual Sunxi callback and MMC thread/resume functions with bounded API shims. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint32_t u32;
#define SDXC_SDIO_INTERRUPT (1U << 16)
#define REG_IMASK 0
#define MMC_CAP_SDIO_IRQ 1
#define MMC_CAP_POWER_OFF_CARD 2
#define MMC_CAP2_SDIO_IRQ_NOTHREAD 1
#define MMC_PM_KEEP_POWER 1
#define MMC_PM_WAKE_SDIO_IRQ 2
#define TASK_INTERRUPTIBLE 1
#define TASK_RUNNING 0
#define MAX_SCHEDULE_TIMEOUT 1000000UL
#define HZ 100UL
#define current NULL
#define pr_debug(...) ((void)0)
#define WARN_ON(x) assert(!(x))

struct device { int refs; };
struct mmc_host;
struct mmc_card { struct mmc_host *host; struct device dev; unsigned int ocr; bool suspended; };
struct mmc_host_ops { void (*enable_sdio_irq)(struct mmc_host *, int); };
struct mmc_host {
	struct device *parent;
	struct mmc_card *card;
	const struct mmc_host_ops *ops;
	unsigned int caps, caps2, pm_flags, sdio_irqs, retune_period;
	int claimed, sdio_irq_thread_abort, sdio_irq_work;
	bool sdio_irq_pending;
	void *sdio_irq_thread, *private;
};
struct sunxi_mmc_host {
	struct device *dev;
	struct mmc_host *mmc;
	int lock;
	u32 sdio_imask, reg;
};
static struct device device;
static struct mmc_host mmc;
static struct mmc_card card;
static struct sunxi_mmc_host host;
static unsigned int gets, put_count, writes, wakes, queued, scenarios;
static bool characterize, stop;
static int base_refs, pending_error, resume_error, thread_error;
static unsigned int step;
enum action { IRQ, RESUME, SPURIOUS, ERROR_WAKE, ABORT, STOP };
static const enum action *script;
static size_t script_size;

#define mmc_priv(m) ((struct sunxi_mmc_host *)(m)->private)
#define spin_lock_irqsave(l, f) do { assert(!*(l)); *(l) = 1; (f) = 0; } while (0)
#define spin_unlock_irqrestore(l, f) do { (void)(f); assert(*(l)); *(l) = 0; } while (0)

static void pm_runtime_get_noresume(struct device *dev)
{
	assert(dev == &device);
	if (!characterize)
		assert(host.lock); /* Check reference/state serialization contract. */
	dev->refs++;
	gets++;
}
static void pm_runtime_put_noidle(struct device *dev)
{
	assert(dev == &device);
	if (!characterize) {
		assert(host.lock);
		assert(!(host.reg & SDXC_SDIO_INTERRUPT));
	}
	/* Match atomic_add_unless(..., -1, 0), not an unchecked decrement. */
	if (dev->refs)
		dev->refs--;
	put_count++;
}
static u32 mmc_readl(struct sunxi_mmc_host *h, int reg)
{
	assert(h == &host && h->lock && reg == REG_IMASK);
	return h->reg;
}
static void mmc_writel(struct sunxi_mmc_host *h, int reg, u32 value)
{
	assert(h == &host && h->lock && reg == REG_IMASK);
	if (!characterize && (value & SDXC_SDIO_INTERRUPT))
		assert(device.refs == base_refs + 1); /* Get must precede unmask. */
	h->reg = value;
	writes++;
}
static void mmc_claim_host(struct mmc_host *m) { assert(!m->claimed); m->claimed = 1; }
static void mmc_release_host(struct mmc_host *m) { assert(m->claimed); m->claimed = 0; }
static int __mmc_claim_host(struct mmc_host *m, void *unused, int *abort)
{
	(void)unused;
	if (*abort)
		return 1;
	mmc_claim_host(m);
	return 0;
}
static int process_sdio_pending_irqs(struct mmc_host *m)
{
	assert(m->claimed);
	if (m->card->suspended)
		return 0;
	m->sdio_irq_pending = false;
	int ret = pending_error;
	pending_error = 0;
	return ret;
}
static void sched_set_fifo_low(void *task) { (void)task; }
static unsigned long msecs_to_jiffies(unsigned long n) { return n; }
static void set_current_state(int state) { (void)state; }
static bool kthread_should_stop(void) { return stop; }
static void wake_up_process(void *task) { assert(task == &mmc); wakes++; }
static void schedule_work(int *work) { assert(work == &mmc.sdio_irq_work); queued++; }
static void cancel_work_sync(int *work) { assert(work == &mmc.sdio_irq_work); }
static void atomic_set(int *value, int n) { *value = n; }
static const char *mmc_hostname(struct mmc_host *m) { (void)m; return "test"; }
static void *kthread_run(int (*fn)(void *), void *arg, const char *fmt, const char *name)
{
	(void)fn; (void)fmt; (void)name;
	return thread_error ? (void *)(intptr_t)thread_error : arg;
}
#define IS_ERR(p) ((intptr_t)(p) < 0)
#define PTR_ERR(p) ((int)(intptr_t)(p))
static int sdio_irq_thread(void *arg);
static void kthread_stop(void *arg) { stop = true; sdio_irq_thread(arg); }
static bool mmc_card_keep_power(struct mmc_host *m) { return m->pm_flags & MMC_PM_KEEP_POWER; }
static bool mmc_card_wake_sdio_irq(struct mmc_host *m) { return m->pm_flags & MMC_PM_WAKE_SDIO_IRQ; }
static void mmc_card_set_suspended(struct mmc_card *c) { c->suspended = true; }
static void mmc_card_clr_suspended(struct mmc_card *c) { c->suspended = false; }
static void sdio_disable_4bit_bus(struct mmc_card *c) { (void)c; }
static int sdio_enable_4bit_bus(struct mmc_card *c) { (void)c; return resume_error; }
static void mmc_power_off(struct mmc_host *m) { assert(m->claimed); }
static void mmc_power_up(struct mmc_host *m, unsigned int ocr) { (void)ocr; assert(m->claimed); }
static int mmc_sdio_reinit_card(struct mmc_host *m) { assert(m->claimed); return resume_error; }
static void mmc_retune_timer_stop(struct mmc_host *m) { (void)m; }
static void mmc_retune_needed(struct mmc_host *m) { (void)m; }
static void mmc_retune_hold_now(struct mmc_host *m) { (void)m; }
static void mmc_retune_release(struct mmc_host *m) { (void)m; }
static void pm_runtime_disable(struct device *d) { (void)d; }
static void pm_runtime_set_active(struct device *d) { (void)d; }
static void pm_runtime_enable(struct device *d) { (void)d; }
static void schedule_timeout(unsigned long period);

#include "sunxi_sdio_ref_functions.h"

static const struct mmc_host_ops ops = { .enable_sdio_irq = sunxi_mmc_enable_sdio_irq };
static void reset(int baseline)
{
	memset(&host, 0, sizeof(host));
	memset(&mmc, 0, sizeof(mmc));
	memset(&card, 0, sizeof(card));
	device.refs = base_refs = baseline;
	host.dev = &device; host.mmc = &mmc;
	host.reg = 0x1234; /* Unrelated command/error interrupt bits. */
	mmc.parent = &device; mmc.private = &host; mmc.card = &card;
	mmc.ops = &ops; mmc.caps = MMC_CAP_SDIO_IRQ; mmc.sdio_irq_thread = &mmc;
	mmc.pm_flags = MMC_PM_KEEP_POWER; card.host = &mmc;
	gets = put_count = writes = wakes = queued = step = 0;
	pending_error = resume_error = thread_error = 0;
	stop = false;
}
static void balanced(void)
{
	assert(device.refs == base_refs + !!host.sdio_imask);
	assert((int)gets - (int)put_count == !!host.sdio_imask);
	assert(!host.lock);
}
static void schedule_timeout(unsigned long period)
{
	if (period == HZ)
		return; /* The core thread's error backoff, no synthetic IRQ. */
	assert(period == MAX_SCHEDULE_TIMEOUT && step < script_size);
	if (!characterize)
		balanced();
	switch (script[step++]) {
	case IRQ: mmc_signal_sdio_irq(&mmc); break;
	case RESUME:
		mmc.pm_flags = MMC_PM_KEEP_POWER;
		assert(mmc_sdio_suspend(&mmc) == 0);
		assert(mmc_sdio_resume(&mmc) == 0);
		break;
	case SPURIOUS: break;
	case ERROR_WAKE: pending_error = -EIO; break;
	case ABORT: mmc.sdio_irq_thread_abort = 1; break;
	case STOP: stop = true; break;
	}
}
static void sequences(void)
{
	/* All 8-request histories, both initial states, with foreign references. */
	for (int base = 0; base <= 3; base++)
	for (int initial = 0; initial <= 1; initial++)
	for (unsigned int bits = 0; bits < 256; bits++) {
		reset(base);
		if (initial)
			sunxi_mmc_enable_sdio_irq(&mmc, 1);
		for (unsigned int i = 0; i < 8; i++) {
			int on = !!(bits & (1U << i));
			unsigned int n = writes;
			sunxi_mmc_enable_sdio_irq(&mmc, on);
			balanced();
			assert(writes == n + 1);
			assert(host.reg == (0x1234U | (on ? SDXC_SDIO_INTERRUPT : 0)));
		}
		sunxi_mmc_enable_sdio_irq(&mmc, 0);
		balanced(); assert(device.refs == base);
		scenarios++;
	}
}
static void core_paths(void)
{
	const enum action actions[] = { IRQ, RESUME, SPURIOUS, IRQ, ERROR_WAKE, RESUME, STOP };
	const enum action abort_irq[] = { IRQ, ABORT };
	const enum action abort_on[] = { RESUME, ABORT };
	const enum action *runs[] = { actions, abort_irq, abort_on };
	const size_t sizes[] = { sizeof(actions)/sizeof(*actions), 2, 2 };
	for (unsigned int i = 0; i < 3; i++) {
		reset(1); mmc.sdio_irqs = 1;
		script = runs[i]; script_size = sizes[i];
		sdio_irq_thread(&mmc);
		assert(step == script_size);
		balanced(); assert(!host.sdio_imask && device.refs == 1);
		scenarios++;
	}
	/* Restore the IRQ bit after register loss, even if cached state is on. */
	reset(1); sunxi_mmc_enable_sdio_irq(&mmc, 1);
	host.reg = 0x1234;
	sunxi_mmc_enable_sdio_irq(&mmc, 1);
	assert(host.reg == (0x1234U | SDXC_SDIO_INTERRUPT)); balanced(); scenarios++;
	/* Card resume failure must not manufacture another enable or lose ownership. */
	for (int keep = 0; keep <= 1; keep++) {
		reset(1); mmc.sdio_irqs = 1;
		sunxi_mmc_enable_sdio_irq(&mmc, 1);
		mmc.pm_flags = keep ? MMC_PM_KEEP_POWER | MMC_PM_WAKE_SDIO_IRQ : 0;
		card.suspended = true; resume_error = -EIO;
		assert(mmc_sdio_resume(&mmc) == -EIO);
		assert(!wakes && !queued && card.suspended); balanced(); scenarios++;
	}
	/* Core acquisition/release: both threaded and no-thread branches. */
	for (int nothread = 0; nothread <= 1; nothread++) {
		reset(1); mmc.caps2 = nothread ? MMC_CAP2_SDIO_IRQ_NOTHREAD : 0;
		mmc_claim_host(&mmc);
		assert(sdio_card_irq_get(&card) == 0);
		assert(sdio_card_irq_get(&card) == 0);
		assert(mmc.sdio_irqs == 2);
		if (!nothread)
			sunxi_mmc_enable_sdio_irq(&mmc, 1); /* Initial thread rearm. */
		balanced(); assert(sdio_card_irq_put(&card) == 0); balanced();
		assert(sdio_card_irq_put(&card) == 0);
		balanced(); assert(device.refs == 1 && !mmc.sdio_irqs);
		assert(sdio_card_irq_put(&card) == -EINVAL);
		mmc_release_host(&mmc); scenarios++;
	}
	reset(1); thread_error = -ENOMEM; mmc_claim_host(&mmc);
	assert(sdio_card_irq_get(&card) == -ENOMEM);
	assert(!mmc.sdio_irqs && !gets); balanced(); scenarios++;
	/* No registered IRQ: resume has no IRQ thread to rearm. */
	reset(1); card.suspended = true;
	assert(mmc_sdio_resume(&mmc) == 0);
	assert(!wakes && !queued && !card.suspended); balanced(); scenarios++;
}
int main(int argc, char **argv)
{
	if (argc == 2 && !strcmp(argv[1], "--characterize-original")) {
		characterize = true;
		const enum action repeated[] = { RESUME, STOP };
		reset(1); mmc.sdio_irqs = 1; script = repeated; script_size = 2;
		sdio_irq_thread(&mmc);
		assert(gets == 2 && put_count == 1 && device.refs == 2);
		puts("Original: one retained-power resume leaks one reference after thread exit.");
		reset(2); sunxi_mmc_enable_sdio_irq(&mmc, 0);
		assert(device.refs == 1);
		puts("Original: disable while already disabled consumes a foreign reference.");
		return 0;
	}
	sequences(); core_paths();
	printf("%u scenarios passed: transitions, core thread/resume, IRQ service, errors and release.\n", scenarios);
	return 0;
}
