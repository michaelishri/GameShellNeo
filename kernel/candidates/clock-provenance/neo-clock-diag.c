// SPDX-License-Identifier: GPL-2.0-only
/* Isolated diagnostic: never installed by the normal image patch queue. */
#include <linux/capability.h>
#include <linux/debugfs.h>
#include <linux/init.h>
#include <linux/interrupt.h>
#include <linux/mutex.h>
#include <linux/nsproxy.h>
#include <linux/sched.h>
#include <linux/sched/task.h>
#include <linux/seq_file.h>
#include <linux/slab.h>
#include <linux/timekeeper_internal.h>
#include <linux/time_namespace.h>
#include <linux/uaccess.h>
#include <linux/wait.h>
#include "neo-clock-diag.h"

#define NEO_CALLS 1024
#define NEO_WRITERS 2048

enum neo_phase { NEO_READY, NEO_RUNNING, NEO_STOPPED };
enum neo_stop { NEO_NONE, NEO_MANUAL, NEO_CALL_LIMIT, NEO_WRITER_LIMIT, NEO_CLOSED };
struct neo_base {
	u64 mask, cycle_last, xtime_nsec, max_cycles, max_raw_delta;
	s64 base;
	u32 mult, shift, source_id;
};
struct neo_tuple {
	struct neo_base mono, raw;
	u64 xtime_sec, raw_sec;
	s64 wall_sec, wall_nsec, offs_boot;
	u32 clock_set, source_changed;
};
struct neo_clock_call {
	u64 ordinal, read_order, end_order, cycles, ns;
	struct neo_tuple tuple;
	struct timespec64 result, namespace_offset;
	u32 namespace_id;
	u32 seq, attempts, cpu, end_cpu;
	int clock, abi, syscall_nr, tid, tgid, error;
	bool accepted, valid, complete;
};
struct neo_writer {
	u64 order, cycles, delta;
	bool delta_valid;
	struct neo_tuple old, new;
	u32 cpu, seq, action;
	int kind; /* 0: publication; others: read context (SETUP already seeds anchors) */
};
/* Bounded storage exists only in a diagnostic-enabled kernel; no IRQ allocation. */
static struct neo_clock_call calls[NEO_CALLS];
static struct neo_writer writers[NEO_WRITERS];
static DEFINE_RAW_SPINLOCK(neo_lock);
static DEFINE_MUTEX(neo_control);
static DECLARE_WAIT_QUEUE_HEAD(neo_wait);
static struct task_struct *owner;
static struct neo_clock_call *active;
static enum neo_phase phase;
static enum neo_stop reason;
static u32 call_count, writer_count, call_limit, writer_lost;
static u64 order;
static bool started;
#ifdef CONFIG_NEO_CLOCK_DIAG_KUNIT_TEST
static const struct timekeeper *test_writer_filter;
#endif

static void neo_base_copy(struct neo_base *d, const struct tk_read_base *s)
{
	d->mask = s->mask;
	d->cycle_last = s->cycle_last;
	d->xtime_nsec = s->xtime_nsec;
	d->mult = s->mult;
	d->shift = s->shift;
	d->base = s->base;
	d->max_cycles = s->clock ? s->clock->max_cycles : 0;
	d->max_raw_delta = s->clock ? s->clock->max_raw_delta : 0;
	d->source_id = s->clock ? s->clock->id : 0;
}

static void neo_tuple_copy(struct neo_tuple *d, const struct timekeeper *s)
{
	neo_base_copy(&d->mono, &s->tkr_mono);
	neo_base_copy(&d->raw, &s->tkr_raw);
	d->xtime_sec = s->xtime_sec;
	d->raw_sec = s->raw_sec;
	d->wall_sec = s->wall_to_monotonic.tv_sec;
	d->wall_nsec = s->wall_to_monotonic.tv_nsec;
	d->offs_boot = s->offs_boot;
	d->clock_set = s->clock_was_set_seq;
	d->source_changed = s->cs_was_changed_seq;
}

/* Only the owner task can dereference active. IRQ/NMI readers are excluded. */
static struct neo_clock_call *neo_current(void)
{
	if (!in_task() || READ_ONCE(owner) != current)
		return NULL;
	return READ_ONCE(active);
}

struct neo_clock_call *neo_clock_begin(int clock, int abi)
{
	struct neo_clock_call *c = NULL;
	unsigned long flags;

