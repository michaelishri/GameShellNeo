/* SPDX-License-Identifier: ISC */
/* Actual watchdog, console and cleanup bodies; deterministic transport seams. */
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uint8_t u8;
typedef uint32_t u32;
typedef uint32_t __le32;
typedef unsigned uint;
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, y) ((x) = (y))
#define unlikely(x) (x)
#define atomic_set(x, y) (*(x) = (y))
#define wmb() ((void)0)
#define rmb() ((void)0)
#define brcmf_dbg(...) ((void)0)
#define brcmf_err(...) ((void)0)
#define pr_debug(...) (hw.lines++)
#define le32_to_cpu(x) (x)
#define GFP_ATOMIC 0
#define msecs_to_jiffies(x) (x)
#define jiffies_to_msecs(x) (x)
#define BRCMF_FWCON_ON() (hw.fwcon)
#define min_t(type, a, b) ((type)(a) < (type)(b) ? (type)(a) : (type)(b))
#include "brcmfmac_watchdog_types.h"
#ifdef NEO_CLOCK_DEADLINE
#include "brcmfmac_clock_constants.h"
#define time_after(a, b) ((long)((b) - (a)) < 0)
#define time_after_eq(a, b) ((long)((a) - (b)) >= 0)
#endif

enum { BRCMF_SDIOD_DOWN, BRCMF_SDIOD_DATA };
#ifndef NEO_CLOCK_DEADLINE
enum { CLK_SDONLY, CLK_AVAIL };
#endif
struct sdio_func { unsigned num; };
struct timer_list { unsigned long expires; };
struct brcmf_sdio_dev {
	struct sdio_func *func1;
	int io_error;
	bool pm_failed;
	unsigned state;
};
struct brcmf_sdio {
	struct brcmf_sdio_dev *sdiodev;
	struct brcmf_sdio_count sdcnt;
	bool sr_enabled, poll, intr, dpc_triggered, dpc_running, wd_active;
	bool io_error_handled, ctrl_frame_stat;
	unsigned polltick, pollrate, idletime, idlecount, clkstate;
	unsigned ipend, intstatus, datawork;
	int ctrl_frame_err;
	void *brcmf_wq;
	struct timer_list timer;
	struct brcmf_console console;
	unsigned console_interval, console_addr;
	unsigned long clk_pending_deadline;
	bool clkstate_unknown, alp_only;
};
static struct {
	struct brcmf_sdio bus;
	struct brcmf_sdio_dev dev;
	struct sdio_func func;
} f;
enum admission_fault { ADMIT_IO_ERROR, ADMIT_PM_FAILED, ADMIT_BOTH, ADMIT_RETIRED };
enum clock_change { CLOCK_UNCHANGED, CLOCK_RESOLVED, CLOCK_SAVE_RESTORE, CLOCK_NEW_REQUEST, CLOCK_ALREADY_QUEUED };
static struct {
	unsigned host, claims, releases, reads, ram_reads, wakes, sleeps;
	unsigned queue, timer_deletes, timer_adds, timer_mods, states, controls, responses, quiesces, lines;
	unsigned inject_claim, ram_fail_at, allocs, ram_allocs, ram_alloc_fail_at, ram_frees;
	u32 ram_address;
	enum admission_fault admission;
	int poll_error, wake_error, sleep_error, ram_error;
	u8 poll_value, failed_value;
	bool transport_failed, fwcon, alloc_fail, invalid_index, unchanged_index, partial_line;
	bool retire_after_release;
	bool window_failure, direct_ram;
	bool clock_ready;
	u8 clock_filter;
	unsigned clock_reads, clock_writes;
	enum clock_change clock_change;
} hw;
static unsigned long jiffies = 100;
static void brcmf_sdio_dpc_failed(struct brcmf_sdio *bus, int error);
static void access_ok(void)
{
	assert(hw.host >= 1 && hw.host <= 2 && !f.dev.io_error && !f.dev.pm_failed && !hw.transport_failed);
}
static void sdio_claim_host(struct sdio_func *func)
{
	assert(func == &f.func && hw.host < 2);
	if (hw.host++) return; /* The RAM helper recursively claims the same host. */
	hw.claims++;
#ifdef NEO_CLOCK_DEADLINE
	if (hw.clock_change == CLOCK_RESOLVED) f.bus.clkstate = CLK_AVAIL;
	if (hw.clock_change == CLOCK_SAVE_RESTORE) f.bus.sr_enabled = true;
	if (hw.clock_change == CLOCK_NEW_REQUEST) f.bus.clk_pending_deadline = jiffies + 1000;
	if (hw.clock_change == CLOCK_ALREADY_QUEUED) f.bus.dpc_triggered = true;
#endif
	if (hw.inject_claim == hw.claims) {
		if (hw.admission != ADMIT_PM_FAILED) f.dev.io_error = -EILSEQ;
		if (hw.admission == ADMIT_PM_FAILED || hw.admission == ADMIT_BOTH) f.dev.pm_failed = true;
		if (hw.admission == ADMIT_RETIRED) {
			f.bus.io_error_handled = true; f.dev.state = BRCMF_SDIOD_DOWN;
			f.bus.wd_active = false;
		}
	}
}
static void sdio_release_host(struct sdio_func *func)
{
	assert(func == &f.func && hw.host && hw.host <= 2);
	if (--hw.host) return;
	hw.releases++;
	if (hw.retire_after_release) {
		hw.retire_after_release = false;
		sdio_claim_host(func); brcmf_sdio_dpc_failed(&f.bus, -EIO); sdio_release_host(func);
	}
}
static u8 brcmf_sdiod_func0_rb(struct brcmf_sdio_dev *dev, uint reg, int *error)
{
	assert(dev == &f.dev && reg == SDIO_CCCR_INTx); access_ok(); hw.reads++;
	if (error) *error = hw.poll_error;
	if (hw.poll_error) hw.transport_failed = true;
	return hw.poll_error ? hw.failed_value : hw.poll_value;
}
static int brcmf_sdio_bus_sleep(struct brcmf_sdio *bus, bool sleep, bool pendok)
{
	assert(bus == &f.bus && !pendok); access_ok();
	int error = sleep ? hw.sleep_error : hw.wake_error;
	if (sleep) hw.sleeps++; else hw.wakes++;
	if (error) hw.transport_failed = true;
	else bus->clkstate = sleep ? CLK_SDONLY : CLK_AVAIL;
	return error;
}
#ifdef NEO_CLOCK_DEADLINE
static u8 brcmf_sdiod_readb(struct brcmf_sdio_dev *dev, unsigned reg, int *err)
{
	assert(dev == &f.dev); access_ok(); hw.clock_reads++; *err = 0;
	assert(hw.clock_reads < 500);
	if (reg == SBSDIO_DEVICE_CTL) return hw.clock_filter;
	assert(reg == SBSDIO_FUNC1_CHIPCLKCSR);
	return hw.clock_ready ? SBSDIO_HT_AVAIL | SBSDIO_ALP_AVAIL : 0;
}
static void brcmf_sdiod_writeb(struct brcmf_sdio_dev *dev, unsigned reg, u8 value, int *err)
{
	assert(dev == &f.dev); access_ok(); hw.clock_writes++; *err = 0;
	if (reg == SBSDIO_DEVICE_CTL) hw.clock_filter = value;
	else assert(reg == SBSDIO_FUNC1_CHIPCLKCSR);
}
static void usleep_range(unsigned low, unsigned high)
{ assert(low <= high); jiffies += (low + 999) / 1000; }
#endif
static void timer_delete_sync(struct timer_list *timer)
{ assert(timer == &f.bus.timer && hw.host == 1); hw.timer_deletes++; }
static void add_timer(struct timer_list *timer)
{ assert(timer == &f.bus.timer && timer->expires == jiffies + BRCMF_WD_POLL); hw.timer_adds++; }
static void mod_timer(struct timer_list *timer, unsigned long expires)
{ assert(timer == &f.bus.timer && expires == jiffies + BRCMF_WD_POLL); hw.timer_mods++; }
static bool queue_work(void *queue, unsigned *work)
{
	assert(queue == &hw && work == &f.bus.datawork && !f.dev.io_error && !hw.transport_failed);
	hw.queue++; return true;
}
static void brcmf_sdiod_change_state(struct brcmf_sdio_dev *dev, unsigned state)
{ assert(dev == &f.dev && hw.host == 1 && state == BRCMF_SDIOD_DOWN); dev->state = state; hw.states++; }
static void brcmf_sdio_wait_event_wakeup(struct brcmf_sdio *bus)
{ assert(bus == &f.bus && hw.host == 1 && !bus->ctrl_frame_stat && bus->ctrl_frame_err == f.dev.io_error); hw.controls++; }
static void brcmf_sdio_dcmd_resp_wake(struct brcmf_sdio *bus)
{ assert(bus == &f.bus && hw.host == 1); hw.responses++; }
static void brcmf_sdiod_quiesce_irqs(struct brcmf_sdio_dev *dev)
{ assert(dev == &f.dev && hw.host == 1 && dev->io_error && f.bus.io_error_handled); hw.quiesces++; }
#ifdef DEBUG
static void *kmalloc(size_t size, int flags)
{ assert(size == 16 && flags == GFP_ATOMIC); hw.allocs++; return hw.alloc_fail ? NULL : malloc(size); }
struct sk_buff { u8 *data; unsigned len, capacity, priority; };
static struct sk_buff *dev_alloc_skb(unsigned size)
{
	hw.ram_allocs++;
	if (hw.ram_allocs == hw.ram_alloc_fail_at) return NULL;
	struct sk_buff *pkt = calloc(1, sizeof(*pkt)); assert(pkt);
	pkt->data = malloc(size ? size : 1); assert(pkt->data); pkt->capacity = size;
	return pkt;
}
static void dev_kfree_skb(struct sk_buff *pkt)
{ assert(pkt); free(pkt->data); free(pkt); hw.ram_frees++; }
static void skb_put(struct sk_buff *pkt, unsigned size)
{ assert(pkt->len + size <= pkt->capacity); pkt->len += size; }
static void skb_trim(struct sk_buff *pkt, unsigned size)
{ assert(size <= pkt->len); pkt->len = size; }
static int ram_error(void)
{
	int error = hw.ram_reads == hw.ram_fail_at ? hw.ram_error : 0;
	if (error && error != -ENOMEM) hw.transport_failed = true;
	return error;
}
static int brcmf_sdiod_set_backplane_window(struct brcmf_sdio_dev *dev, u32 addr)
{
	assert(dev == &f.dev); access_ok(); hw.ram_reads++; hw.ram_address = addr;
	return hw.window_failure ? ram_error() : 0;
}
static int brcmf_sdiod_skbuff_read(struct brcmf_sdio_dev *dev, struct sdio_func *func,
				 u32 addr, struct sk_buff *pkt)
{
	assert(dev == &f.dev && func == &f.func);
	assert(addr == ((hw.ram_address & SBSDIO_SB_OFT_ADDR_MASK) | SBSDIO_SB_ACCESS_2_4B_FLAG));
	access_ok(); int error = ram_error(); unsigned len = pkt->len; u8 *data = pkt->data;
	if (error) {
		memset(data, hw.failed_value, len); return error;
	}
	if (hw.direct_ram) { memset(data, 0xa5, len); return 0; }
	if (hw.ram_address == f.bus.console_addr + offsetof(struct rte_console, log_le)) {
		assert(len == sizeof(struct rte_log_le));
		struct rte_log_le log = {.buf = 0x3000, .buf_size = 16,
			.idx = hw.invalid_index ? 17 : hw.unchanged_index ? 0 : 2};
		memcpy(data, &log, len);
	} else {
		assert(hw.ram_address == 0x3000 && len == 16); memset(data, 0, len);
		data[0] = 'x'; data[1] = hw.partial_line ? 'y' : '\n';
	}
	return 0;
}
static int brcmf_sdiod_skbuff_write(struct brcmf_sdio_dev *dev, struct sdio_func *func,
				  u32 addr, struct sk_buff *pkt)
{
	assert(dev == &f.dev && func == &f.func && hw.direct_ram);
	assert(addr == ((hw.ram_address & SBSDIO_SB_OFT_ADDR_MASK) | SBSDIO_SB_ACCESS_2_4B_FLAG));
	access_ok(); for (unsigned i = 0; i < pkt->len; i++) assert(pkt->data[i] == 0xa5);
	return ram_error();
}
#endif

