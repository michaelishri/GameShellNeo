// SPDX-License-Identifier: GPL-2.0-only
#include <kunit/test.h>
#include <linux/completion.h>
#include <linux/kthread.h>
#include <linux/seqlock.h>

extern u64 neo_clock_test_read(const struct timekeeper *, unsigned int, int);
struct neo_fixture {
	struct timekeeper tk;
	struct clocksource clock;
	struct file file;
	u64 next;
	u32 reads;
	int preempt_count_at_read;
};
static struct neo_fixture *fixture;

static u64 scripted_counter(struct clocksource *clock)
{
	fixture->reads++;
	fixture->preempt_count_at_read = preempt_count();
	return fixture->next;
}

static int clock_fixture_init(struct kunit *test)
{
	struct neo_fixture *f = kunit_kzalloc(test, sizeof(*f), GFP_KERNEL);
	int ret;

	if (!f)
		return -ENOMEM;
	fixture = f;
	test->priv = f;
	f->clock.read = scripted_counter;
	f->clock.max_cycles = 1ULL << 40;
	f->clock.max_raw_delta = (1ULL << 55);
	f->clock.id = CSID_ARM_ARCH_COUNTER;
	f->tk.tkr_raw.clock = &f->clock;
	f->tk.tkr_raw.mask = (1ULL << 56) - 1;
	f->tk.tkr_raw.cycle_last = 1000;
	f->tk.tkr_raw.mult = 125;
	f->tk.tkr_raw.shift = 2;
	f->tk.tkr_raw.xtime_nsec = 400;
	f->tk.tkr_raw.base = 7000000000LL;
	f->tk.tkr_mono = f->tk.tkr_raw;
	f->tk.raw_sec = 7;
	f->tk.xtime_sec = 1007;
	f->tk.wall_to_monotonic.tv_sec = -1000;
	f->tk.offs_boot = 9000000000LL;
	f->next = 1200;
	test_writer_filter = &f->tk;
	ret = neo_open(NULL, &f->file);
	return ret;
}

static void clock_fixture_exit(struct kunit *test)
{
	struct neo_fixture *f = test->priv;

	if (active)
		neo_clock_end(active, NULL, false, -EINTR);
	neo_release(NULL, &f->file);
	test_writer_filter = NULL;
	fixture = NULL;
}

static void clock_exact_counter_test(struct kunit *test)
{
	struct neo_fixture *f = test->priv;
	struct neo_clock_call *c;
	struct timespec64 ts;
	u64 previous = 0, ns;
	int clocks[] = { CLOCK_MONOTONIC, CLOCK_MONOTONIC_RAW, CLOCK_BOOTTIME };
	int i;

	KUNIT_ASSERT_EQ(test, neo_start(6), 0);
	for (i = 0; i < 6; i++) {
		int clock = clocks[i / 2];

		f->next = i % 2 ? 1176 : 1200; /* Regression stays above update anchor. */
		c = neo_clock_begin(clock, i % 2 ? 32 : 64);
		KUNIT_ASSERT_NOT_NULL(test, c);
		ns = neo_clock_test_read(&f->tk, 8, clock);
		ts.tv_sec = clock == CLOCK_BOOTTIME ? 16 : 7;
		ts.tv_nsec = ns;
		neo_clock_accepted(clock);
		neo_clock_end(c, &ts, true, 0);
		KUNIT_EXPECT_EQ(test, c->cycles, f->next);
		KUNIT_EXPECT_EQ(test, c->ns, ns);
		KUNIT_EXPECT_EQ(test, c->attempts, 1U);
		KUNIT_EXPECT_EQ(test, c->seq, 8U);
		KUNIT_EXPECT_TRUE(test, c->accepted && c->valid && c->complete);
		KUNIT_EXPECT_EQ(test, c->cpu, (u32)raw_smp_processor_id());
		KUNIT_EXPECT_GT(test, f->preempt_count_at_read, 0);
		if (i % 2)
			KUNIT_EXPECT_EQ(test, previous - ns, 750ULL);
		previous = ns;
	}
	KUNIT_EXPECT_EQ(test, f->reads, 6U);
	KUNIT_EXPECT_EQ(test, phase, NEO_STOPPED);
	KUNIT_EXPECT_EQ(test, reason, NEO_CALL_LIMIT);
	KUNIT_EXPECT_PTR_EQ(test, neo_clock_begin(CLOCK_MONOTONIC_RAW, 64), NULL);
}

