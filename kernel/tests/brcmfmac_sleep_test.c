/* SPDX-License-Identifier: ISC */
/* Locked driver functions, scripted SDIO transfers and deterministic time.
 * This checks return/state/cleanup contracts, not hardware or PM concurrency.
 */
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef unsigned char u8;
typedef unsigned int uint;
#include "brcmfmac_sleep_constants.h"

struct sdio_func { int unused; };
struct brcmf_sdio_dev { struct sdio_func *func1; };
struct brcmf_chip { uint chip; };
struct brcmf_sdio {
	struct brcmf_sdio_dev *sdiodev;
	struct brcmf_chip *ci;
	bool sr_enabled, sleeping, alp_only, clkstate_unknown, sleep_state_unknown;
	uint clkstate;
};
static struct sdio_func func;
static struct brcmf_sdio_dev dev = { .func1 = &func };
static struct brcmf_chip chip;
static struct brcmf_sdio bus;
static unsigned long jiffies;
static unsigned scenarios, wd_starts, crc_disables, crc_enables, holds, releases;
static bool crc_disabled, retune_held;
static uint32_t transcript = 2166136261U;
static struct transfer { bool write; uint address; u8 value; int error; }
	plan[2 * MAX_KSO_ATTEMPTS + 16];
static unsigned planned, consumed;

#define brcmf_dbg(level, ...) do { if (0) fprintf(stderr, __VA_ARGS__); } while (0)
#define brcmf_err(...) do { if (0) fprintf(stderr, __VA_ARGS__); } while (0)
#define msecs_to_jiffies(ms) (ms)
#define time_after(a, b) ((long)((b) - (a)) < 0)

static void record(uint32_t value) { transcript = (transcript ^ value) * 16777619U; }
static void usleep_range(unsigned low, unsigned high)
{
	assert(low <= high);
	jiffies += (low + 999) / 1000;
	record(low);
	record(high);
}
static void udelay(unsigned usec) { record(usec); }
static void sdio_retune_crc_disable(struct sdio_func *f)
{
	assert(f == &func && !crc_disabled);
	crc_disabled = true;
	crc_disables++;
	record(1);
}
static void sdio_retune_crc_enable(struct sdio_func *f)
{
	assert(f == &func && crc_disabled && !retune_held);
	crc_disabled = false;
	crc_enables++;
	record(2);
}
static void sdio_retune_hold_now(struct sdio_func *f)
{
	assert(f == &func && crc_disabled && !retune_held);
	retune_held = true;
	holds++;
	record(3);
}
static void sdio_retune_release(struct sdio_func *f)
{
	assert(f == &func && crc_disabled && retune_held);
	retune_held = false;
	releases++;
	record(4);
}
static struct transfer next(bool write, uint address)
{
	assert(consumed < planned);
	struct transfer t = plan[consumed++];
	assert(t.write == write && t.address == address);
	record(write);
	record(address);
	record(t.value);
	record((uint32_t)t.error);
	return t;
}
static u8 brcmf_sdiod_readb(struct brcmf_sdio_dev *d, uint address, int *error)
{
	assert(d == &dev);
	struct transfer t = next(false, address);
	*error = t.error;
	return t.value;
}
static void brcmf_sdiod_writeb(struct brcmf_sdio_dev *d, uint address, u8 value, int *error)
{
	assert(d == &dev);
	struct transfer t = next(true, address);
	assert(t.value == value);
	*error = t.error;
}
static void brcmf_sdio_wd_timer(struct brcmf_sdio *b, bool active)
{
	assert(b == &bus && active);
	wd_starts++;
	record(5);
}

#include "brcmfmac_sleep_functions.h"