#include "brcmfmac_watchdog_functions.h"

static void begin(void)
{
	memset(&f, 0, sizeof(f)); memset(&hw, 0, sizeof(hw));
	f.dev.func1 = &f.func; f.dev.state = BRCMF_SDIOD_DATA;
	f.bus.sdiodev = &f.dev; f.bus.brcmf_wq = &hw; f.bus.clkstate = CLK_AVAIL;
	f.bus.wd_active = true; f.bus.ctrl_frame_stat = true; f.bus.intstatus = 0x8000;
	f.bus.pollrate = 1; f.bus.console_addr = 0x2000;
	jiffies = 100;
}
static void finish(void)
{
	assert(!hw.host && hw.claims == hw.releases);
	assert(hw.ram_frees == hw.ram_allocs - (hw.ram_alloc_fail_at && hw.ram_allocs >= hw.ram_alloc_fail_at));
	free(f.bus.console.buf);
}
static void fatal(int error)
{
	assert(f.dev.io_error == error && f.bus.io_error_handled && f.dev.state == BRCMF_SDIOD_DOWN);
	assert(!f.bus.wd_active && !f.bus.ipend && !f.bus.intstatus && !f.bus.ctrl_frame_stat);
	assert(hw.states == 1 && hw.controls == 1 && hw.responses == 1 && hw.quiesces == 1);
	assert(f.bus.ctrl_frame_err == error);
	unsigned claims = hw.claims;
	brcmf_sdio_bus_watchdog(&f.bus);
	brcmf_sdio_wd_timer(&f.bus, true);
	assert(hw.claims == claims && !hw.timer_adds && !hw.timer_mods);
	sdio_claim_host(&f.func); brcmf_sdio_dpc_failed(&f.bus, -ENOMEDIUM); sdio_release_host(&f.func);
	assert(f.dev.io_error == error && hw.states == 1 && hw.controls == 1 && hw.responses == 1 && hw.quiesces == 1);
}
static const int errors[] = {-EIO, -ETIMEDOUT, -EILSEQ};
static const u8 failed_values[] = {0, 0xff, INTR_STATUS_FUNC1};
static void poll_failure(unsigned index)
{
	begin(); assert(index < 9); f.bus.poll = true;
	hw.poll_error = errors[index / 3]; hw.failed_value = failed_values[index % 3];
	brcmf_sdio_bus_watchdog(&f.bus); fatal(hw.poll_error);
	assert(hw.reads == 1 && !hw.queue && !hw.wakes && !hw.sleeps && hw.timer_deletes == 1);
	finish();
}
static void poll_success(unsigned index)
{
	begin(); assert(index < 8); f.bus.poll = true; f.bus.intr = index & 1;
	const u8 values[] = {0, INTR_STATUS_FUNC1, INTR_STATUS_FUNC2, INTR_STATUS_FUNC1 | INTR_STATUS_FUNC2};
	hw.poll_value = values[index / 2]; brcmf_sdio_bus_watchdog(&f.bus);
	assert(hw.reads == 1 && hw.queue == (unsigned)!!hw.poll_value);
	assert(f.bus.ipend == hw.queue && f.bus.sdcnt.pollcnt == hw.queue && f.bus.dpc_triggered == !!hw.queue);
	assert(!f.dev.io_error && !hw.quiesces && f.bus.wd_active); finish();
}
static void retire_after_poll(unsigned index)
{
	begin(); assert(index < 3); f.bus.poll = true;
	const u8 values[] = {INTR_STATUS_FUNC1, INTR_STATUS_FUNC2, INTR_STATUS_FUNC1 | INTR_STATUS_FUNC2};
	hw.poll_value = values[index]; hw.retire_after_release = true;
	brcmf_sdio_bus_watchdog(&f.bus);
	fatal(-EIO); assert(hw.reads == 1 && hw.queue == 1 && !hw.wakes && !hw.sleeps);
	finish();
}
enum quiet_scenario { POLL_DISABLED, POLL_SAVE_RESTORE, POLL_NOT_DUE, POLL_IRQ_ACTIVE, POLL_DPC_PENDING };
static void quiet(unsigned index)
{
	begin(); assert(index <= POLL_DPC_PENDING); f.bus.poll = index != POLL_DISABLED;
	if (index == POLL_SAVE_RESTORE) f.bus.sr_enabled = true;
	if (index == POLL_NOT_DUE) f.bus.pollrate = 2;
	if (index == POLL_IRQ_ACTIVE) { f.bus.intr = true; f.bus.sdcnt.intrcount = 1; }
	if (index == POLL_DPC_PENDING) f.bus.dpc_triggered = true;
	brcmf_sdio_bus_watchdog(&f.bus); assert(!hw.reads && !hw.queue && !hw.claims && !f.dev.io_error); finish();
}
static void idle_setup(void) { f.bus.idletime = 1; f.bus.idlecount = 1; }
static void idle_failure(unsigned index)
{
	begin();
#ifdef DEBUG
	assert(index < 12); unsigned group = index / 4;
	if (index & 2) { hw.fwcon = true; f.bus.console_interval = 100; }
#else
	assert(index < 6); unsigned group = index / 2;
#endif
	f.bus.wd_active = index & 1; idle_setup(); hw.sleep_error = errors[group];
	brcmf_sdio_bus_watchdog(&f.bus); fatal(hw.sleep_error);
	assert(hw.sleeps == 1 && !hw.wakes && hw.timer_deletes == (index & 1)); finish();
}
enum idle_scenario { IDLE_EXPIRED, IDLE_NOT_DUE, IDLE_DISABLED, IDLE_DPC_RUNNING,
	IDLE_DPC_PENDING, IDLE_CLOCK_OFF, IDLE_TIMER_OFF };