static void clock_retry_and_branches_test(struct kunit *test)
{
	struct neo_fixture *f = test->priv;
	struct neo_clock_call *c;
	struct timespec64 ts = { .tv_sec = 7 };
	seqcount_t seq;
	unsigned int start;
	u64 ns;

	KUNIT_ASSERT_EQ(test, neo_start(4), 0);
	seqcount_init(&seq);
	c = neo_clock_begin(CLOCK_MONOTONIC_RAW, 64);
	KUNIT_ASSERT_NOT_NULL(test, c);
	start = read_seqcount_begin(&seq);
	neo_clock_test_read(&f->tk, start, CLOCK_MONOTONIC_RAW);
	preempt_disable();
	write_seqcount_begin(&seq);
	f->tk.raw_sec = 8;
	f->next = 1400;
	write_seqcount_end(&seq);
	preempt_enable();
	KUNIT_EXPECT_TRUE(test, read_seqcount_retry(&seq, start));
	start = read_seqcount_begin(&seq);
	ts.tv_nsec = neo_clock_test_read(&f->tk, start, CLOCK_MONOTONIC_RAW);
	ts.tv_sec = f->tk.raw_sec;
	KUNIT_EXPECT_FALSE(test, read_seqcount_retry(&seq, start));
	neo_clock_accepted(CLOCK_MONOTONIC_RAW);
	neo_clock_end(c, &ts, true, 0);
	KUNIT_EXPECT_EQ(test, c->attempts, 2U);
	KUNIT_EXPECT_EQ(test, c->seq, start);
	KUNIT_EXPECT_EQ(test, c->cycles, 1400ULL);
	KUNIT_EXPECT_EQ(test, c->tuple.raw_sec, 8ULL);

	c = neo_clock_begin(CLOCK_MONOTONIC_RAW, 64);
	f->next = 999; /* Native upstream negative-delta branch returns the anchor. */
	ns = neo_clock_test_read(&f->tk, 2, CLOCK_MONOTONIC_RAW);
	KUNIT_EXPECT_EQ(test, ns, 100ULL);
	neo_clock_end(c, NULL, false, -EINVAL);
	KUNIT_EXPECT_FALSE(test, c->valid);
	KUNIT_EXPECT_FALSE(test, c->accepted);

	c = neo_clock_begin(CLOCK_MONOTONIC_RAW, 64);
	f->clock.max_cycles = 100;
	f->next = 2000; /* Force original overflow-safe conversion branch. */
	ns = neo_clock_test_read(&f->tk, 4, CLOCK_MONOTONIC_RAW);
	KUNIT_EXPECT_EQ(test, ns, 31350ULL);
	neo_clock_accepted(CLOCK_MONOTONIC_RAW);
	ts.tv_nsec = ns;
	neo_clock_end(c, &ts, true, -EFAULT);
	KUNIT_EXPECT_EQ(test, c->error, -EFAULT);
	KUNIT_EXPECT_TRUE(test, c->valid && c->complete);
	KUNIT_EXPECT_EQ(test, c->result.tv_nsec, (long)ns);
	c = neo_clock_begin(CLOCK_MONOTONIC_RAW, 64);
	f->tk.tkr_raw.cycle_last = 0;
	f->tk.tkr_raw.mult = U32_MAX;
	f->tk.tkr_raw.shift = 32;
	f->tk.tkr_raw.xtime_nsec = 0;
	f->next = 1ULL << 40;
	ns = neo_clock_test_read(&f->tk, 6, CLOCK_MONOTONIC_RAW);
	KUNIT_EXPECT_EQ(test, ns, (1ULL << 40) - 256);
	neo_clock_end(c, NULL, false, -EINVAL);
	KUNIT_EXPECT_EQ(test, f->reads, 5U);
}

