/* SPDX-License-Identifier: ISC */
/* Reuse the actual RAM/cleanup fixture; this file owns diagnostic call scenarios. */
#define main watchdog_fixture_main
#include "brcmfmac_watchdog_test.c"
#undef main

struct seq_file { unsigned unused; };
#define seq_printf(seq, ...) do { assert(seq); hw.seq_lines++; } while (0)
static int seq_write(struct seq_file *seq, const void *data, unsigned size)
{ assert(seq && data && size <= 16); hw.seq_bytes += size; return 0; }
static void *vzalloc(unsigned size) { assert(size == 17); return calloc(1, size); }
#define vfree free
static bool brcmf_chip_sr_capable(struct brcmf_chip *chip)
{ assert(chip == &f.chip); return chip->sr_capable; }

#include "brcmfmac_shared_functions.h"

/* Adapt the historical void API only; candidate status must reach its caller. */
static int console_address(void)
{
#ifdef NEO_SHARED_RETURNS_STATUS
	return brcmf_sdio_get_console_addr(&f.bus);
#else
	brcmf_sdio_get_console_addr(&f.bus); return 0;
#endif
}

static void shared_begin(bool nested)
{
	begin(); f.bus.ci = &f.chip; f.chip.ramsize = 0x10000; f.chip.srsize = 0x1000;
	hw.shared = true; hw.shared_address = 0x5000; hw.shared_flags = SDPCM_SHARED_VERSION;
	if (nested) sdio_claim_host(&f.func);
}
static void shared_end(bool nested)
{
	if (nested) sdio_release_host(&f.func);
	finish();
}
static void unchanged(const struct sdpcm_shared *sh)
{
	const u8 *bytes = (const u8 *)sh;
	for (unsigned i = 0; i < sizeof(*sh); i++) assert(bytes[i] == 0xa5);
}
static void diagnosed(int error)
{
	assert(f.dev.io_error == error && f.bus.io_error_handled && f.dev.state == BRCMF_SDIOD_DOWN);
	assert(hw.states == 1 && hw.responses == 1 && hw.quiesces == 1 && hw.controls == 1);
	assert(!f.bus.ctrl_frame_stat && f.bus.ctrl_frame_err == error && !f.bus.wd_active);
	assert(!f.bus.ipend && !f.bus.intstatus && hw.timer_deletes == 1);
	unsigned wakes = hw.wakes, reads = hw.ram_reads;
	struct sdpcm_shared sh; memset(&sh, 0xa5, sizeof(sh));
	assert(brcmf_sdio_readshared(&f.bus, &sh) == error); unchanged(&sh);
	assert(hw.wakes == wakes && hw.ram_reads == reads && hw.quiesces == 1 && hw.responses == 1);
}
static void shared_success(unsigned index)
{
	assert(index < 8); bool nested = index & 1; shared_begin(nested);
	f.chip.rambase = index & 2 ? 0x10000 : 0;
	f.chip.sr_capable = index & 4;
	struct sdpcm_shared sh; memset(&sh, 0xa5, sizeof(sh));
	assert(brcmf_sdio_readshared(&f.bus, &sh) == 0);
	assert(sh.flags == SDPCM_SHARED_VERSION && sh.trap_addr == 0x6000);
	assert(sh.assert_file_addr == 0x6100 && sh.assert_exp_addr == 0x6200 && sh.assert_line == 23);
	assert(sh.console_addr == 0x2000 && sh.msgtrace_addr == 0x6300);
	assert(hw.ram_reads == 2 && !f.dev.io_error && !hw.quiesces);
	f.bus.console_addr = 0;
	assert(console_address() == 0);
	assert(f.bus.console_addr == 0x2000 && hw.ram_reads == 4);
	shared_end(nested);
}
static void shared_wake_failure(unsigned index)
{
	assert(index < 12); bool nested = index & 1; shared_begin(nested);
	hw.wake_error = errors[index / 4];
	struct sdpcm_shared sh; memset(&sh, 0xa5, sizeof(sh));
	if (index & 2) {
		f.bus.console_addr = 0x7770;
		assert(console_address() == hw.wake_error);
		assert(f.bus.console_addr == 0x7770);
	} else {
		assert(brcmf_sdio_readshared(&f.bus, &sh) == hw.wake_error); unchanged(&sh);
	}
	assert(hw.wakes == 1 && !hw.ram_reads && !hw.ram_allocs);
	diagnosed(hw.wake_error); shared_end(nested);
}
static void shared_admission(unsigned index)
{
	assert(index < 16); bool nested = index & 8; shared_begin(false);
	unsigned mode = index % 4;
	hw.admission = mode == 3 ? ADMIT_NOMEDIUM : (enum admission_fault)mode;
	if (index & 4) hw.inject_claim = 1;
	else {
		if (mode == 0 || mode == 2) f.dev.io_error = -EILSEQ;
		if (mode == 1 || mode == 2) f.dev.pm_failed = true;
		if (mode == 3) f.dev.state = BRCMF_SDIOD_NOMEDIUM;
	}
	if (nested) sdio_claim_host(&f.func);
	struct sdpcm_shared sh; memset(&sh, 0xa5, sizeof(sh));
	int expected = mode == 1 ? -EHOSTDOWN : mode == 3 ? -ENOMEDIUM : -EILSEQ;
	assert(brcmf_sdio_readshared(&f.bus, &sh) == expected); unchanged(&sh);
	assert(!hw.wakes && !hw.ram_reads && !hw.ram_allocs && !hw.quiesces && !hw.responses);
	shared_end(nested);
}
static void shared_ram_failure(unsigned index)
{
	assert(index < 24); bool nested = index & 1; shared_begin(nested);
	hw.ram_fail_at = 1 + (index / 2 % 2); hw.window_failure = index & 4;
	hw.ram_error = errors[index / 8]; hw.failed_value = 0xff;
	struct sdpcm_shared sh; memset(&sh, 0xa5, sizeof(sh));
	assert(brcmf_sdio_readshared(&f.bus, &sh) == hw.ram_error); unchanged(&sh);
	assert(hw.ram_reads == hw.ram_fail_at);
	diagnosed(hw.ram_error); shared_end(nested);
}
static void shared_metadata(unsigned index)
{
	assert(index < 6); shared_begin(false); unsigned mode = index / 2;
	if (!mode) hw.shared_address = 0;
	if (mode == 1) hw.shared_address = 0xffff0000;
	if (mode == 2) hw.shared_flags = SDPCM_SHARED_VERSION + 1;
	f.bus.console_addr = 0x7770;
	struct sdpcm_shared sh; memset(&sh, 0xa5, sizeof(sh));
	if (index & 1) {
		assert(console_address() == 0); assert(f.bus.console_addr == 0x7770);
	} else {
		assert(brcmf_sdio_readshared(&f.bus, &sh) == (mode == 2 ? -EPROTO : -EINVAL));
		unchanged(&sh);
	}
	assert(!f.dev.io_error && !hw.quiesces && !hw.responses);
	assert(hw.ram_reads == (mode == 2 ? 2u : 1u)); shared_end(false);
}
static void shared_allocation(unsigned index)
{
	assert(index < 16); bool nested = index & 1; shared_begin(nested);
	unsigned stage = 1 + (index / 2 % 2);
	if (index & 4) { hw.ram_fail_at = stage; hw.ram_error = -ENOMEM; }
	else hw.ram_alloc_fail_at = stage;
	struct sdpcm_shared sh; memset(&sh, 0xa5, sizeof(sh));
	if (index & 8) {
		f.bus.console_addr = 0x7770;
		assert(console_address() == 0); assert(f.bus.console_addr == 0x7770);
	} else {
		assert(brcmf_sdio_readshared(&f.bus, &sh) == -ENOMEM); unchanged(&sh);
	}
	assert(!f.dev.io_error && !hw.quiesces && !hw.responses && f.dev.state == BRCMF_SDIOD_DATA);
	assert(hw.ram_reads == stage - (unsigned)!(index & 4)); shared_end(nested);
}
static void shared_callers(unsigned index)
{
	assert(index < 12); shared_begin(false); bool dump = index & 1, late = index & 2;
	unsigned mode = index / 4;
	hw.shared_flags |= SDPCM_SHARED_ASSERT_BUILT | SDPCM_SHARED_ASSERT | SDPCM_SHARED_TRAP;
	if (mode) {
		hw.ram_fail_at = dump ? (late ? 5 : 3) : (late ? 3 : 2);
		hw.ram_error = mode == 1 ? -ENOMEM : -EILSEQ;
	}
	struct seq_file seq = {0};
	int result = dump ? brcmf_sdio_died_dump(&seq, &f.bus) : brcmf_sdio_checkdied(&f.bus);
	assert(result == hw.ram_error);
	if (mode == 2) diagnosed(hw.ram_error);
	else assert(!f.dev.io_error && !hw.quiesces && !hw.responses);
	if (!mode) assert(hw.ram_reads == (dump ? 9u : 3u));
	else assert(hw.ram_reads == hw.ram_fail_at);
	shared_end(false);
}
enum diagnostic_boundary {
	CHECKDIED_TRAP, DUMP_ASSERT, DUMP_TRAP, DUMP_CONSOLE_POINTER,
	DUMP_CONSOLE_SIZE, DUMP_CONSOLE_INDEX, DUMP_CONSOLE_DATA, DIAGNOSTIC_BOUNDARIES
};
static void shared_later_admission(unsigned index)
{
	static const struct {
		bool dump;
		unsigned host_claim, preceding_reads;
	} boundaries[DIAGNOSTIC_BOUNDARIES] = {
		[CHECKDIED_TRAP] = {false, 2, 2},
		[DUMP_ASSERT] = {true, 2, 2},
		[DUMP_TRAP] = {true, 3, 4},
		[DUMP_CONSOLE_POINTER] = {true, 4, 5},
		[DUMP_CONSOLE_SIZE] = {true, 5, 6},
		[DUMP_CONSOLE_INDEX] = {true, 6, 7},
		[DUMP_CONSOLE_DATA] = {true, 7, 8},
	};
	assert(index < DIAGNOSTIC_BOUNDARIES * 4); shared_begin(false);
	enum diagnostic_boundary boundary = index / 4;
	unsigned mode = index % 4;
	hw.shared_flags |= SDPCM_SHARED_ASSERT_BUILT | SDPCM_SHARED_ASSERT | SDPCM_SHARED_TRAP;
	hw.inject_claim = boundaries[boundary].host_claim;
	hw.admission = mode == 3 ? ADMIT_NOMEDIUM : (enum admission_fault)mode;
	struct seq_file seq = {0};
	int expected = mode == 1 ? -EHOSTDOWN : mode == 3 ? -ENOMEDIUM : -EILSEQ;
	int result = boundaries[boundary].dump ? brcmf_sdio_died_dump(&seq, &f.bus) :
		brcmf_sdio_checkdied(&f.bus);
	assert(result == expected && hw.ram_reads == boundaries[boundary].preceding_reads);
	assert(!hw.quiesces && !hw.responses && !hw.controls);
	shared_end(false);
}
static void shared_startup(unsigned index)
{
	assert(index < 16); bool nested = index & 1; shared_begin(nested);
	bool timer = index & 2, control = index & 4;
	f.dev.state = BRCMF_SDIOD_DOWN; f.bus.wd_active = timer; f.bus.ctrl_frame_stat = control;
	if (index & 8) { hw.ram_fail_at = 1; hw.ram_error = -EILSEQ; }
	else hw.wake_error = -EILSEQ;
	assert(brcmf_sdio_checkdied(&f.bus) == -EILSEQ);
	assert(f.dev.io_error == -EILSEQ && f.bus.io_error_handled && f.dev.state == BRCMF_SDIOD_DOWN);
	assert(hw.quiesces == 1 && hw.responses == 1 && hw.states == 1);
	assert(hw.timer_deletes == timer && hw.controls == control && !f.bus.wd_active);
	assert(!f.bus.ctrl_frame_stat && !f.bus.ipend && !f.bus.intstatus);
	if (control) assert(f.bus.ctrl_frame_err == -EILSEQ);
	unsigned reads = hw.ram_reads, wakes = hw.wakes;
	assert(brcmf_sdio_checkdied(&f.bus) == -EILSEQ);
	/* The later worker/unwind cleanup must retain the first error and owner. */
	sdio_claim_host(&f.func); brcmf_sdio_dpc_failed(&f.bus, -ETIMEDOUT); sdio_release_host(&f.func);
	assert(f.dev.io_error == -EILSEQ && hw.quiesces == 1 && hw.responses == 1);
	assert(hw.timer_deletes == timer && hw.controls == control && hw.states == 1);
	assert(hw.ram_reads == reads && hw.wakes == wakes); shared_end(nested);
}
static void shared_later_failure(unsigned index)
{
	assert(index < 56); shared_begin(false);
	const int faults[] = {-EIO, -ETIMEDOUT, -EILSEQ, -ENOMEM};
	hw.shared_flags |= SDPCM_SHARED_ASSERT_BUILT | SDPCM_SHARED_ASSERT | SDPCM_SHARED_TRAP;
	hw.ram_fail_at = 3 + index % 7; hw.window_failure = index / 7 % 2;
	hw.ram_error = faults[index / 14];
	struct seq_file seq = {0};
	assert(brcmf_sdio_died_dump(&seq, &f.bus) == hw.ram_error);
	assert(hw.ram_reads == hw.ram_fail_at);
	if (hw.ram_error != -ENOMEM) diagnosed(hw.ram_error);
	else assert(!f.dev.io_error && !hw.quiesces && !hw.responses);
	shared_end(false);
}
int main(int argc, char **argv)
{
	assert(argc == 3); unsigned index = strtoul(argv[2], NULL, 10);
	if (!strcmp(argv[1], "success")) shared_success(index);
	else if (!strcmp(argv[1], "wake_failure")) shared_wake_failure(index);
	else if (!strcmp(argv[1], "admission")) shared_admission(index);
	else if (!strcmp(argv[1], "ram_failure")) shared_ram_failure(index);
	else if (!strcmp(argv[1], "metadata")) shared_metadata(index);
	else if (!strcmp(argv[1], "allocation")) shared_allocation(index);
	else if (!strcmp(argv[1], "callers")) shared_callers(index);
	else if (!strcmp(argv[1], "later_admission")) shared_later_admission(index);
	else if (!strcmp(argv[1], "startup")) shared_startup(index);
	else if (!strcmp(argv[1], "later_failure")) shared_later_failure(index);
	else assert(false);
	printf("%s %u passed\n", argv[1], index); return 0;
}