	if (clock != CLOCK_MONOTONIC && clock != CLOCK_MONOTONIC_RAW && clock != CLOCK_BOOTTIME)
		return NULL;
	if (!in_task() || READ_ONCE(owner) != current)
		return NULL;
	raw_spin_lock_irqsave(&neo_lock, flags);
	if (phase == NEO_RUNNING && !active) {
		c = &calls[call_count++];
		c->ordinal = call_count;
		c->clock = clock;
		c->abi = abi;
		/* These are ARM EABI numbers. UML tests explicitly have no ARM syscall. */
		c->syscall_nr = IS_ENABLED(CONFIG_ARM) ? (abi == 64 ? 403 : 263) : -1;
		c->tid = task_pid_nr(current);
		c->tgid = task_tgid_nr(current);
		WRITE_ONCE(active, c);
	}
	raw_spin_unlock_irqrestore(&neo_lock, flags);
	return c;
}

bool neo_clock_target(int clock)
{
	struct neo_clock_call *c = neo_current();

	return c && !c->accepted && c->clock == clock;
}

u64 neo_clock_read(const struct timekeeper *tk, const struct tk_read_base *tkr,
		   unsigned int seq, u64 (*read)(const struct tk_read_base *),
		   u64 (*convert)(const struct tk_read_base *, u64))
{
	struct neo_clock_call *c = neo_current();
	struct tk_read_base frozen = *tkr;
	struct clocksource source = { .max_cycles = tkr->clock->max_cycles };
	struct neo_base *b;
	unsigned long flags;

	/* Run the original conversion on precisely the tuple saved for this attempt.
	 * A sequence retry replaces this attempt, never the API's returned sample.
	 */
	neo_tuple_copy(&c->tuple, tk);
	b = c->clock == CLOCK_MONOTONIC_RAW ? &c->tuple.raw : &c->tuple.mono;
	neo_base_copy(b, &frozen);
	b->max_cycles = source.max_cycles;
	preempt_disable_notrace();
	c->cycles = read(tkr); /* Exactly one real counter read. */
	c->cpu = raw_smp_processor_id();
	preempt_enable_notrace();
	frozen.clock = &source;
	c->ns = convert(&frozen, c->cycles);
	c->seq = seq;
	if (c->attempts != U32_MAX)
		c->attempts++;
	/* Record order is diagnostic lock order, not a counter-read timestamp. */
	raw_spin_lock_irqsave(&neo_lock, flags);
	c->read_order = ++order;
	raw_spin_unlock_irqrestore(&neo_lock, flags);
	return c->ns;
}

void neo_clock_accepted(int clock)
{
	struct neo_clock_call *c = neo_current();

	if (c && c->clock == clock)
		c->accepted = true;
}

void neo_clock_end(struct neo_clock_call *c, const struct timespec64 *ts, bool valid, int error)
{
	unsigned long flags;

	if (!c)
		return;
	raw_spin_lock_irqsave(&neo_lock, flags);
	c->valid = valid;
	if (valid)
		c->result = *ts; /* After namespace addition, even when user copy failed. */
	if (IS_ENABLED(CONFIG_TIME_NS)) {
		c->namespace_id = current->nsproxy->time_ns->ns.inum;
		c->namespace_offset = c->clock == CLOCK_BOOTTIME ?
			current->nsproxy->time_ns->offsets.boottime :
			current->nsproxy->time_ns->offsets.monotonic;
	}
	c->error = error;
	c->end_cpu = raw_smp_processor_id();
	c->end_order = ++order;
	c->complete = true;
	WRITE_ONCE(active, NULL);
	if (phase == NEO_RUNNING && call_count == call_limit) {
		WRITE_ONCE(phase, NEO_STOPPED);
		reason = NEO_CALL_LIMIT;
	}
	raw_spin_unlock_irqrestore(&neo_lock, flags);
	wake_up_all(&neo_wait);
}

/* Called under the core timekeeper's IRQ-safe writer lock. Never reads time. */
static struct neo_writer *neo_writer_reserve(void)
{
	if (phase != NEO_RUNNING)
		return NULL;
	if (writer_count == NEO_WRITERS) {
		writer_lost++;
		WRITE_ONCE(phase, NEO_STOPPED);
		reason = NEO_WRITER_LIMIT;
		return NULL;
	}
	writers[writer_count].order = ++order;
	writers[writer_count].cpu = raw_smp_processor_id();
	return &writers[writer_count++];
}

