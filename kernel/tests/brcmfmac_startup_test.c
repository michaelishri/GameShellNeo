/* SPDX-License-Identifier: ISC */
/* Actual firmware callback, download and SR bodies; synchronous kernel seams. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef unsigned int uint;
#define BIT(n) (1U << (n))
#include "brcmfmac_startup_types.h"

struct device { unsigned number; void *data; };
struct sdio_func { struct device dev; unsigned device; };
struct brcmf_core { u32 base; };
struct brcmf_chip { unsigned chiprev, chip; bool sr, ulp; };
struct firmware { const u8 *data; };
struct brcmf_fw_item {
	const struct firmware *binary;
	struct { void *data; u32 len; } nv_data;
};
struct brcmf_fw_request { struct brcmf_fw_item items[3]; };
struct brcmf_bus {
	struct { struct brcmf_sdio_dev *sdio; } bus_priv;
	struct device *dev;
	const void *ops;
	unsigned chip, chiprev;
};
struct brcmf_sdio_dev {
	struct brcmf_bus *bus_if;
	struct brcmf_sdio *bus;
	struct sdio_func *func1, *func2;
	struct device *dev;
	const struct firmware *clm_fw;
	void *settings;
};
struct brcmf_sdio {
	struct brcmf_sdio_dev *sdiodev;
	struct brcmf_core *sdio_core;
	struct brcmf_chip *ci;
	struct { unsigned tickcnt; } sdcnt;
	bool alp_only, sr_enabled;
	int clkstate;
	u32 hostintmask;
};
#define BRCMF_SDIOD_DATA 2
static const unsigned brcmf_sdio_bus_ops;

enum operation {
	DL_CLOCK, DL_CODE, DL_NVRAM, DL_ACTIVE, DL_DROP_CLOCK,
	SETUP_CLOCK, FORCE_READ, FORCE_WRITE, PROTOCOL, ENABLE_F2,
	HOST_MASK, WATERMARK, DEVICE_READ, DEVICE_WRITE, MESBUSY,
	SR_READ, SR_WRITE, SR_CARD, SR_CLOCK, RESTORE_CLOCK,
	REGISTER_IRQ, ALLOC_DRIVER, ATTACH_DRIVER, DROP_CLOCK, CHECKDIED,
	OPERATIONS
};
static const char *const operation_names[OPERATIONS] = {
	"download_clock", "download_code", "download_nvram", "activate", "download_drop",
	"setup_clock", "force_read", "force_write", "protocol", "enable_f2",
	"host_mask", "watermark", "device_read", "device_write", "mesbusy",
	"sr_read", "sr_write", "sr_card", "sr_clock", "restore_clock",
	"register_irq", "allocate", "attach", "drop_clock", "checkdied"
};
static struct {
	struct brcmf_bus interface;
	struct brcmf_sdio_dev dev;
	struct brcmf_sdio bus;
	struct brcmf_chip chip;
	struct brcmf_core core;
	struct sdio_func f1, f2;
	struct firmware code, clm;
	struct brcmf_fw_request request;
	u8 code_data[4], nvram[8];
} f;
static struct {
	unsigned seen[OPERATIONS], hosts, request_frees, code_frees, nvram_frees;
	unsigned release_f1, release_f2, driver_frees, published, timer_starts, disabled;
	enum operation fail;
	int error, secondary_drop_error, final_error;
	bool failed, downloaded, forced, sr_started, allocated, invalid_clock_state;
} hw;

static int operation(enum operation op)
{
	/* A later successful setup operation must never erase the first error. */
	if (hw.failed)
		assert(op == DL_DROP_CLOCK || op == DROP_CLOCK || op == CHECKDIED);
	hw.seen[op]++;
	if (op == hw.fail) {
		hw.failed = true;
		return hw.error;
	}
	if (op == DL_DROP_CLOCK) return hw.secondary_drop_error;
	return 0;
}
static void *dev_get_drvdata(struct device *dev) { assert(dev == &f.f1.dev); return dev->data; }
static const char *dev_name(struct device *dev) { assert(dev); return "fixture"; }
static void debug(const char *format, ...)
{
	char text[160]; va_list ap;
	va_start(ap, format); vsnprintf(text, sizeof(text), format, ap); va_end(ap);
	if (!strncmp(format, "failed:", 7)) {
		char *error = strstr(text, "err="); assert(error);
		hw.final_error = atoi(error + 4);
	}
}
#define brcmf_dbg(level, ...) debug(__VA_ARGS__)
#define brcmf_err(...) debug(__VA_ARGS__)
static void sdio_claim_host(struct sdio_func *func) { assert(func == &f.f1); hw.hosts++; }
static void sdio_release_host(struct sdio_func *func) { assert(func == &f.f1 && hw.hosts); hw.hosts--; }
static void kfree(void *p) { assert(p == &f.request && !hw.request_frees++); }
static void release_firmware(const struct firmware *fw)
{ assert(fw == &f.code && !hw.code_frees++); }
static void brcmf_fw_nvram_free(void *nvram)
{ assert(nvram == f.nvram && !hw.nvram_frees++); }
static u32 get_unaligned_le32(const void *data)
{ const u8 *p = data; return p[0] | p[1] << 8 | p[2] << 16 | (u32)p[3] << 24; }
static int brcmf_sdio_clkctl(struct brcmf_sdio *bus, int clock, bool pending)
{
	assert(bus == &f.bus && hw.hosts && !pending);
	enum operation op = clock == CLK_NONE ? DROP_CLOCK :
		clock == CLK_SDONLY ? DL_DROP_CLOCK : hw.downloaded ? SETUP_CLOCK : DL_CLOCK;
	int error = operation(op);
	if (op == DL_DROP_CLOCK) hw.downloaded = true;
	if (!error && !hw.invalid_clock_state) bus->clkstate = clock;
	return error;
}
static int brcmf_sdio_download_code_file(struct brcmf_sdio *bus, const struct firmware *fw)
{ assert(bus == &f.bus && fw == &f.code && hw.hosts); return operation(DL_CODE); }
static int brcmf_sdio_download_nvram(struct brcmf_sdio *bus, void *data, u32 size)
{ assert(bus == &f.bus && data == f.nvram && size == sizeof(f.nvram) && hw.hosts); return operation(DL_NVRAM); }
static bool brcmf_chip_set_active(struct brcmf_chip *chip, u32 vector)
{ assert(chip == &f.chip && vector == 0x44332211 && hw.hosts); return !operation(DL_ACTIVE); }
static bool brcmf_chip_is_ulp(struct brcmf_chip *chip) { assert(chip == &f.chip); return chip->ulp; }
static bool brcmf_chip_sr_capable(struct brcmf_chip *chip) { assert(chip == &f.chip); return chip->sr; }
static void brcmf_sdio_wd_timer(struct brcmf_sdio *bus, bool active)
{ assert(bus == &f.bus && active); hw.timer_starts++; }
static u8 brcmf_sdiod_readb(struct brcmf_sdio_dev *dev, u32 addr, int *error)
{
	assert(dev == &f.dev && hw.hosts);
	enum operation op = addr == SBSDIO_FUNC1_WAKEUPCTRL ? SR_READ :
		addr == SBSDIO_DEVICE_CTL ? DEVICE_READ : FORCE_READ;
	assert(addr == SBSDIO_FUNC1_WAKEUPCTRL || addr == SBSDIO_DEVICE_CTL || addr == SBSDIO_FUNC1_CHIPCLKCSR);
	if (op == SR_READ) hw.sr_started = true;
	int ret = operation(op); if (error) *error = ret;
	return ret ? 0xff : op == FORCE_READ ? 0x40 : 0x02;
}
static void brcmf_sdiod_writeb(struct brcmf_sdio_dev *dev, u32 addr, u8 value, int *error)
{
	assert(dev == &f.dev && hw.hosts);
	enum operation op;
	if (addr == SBSDIO_WATERMARK) op = WATERMARK;
	else if (addr == SBSDIO_DEVICE_CTL) { op = DEVICE_WRITE; assert(value == (0x02 | SBSDIO_DEVCTL_F2WM_ENAB)); }
	else if (addr == SBSDIO_FUNC1_MESBUSYCTRL) op = MESBUSY;
	else if (addr == SBSDIO_FUNC1_WAKEUPCTRL) op = SR_WRITE;
	else {
		assert(addr == SBSDIO_FUNC1_CHIPCLKCSR);
		op = hw.sr_started ? SR_CLOCK : hw.forced ? RESTORE_CLOCK : FORCE_WRITE;
		if (op == FORCE_WRITE) {
			assert(value == (0x40 | (f.chip.ulp ? SBSDIO_HT_AVAIL_REQ : SBSDIO_FORCE_HT)));
			hw.forced = true;
		}
		if (op == RESTORE_CLOCK) assert(value == 0x40);
	}
	int ret = operation(op); if (error) *error = ret;
}
static void brcmf_sdiod_func0_wb(struct brcmf_sdio_dev *dev, u32 addr, u8 value, int *error)
{
	assert(dev == &f.dev && hw.hosts && addr == SDIO_CCCR_BRCM_CARDCAP);
	u8 expected;
	/* aos_no_decode uses chip IDs, separately controlled from ULP mode. */
	if (f.chip.chip != BRCM_CC_43751_CHIP_ID && f.chip.chip != BRCM_CC_43752_CHIP_ID &&
	    f.chip.chip != CY_CC_43012_CHIP_ID)
		expected = SDIO_CCCR_BRCM_CARDCAP_CMD14_SUPPORT | SDIO_CCCR_BRCM_CARDCAP_CMD14_EXT;
	else expected = SDIO_CCCR_BRCM_CARDCAP_CMD_NODEC;
	assert(value == expected);
	int ret = operation(SR_CARD); if (error) *error = ret;
}
static void brcmf_sdiod_writel(struct brcmf_sdio_dev *dev, u32 addr, u32 value, int *error)
{
	assert(dev == &f.dev && hw.hosts);
	enum operation op = addr == f.core.base + SD_REG(tosbmailboxdata) ? PROTOCOL : HOST_MASK;
	assert(addr == f.core.base + SD_REG(tosbmailboxdata) || addr == f.core.base + SD_REG(hostintmask));
	assert(value == (op == PROTOCOL ? SDPCM_PROT_VERSION << SMB_DATA_VERSION_SHIFT : HOSTINTMASK));
	int ret = operation(op); if (error) *error = ret;
}
static int sdio_enable_func(struct sdio_func *func)
{ assert(func == &f.f2 && hw.hosts); return operation(ENABLE_F2); }
static int sdio_disable_func(struct sdio_func *func)
{ assert(func == &f.f2 && hw.hosts); hw.disabled++; return 0; }
static void brcmf_sdiod_change_state(struct brcmf_sdio_dev *dev, int state)
{ assert(dev == &f.dev && state == BRCMF_SDIOD_DATA && !hw.failed && hw.hosts); hw.published++; }
static int brcmf_sdiod_intr_register(struct brcmf_sdio_dev *dev)
{ assert(dev == &f.dev && hw.hosts && hw.published == 1); return operation(REGISTER_IRQ); }
static int brcmf_alloc(struct device *dev, void *settings)
{
	assert(dev == &f.f1.dev && settings == f.dev.settings && !hw.hosts);
	int ret = operation(ALLOC_DRIVER); if (!ret) hw.allocated = true; return ret;
}
static int brcmf_attach(struct device *dev)
{ assert(dev == &f.f1.dev && hw.allocated && !hw.hosts); return operation(ATTACH_DRIVER); }
static void brcmf_free(struct device *dev)
{ assert(dev == &f.f1.dev && hw.allocated && !hw.driver_frees++ && !hw.hosts); hw.allocated = false; }
static int brcmf_sdio_checkdied(struct brcmf_sdio *bus)
{ assert(bus == &f.bus && hw.hosts); operation(CHECKDIED); return -EPROTO; }
static void device_release_driver(struct device *dev)
{
	assert(!hw.hosts);
	if (dev == &f.f2.dev) { assert(!hw.release_f2++ && !hw.release_f1); }
	else { assert(dev == &f.f1.dev && !hw.release_f1++ && hw.release_f2 == 1); }
}