static void clock_writer_bound_test(struct kunit *test)
{
	struct neo_fixture *f = test->priv;
	struct timekeeper before = f->tk;
	struct neo_clock_call *c;
	unsigned int i;

	KUNIT_ASSERT_EQ(test, neo_start(5), 0);
	c = neo_clock_begin(CLOCK_MONOTONIC_RAW, 64);
	KUNIT_ASSERT_NOT_NULL(test, c);
	neo_clock_writer_read(&f->tk, 1300, NEO_ADVANCE, 300, true);
	f->tk.tkr_raw.cycle_last = 1300;
	f->tk.tkr_raw.xtime_nsec += 300 * f->tk.tkr_raw.mult;
	neo_clock_publish(&before, &f->tk, 9, 3);
	KUNIT_EXPECT_EQ(test, writers[0].cycles, 1300ULL);
	KUNIT_EXPECT_EQ(test, writers[0].delta, 300ULL);
	KUNIT_EXPECT_TRUE(test, writers[0].delta_valid);
	KUNIT_EXPECT_EQ(test, writers[0].old.raw.cycle_last, 1000ULL);
	KUNIT_EXPECT_EQ(test, writers[1].old.raw.cycle_last, 1000ULL);
	KUNIT_EXPECT_EQ(test, writers[1].new.raw.cycle_last, 1300ULL);
	KUNIT_EXPECT_EQ(test, writers[1].seq, 9U);
	KUNIT_EXPECT_EQ(test, writers[1].action, 3U);
	for (i = 2; i <= NEO_WRITERS; i++)
		neo_clock_writer_read(&f->tk, i, NEO_FORWARD, i, true);
	KUNIT_EXPECT_EQ(test, writer_count, (u32)NEO_WRITERS);
	KUNIT_EXPECT_EQ(test, writer_lost, 1U);
	KUNIT_EXPECT_EQ(test, reason, NEO_WRITER_LIMIT);
	KUNIT_EXPECT_EQ(test, writers[0].cycles, 1300ULL); /* No overwrite. */
	neo_clock_writer_read(&f->tk, 99999, NEO_FORWARD, 0, true);
	KUNIT_EXPECT_EQ(test, writer_lost, 1U);
	neo_clock_end(c, NULL, false, -EINTR); /* In-flight call still retained. */
	KUNIT_EXPECT_TRUE(test, c->complete);
}