void neo_clock_writer_read(const struct timekeeper *tk, u64 cycles, int kind,
			   u64 delta, bool delta_valid)
{
	struct neo_writer *w;
	unsigned long flags;

#ifdef CONFIG_NEO_CLOCK_DIAG_KUNIT_TEST
	if (test_writer_filter && test_writer_filter != tk)
		return;
#endif
	if (tk->id != TIMEKEEPER_CORE || READ_ONCE(phase) != NEO_RUNNING)
		return;
	raw_spin_lock_irqsave(&neo_lock, flags);
	w = neo_writer_reserve();
	if (w) {
		w->kind = kind;
		w->cycles = cycles;
		w->delta = delta;
		w->delta_valid = delta_valid;
		neo_tuple_copy(&w->old, tk);
	}
	raw_spin_unlock_irqrestore(&neo_lock, flags);
}

void neo_clock_publish(const struct timekeeper *old, const struct timekeeper *new,
		       unsigned int seq, unsigned int action)
{
	struct neo_writer *w;
	unsigned long flags;

#ifdef CONFIG_NEO_CLOCK_DIAG_KUNIT_TEST
	if (test_writer_filter && test_writer_filter != new)
		return;
#endif
	if (new->id != TIMEKEEPER_CORE || READ_ONCE(phase) != NEO_RUNNING)
		return;
	raw_spin_lock_irqsave(&neo_lock, flags);
	w = neo_writer_reserve();
	if (w) {
		w->seq = seq; /* Odd publication sequence; accepted readers use seq+1. */
		w->action = action;
		neo_tuple_copy(&w->old, old);
		neo_tuple_copy(&w->new, new);
	}
	raw_spin_unlock_irqrestore(&neo_lock, flags);
}

static int neo_start(u32 limit)
{
	unsigned long flags;

	if (started || limit < 1 || limit > NEO_CALLS)
		return -EINVAL;
	/* No active reader/writer can touch the buffers before RUNNING. */
	memset(calls, 0, sizeof(calls));
	memset(writers, 0, sizeof(writers));
	raw_spin_lock_irqsave(&neo_lock, flags);
	call_count = writer_count = writer_lost = 0;
	order = 0;
	call_limit = limit;
	started = true;
	reason = NEO_NONE;
	WRITE_ONCE(phase, NEO_RUNNING);
	raw_spin_unlock_irqrestore(&neo_lock, flags);
	return 0;
}

static void neo_stop_capture(enum neo_stop stop)
{
	unsigned long flags;

	raw_spin_lock_irqsave(&neo_lock, flags);
	if (phase != NEO_STOPPED) {
		WRITE_ONCE(phase, NEO_STOPPED);
		reason = stop;
	}
	raw_spin_unlock_irqrestore(&neo_lock, flags);
	/* Closing from another thread must not recycle an in-flight record. */
	wait_event(neo_wait, !READ_ONCE(active));
}

static void neo_print_base(struct seq_file *m, const struct neo_base *b)
{
	seq_printf(m, "{\"mask\":%llu,\"last\":%llu,\"xtime\":%llu,\"max\":%llu,\"max_raw\":%llu,\"base\":%lld,\"mult\":%u,\"shift\":%u,\"source_id\":%u}",
		b->mask, b->cycle_last, b->xtime_nsec, b->max_cycles, b->max_raw_delta,
		b->base, b->mult, b->shift, b->source_id);
}

static void neo_print_tuple(struct seq_file *m, const struct neo_tuple *t)
{
	seq_puts(m, "{\"mono\":");
	neo_print_base(m, &t->mono);
	seq_puts(m, ",\"raw\":");
	neo_print_base(m, &t->raw);
	seq_printf(m, ",\"xtime_sec\":%llu,\"raw_sec\":%llu,\"wall_sec\":%lld,\"wall_nsec\":%lld,\"offs_boot\":%lld,\"clock_set\":%u,\"source_changed\":%u}",
		t->xtime_sec, t->raw_sec, t->wall_sec, t->wall_nsec, t->offs_boot,
		t->clock_set, t->source_changed);
}