static void reset(uint state, bool sr)
{
	assert(!crc_disabled && !retune_held);
	bus = (struct brcmf_sdio) { .sdiodev = &dev, .ci = &chip,
		.clkstate = state, .sr_enabled = sr };
	chip.chip = 43430;
	jiffies = 0;
	planned = consumed = wd_starts = 0;
	crc_disables = crc_enables = holds = releases = 0;
	scenarios++;
}
static void op(bool write, uint address, u8 value, int error)
{
	assert(planned < sizeof(plan) / sizeof(plan[0]));
	plan[planned++] = (struct transfer) { write, address, value, error };
}
static void rd(uint address, u8 value) { op(false, address, value, 0); }
static void wr(uint address, u8 value) { op(true, address, value, 0); }
static void finish(int actual, int expected, uint state, bool sleeping, unsigned watchdog)
{
	assert(actual == expected && consumed == planned);
	assert(bus.clkstate == state && bus.sleeping == sleeping && wd_starts == watchdog);
	assert(!crc_disabled && !retune_held);
	assert(crc_disables == crc_enables && holds == releases);
	if (!actual)
		assert(!bus.clkstate_unknown && !bus.sleep_state_unknown);
	record((uint32_t)actual);
	record(state);
	record(sleeping);
	record(watchdog);
}
static void kso_script(bool on, unsigned mismatches)
{
	u8 request = on ? SBSDIO_FUNC1_SLEEPCSR_KSO_MASK : 0;
	u8 match = on ? request | SBSDIO_FUNC1_SLEEPCSR_DEVON_MASK : 0;
	wr(SBSDIO_FUNC1_SLEEPCSR, request);
	for (unsigned i = 0; i < mismatches; i++) {
		rd(SBSDIO_FUNC1_SLEEPCSR, on ? 0 : SBSDIO_FUNC1_SLEEPCSR_KSO_MASK);
		wr(SBSDIO_FUNC1_SLEEPCSR, request);
	}
	rd(SBSDIO_FUNC1_SLEEPCSR, match);
}
static void ht_on_script(bool alp, bool pending, bool defer)
{
	wr(SBSDIO_FUNC1_CHIPCLKCSR, alp ? SBSDIO_ALP_AVAIL_REQ : SBSDIO_HT_AVAIL_REQ);
	rd(SBSDIO_FUNC1_CHIPCLKCSR, defer ? 0 : SBSDIO_AVBITS);
	if (pending || defer) {
		rd(SBSDIO_DEVICE_CTL, pending ? 0xa4 : 0xa0);
		wr(SBSDIO_DEVICE_CTL, defer ? 0xa4 : 0xa0);
	}
}
static void ht_off_script(bool pending)
{
	if (pending) {
		rd(SBSDIO_DEVICE_CTL, 0xa4);
		wr(SBSDIO_DEVICE_CTL, 0xa0);
	}
	wr(SBSDIO_FUNC1_CHIPCLKCSR, 0);
}

static void happy(void)
{
	for (unsigned on = 0; on < 2; on++) {
		unsigned retries[] = { 0, 2, MAX_KSO_ATTEMPTS };
		for (unsigned i = 0; i < sizeof(retries) / sizeof(retries[0]); i++) {
			reset(CLK_AVAIL, true);
			kso_script(on, retries[i]);
			finish(brcmf_sdio_kso_control(&bus, on), 0, CLK_AVAIL, false, 0);
			assert(holds == on && crc_disables == 1);
		}
		/* An initial write failure is recoverable if readback confirms the target. */
		reset(CLK_AVAIL, true);
		kso_script(on, 0);
		plan[0].error = -EIO;
		finish(brcmf_sdio_kso_control(&bus, on), 0, CLK_AVAIL, false, 0);
		/* A transient read error followed by a verified match is also recoverable. */
		reset(CLK_AVAIL, true);
		kso_script(on, 2);
		plan[1].error = -EIO;
		finish(brcmf_sdio_kso_control(&bus, on), 0, CLK_AVAIL, false, 0);
	}
	for (unsigned alp = 0; alp < 2; alp++) {
		for (unsigned pending = 0; pending < 2; pending++) {
			for (unsigned defer = 0; defer < 2; defer++) {
				reset(pending ? CLK_PENDING : CLK_SDONLY, false);
				bus.alp_only = alp;
				ht_on_script(alp, pending, defer);
				finish(brcmf_sdio_htclk(&bus, true, defer), 0,
				       defer ? CLK_PENDING : CLK_AVAIL, false, 0);
			}
		}
	}
	for (unsigned pending = 0; pending < 2; pending++) {
		reset(pending ? CLK_PENDING : CLK_AVAIL, false);
		ht_off_script(pending);
		finish(brcmf_sdio_htclk(&bus, false, false), 0, CLK_SDONLY, false, 0);
	}
	for (unsigned on = 0; on < 2; on++) {
		reset(CLK_SDONLY, true);
		finish(brcmf_sdio_htclk(&bus, on, false), 0,
		       on ? CLK_AVAIL : CLK_SDONLY, false, 0);
	}
	reset(CLK_SDONLY, false);
	bus.alp_only = true;
	wr(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_ALP_AVAIL_REQ);
	rd(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_ALP_AVAIL);
	finish(brcmf_sdio_htclk(&bus, true, false), 0, CLK_AVAIL, false, 0);
	/* Every previously supported synchronous clock-state transition. */
	const uint targets[] = { CLK_NONE, CLK_SDONLY, CLK_AVAIL };
	for (unsigned i = 0; i < 3; i++) {
		for (unsigned j = 0; j < 3; j++) {
			reset(targets[i], false);
			if (i != j && targets[j] == CLK_AVAIL)
				ht_on_script(false, false, false);
			if (i != j && targets[i] == CLK_AVAIL)
				ht_off_script(false);
			finish(brcmf_sdio_clkctl(&bus, targets[j], false), 0, targets[j], false, 0);
		}
	}
	/* The polling clock path, including an unsigned-jiffies rollover. */
	for (unsigned rollover = 0; rollover < 2; rollover++) {
		reset(CLK_SDONLY, false);
		jiffies = rollover ? ULONG_MAX - 3 : 0;
		wr(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_HT_AVAIL_REQ);
		rd(SBSDIO_FUNC1_CHIPCLKCSR, 0);
		rd(SBSDIO_FUNC1_CHIPCLKCSR, 0);
		rd(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_AVBITS);
		finish(brcmf_sdio_htclk(&bus, true, false), 0, CLK_AVAIL, false, 0);
	}
	for (unsigned sr = 0; sr < 2; sr++) {
		for (unsigned sleeping = 0; sleeping < 2; sleeping++) {
			for (unsigned sleep = 0; sleep < 2; sleep++) {
				reset(sleeping ? CLK_SDONLY : CLK_AVAIL, sr);
				bus.sleeping = sleeping;
				if (sr && sleep != sleeping) {
					if (sleep)
						rd(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_HT_AVAIL_REQ);
					kso_script(!sleep, 0);
				} else if (!sr && sleeping && !sleep) {
					ht_on_script(false, false, false);
				} else if (!sr && !sleeping && sleep) {
					ht_off_script(false);
				}
				uint state = !sleep ? CLK_AVAIL : sr ? bus.clkstate : CLK_NONE;
				finish(brcmf_sdio_bus_sleep(&bus, sleep, false), 0, state, sleep, !sleep);
			}
		}
	}
	/* SR sleep must request ALP when no clock request is present. */
	reset(CLK_AVAIL, true);
	rd(SBSDIO_FUNC1_CHIPCLKCSR, 0);
	wr(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_ALP_AVAIL_REQ);
	kso_script(false, 0);
	finish(brcmf_sdio_bus_sleep(&bus, true, false), 0, CLK_AVAIL, true, 0);
	printf("happy: %u scenarios, transfer/delay/state transcript %08x\n", scenarios, transcript);
}

