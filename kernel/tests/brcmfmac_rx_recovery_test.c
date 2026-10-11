/* SPDX-License-Identifier: ISC */
/* Actual abort/RX recovery functions; scripted synchronous SDIO transfers. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef unsigned int uint;
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, y) ((x) = (y))
#define brcmf_dbg(level, ...) do { if (0) fprintf(stderr, __VA_ARGS__); } while (0)
#define brcmf_err(...) do { if (0) fprintf(stderr, __VA_ARGS__); } while (0)
#include "brcmfmac_rx_constants.h"

struct sdio_func { unsigned num; };
struct brcmf_core { unsigned base; };
struct brcmf_sdio_dev { struct sdio_func *func2; int io_error; };
struct brcmf_sdio {
	struct brcmf_sdio_dev *sdiodev;
	struct brcmf_core *sdio_core;
	struct { unsigned f1regdata, rxrtx; } sdcnt;
	struct { unsigned len; } cur_read;
	bool rxskip;
};
static struct {
	struct sdio_func function;
	struct brcmf_core core;
	struct brcmf_sdio_dev dev;
	struct brcmf_sdio bus;
} f;
static struct {
	unsigned operations, fail_at, byte_reads, aborts, terms, naks, empty_after;
	int error;
	u8 poison;
	bool host_claimed, failed;
} hw;
static unsigned scenarios;

static int access(void)
{
	assert(hw.host_claimed && !f.dev.io_error && !hw.failed);
	hw.operations++;
	if (hw.operations == hw.fail_at) {
		hw.failed = true;
		return hw.error;
	}
	return 0;
}

static void brcmf_sdiod_func0_wb(struct brcmf_sdio_dev *dev, uint addr, u8 value, int *error)
{
	int result = access();
	assert(dev == &f.dev && addr == SDIO_CCCR_ABORT && value == 2);
	hw.aborts++;
	if (error)
		*error = result;
}

static void brcmf_sdiod_writeb(struct brcmf_sdio_dev *dev, uint addr, u8 value, int *error)
{
	assert(dev == &f.dev && addr == SBSDIO_FUNC1_FRAMECTRL && value == SFC_RF_TERM);
	*error = access();
	hw.terms++;
}

static u8 brcmf_sdiod_readb(struct brcmf_sdio_dev *dev, uint addr, int *error)
{
	bool high = (hw.byte_reads++ & 1) == 0;
	assert(dev == &f.dev && hw.terms == 1);
	assert(addr == (high ? SBSDIO_FUNC1_RFRAMEBCHI : SBSDIO_FUNC1_RFRAMEBCLO));
	*error = access();
	if (*error)
		return hw.poison; /* A failed read may return zero or an error sentinel. */
	return high ? 0 : hw.byte_reads / 2 <= hw.empty_after;
}

static void brcmf_sdiod_writel(struct brcmf_sdio_dev *dev, u32 addr, u32 value, int *error)
{
	assert(dev == &f.dev && addr == f.core.base + SD_REG(tosbmailbox) && value == SMB_NAK);
	assert(hw.byte_reads && !(hw.byte_reads & 1) && hw.byte_reads / 2 > hw.empty_after);
	*error = access();
	hw.naks++;
}

#include "brcmfmac_rx_functions.h"

static void begin(void)
{
	memset(&f, 0, sizeof(f));
	memset(&hw, 0, sizeof(hw));
	f.function.num = 2;
	f.core.base = 0x18002000;
	f.dev.func2 = &f.function;
	f.bus.sdiodev = &f.dev;
	f.bus.sdio_core = &f.core;
	f.bus.cur_read.len = 99;
	hw.host_claimed = true;
}

static void happy(bool abort, bool retransmit, unsigned busy)
{
	begin(); hw.empty_after = busy;
	brcmf_sdio_rxfail(&f.bus, abort, retransmit);
	assert(!f.dev.io_error && !f.bus.cur_read.len);
	assert(hw.aborts == (unsigned)abort && hw.terms == 1);
	assert(hw.byte_reads == 2 * (busy + 1));
	assert(hw.naks == (unsigned)retransmit && f.bus.rxskip == retransmit);
	assert(f.bus.sdcnt.f1regdata == 1 + hw.byte_reads + (unsigned)retransmit);
	assert(f.bus.sdcnt.rxrtx == (unsigned)retransmit);
	scenarios++;
}

static void fail(unsigned at, int error, u8 poison)
{
	unsigned before;
	begin(); hw.fail_at = at; hw.error = error; hw.poison = poison;
	brcmf_sdio_rxfail(&f.bus, true, true);
	assert(hw.operations == at && f.dev.io_error == error);
	assert(!f.bus.rxskip && !f.bus.cur_read.len);
	assert(f.bus.sdcnt.f1regdata == at - 1); /* Abort is a function-zero access. */
	assert(hw.naks == (unsigned)(at == 5));
	before = hw.operations;
	f.bus.cur_read.len = 77;
	brcmf_sdio_rxfail(&f.bus, true, true);
	assert(hw.operations == before && f.dev.io_error == error && !f.bus.cur_read.len);
	scenarios++;
}

int main(void)
{
	const int errors[] = { -EIO, -ETIMEDOUT, -ENOMEDIUM };
	const unsigned busy[] = { 0, 1, 65534 };
	unsigned i, j, a, r;
	for (a = 0; a < 2; a++)
		for (r = 0; r < 2; r++)
			for (i = 0; i < sizeof(busy) / sizeof(busy[0]); i++)
				happy(a, r, busy[i]);
	for (i = 0; i < sizeof(errors) / sizeof(errors[0]); i++)
		for (j = 1; j <= 5; j++) {
			fail(j, errors[i], 0);
			fail(j, errors[i], 0xff);
		}
	begin(); hw.empty_after = 65535;
	brcmf_sdio_rxfail(&f.bus, false, true);
	assert(f.dev.io_error == -ETIMEDOUT && hw.byte_reads == 2 * 65535);
	assert(hw.operations == 1 + 2 * 65535 && !hw.naks && !f.bus.rxskip);
	assert(!f.bus.cur_read.len); scenarios++;
	begin(); f.dev.io_error = -ENOSPC;
	brcmf_sdio_rxfail(&f.bus, true, true);
	assert(!hw.operations && f.dev.io_error == -ENOSPC && !f.bus.cur_read.len);
	scenarios++;
	printf("%u RX recovery helper scenarios passed\n", scenarios);
	return 0;
}