static int neo_show(struct seq_file *m, void *unused)
{
	u32 i;
	unsigned long flags;
	bool readable;
	int ret = 0;

	mutex_lock(&neo_control);
	raw_spin_lock_irqsave(&neo_lock, flags);
	readable = current == owner && started && phase == NEO_STOPPED && !active;
	raw_spin_unlock_irqrestore(&neo_lock, flags);
	if (!readable) {
		ret = -EBUSY;
		goto out;
	}
	seq_printf(m, "{\"type\":\"header\",\"schema\":1,\"reason\":%u,\"calls\":%u,\"writers\":%u,\"writer_lost\":%u,\"limit\":%u,\"time_ns\":%u}\n",
		reason, call_count, writer_count, writer_lost, call_limit,
		IS_ENABLED(CONFIG_TIME_NS) ? current->nsproxy->time_ns->ns.inum : 0);
	for (i = 0; i < call_count; i++) {
		struct neo_clock_call *c = &calls[i];

		seq_printf(m, "{\"type\":\"call\",\"ordinal\":%llu,\"read_order\":%llu,\"end_order\":%llu,\"clock\":%d,\"abi\":%d,\"syscall\":%d,\"tid\":%d,\"tgid\":%d,\"cycles\":%llu,\"ns\":%llu,\"seq\":%u,\"attempts\":%u,\"cpu\":%u,\"end_cpu\":%u,\"accepted\":%u,\"valid\":%u,\"complete\":%u,\"error\":%d,\"sec\":%lld,\"nsec\":%ld,\"namespace_id\":%u,\"offset_sec\":%lld,\"offset_nsec\":%ld,\"tuple\":",
			c->ordinal, c->read_order, c->end_order, c->clock, c->abi, c->syscall_nr,
			c->tid, c->tgid, c->cycles, c->ns, c->seq, c->attempts, c->cpu,
			c->end_cpu, c->accepted, c->valid, c->complete, c->error,
			c->result.tv_sec, c->result.tv_nsec, c->namespace_id,
			c->namespace_offset.tv_sec, c->namespace_offset.tv_nsec);
		neo_print_tuple(m, &c->tuple);
		seq_puts(m, "}\n");
	}
	for (i = 0; i < writer_count; i++) {
		struct neo_writer *w = &writers[i];

		seq_printf(m, "{\"type\":\"writer\",\"order\":%llu,\"cpu\":%u,\"kind\":%d,\"cycles\":%llu,\"seq\":%u,\"action\":%u,\"delta\":%llu,\"delta_valid\":%u,\"old\":",
			w->order, w->cpu, w->kind, w->cycles, w->seq, w->action,
			w->delta, w->delta_valid);
		neo_print_tuple(m, &w->old);
		seq_puts(m, ",\"new\":");
		neo_print_tuple(m, &w->new);
		seq_puts(m, "}\n");
	}
 out:
	mutex_unlock(&neo_control);
	return ret;
}

static int neo_open(struct inode *inode, struct file *file)
{
	int ret;

	if (!capable(CAP_SYS_ADMIN))
		return -EPERM;
	mutex_lock(&neo_control);
	if (owner) {
		ret = -EBUSY;
		goto out;
	}
	ret = single_open(file, neo_show, NULL);
	if (!ret) {
		get_task_struct(current);
		WRITE_ONCE(owner, current);
		WRITE_ONCE(phase, NEO_READY);
		started = false;
	}
 out:
	mutex_unlock(&neo_control);
	return ret;
}

static ssize_t neo_write(struct file *f, const char __user *buf, size_t len, loff_t *pos)
{
	char command[32];
	u32 limit;
	int ret = -EINVAL;

	if (!len || len >= sizeof(command))
		return -EINVAL;
	if (copy_from_user(command, buf, len))
		return -EFAULT;
	if (memchr(command, 0, len))
		return -EINVAL;
	command[len] = 0;
	mutex_lock(&neo_control);
	if (current != owner) {
		ret = -EPERM;
	} else if (!strcmp(command, "stop\n")) {
		neo_stop_capture(NEO_MANUAL);
		ret = 0;
	} else if (!strncmp(command, "start ", 6) && !kstrtou32(command + 6, 10, &limit)) {
		ret = neo_start(limit);
	}
	mutex_unlock(&neo_control);
	return ret ? ret : len;
}

static int neo_release(struct inode *inode, struct file *file)
{
	struct task_struct *old;

	mutex_lock(&neo_control);
	neo_stop_capture(NEO_CLOSED);
	old = owner;
	WRITE_ONCE(owner, NULL);
	mutex_unlock(&neo_control);
	put_task_struct(old);
	return single_release(inode, file);
}

static const struct file_operations neo_fops = {
	.open = neo_open, .read = seq_read, .write = neo_write,
	.llseek = seq_lseek, .release = neo_release,
};

static int __init neo_init(void)
{
	/* No boot parameter or persistent service arms this diagnostic. */
	return PTR_ERR_OR_ZERO(debugfs_create_file("neo_clock_capture", 0600,
					     NULL, NULL, &neo_fops));
}
late_initcall(neo_init);

#ifdef CONFIG_NEO_CLOCK_DIAG_KUNIT_TEST
#include "neo-clock-diag-test.c"
#endif