#ifndef NEO_BASELINE
static void errors(void)
{
	for (unsigned on = 0; on < 2; on++) {
		for (unsigned write_error = 0; write_error < 2; write_error++) {
			reset(CLK_AVAIL, true);
			kso_script(on, MAX_KSO_ATTEMPTS + 1);
			planned--; /* Exhaustion ends after a write, without another read. */
			if (write_error)
				plan[planned - 1].error = -EIO;
			finish(brcmf_sdio_kso_control(&bus, on), write_error ? -EIO : -ETIMEDOUT,
			       CLK_AVAIL, false, 0);
		}
		reset(CLK_AVAIL, true);
		kso_script(on, BRCMF_SDIO_MAX_ACCESS_ERRORS + 1);
		for (unsigned i = 1; i < planned; i += 2)
			plan[i].error = -EILSEQ;
		finish(brcmf_sdio_kso_control(&bus, on), -EILSEQ, CLK_AVAIL, false, 0);
	}
	/* The special chip must retain its no-read path but balance CRC retuning. */
	for (unsigned fail = 0; fail < 2; fail++) {
		reset(CLK_AVAIL, true);
		chip.chip = CY_CC_43012_CHIP_ID;
		op(true, SBSDIO_FUNC1_SLEEPCSR, 0, fail ? -EIO : 0);
		finish(brcmf_sdio_kso_control(&bus, false), fail ? -EIO : 0, CLK_AVAIL, false, 0);
		assert(crc_disables == 1 && holds == 0);
	}
	/* Fail each transfer in the ordinary, deferred, and pending-cancel paths. */
	for (unsigned variant = 0; variant < 4; variant++) {
		unsigned count = variant ? 4 : 2;
		for (unsigned site = 0; site < count; site++) {
			bool pending = variant >= 2, defer = variant & 1;
			uint start = pending ? CLK_PENDING : CLK_SDONLY;
			reset(start, false);
			ht_on_script(false, pending, defer);
			assert(planned == count);
			plan[site].error = -EIO;
			if (!plan[site].write)
				plan[site].value = 0xff; /* Never interpret data from a failed read. */
			planned = site + 1;
			finish(brcmf_sdio_htclk(&bus, true, defer), -EBADE, start, false, 0);
		}
	}
	for (unsigned pending = 0; pending < 2; pending++) {
		for (unsigned site = 0; site < (pending ? 3U : 1U); site++) {
			uint start = pending ? CLK_PENDING : CLK_AVAIL;
			reset(start, false);
			ht_off_script(pending);
			plan[site].error = -EIO;
			planned = site + 1;
			finish(brcmf_sdio_htclk(&bus, false, false), -EBADE, start, false, 0);
		}
	}
	/* A failed polling read cannot be overwritten by a later successful read. */
	for (unsigned poison = 0; poison < 2; poison++) {
		reset(CLK_SDONLY, false);
		wr(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_HT_AVAIL_REQ);
		rd(SBSDIO_FUNC1_CHIPCLKCSR, 0);
		op(false, SBSDIO_FUNC1_CHIPCLKCSR, poison ? 0xff : 0, -EIO);
		finish(brcmf_sdio_htclk(&bus, true, false), -EBADE, CLK_SDONLY, false, 0);
	}
	/* Clock target never becomes available: retain the existing clock errno. */
	reset(CLK_SDONLY, false);
	wr(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_HT_AVAIL_REQ);
	rd(SBSDIO_FUNC1_CHIPCLKCSR, 0);
	for (unsigned ms = 0; ms <= PMU_MAX_TRANSITION_DLY / 1000 + 5; ms += 5)
		rd(SBSDIO_FUNC1_CHIPCLKCSR, 0);
	finish(brcmf_sdio_htclk(&bus, true, false), -EBADE, CLK_SDONLY, false, 0);
	/* Preserve errors through clkctl; do not publish NONE after a failed off. */
	for (unsigned source = 0; source < 2; source++) {
		for (unsigned site = 0; site < 2; site++) {
			reset(source ? CLK_SDONLY : CLK_NONE, false);
			ht_on_script(false, false, false);
			plan[site].error = -EIO;
			planned = site + 1;
			finish(brcmf_sdio_clkctl(&bus, CLK_AVAIL, false), -EBADE, CLK_SDONLY, false, 0);
		}
	}
	for (unsigned target = CLK_NONE; target <= CLK_SDONLY; target++) {
		reset(CLK_AVAIL, false);
		op(true, SBSDIO_FUNC1_CHIPCLKCSR, 0, -EIO);
		finish(brcmf_sdio_clkctl(&bus, target, false), -EBADE, CLK_AVAIL, false, 0);
	}
	/* Both clock-control errors reach bus_sleep without state/watchdog success. */
	for (unsigned sleep = 0; sleep < 2; sleep++) {
		uint start = sleep ? CLK_AVAIL : CLK_SDONLY;
		reset(start, false);
		bus.sleeping = !sleep;
		op(true, SBSDIO_FUNC1_CHIPCLKCSR, sleep ? 0 : SBSDIO_HT_AVAIL_REQ, -EIO);
		finish(brcmf_sdio_bus_sleep(&bus, sleep, false), -EBADE, start, !sleep, 0);
	}
	/* Preliminary SR read/ALP-write errors must stop before KSO access. */
	for (unsigned site = 0; site < 2; site++) {
		reset(CLK_AVAIL, true);
		rd(SBSDIO_FUNC1_CHIPCLKCSR, 0);
		wr(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_ALP_AVAIL_REQ);
		plan[site].error = -EIO;
		planned = site + 1;
		finish(brcmf_sdio_bus_sleep(&bus, true, false), -EIO, CLK_AVAIL, false, 0);
	}
	for (unsigned sleep = 0; sleep < 2; sleep++) {
		reset(CLK_AVAIL, true);
		bus.sleeping = !sleep;
		if (sleep)
			rd(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_HT_AVAIL_REQ);
		kso_script(!sleep, MAX_KSO_ATTEMPTS + 1);
		planned--;
		finish(brcmf_sdio_bus_sleep(&bus, sleep, false), -ETIMEDOUT, CLK_AVAIL, !sleep, 0);
	}
	printf("total: %u scenarios passed\n", scenarios);
}