static void idle_success(unsigned index)
{
	begin(); assert(index <= IDLE_TIMER_OFF); idle_setup();
	if (index == IDLE_NOT_DUE) f.bus.idlecount = 0;
	if (index == IDLE_DISABLED) f.bus.idletime = 0;
	if (index == IDLE_DPC_RUNNING) f.bus.dpc_running = true;
	if (index == IDLE_DPC_PENDING) f.bus.dpc_triggered = true;
	if (index == IDLE_CLOCK_OFF) f.bus.clkstate = CLK_SDONLY;
	if (index == IDLE_TIMER_OFF) f.bus.wd_active = false;
	brcmf_sdio_bus_watchdog(&f.bus);
	bool slept = index == IDLE_EXPIRED || index == IDLE_TIMER_OFF;
	assert(hw.sleeps == (unsigned)slept && !hw.wakes && !f.dev.io_error && !hw.quiesces);
	assert(hw.timer_deletes == (unsigned)(index == IDLE_EXPIRED));
	if (slept) assert(!f.bus.wd_active && !f.bus.idlecount && f.bus.clkstate == CLK_SDONLY);
	finish();
}
#ifdef DEBUG
static void console_setup(void) { hw.fwcon = true; f.bus.console_interval = 1; }
#endif
static void admission(unsigned index, bool between)
{
	begin();
#ifdef DEBUG
	assert(index < (between ? 8u : 12u));
#else
	assert(index < (between ? 4u : 8u));
#endif
	unsigned stage = index / 4; hw.admission = index % 4;
	hw.inject_claim = between ? 2 : 1;
	if (between) {
#ifdef DEBUG
		console_setup();
		if (stage) idle_setup(); else f.bus.poll = true;
#else
		(void)stage; f.bus.poll = true; idle_setup();
#endif
	} else if (stage == 0) f.bus.poll = true;
#ifdef DEBUG
	else if (stage == 1) console_setup();
#endif
	else idle_setup();
	brcmf_sdio_bus_watchdog(&f.bus);
	assert(hw.claims == hw.inject_claim && !hw.quiesces && !hw.states && !hw.controls);
	assert(f.dev.io_error == (hw.admission == ADMIT_PM_FAILED ? 0 : -EILSEQ));
	assert(!hw.sleeps && !hw.queue);
	if (!between) assert(!hw.reads && !hw.ram_reads && !hw.wakes);
	else {
#ifdef DEBUG
		assert(hw.reads == (unsigned)!stage && hw.ram_reads == (stage ? 2u : 0u) && hw.wakes == stage);
#else
		assert(hw.reads == 1);
#endif
	}
	finish();
}
#ifdef DEBUG
static void console_failure(unsigned index, bool queued)
{
	begin(); assert(index < 27); console_setup(); idle_setup();
	f.bus.poll = queued; hw.poll_value = INTR_STATUS_FUNC1;
	unsigned stage = index / 9; int error = errors[index / 3 % 3];
	hw.failed_value = failed_values[index % 3];
	if (!stage) hw.wake_error = error;
	else { hw.ram_error = error; hw.ram_fail_at = stage; }
	brcmf_sdio_bus_watchdog(&f.bus); fatal(error);
	assert(hw.wakes == 1 && hw.ram_reads == stage && !hw.sleeps && !hw.lines);
	assert(hw.queue == (unsigned)queued && hw.reads == (unsigned)queued);
	assert(hw.timer_deletes == 1); finish();
}
static void console_local(unsigned index)
{
	begin(); assert(index < 4); console_setup();
	hw.alloc_fail = !(index & 1); hw.invalid_index = index & 1;
	if (index & 2) idle_setup();
	brcmf_sdio_bus_watchdog(&f.bus);
	assert(!f.dev.io_error && f.dev.state == BRCMF_SDIOD_DATA && !hw.quiesces && !hw.controls);
	assert(!f.bus.console_interval && hw.ram_reads == 1 && !hw.lines);
	assert(hw.sleeps == (unsigned)!!(index & 2)); finish();
}
static void console_ram_allocation(unsigned index)
{
	begin(); assert(index < 8); console_setup();
	hw.ram_alloc_fail_at = 1 + (index & 1);
	if (index & 2) idle_setup();
	f.bus.poll = index & 4; hw.poll_value = INTR_STATUS_FUNC1;
	brcmf_sdio_bus_watchdog(&f.bus);
	assert(!f.dev.io_error && f.dev.state == BRCMF_SDIOD_DATA && !hw.quiesces);
	assert(!f.bus.console_interval && !hw.lines && hw.ram_allocs == hw.ram_alloc_fail_at);
	assert(hw.ram_reads == hw.ram_alloc_fail_at - 1);
	assert(hw.queue == (unsigned)!!(index & 4));
	assert(hw.sleeps == (unsigned)((index & 2) && !(index & 4))); finish();
}
static void console_window_failure(unsigned index)
{
	begin(); assert(index < 6); console_setup(); idle_setup();
	hw.window_failure = true; hw.ram_fail_at = 1 + (index & 1); hw.ram_error = errors[index / 2];
	brcmf_sdio_bus_watchdog(&f.bus); fatal(hw.ram_error);
	assert(hw.ram_reads == hw.ram_fail_at && !hw.sleeps && !hw.lines); finish();
}
static void console_transfer_allocation(unsigned index)
{
	begin(); assert(index < 4); console_setup(); idle_setup();
	hw.ram_fail_at = 1 + (index & 1); hw.ram_error = -ENOMEM; hw.window_failure = index & 2;
	brcmf_sdio_bus_watchdog(&f.bus);
	assert(!f.dev.io_error && !hw.quiesces && !f.bus.console_interval);
	assert(hw.sleeps == 1 && !hw.lines); finish();
}
static void ram_helper(unsigned index)
{
	begin(); assert(index < 8); hw.direct_ram = true;
	bool write = index & 1; unsigned scenario = index / 2;
	u8 data[32]; memset(data, write ? 0xa5 : 0x5a, sizeof(data));
	if (!scenario) hw.ram_alloc_fail_at = 1;
	if (scenario == 3) { hw.ram_fail_at = 2; hw.ram_error = -ETIMEDOUT; }
	u32 address = scenario > 1 ? SBSDIO_SB_OFT_ADDR_LIMIT - 16 : 0x3000;
	int err = brcmf_sdiod_ramrw(&f.dev, write, address, data, sizeof(data));
	assert(err == (!scenario ? -ENOMEM : scenario == 3 ? -ETIMEDOUT : 0));
	assert(hw.ram_reads == (!scenario ? 0u : scenario > 1 ? 2u : 1u));
	if (!write) for (unsigned i = 0; i < sizeof(data); i++)
		assert(data[i] == (!scenario || (scenario == 3 && i >= 16) ? 0x5a : 0xa5));
	finish();
}
enum console_scenario { CONSOLE_LINE, CONSOLE_UNPUBLISHED, CONSOLE_UNCHANGED,
	CONSOLE_PARTIAL, CONSOLE_REUSE, CONSOLE_DISABLED, CONSOLE_INTERVAL_OFF, CONSOLE_NOT_DUE,
	CONSOLE_IDLE_KEEP_TIMER };
