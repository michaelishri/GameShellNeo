/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual old/new context functions against deterministic register banks. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
#define __iomem
#define BIT(n) (1U << (n))
#define MUSB_C_NUM_EPS 3
#include "musb_context_defs.h"

struct musb_platform_ops { u32 quirks; };
struct config { unsigned num_eps; };
struct endpoint { void *regs; };
struct musb {
	void *mregs;
	struct musb_platform_ops *ops;
	struct config *config;
	struct musb_context_registers context;
	struct endpoint endpoints[MUSB_C_NUM_EPS];
	bool dyn_fifo;
	u16 intrtxe, intrrxe;
};
struct access { unsigned bank, offset, width, value, write; };
struct result {
	u8 banks[8][128];
	struct musb_context_registers context;
	struct access trace[256];
	unsigned count, ulpi;
};
static struct result state;
static bool unsupported;

static unsigned access_reg(void *address, unsigned offset, unsigned width,
			   unsigned value, bool write)
{
	unsigned bank = 8;
	for (unsigned i = 0; i < 8; i++)
		if (address == state.banks[i])
			bank = i;
	assert(bank < 8 && offset + width <= 128);
	if (bank == 0 && offset == MUSB_ULPI_BUSCONTROL) {
		state.ulpi++;
		if (unsupported)
			return 0; /* Existing Sunxi accessor: read zero, ignore write. */
	}
	if (write) {
		state.banks[bank][offset] = value;
		if (width == 2)
			state.banks[bank][offset + 1] = value >> 8;
	} else {
		value = state.banks[bank][offset];
		if (width == 2)
			value |= state.banks[bank][offset + 1] << 8;
	}
	assert(state.count < 256);
	state.trace[state.count++] = (struct access){bank, offset, width, value, write};
	return value;
}
static u8 musb_readb(void *address, unsigned offset)
{ return access_reg(address, offset, 1, 0, false); }
static u16 musb_readw(void *address, unsigned offset)
{ return access_reg(address, offset, 2, 0, false); }
static void musb_writeb(void *address, unsigned offset, u8 value)
{ access_reg(address, offset, 1, value, true); }
static void musb_writew(void *address, unsigned offset, u16 value)
{ access_reg(address, offset, 2, value, true); }

/* Target-address helpers have a separate bank per endpoint in this model. */
#define TARGET_HELPERS(name, offset) \
static u8 musb_read_##name(struct musb *musb, unsigned ep) \
{ (void)musb; return musb_readb(state.banks[4 + ep], offset); } \
static void musb_write_##name(struct musb *musb, unsigned ep, u8 value) \
{ (void)musb; musb_writeb(state.banks[4 + ep], offset, value); }
TARGET_HELPERS(txfunaddr, 0)
TARGET_HELPERS(txhubaddr, 1)
TARGET_HELPERS(txhubport, 2)
TARGET_HELPERS(rxfunaddr, 3)
TARGET_HELPERS(rxhubaddr, 4)
TARGET_HELPERS(rxhubport, 5)

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsign-compare"
#include "musb_context_functions.h"
#pragma GCC diagnostic pop

static struct result exercise(bool candidate, unsigned quirks, unsigned fifo,
			      unsigned eps, unsigned session, unsigned power)
{
	memset(&state, 0, sizeof(state));
	for (unsigned b = 0; b < 8; b++)
	for (unsigned r = 0; r < 128; r++)
		state.banks[b][r] = (b * 19 + r * 17 + eps * 7 + fifo * 33) & 255;
	unsupported = quirks != 0;
	struct config config = {MUSB_C_NUM_EPS};
	struct musb_platform_ops ops = {quirks ? SUNXI_QUIRKS : 0};
	struct musb musb = {.mregs = state.banks[0], .ops = &ops, .config = &config,
		.dyn_fifo = fifo, .intrtxe = 0xa5, .intrrxe = 0x5a};
	for (unsigned i = 0; i < MUSB_C_NUM_EPS; i++)
		musb.endpoints[i].regs = eps & BIT(i) ? state.banks[1 + i] : NULL;
	state.banks[0][MUSB_DEVCTL] = session ? MUSB_DEVCTL_SESSION : 0;
	if (candidate)
		musb_save_context(&musb);
	else
		original_musb_save_context(&musb);
	/* Distinct resume state: exercise preservation of SUSPENDM/RESUME. */
	memset(state.banks, 0xa3, sizeof(state.banks));
	state.banks[0][MUSB_POWER] = power << 1;
	if (candidate)
		musb_restore_context(&musb);
	else
		original_musb_restore_context(&musb);
	state.context = musb.context;
	assert((state.banks[0][MUSB_POWER] & (MUSB_POWER_SUSPENDM | MUSB_POWER_RESUME)) == power << 1);
	return state;
}

int main(void)
{
	unsigned scenarios = 0;
	assert(SUNXI_QUIRKS & MUSB_NO_ULPI_BUSCONTROL);
	assert(SUNXI_QUIRKS & MUSB_INDEXED_EP);
	for (unsigned quirks = 0; quirks < 2; quirks++)
	for (unsigned fifo = 0; fifo < 2; fifo++)
	for (unsigned eps = 0; eps < 8; eps++)
	for (unsigned session = 0; session < 2; session++)
	for (unsigned power = 0; power < 4; power++) {
		struct result old = exercise(false, quirks, fifo, eps, session, power);
		struct result new = exercise(true, quirks, fifo, eps, session, power);
		assert(old.ulpi == 2);
		assert(new.ulpi == (quirks ? 0 : 2));
		/* Every supported access and resulting register/context stays equal. */
		old.ulpi = new.ulpi = 0;
		assert(!memcmp(&old, &new, sizeof(old)));
		scenarios++;
	}
	printf("MUSB context: %u register/state equivalence scenarios passed\n", scenarios);
	return 0;
}
