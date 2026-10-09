/* SPDX-License-Identifier: ISC */
/* Actual ISR/status/DPC bodies; scripted hardware and ordered workqueue seams.
 * This tests status service after PM restoration, not the PM/MMC scheduler.
 */
#include <assert.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef unsigned int uint;
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, y) ((x) = (y))
#define unlikely(x) (x)
#define atomic_read(x) atomic_load(x)
#define atomic_set(x, y) atomic_store(x, y)
#define atomic_or(y, x) atomic_fetch_or(x, y)
#define atomic_xchg(x, y) atomic_exchange(x, y)
#define wmb() atomic_thread_fence(memory_order_seq_cst)
#define min(x, y) ((x) < (y) ? (x) : (y))
#define container_of(p, type, member) ((type *)((char *)(p) - offsetof(type, member)))
#define brcmf_dbg(level, ...) do { if (0) fprintf(stderr, __VA_ARGS__); } while (0)
static unsigned errors;
#define brcmf_err(...) do { errors++; if (0) fprintf(stderr, __VA_ARGS__); } while (0)
#include "brcmfmac_irq_types.h"

enum { BRCMF_SDIOD_DOWN, BRCMF_SDIOD_DATA };
struct device { int unused; };
struct sdio_func { struct device dev; };
struct work_struct { int unused; };
struct brcmf_core { u32 base; };
struct pktq { unsigned len; };
struct settings { struct { struct { int oob_irq_nr; } sdio; } bus; };
struct brcmf_sdio_dev {
 bool pm_failed, pm_irq_blocked, oob_irq_requested, irq_en;
 bool sd_irq_requested;
 int io_error;
 unsigned irq_en_lock, state;
 struct sdio_func *func1, *func2;
 struct settings *settings;
};
struct brcmf_sdio {
 struct brcmf_sdio_dev *sdiodev;
 struct brcmf_core *sdio_core;
 struct work_struct datawork;
 void *brcmf_wq;
 atomic_int intstatus, ipend, fcstate;
 bool sr_enabled, rxskip, rxpending, intr, dpc_triggered, dpc_running;
 bool ctrl_frame_stat;
 bool io_error_handled;
 u8 *ctrl_frame_buf;
 unsigned ctrl_frame_len;
 int ctrl_frame_err;
 uint txbound, rxbound, txminmax, clkstate, hostintmask, flowcontrol, idlecount;
 u8 rx_seq, sdpcm_ver;
 struct pktq txq;
 struct { unsigned f1regdata, intrcount, fc_xoff, fc_xon, fc_rcvd; } sdcnt;
};
static struct {
 struct brcmf_sdio bus;
 struct brcmf_sdio_dev dev;
 struct brcmf_core core;
 struct sdio_func func, func2;
 struct settings settings;
} f;
static struct {
 unsigned host_depth, claims, releases, spin_depth;
 unsigned reads, writes, sleeps, frames, mail, queue, runs, freezes, enables, wakes;
 unsigned frames_remaining;
 unsigned byte_reads, byte_writes, fail_read_at, fail_write_at, fail_byte_read_at;
 unsigned stops, responses, releases_irq, disables;
 u32 status, acked, mailbox_result;
 int read_error, write_error, wake_error;
 bool pending_work, running_work, parked, inject_during_frames, hold_receive;
 bool in_irq, clock_pending, clock_ready, byte_write_error, release_irq_error;
 bool retire_on_spin, irq_retired;
#ifdef NEO_MAILBOX_ERRORS
 u32 mailbox_data;
 int mailbox_read_error, mailbox_ack_error;
 unsigned mailbox_writes, crashes, console_reads;
#endif
} hw;
static unsigned scenarios, characterizations;
static void brcmf_sdio_isr(struct brcmf_sdio *bus, bool in_isr);