static void console_success(unsigned index)
{
	begin(); assert(index <= CONSOLE_IDLE_KEEP_TIMER); console_setup();
	if (index == CONSOLE_UNPUBLISHED) f.bus.console_addr = 0;
	if (index == CONSOLE_UNCHANGED) hw.unchanged_index = true;
	if (index == CONSOLE_PARTIAL) hw.partial_line = true;
	if (index == CONSOLE_REUSE) { f.bus.console.buf = malloc(16); f.bus.console.bufsize = 16; }
	if (index == CONSOLE_DISABLED) hw.fwcon = false;
	if (index == CONSOLE_INTERVAL_OFF) f.bus.console_interval = 0;
	if (index == CONSOLE_NOT_DUE || index == CONSOLE_IDLE_KEEP_TIMER) f.bus.console_interval = 100;
	if (index == CONSOLE_IDLE_KEEP_TIMER) idle_setup();
	brcmf_sdio_bus_watchdog(&f.bus);
	bool due = index < CONSOLE_DISABLED;
	assert(hw.wakes == (unsigned)due && !f.dev.io_error && !hw.quiesces);
	assert(hw.ram_reads == (!due || index == CONSOLE_UNPUBLISHED ? 0u : index == CONSOLE_UNCHANGED ? 1u : 2u));
	assert(hw.lines == (unsigned)(index == CONSOLE_LINE || index == CONSOLE_REUSE));
	assert(hw.allocs == (unsigned)(due && index != CONSOLE_UNPUBLISHED && index != CONSOLE_REUSE));
	assert(hw.sleeps == (unsigned)(index == CONSOLE_IDLE_KEEP_TIMER));
	assert(f.bus.wd_active && !hw.timer_deletes); finish();
}
#endif
#ifdef NEO_CLOCK_DEADLINE
enum clock_request_scenario { REQUEST_PENDING, REQUEST_REPEATED, REQUEST_CANCELLED,
	REQUEST_READY, REQUEST_SAVE_RESTORE, REQUEST_SYNC_EXPIRED, REQUEST_SCENARIOS };