#include "brcmfmac_startup_functions.h"

static const unsigned chips[] = {
	SDIO_DEVICE_ID_BROADCOM_43751, SDIO_DEVICE_ID_BROADCOM_43752,
	SDIO_DEVICE_ID_BROADCOM_CYPRESS_4373, SDIO_DEVICE_ID_BROADCOM_CYPRESS_43012,
	SDIO_DEVICE_ID_BROADCOM_4329, SDIO_DEVICE_ID_BROADCOM_4339,
	SDIO_DEVICE_ID_BROADCOM_43455, SDIO_DEVICE_ID_BROADCOM_4359,
	SDIO_DEVICE_ID_BROADCOM_4354, SDIO_DEVICE_ID_BROADCOM_4356,
	SDIO_DEVICE_ID_BROADCOM_43430
};
static const int errors[] = {-EILSEQ, -ETIMEDOUT, -ENOMEM};
static void begin(unsigned chip, unsigned mode)
{
	assert(chip < sizeof(chips) / sizeof(*chips) && mode < 3);
	memset(&f, 0, sizeof(f)); memset(&hw, 0, sizeof(hw)); hw.fail = OPERATIONS;
	f.interface.bus_priv.sdio = &f.dev; f.f1.dev.data = &f.interface;
	f.dev.bus_if = &f.interface; f.dev.bus = &f.bus; f.dev.func1 = &f.f1; f.dev.func2 = &f.f2;
	f.dev.dev = &f.f1.dev; f.dev.settings = &f;
	f.bus.sdiodev = &f.dev; f.bus.sdio_core = &f.core; f.bus.ci = &f.chip;
	f.f1.device = chips[chip]; f.core.base = 0x18002000; f.chip.sr = mode != 0; f.chip.ulp = mode == 2;
	f.chip.chip = chip == 0 ? BRCM_CC_43751_CHIP_ID : chip == 1 ? BRCM_CC_43752_CHIP_ID :
		chip == 3 ? CY_CC_43012_CHIP_ID : 43430;
	f.code_data[0] = 0x11; f.code_data[1] = 0x22; f.code_data[2] = 0x33; f.code_data[3] = 0x44;
	f.code.data = f.code_data;
	f.request.items[BRCMF_SDIO_FW_CODE].binary = &f.code;
	f.request.items[BRCMF_SDIO_FW_NVRAM].nv_data.data = f.nvram;
	f.request.items[BRCMF_SDIO_FW_NVRAM].nv_data.len = sizeof(f.nvram);
	f.request.items[BRCMF_SDIO_FW_CLM].binary = &f.clm;
}
static void checked_inputs(void)
{ assert(hw.hosts == 0 && hw.request_frees == 1 && hw.code_frees == 1 && hw.nvram_frees == 1); }
static enum operation named_operation(const char *name)
{
	for (unsigned i = 0; i < OPERATIONS; i++) if (!strcmp(name, operation_names[i])) return (enum operation)i;
	assert(false); return OPERATIONS;
}
int main(int argc, char **argv)
{
	assert(argc >= 4); unsigned chip = (unsigned)atoi(argv[2]), mode = (unsigned)atoi(argv[3]);
	begin(chip, mode);
	if (!strcmp(argv[1], "success")) {
		assert(argc == 4); brcmf_sdio_firmware_callback(&f.f1.dev, 0, &f.request);
		checked_inputs(); assert(!hw.release_f1 && !hw.release_f2 && !hw.driver_frees);
		assert(hw.published == 1 && hw.seen[ATTACH_DRIVER] == 1 && hw.allocated);
		assert(f.bus.sr_enabled == f.chip.sr && !f.bus.alp_only && hw.timer_starts == 1);
		assert(hw.seen[WATERMARK] == 1 && hw.seen[DEVICE_READ] == (unsigned)(chip != 10));
		assert(hw.seen[RESTORE_CLOCK] == (unsigned)(mode == 0));
		assert(hw.seen[SR_CARD] == (unsigned)(mode != 0));
	} else if (!strcmp(argv[1], "failure")) {
		assert(argc == 6); hw.fail = named_operation(argv[4]);
		unsigned error = (unsigned)atoi(argv[5]); assert(error < 3); hw.error = errors[error];
		brcmf_sdio_firmware_callback(&f.f1.dev, 0, &f.request); checked_inputs();
		assert(hw.seen[hw.fail] == 1 && hw.release_f1 == 1 && hw.release_f2 == 1);
		assert(hw.final_error == (hw.fail == DL_ACTIVE ? -EIO : hw.error));
		assert(hw.seen[ATTACH_DRIVER] == (unsigned)(hw.fail == ATTACH_DRIVER));
		assert(hw.driver_frees == (unsigned)(hw.fail == ATTACH_DRIVER));
		assert(hw.published == (unsigned)(hw.fail >= REGISTER_IRQ));
		if (hw.fail >= SR_READ && hw.fail <= SR_CLOCK) assert(!f.bus.sr_enabled);
	} else if (!strcmp(argv[1], "download_primary")) {
		assert(argc == 4); hw.fail = DL_CODE; hw.error = -ENOMEM; hw.secondary_drop_error = -ETIMEDOUT;
		assert(brcmf_sdio_download_firmware(&f.bus, &f.code, f.nvram, sizeof(f.nvram)) == -ENOMEM);
		assert(hw.code_frees == 1 && hw.nvram_frees == 1 && !hw.hosts && !hw.seen[DL_NVRAM]);
	} else if (!strcmp(argv[1], "incoming")) {
		assert(argc == 4); brcmf_sdio_firmware_callback(&f.f1.dev, -ENOENT, NULL);
		assert(hw.final_error == -ENOENT && !hw.request_frees && !hw.code_frees && !hw.nvram_frees);
		assert(hw.release_f1 == 1 && hw.release_f2 == 1 && !hw.hosts && !hw.timer_starts);
	} else if (!strcmp(argv[1], "clock_state")) {
		assert(argc == 4); hw.invalid_clock_state = true;
		brcmf_sdio_firmware_callback(&f.f1.dev, 0, &f.request); checked_inputs();
		assert(hw.final_error == -EIO && hw.release_f1 == 1 && hw.release_f2 == 1 && !hw.seen[FORCE_READ]);
	} else assert(false);
	for (int i = 1; i < argc; i++) printf("%s%s", i == 1 ? "" : " ", argv[i]);
	puts(" passed"); return 0;
}