static void access_ok(void)
{
 assert(hw.host_depth && !hw.parked && !f.dev.pm_irq_blocked && !f.dev.pm_failed && !f.dev.io_error);
}
static void sdio_claim_host(struct sdio_func *func)
{ assert(func == &f.func && !hw.spin_depth); hw.host_depth++; hw.claims++; }
static void sdio_release_host(struct sdio_func *func)
{ assert(func == &f.func && hw.host_depth); hw.host_depth--; hw.releases++; }
#define spin_lock_irqsave(lock, flags) do { (void)(lock); (flags) = 0; \
 assert(!hw.spin_depth); hw.spin_depth++; \
 if (hw.retire_on_spin) { f.dev.oob_irq_requested = false; \
  hw.irq_retired = true; hw.retire_on_spin = false; } } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(lock); (void)(flags); \
 assert(hw.spin_depth == 1); hw.spin_depth--; } while (0)
static void enable_irq(int irq)
{ assert(irq == 7 && !hw.irq_retired && hw.spin_depth == 1 &&
         (!f.bus.ipend || f.bus.clkstate == CLK_PENDING)); hw.enables++; }
static u32 brcmf_sdiod_readl(struct brcmf_sdio_dev *dev, u32 addr, int *err)
{
#ifdef NEO_MAILBOX_ERRORS
 if (addr == f.core.base + SD_REG(tohostmailboxdata)) {
  assert(dev == &f.dev); access_ok(); assert(f.bus.clkstate == CLK_AVAIL);
  hw.mail++; *err = hw.mailbox_read_error;
  return hw.mailbox_data; /* Model zero/window and all-ones/transfer failures. */
 }
#endif
 assert(dev == &f.dev && addr == f.core.base + SD_REG(intstatus));
 access_ok(); assert(f.bus.clkstate == CLK_AVAIL); hw.reads++;
 *err = hw.read_error ? hw.read_error : hw.reads == hw.fail_read_at ? -EIO : 0;
 return hw.status; /* Poisoned/nonzero data is deliberately returned on error. */
}
static void brcmf_sdiod_writel(struct brcmf_sdio_dev *dev, u32 addr, u32 val, int *err)
{
#ifdef NEO_MAILBOX_ERRORS
 if (addr == f.core.base + SD_REG(tosbmailbox)) {
  assert(dev == &f.dev && val == SMB_INT_ACK); access_ok();
  assert(f.bus.clkstate == CLK_AVAIL && hw.mail && !hw.mailbox_read_error);
  hw.mailbox_writes++; *err = hw.mailbox_ack_error;
  return;
 }
#endif
 assert(dev == &f.dev && addr == f.core.base + SD_REG(intstatus));
 access_ok(); assert(f.bus.clkstate == CLK_AVAIL); hw.writes++;
 *err = hw.write_error ? hw.write_error : hw.writes == hw.fail_write_at ? -EIO : 0;
 if (!*err) { hw.acked |= val; hw.status &= ~val; }
}
static u8 brcmf_sdiod_readb(struct brcmf_sdio_dev *dev, uint addr, int *err)
{
 assert(dev == &f.dev && (addr == SBSDIO_DEVICE_CTL || addr == SBSDIO_FUNC1_CHIPCLKCSR));
 access_ok(); hw.byte_reads++;
 *err = hw.byte_reads == hw.fail_byte_read_at ? -EIO : 0;
 return addr == SBSDIO_DEVICE_CTL ? SBSDIO_DEVCTL_CA_INT_ONLY :
        hw.clock_ready ? (SBSDIO_HT_AVAIL | SBSDIO_ALP_AVAIL) : 0;
}
static void brcmf_sdiod_writeb(struct brcmf_sdio_dev *dev, uint addr, u8 val, int *err)
{
 assert(dev == &f.dev && addr == SBSDIO_DEVICE_CTL && !(val & SBSDIO_DEVCTL_CA_INT_ONLY));
 access_ok(); hw.byte_writes++; *err = hw.byte_write_error ? -EIO : 0;
}
static int brcmf_sdio_bus_sleep(struct brcmf_sdio *bus, bool sleep, bool pending)
{
 assert(bus == &f.bus && !sleep && pending); access_ok();
 assert(++hw.sleeps <= 32); /* Bound a broken pending-status loop by assertion. */
 if (hw.clock_pending) bus->clkstate = CLK_PENDING;
 return hw.wake_error;
}
#ifndef NEO_MAILBOX_ERRORS
static u32 brcmf_sdio_hostmail(struct brcmf_sdio *bus)
{ assert(bus == &f.bus); access_ok(); hw.mail++; return hw.mailbox_result; }
#else
static void decoded_mailbox_ok(void)
{
 access_ok();
 assert(hw.mail && hw.mailbox_writes == hw.mail);
 assert(!hw.mailbox_read_error && !hw.mailbox_ack_error);
}
static void brcmf_fw_crashed(struct device *dev)
{ assert(dev == &f.func.dev); decoded_mailbox_ok(); hw.crashes++; }
static void brcmf_sdio_get_console_addr(struct brcmf_sdio *bus)
{
 assert(bus == &f.bus); decoded_mailbox_ok();
#ifdef DEBUG
 hw.console_reads++;
#endif
}
#endif
static void brcmf_sdio_readframes(struct brcmf_sdio *bus, uint limit)
{
 assert(bus == &f.bus && limit == 8 && !hw.host_depth);
 assert(!hw.parked && !f.dev.pm_irq_blocked && !f.dev.pm_failed);
 assert(++hw.frames <= 8);
 if (hw.inject_during_frames) {
  hw.inject_during_frames = false;
  hw.status |= I_HMB_HOST_INT;
  brcmf_sdio_isr(bus, true); /* New IRQ after the previous status was consumed. */
 }
 if (hw.frames_remaining) hw.frames_remaining--;
 bus->rxpending = hw.frames_remaining != 0 || hw.hold_receive;
}
static bool txctl_ok(struct brcmf_sdio *bus) { (void)bus; return true; }
static bool data_ok(struct brcmf_sdio *bus) { (void)bus; return true; }
static unsigned brcmu_pktq_mlen(struct pktq *q, uint mask)
{ (void)mask; return q->len; }
static void brcmf_sdio_sendfromq(struct brcmf_sdio *bus, uint count)
{ (void)bus; (void)count; assert(false); }
static int brcmf_sdio_tx_ctrlframe(struct brcmf_sdio *bus, u8 *data, uint len)
{ (void)bus; (void)data; (void)len; assert(false); return 0; }
static void brcmf_sdio_wait_event_wakeup(struct brcmf_sdio *bus)
{ assert(bus == &f.bus); hw.wakes++; }
static bool queue_work(void *queue, struct work_struct *work)
{
 assert(queue == &hw && work == &f.bus.datawork);
 hw.queue++;
 bool fresh = !hw.pending_work;
 hw.pending_work = true; /* Single ordered queue; a running item can be requeued. */
 return fresh;
}
static void brcmf_sdiod_try_freeze(struct brcmf_sdio_dev *dev)
{ assert(dev == &f.dev && !hw.host_depth); hw.freezes++; }