static void clock_request(unsigned index)
{
	begin(); assert(index < 2 * REQUEST_SCENARIOS);
	enum clock_request_scenario mode = index % REQUEST_SCENARIOS;
	jiffies = index >= REQUEST_SCENARIOS ? ULONG_MAX - 500 : 100;
	unsigned long start = jiffies, budget = msecs_to_jiffies(PMU_MAX_TRANSITION_DLY / 1000);
	f.bus.clkstate = CLK_SDONLY;
	sdio_claim_host(&f.func);
	if (mode == REQUEST_READY) hw.clock_ready = true;
	if (mode == REQUEST_SAVE_RESTORE) f.bus.sr_enabled = true;
	assert(brcmf_sdio_htclk(&f.bus, true, true) == 0);
	if (mode == REQUEST_READY || mode == REQUEST_SAVE_RESTORE) {
		assert(f.bus.clkstate == CLK_AVAIL);
		if (mode == REQUEST_SAVE_RESTORE) assert(!hw.clock_reads && !hw.clock_writes);
	} else {
		assert(f.bus.clkstate == CLK_PENDING && f.bus.clk_pending_deadline == start + budget);
		assert(hw.clock_filter & SBSDIO_DEVCTL_CA_INT_ONLY);
		if (mode == REQUEST_REPEATED) {
			for (unsigned i = 0; i < 5; i++) {
				jiffies += budget / 4;
				assert(brcmf_sdio_htclk(&f.bus, true, true) == 0);
				assert(f.bus.clk_pending_deadline == start + budget);
			}
		} else if (mode == REQUEST_CANCELLED) {
			assert(brcmf_sdio_htclk(&f.bus, false, false) == 0);
			assert(f.bus.clkstate == CLK_SDONLY && !hw.clock_filter);
			jiffies += budget / 2;
			assert(brcmf_sdio_htclk(&f.bus, true, true) == 0);
			assert(f.bus.clk_pending_deadline == jiffies + budget);
		} else if (mode == REQUEST_SYNC_EXPIRED) {
			jiffies = start + budget;
			assert(brcmf_sdio_htclk(&f.bus, true, false) == -EBADE);
			assert((unsigned long)(jiffies - start - budget) <= 10);
		}
	}
	sdio_release_host(&f.func); finish();
}
enum clock_watchdog_scenario { CLOCK_WAIT, CLOCK_WRAP, CLOCK_SR, CLOCK_AVAILABLE,
	CLOCK_QUEUED, CLOCK_IDLE, CLOCK_PM_FAILED, CLOCK_IO_FAILED, CLOCK_SCENARIOS };