static void recovery(void)
{
	/* Failed sleep followed by wake, and failed wake followed by sleep.
	 * The inverse request equals the old cache but must still access KSO.
	 */
	for (unsigned first_sleep = 0; first_sleep < 2; first_sleep++) {
		for (unsigned repeat_failure = 0; repeat_failure < 2; repeat_failure++) {
			reset(CLK_AVAIL, true);
			bus.sleeping = !first_sleep;
			if (first_sleep)
				rd(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_HT_AVAIL_REQ);
			kso_script(!first_sleep, BRCMF_SDIO_MAX_ACCESS_ERRORS + 1);
			for (unsigned i = first_sleep + 1; i < planned; i += 2)
				plan[i].error = -EIO;
			finish(brcmf_sdio_bus_sleep(&bus, first_sleep, false), -EIO,
			       CLK_AVAIL, !first_sleep, 0);
			assert(bus.sleep_state_unknown);
			if (repeat_failure) {
				if (!first_sleep)
					rd(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_HT_AVAIL_REQ);
				unsigned begin = planned;
				kso_script(first_sleep, BRCMF_SDIO_MAX_ACCESS_ERRORS + 1);
				for (unsigned i = begin + 1; i < planned; i += 2)
					plan[i].error = -EIO;
				finish(brcmf_sdio_bus_sleep(&bus, !first_sleep, false), -EIO,
				       CLK_AVAIL, !first_sleep, 0);
				assert(bus.sleep_state_unknown);
			}
			if (!first_sleep)
				rd(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_HT_AVAIL_REQ);
			kso_script(first_sleep, 0);
			finish(brcmf_sdio_bus_sleep(&bus, !first_sleep, false), 0,
			       CLK_AVAIL, !first_sleep, first_sleep);
			/* A subsequent identical request regains the normal cached fast path. */
			finish(brcmf_sdio_bus_sleep(&bus, !first_sleep, false), 0,
			       CLK_AVAIL, !first_sleep, 2 * first_sleep);
		}
	}
	/* Failed clock-off leaves an uncertain AVAIL cache: same-target wake must verify. */
	reset(CLK_AVAIL, false);
	op(true, SBSDIO_FUNC1_CHIPCLKCSR, 0, -EIO);
	finish(brcmf_sdio_bus_sleep(&bus, true, false), -EBADE, CLK_AVAIL, false, 0);
	assert(bus.clkstate_unknown && bus.sleep_state_unknown);
	ht_on_script(false, true, false);
	finish(brcmf_sdio_bus_sleep(&bus, false, false), 0, CLK_AVAIL, false, 1);
	/* Failed clock-on may have set its request; inverse off must cancel it. */
	for (unsigned target = CLK_NONE; target <= CLK_SDONLY; target++) {
		reset(CLK_SDONLY, false);
		wr(SBSDIO_FUNC1_CHIPCLKCSR, SBSDIO_HT_AVAIL_REQ);
		op(false, SBSDIO_FUNC1_CHIPCLKCSR, 0, -EIO);
		finish(brcmf_sdio_clkctl(&bus, CLK_AVAIL, false), -EBADE, CLK_SDONLY, false, 0);
		assert(bus.clkstate_unknown);
		ht_off_script(true);
		finish(brcmf_sdio_clkctl(&bus, target, false), 0, target, false, 0);
	}
	/* Pending requests must clear their interrupt filter before clock shutdown. */
	for (unsigned target = CLK_NONE; target <= CLK_SDONLY; target++) {
		reset(CLK_PENDING, false);
		ht_off_script(true);
		finish(brcmf_sdio_clkctl(&bus, target, false), 0, target, false, 0);
	}
	/* A failed pending-filter write must not make a later off skip that cleanup. */
	reset(CLK_PENDING, false);
	rd(SBSDIO_DEVICE_CTL, 0xa4);
	op(true, SBSDIO_DEVICE_CTL, 0xa0, -EIO);
	finish(brcmf_sdio_clkctl(&bus, CLK_NONE, false), -EBADE, CLK_PENDING, false, 0);
	assert(bus.clkstate_unknown);
	ht_off_script(true);
	finish(brcmf_sdio_clkctl(&bus, CLK_NONE, false), 0, CLK_NONE, false, 0);
	/* Setting PENDING may fail after the filter write reached the card. */
	reset(CLK_SDONLY, false);
	ht_on_script(false, false, true);
	plan[planned - 1].error = -EIO;
	finish(brcmf_sdio_clkctl(&bus, CLK_AVAIL, true), -EBADE, CLK_SDONLY, false, 0);
	assert(bus.clkstate_unknown);
	ht_off_script(true);
	finish(brcmf_sdio_clkctl(&bus, CLK_SDONLY, false), 0, CLK_SDONLY, false, 0);
	printf("with recovery: %u scenarios passed\n", scenarios);
}
#endif

int main(void)
{
	happy();
#ifndef NEO_BASELINE
	errors();
	recovery();
#endif
	return 0;
}