#ifdef NEO_WORKER_ERRORS
static void brcmf_sdiod_change_state(struct brcmf_sdio_dev *dev, unsigned state)
{ assert(dev == &f.dev && hw.host_depth && state == BRCMF_SDIOD_DOWN); dev->state = state; }
static void brcmf_sdio_wd_timer(struct brcmf_sdio *bus, bool active)
{ assert(bus == &f.bus && !active && hw.host_depth); hw.stops++; }
static int brcmf_sdio_dcmd_resp_wake(struct brcmf_sdio *bus)
{ assert(bus == &f.bus); hw.responses++; return 0; }
static void disable_irq_nosync(int irq)
{ assert(irq == 7 && hw.spin_depth == 1); hw.disables++; }
static int sdio_release_irq(struct sdio_func *func)
{
 assert(hw.host_depth && !hw.in_irq && hw.running_work);
 assert(func == &f.func || func == &f.func2);
 hw.releases_irq++;
 return hw.release_irq_error ? -EIO : 0;
}
#endif

#include "brcmfmac_freezer_functions.h"

static void setup(void)
{
 memset(&f, 0, sizeof(f)); memset(&hw, 0, sizeof(hw)); errors = 0;
 f.core.base = 0x18002000;
 f.settings.bus.sdio.oob_irq_nr = 7;
 f.dev.func1 = &f.func; f.dev.settings = &f.settings;
 f.dev.func2 = &f.func2;
 f.dev.state = BRCMF_SDIOD_DATA;
 f.bus.sdiodev = &f.dev; f.bus.sdio_core = &f.core;
 f.bus.clkstate = CLK_AVAIL; f.bus.rxbound = 8; f.bus.intr = true;
 f.bus.hostintmask = HOSTINTMASK; f.bus.brcmf_wq = &hw;
 assert(SD_REG(intstatus) == 0x20);
}
static void finish(void)
{
 assert(!hw.host_depth && !hw.spin_depth && !hw.running_work && !hw.pending_work);
 assert(hw.claims == hw.releases && !f.bus.dpc_running && !f.bus.dpc_triggered);
 scenarios++;
}
static void irq(bool hard)
{
 hw.in_irq = true;
 if (!hard) sdio_claim_host(&f.func);
 brcmf_sdio_isr(&f.bus, hard);
 if (!hard) sdio_release_host(&f.func);
 hw.in_irq = false;
}
static void drain(void)
{
 assert(!hw.parked && !hw.running_work);
 while (hw.pending_work) {
  assert(++hw.runs <= 8);
  hw.pending_work = false; hw.running_work = true;
  brcmf_sdio_dataworker(&f.bus.datawork);
  hw.running_work = false;
 }
}
static void deferred(unsigned count, bool hard, bool fail_wake)
{
 setup();
 hw.status = I_HMB_FRAME_IND | I_HMB_HOST_INT | I_SMB_SW0;
 hw.frames_remaining = 2;
 f.dev.pm_irq_blocked = true; f.dev.state = BRCMF_SDIOD_DOWN; hw.parked = true;
 for (unsigned i = 0; i < count; i++) irq(hard);
 assert(!hw.reads && !hw.writes && !hw.frames && !hw.mail && !hw.runs);
 assert(hw.queue == count && f.bus.ipend == 1 && f.bus.sdcnt.intrcount == count);
 /* PM restore/freezer ordering is covered by the separate lifecycle suite. */
 f.dev.pm_failed = fail_wake;
 if (!fail_wake) { f.dev.state = BRCMF_SDIOD_DATA; f.dev.pm_irq_blocked = false; }
 hw.parked = false;
 drain();
 assert(hw.runs == 1 && hw.freezes == 1);
 if (fail_wake) {
  assert(!hw.reads && !hw.writes && !hw.frames && !hw.mail);
  unsigned queued = hw.queue;
  irq(false); irq(true); brcmf_sdio_trigger_dpc(&f.bus);
  assert(hw.queue == queued && f.bus.ipend == 1);
 } else {
  assert(hw.reads == 1 && hw.writes == 1 && hw.frames == 2 && hw.mail == 1);
  assert(hw.status == I_SMB_SW0 && hw.acked == (I_HMB_FRAME_IND | I_HMB_HOST_INT));
  assert(!f.bus.ipend && !f.bus.intstatus && !errors);
 }
 finish();
}
static void active_or_leftover(bool leftover)
{
 setup(); hw.frames_remaining = 1;
 if (leftover) {
  f.bus.intstatus = I_HMB_FRAME_IND;
  brcmf_sdio_trigger_dpc(&f.bus);
  brcmf_sdio_trigger_dpc(&f.bus);
  assert(hw.queue == 1);
 } else {
  hw.status = I_HMB_FRAME_IND;
  irq(false);
  assert(hw.reads == 1 && hw.writes == 1 && !f.bus.ipend);
 }
 drain();
 assert(hw.reads == !leftover && hw.writes == !leftover && hw.frames == 1);
 assert(!f.bus.intstatus && !errors);
 finish();
}
static void arrival_during_service(void)
{
 setup(); hw.status = I_HMB_FRAME_IND; hw.frames_remaining = 1;
 hw.inject_during_frames = true;
 irq(true); drain();
 assert(hw.frames == 1 && hw.mail == 1 && hw.reads == 2 && hw.writes == 2);
 assert(!hw.status && !f.bus.intstatus && !f.bus.ipend && !errors);
 assert(hw.runs == 2 && hw.freezes == 2);
 finish();
}
static void no_status(void)
{
 setup(); irq(true); drain();
 assert(hw.reads == 1 && !hw.writes && !hw.frames && !hw.mail);
 assert(!f.bus.ipend && !errors);
 finish();
}
static void read_error(bool hard)
{
 setup(); hw.read_error = -EIO;
 hw.status = I_HMB_FRAME_IND; hw.frames_remaining = 1;
 irq(hard); drain();
 assert(hw.reads == 1 && !hw.writes && !hw.frames && !hw.mail);
 assert(hw.status == I_HMB_FRAME_IND && !f.bus.ipend && !f.bus.intstatus);
 assert(errors && !f.dev.pm_failed); /* Existing behavior: no automatic recovery. */
#ifdef NEO_WORKER_ERRORS
 assert(f.dev.io_error == -EIO && f.bus.io_error_handled && hw.responses == 1);
#else
 characterizations++;
#endif
 finish();
}
static void existing_error_behavior(bool failed_ack)
{
 setup(); hw.status = I_HMB_FRAME_IND; hw.frames_remaining = 1;
 if (failed_ack) hw.write_error = -EIO;
 else hw.wake_error = -ETIMEDOUT;
 irq(true); drain();
#ifdef NEO_WORKER_ERRORS
 assert(hw.reads == failed_ack && hw.writes == failed_ack && !hw.frames && !hw.mail);
 assert(f.dev.io_error == (failed_ack ? -EIO : -ETIMEDOUT));
 assert(hw.status == I_HMB_FRAME_IND && errors && !f.bus.intstatus && !f.bus.ipend);
#else
 /* The current DPC still dispatches RX after either injected error. This is
  * a characterization to support a future fix, not desired recovery behavior.
  */
 assert(hw.reads == 1 && hw.writes == 1 && hw.frames == 1 && !f.dev.pm_failed);
 assert(hw.status == (failed_ack ? I_HMB_FRAME_IND : 0));
 assert(!!errors == failed_ack && !f.bus.ipend && !f.bus.intstatus);
 characterizations++;
#endif
 finish();
}
static void failure_gate(void)
{
 setup(); f.dev.pm_failed = true;
 hw.pending_work = true; f.bus.dpc_triggered = true;
 drain(); irq(false); irq(true); brcmf_sdio_trigger_dpc(&f.bus);
 assert(!hw.sleeps && !hw.reads && !hw.writes && !hw.queue);
 finish();
}
static void oob_rearm(void)
{
 setup(); f.dev.oob_irq_requested = true;
 f.bus.ipend = 1;
 brcmf_sdio_clrintr(&f.bus);
 assert(!hw.enables && !f.dev.irq_en);
 hw.status = I_HMB_FRAME_IND; hw.frames_remaining = 1;
 brcmf_sdio_trigger_dpc(&f.bus); drain();
 assert(hw.enables == 1 && f.dev.irq_en);
 brcmf_sdio_clrintr(&f.bus);
 assert(hw.enables == 1);
 finish();
}
static void mailbox_frame(void)
{
 setup(); hw.status = I_HMB_HOST_INT; hw.mailbox_result = I_HMB_FRAME_IND;
#ifdef NEO_MAILBOX_ERRORS
 hw.mailbox_data = HMB_DATA_NAKHANDLED; f.bus.rxskip = true;
#endif
 hw.frames_remaining = 1;
 irq(true); drain();
 assert(hw.mail == 1 && hw.frames == 1 && !f.bus.intstatus);
 finish();
}
#ifdef NEO_WORKER_ERRORS
static void retired_oob_rearm(void)
{
 setup(); f.dev.oob_irq_requested = true;
 /* Teardown wins the lock after the outer request check. */
 hw.retire_on_spin = true;
 brcmf_sdio_clrintr(&f.bus);
 assert(hw.irq_retired && !hw.enables && !f.dev.irq_en);
 finish();
}
static void failed_ack_publication(void)
{
 setup(); f.bus.intstatus = I_HMB_HOST_INT;
 hw.status = I_HMB_FRAME_IND; hw.write_error = -EIO;
 sdio_claim_host(&f.func);
 assert(brcmf_sdio_intr_rstatus(&f.bus) == -EIO);
 sdio_release_host(&f.func);
 assert(f.bus.intstatus == I_HMB_HOST_INT && hw.status == I_HMB_FRAME_IND);
 assert(hw.reads == 1 && hw.writes == 1);
 finish();
}
static void fatal(unsigned mode, bool oob, bool release_fails)
{
 setup(); hw.status = I_HMB_FRAME_IND | I_HMB_FC_CHANGE;
 hw.frames_remaining = 1;
 f.bus.ctrl_frame_stat = true; f.bus.txbound = 1; f.bus.txq.len = 1;
 f.dev.oob_irq_requested = oob; f.dev.irq_en = oob;
 f.dev.sd_irq_requested = !oob; hw.release_irq_error = release_fails;
 if (mode == 0) hw.wake_error = -ETIMEDOUT;
 if (mode == 1) hw.read_error = -EIO;
 if (mode == 2) hw.write_error = -EIO;
 if (mode == 3) hw.fail_write_at = 2; /* flow-control acknowledgement */
 if (mode == 4) hw.fail_read_at = 2; /* flow-control follow-up read */
 if (mode == 8) hw.write_error = -EIO;
 if ((mode >= 5 && mode <= 7) || mode == 9) {
  f.bus.clkstate = CLK_PENDING; hw.clock_ready = true;
  if (mode == 5) hw.fail_byte_read_at = 1;
  if (mode == 6) hw.fail_byte_read_at = 2;
  if (mode == 7) hw.byte_write_error = true;
  if (mode == 9) hw.fail_byte_read_at = 3;
 }
 irq(mode != 8); drain();
 int expected = mode == 0 ? -ETIMEDOUT : -EIO;
 assert(f.dev.io_error == expected && f.bus.io_error_handled);
 assert(f.dev.state == BRCMF_SDIOD_DOWN && !f.bus.ctrl_frame_stat);
 assert(f.bus.ctrl_frame_err == expected && hw.wakes == 1 && hw.responses == 1);
 assert(hw.stops == 1 && !hw.frames && !hw.mail && !hw.enables);
 assert(!f.bus.ipend && !f.bus.intstatus && !f.dev.sd_irq_requested);
 assert(hw.disables == oob && hw.releases_irq == (oob ? 0 : 2));
 unsigned reads = hw.reads, writes = hw.writes, bytes = hw.byte_reads;
 irq(false); irq(true); brcmf_sdio_trigger_dpc(&f.bus);
 /* Model an already queued pass; cleanup remains idempotent. */
 hw.pending_work = true; f.bus.dpc_triggered = true; drain();
 assert(hw.stops == 1 && hw.responses == 1 && hw.wakes == 1);
 assert(hw.reads == reads && hw.writes == writes && hw.byte_reads == bytes);
 assert(f.dev.io_error == expected);
 finish();
}
static void pending_clock(bool oob, bool start_pending)
{
 setup(); hw.status = I_HMB_FRAME_IND; hw.frames_remaining = 1;
 f.dev.oob_irq_requested = oob;
 hw.clock_pending = true;
 if (start_pending) f.bus.clkstate = CLK_PENDING;
 irq(oob); drain();
 assert(!f.dev.io_error && !hw.frames && f.bus.ipend == (start_pending || oob));
 assert(f.bus.clkstate == CLK_PENDING && !hw.responses && !hw.stops);
 assert(hw.enables == oob && hw.sleeps == 1 && hw.runs == 1);
 unsigned reads = hw.reads;
 hw.clock_pending = false; hw.clock_ready = true;
 f.dev.irq_en = false; /* OOB handler masks its line before dispatch. */
 irq(oob); drain();
 assert(!f.dev.io_error && hw.frames == 1 && !f.bus.ipend && !f.bus.intstatus);
 assert(hw.reads == reads + 1 && hw.sleeps == 2 && hw.runs == 2);
 finish();
}
#endif
#ifdef NEO_MAILBOX_ERRORS
static void mailbox_seed(void)
{
 f.bus.rxskip = true; f.bus.rx_seq = 12; f.bus.sdpcm_ver = 7;
 f.bus.flowcontrol = 0x12;
 f.bus.sdcnt.fc_xoff = 3; f.bus.sdcnt.fc_xon = 5; f.bus.sdcnt.fc_rcvd = 9;
}
static void mailbox_unchanged(void)
{
 assert(f.bus.rxskip && f.bus.rx_seq == 12 && f.bus.sdpcm_ver == 7);
 assert(f.bus.flowcontrol == 0x12 && f.bus.sdcnt.fc_xoff == 3);
 assert(f.bus.sdcnt.fc_xon == 5 && f.bus.sdcnt.fc_rcvd == 9);
 assert(!hw.crashes && !hw.console_reads);
}
static void mailbox_error(bool ack, u32 data, int error)
{
 setup(); mailbox_seed(); hw.mailbox_data = data;
 if (ack) hw.mailbox_ack_error = error;
 else hw.mailbox_read_error = error;
 u32 status = UINT32_MAX;
 sdio_claim_host(&f.func);
 assert(brcmf_sdio_hostmail(&f.bus, &status) == error);
 sdio_release_host(&f.func);
 assert(!status && hw.mail == 1 && hw.mailbox_writes == ack);
 assert(f.bus.sdcnt.f1regdata == 1u + ack && !errors);
 mailbox_unchanged(); finish();
}
static void mailbox_fatal(bool ack, bool oob, bool hard, u32 data, int error)
{
 setup(); mailbox_seed(); hw.mailbox_data = data;
 if (ack) hw.mailbox_ack_error = error;
 else hw.mailbox_read_error = error;
 hw.status = I_HMB_HOST_INT | I_HMB_FRAME_IND;
 hw.frames_remaining = 1;
 f.bus.ctrl_frame_stat = true; f.bus.txbound = 1; f.bus.txq.len = 1;
 f.dev.oob_irq_requested = oob; f.dev.irq_en = oob;
 f.dev.sd_irq_requested = !oob;
 irq(hard); drain();
 assert(f.dev.io_error == error && f.bus.io_error_handled);
 assert(f.dev.state == BRCMF_SDIOD_DOWN && !f.bus.ctrl_frame_stat);
 assert(f.bus.ctrl_frame_err == error && hw.wakes == 1 && hw.responses == 1);
 assert(hw.stops == 1 && !hw.frames && !hw.enables);
 assert(!f.bus.ipend && !f.bus.intstatus && !f.dev.sd_irq_requested);
 assert(hw.disables == oob && hw.releases_irq == (oob ? 0 : 2));
 assert(hw.reads == 1 && hw.writes == 1 && hw.mail == 1 && hw.mailbox_writes == ack);
 assert(f.bus.sdcnt.f1regdata == 3u + ack);
 mailbox_unchanged();
 unsigned count = hw.queue;
 irq(false); irq(true); brcmf_sdio_trigger_dpc(&f.bus);
 assert(hw.queue == count);
 /* Already queued work must neither repeat I/O nor retire IRQs twice. */
 hw.pending_work = true; f.bus.dpc_triggered = true; drain();
 assert(hw.stops == 1 && hw.responses == 1 && hw.wakes == 1);
 assert(hw.disables == oob && hw.releases_irq == (oob ? 0 : 2));
 assert(hw.reads == 1 && hw.writes == 1 && hw.mail == 1 && hw.mailbox_writes == ack);
 assert(f.dev.io_error == error); mailbox_unchanged(); finish();
}
static void mailbox_success(u32 data, bool skipped)
{
 setup(); mailbox_seed(); hw.mailbox_data = data; f.bus.rxskip = skipped;
 u32 status = UINT32_MAX;
 sdio_claim_host(&f.func);
 assert(!brcmf_sdio_hostmail(&f.bus, &status));
 sdio_release_host(&f.func);
 assert(hw.mail == 1 && hw.mailbox_writes == 1 && f.bus.sdcnt.f1regdata == 2);
 assert(status == ((data & HMB_DATA_NAKHANDLED) ? I_HMB_FRAME_IND : 0));
 assert(f.bus.rxskip == (skipped && !(data & HMB_DATA_NAKHANDLED)));
 assert(hw.crashes == !!(data & HMB_DATA_FWHALT));
 bool ready = data & (HMB_DATA_DEVREADY | HMB_DATA_FWREADY);
 u8 version = (data & HMB_DATA_VERSION_MASK) >> HMB_DATA_VERSION_SHIFT;
 assert(f.bus.sdpcm_ver == (ready ? version : 7));
#ifdef DEBUG
 assert(hw.console_reads == ready);
#else
 assert(!hw.console_reads);
#endif
 bool flow = data & HMB_DATA_FC;
 u8 fc = (data & HMB_DATA_FCDATA_MASK) >> HMB_DATA_FCDATA_SHIFT;
 assert(f.bus.flowcontrol == (flow ? fc : 0x12));
 assert(f.bus.sdcnt.fc_xoff == 3u + (flow && (fc & ~0x12)));
 assert(f.bus.sdcnt.fc_xon == 5u + (flow && (0x12 & ~fc)));
 assert(f.bus.sdcnt.fc_rcvd == 9u + flow);
 u32 known = HMB_DATA_DEVREADY | HMB_DATA_FWREADY | HMB_DATA_NAKHANDLED |
             HMB_DATA_FWHALT | HMB_DATA_FC | HMB_DATA_FCDATA_MASK | HMB_DATA_VERSION_MASK;
 assert(errors == (unsigned)(ready && version != SDPCM_PROT_VERSION) +
                  (unsigned)(!skipped && (data & HMB_DATA_NAKHANDLED)) + !!(data & ~known));
 finish();
}
static void mailbox_cases(void)
{
 const u32 data[] = {0, UINT32_MAX};
 const int faults[] = {-EIO, -ETIMEDOUT, -EILSEQ};
 for (unsigned ack = 0; ack < 2; ack++)
  for (unsigned d = 0; d < 2; d++)
   for (unsigned e = 0; e < 3; e++) {
    mailbox_error(ack, data[d], faults[e]);
    for (unsigned oob = 0; oob < 2; oob++)
     for (unsigned hard = 0; hard < 2; hard++)
      mailbox_fatal(ack, oob, hard, data[d], faults[e]);
   }
 const u32 ready = SDPCM_PROT_VERSION << HMB_DATA_VERSION_SHIFT;
 const u32 valid[] = {0, HMB_DATA_NAKHANDLED, HMB_DATA_DEVREADY | ready,
  HMB_DATA_FWREADY | ready, HMB_DATA_FWREADY | (5u << HMB_DATA_VERSION_SHIFT),
  HMB_DATA_FC, HMB_DATA_FC | (0x12u << HMB_DATA_FCDATA_SHIFT),
  HMB_DATA_FC | (0x25u << HMB_DATA_FCDATA_SHIFT), HMB_DATA_FWHALT,
  HMB_DATA_FWHALT | HMB_DATA_NAKHANDLED | HMB_DATA_DEVREADY | HMB_DATA_FWREADY |
  HMB_DATA_FC | ready | (0x25u << HMB_DATA_FCDATA_SHIFT), 0x8000};
 for (unsigned n = 0; n < sizeof(valid) / sizeof(valid[0]); n++)
  for (unsigned skipped = 0; skipped < 2; skipped++) mailbox_success(valid[n], skipped);
}
#endif
int main(void)
{
 for (unsigned hard = 0; hard < 2; hard++)
  for (unsigned fail = 0; fail < 2; fail++)
   for (unsigned n = 1; n <= 64; n *= 8) deferred(n, hard, fail);
 active_or_leftover(false); active_or_leftover(true);
 arrival_during_service(); no_status();
 read_error(false); read_error(true);
 existing_error_behavior(false); existing_error_behavior(true);
 failure_gate(); oob_rearm(); mailbox_frame();
#ifdef NEO_WORKER_ERRORS
 retired_oob_rearm();
 failed_ack_publication();
 for (unsigned mode = 0; mode < 9; mode++)
  for (unsigned oob = 0; oob < 2; oob++) fatal(mode, oob, false);
 fatal(0, false, true); fatal(2, false, true);
#ifdef DEBUG
 fatal(9, false, false); fatal(9, true, false);
#endif
 for (unsigned oob = 0; oob < 2; oob++)
  for (unsigned pending = 0; pending < 2; pending++) pending_clock(oob, pending);
#endif
#ifdef NEO_MAILBOX_ERRORS
 mailbox_cases();
#endif
 printf("%u IRQ service scenarios passed (%u characterize existing error limitations)\n",
        scenarios, characterizations);
 return 0;
}