static void clock_watchdog(unsigned index)
{
	begin(); assert(index < 3 * CLOCK_SCENARIOS); unsigned phase = index % 3;
	enum clock_watchdog_scenario mode = index / 3;
	f.bus.clkstate = mode == CLOCK_AVAILABLE ? CLK_AVAIL : CLK_PENDING;
	f.bus.clk_pending_deadline = mode == CLOCK_WRAP ? 0 : 1100;
	jiffies = f.bus.clk_pending_deadline + phase - 1;
	if (mode == CLOCK_SR) f.bus.sr_enabled = true;
	if (mode == CLOCK_QUEUED) f.bus.dpc_triggered = true;
	if (mode == CLOCK_IDLE) { f.bus.idletime = 1; f.bus.idlecount = 1; }
	if (mode == CLOCK_PM_FAILED) f.dev.pm_failed = true;
	if (mode == CLOCK_IO_FAILED) f.dev.io_error = -EILSEQ;
	bool claim = phase && mode != CLOCK_SR && mode != CLOCK_AVAILABLE &&
		mode != CLOCK_PM_FAILED && mode != CLOCK_IO_FAILED;
	bool notify = claim && mode != CLOCK_QUEUED;
	brcmf_sdio_bus_watchdog(&f.bus);
	assert(hw.queue == (unsigned)notify);
	assert(hw.claims == (unsigned)claim);
	assert(!hw.reads && !hw.clock_reads && !hw.clock_writes && !hw.wakes && !hw.sleeps);
	assert(!hw.timer_adds && !hw.timer_mods && !hw.timer_deletes);
	if (notify) assert(f.bus.dpc_triggered && f.bus.ipend == 1);
	finish();
}
static void clock_admission(unsigned index)
{
	begin(); assert(index < 8); f.bus.clkstate = CLK_PENDING; f.bus.clk_pending_deadline = jiffies;
	if (index < 4) { hw.inject_claim = 1; hw.admission = index; }
	else hw.clock_change = index - 3;
	brcmf_sdio_bus_watchdog(&f.bus);
	assert(hw.claims == 1 && !hw.queue && !hw.reads && !hw.clock_reads && !hw.clock_writes);
	assert(!hw.wakes && !hw.sleeps && !hw.quiesces); finish();
}
static void clock_retirement(unsigned index)
{
	begin(); assert(index == 0); f.bus.clkstate = CLK_PENDING;
	f.bus.clk_pending_deadline = jiffies; hw.retire_after_release = true;
	brcmf_sdio_bus_watchdog(&f.bus);
	fatal(-EIO);
	assert(hw.queue == 1 && !hw.reads && !hw.clock_reads && !hw.clock_writes);
	finish();
}
#endif
int main(int argc, char **argv)
{
	assert(argc == 3); unsigned index = strtoul(argv[2], NULL, 10);
	if (!strcmp(argv[1], "poll_failure")) poll_failure(index);
	else if (!strcmp(argv[1], "poll_success")) poll_success(index);
	else if (!strcmp(argv[1], "retire_after_poll")) retire_after_poll(index);
	else if (!strcmp(argv[1], "quiet")) quiet(index);
	else if (!strcmp(argv[1], "idle_failure")) idle_failure(index);
	else if (!strcmp(argv[1], "idle_success")) idle_success(index);
	else if (!strcmp(argv[1], "admission")) admission(index, false);
	else if (!strcmp(argv[1], "between")) admission(index, true);
#ifdef DEBUG
	else if (!strcmp(argv[1], "console_failure")) console_failure(index, false);
	else if (!strcmp(argv[1], "console_queued_failure")) console_failure(index, true);
	else if (!strcmp(argv[1], "console_local")) console_local(index);
	else if (!strcmp(argv[1], "console_success")) console_success(index);
	else if (!strcmp(argv[1], "console_ram_allocation")) console_ram_allocation(index);
	else if (!strcmp(argv[1], "console_window_failure")) console_window_failure(index);
	else if (!strcmp(argv[1], "console_transfer_allocation")) console_transfer_allocation(index);
	else if (!strcmp(argv[1], "ram_helper")) ram_helper(index);
#endif
#ifdef NEO_CLOCK_DEADLINE
	else if (!strcmp(argv[1], "clock_request")) clock_request(index);
	else if (!strcmp(argv[1], "clock_watchdog")) clock_watchdog(index);
	else if (!strcmp(argv[1], "clock_admission")) clock_admission(index);
	else if (!strcmp(argv[1], "clock_retirement")) clock_retirement(index);
#endif
	else assert(false);
	printf("%s %u passed\n", argv[1], index); return 0;
}