static void clock_access_and_export_test(struct kunit *test)
{
	struct neo_fixture *f = test->priv;
	struct seq_file output = { };
	struct file second = { };
	struct neo_clock_call *c;
	struct timespec64 ts = { .tv_sec = 7, .tv_nsec = 6350 };

	output.size = 16384;
	output.buf = kunit_kzalloc(test, output.size, GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, output.buf);
	KUNIT_EXPECT_EQ(test, neo_open(NULL, &second), -EBUSY);
	KUNIT_EXPECT_PTR_EQ(test, neo_clock_begin(CLOCK_MONOTONIC_RAW, 64), NULL);
	/* Stopping an unstarted new session must not export a previous capture. */
	neo_stop_capture(NEO_MANUAL);
	KUNIT_EXPECT_EQ(test, neo_show(&output, NULL), -EBUSY);
	KUNIT_EXPECT_EQ(test, neo_start(0), -EINVAL);
	KUNIT_EXPECT_EQ(test, neo_start(NEO_CALLS + 1), -EINVAL);
	KUNIT_ASSERT_EQ(test, neo_start(1), 0);
	KUNIT_EXPECT_EQ(test, neo_show(&output, NULL), -EBUSY);
	KUNIT_EXPECT_EQ(test, output.count, (size_t)0);
	KUNIT_EXPECT_EQ(test, neo_start(1), -EINVAL);
	KUNIT_EXPECT_PTR_EQ(test, neo_clock_begin(CLOCK_REALTIME, 64), NULL);
	c = neo_clock_begin(CLOCK_MONOTONIC_RAW, 64);
	KUNIT_ASSERT_NOT_NULL(test, c);
	KUNIT_EXPECT_FALSE(test, neo_clock_target(CLOCK_MONOTONIC));
	neo_clock_test_read(&f->tk, 4, CLOCK_MONOTONIC_RAW);
	neo_clock_accepted(CLOCK_MONOTONIC_RAW);
	neo_clock_end(c, &ts, true, 0);
	KUNIT_ASSERT_EQ(test, neo_show(&output, NULL), 0);
	KUNIT_EXPECT_NOT_NULL(test, strstr(output.buf, "\"ordinal\":1"));
	KUNIT_EXPECT_NOT_NULL(test, strstr(output.buf, "\"cycles\":1200"));
	KUNIT_EXPECT_NOT_NULL(test, strstr(output.buf, "\"accepted\":1,\"valid\":1,\"complete\":1"));
	KUNIT_EXPECT_EQ(test, c->result.tv_sec, ts.tv_sec);
	/* Replay the real serializer output on the host after the kernel exits. */
	{
		char *line = output.buf, *end;

		while ((end = strchr(line, '\n'))) {
			*end = 0;
			kunit_info(test, "NEO_CLOCK_FIXTURE %s", line);
			line = end + 1;
		}
	}
}

struct close_job { struct completion entered, done; bool foreign_rejected; };
static int stop_worker(void *data)
{
	struct close_job *job = data;

	job->foreign_rejected = !neo_clock_begin(CLOCK_MONOTONIC_RAW, 64) &&
		!neo_clock_target(CLOCK_MONOTONIC_RAW);
	complete(&job->entered);
	neo_stop_capture(NEO_CLOSED);
	complete(&job->done);
	while (!kthread_should_stop()) {
		set_current_state(TASK_INTERRUPTIBLE);
		if (!kthread_should_stop())
			schedule();
	}
	__set_current_state(TASK_RUNNING);
	return 0;
}

static void clock_stop_drain_test(struct kunit *test)
{
	struct close_job job;
	struct task_struct *thread;
	struct neo_clock_call *c;

	KUNIT_ASSERT_EQ(test, neo_start(2), 0);
	c = neo_clock_begin(CLOCK_MONOTONIC_RAW, 64);
	KUNIT_ASSERT_NOT_NULL(test, c);
	init_completion(&job.entered);
	init_completion(&job.done);
	thread = kthread_run(stop_worker, &job, "neo-clock-stop-test");
	KUNIT_ASSERT_FALSE(test, IS_ERR(thread));
	wait_for_completion(&job.entered);
	KUNIT_EXPECT_FALSE(test, completion_done(&job.done));
	KUNIT_EXPECT_TRUE(test, job.foreign_rejected);
	neo_clock_end(c, NULL, false, -EFAULT);
	wait_for_completion(&job.done);
	kthread_stop(thread);
	KUNIT_EXPECT_PTR_EQ(test, active, NULL);
	KUNIT_EXPECT_TRUE(test, c->complete);
	KUNIT_EXPECT_EQ(test, reason, NEO_CLOSED);
}

static struct kunit_case neo_clock_cases[] = {
	KUNIT_CASE(clock_exact_counter_test),
	KUNIT_CASE(clock_retry_and_branches_test),
	KUNIT_CASE(clock_writer_bound_test),
	KUNIT_CASE(clock_access_and_export_test),
	KUNIT_CASE(clock_stop_drain_test),
	{}
};
static struct kunit_suite neo_clock_suite = {
	.name = "neo-clock-provenance", .init = clock_fixture_init,
	.exit = clock_fixture_exit, .test_cases = neo_clock_cases,
};
kunit_test_suite(neo_clock_suite);
