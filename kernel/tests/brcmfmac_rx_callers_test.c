/* SPDX-License-Identifier: ISC */
/* Actual RX callers/parser/recovery; bounded packet and synchronous SDIO seams. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint32_t __le32;
typedef unsigned uint;
typedef unsigned long ulong;
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, y) ((x) = (y))
#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))
#define min_t(t, a, b) ((t)(a) < (t)(b) ? (t)(a) : (t)(b))
#define roundup(x, y) ((((x) + (y) - 1) / (y)) * (y))
#define le32_to_cpu(x) (x) /* Both tested hosts are little-endian. */
#define brcmf_dbg(...) ((void)0)
#define brcmf_err(...) ((void)0)
#define brcmf_dbg_hex_dump(...) ((void)0)
#define BRCMF_GLOM_ON() false
#define BRCMF_BYTES_ON() false
#define BRCMF_HDRS_ON() false
#define BRCMF_DATA_ON() false
#define BRCMF_CTL_ON() false
#define trace_brcmf_sdpcm_hdr(...) ((void)0)
#include "brcmfmac_rx_caller_types.h"

struct sk_buff_head;
struct sk_buff {
	u8 *data, *storage;
	unsigned len, capacity;
	struct sk_buff *next, *prev;
	struct sk_buff_head *owner;
	bool freed;
};
struct sk_buff_head { struct sk_buff *first, *last; unsigned qlen; };
struct sdio_func { unsigned num; };
struct brcmf_core { u32 base; };
struct brcmf_bus { unsigned maxctl; };
struct brcmf_sdio_dev {
	struct sdio_func *func1, *func2;
	struct brcmf_bus *bus_if;
	void *dev;
	int io_error;
	unsigned state;
};
enum { BRCMF_SDIOD_DOWN, BRCMF_SDIOD_DATA };
struct brcmf_sdio {
	struct brcmf_sdio_dev *sdiodev;
	struct brcmf_core *sdio_core;
	struct brcmf_sdio_count sdcnt;
	struct brcmf_sdio_hdrinfo cur_read;
	struct sk_buff *glomd;
	struct sk_buff_head glom;
	bool rxskip, rxpending;
	u8 rx_seq, flowcontrol, tx_seq, tx_max;
	u8 *rxhdr, *rxbuf, *rxctl, *rxctl_orig;
	unsigned blocksize, roundup, head_align, sgentry_align, rxblen, rxlen, rxctl_lock;
};
static struct {
	struct brcmf_sdio bus;
	struct brcmf_sdio_dev dev;
	struct brcmf_core core;
	struct sdio_func f1, f2;
	struct brcmf_bus bus_if;
	_Alignas(8) u8 hdr[64], control[512];
} f;
static struct {
	unsigned host, claims, releases, lock, allocations, frees, delivered, responses;
	unsigned alloc_fail_at, control_live, control_allocs, control_frees;
	unsigned received, receive_fail_at, recovery_ops, recovery_fail_at, terms, naks;
	unsigned reads_after_failure, empty_after, body_offset, record_count;
	bool fail_control_alloc, forbid_packet_pull, frame_consumed, readahead;
	bool fifo, nak_pending;
	unsigned fifo_pos, fifo_end, fifo_size, partial_failure_bytes;
	int recovery_error;
	_Alignas(8) u8 frame[512];
	struct sk_buff *records[32];
} hw;

static void sdio_claim_host(struct sdio_func *func)
{ assert(func == &f.f1 && !hw.host); hw.host = 1; hw.claims++; }
static void sdio_release_host(struct sdio_func *func)
{ assert(func == &f.f1 && hw.host == 1); hw.host = 0; hw.releases++; }
static void spin_lock_bh(unsigned *lock)
{ assert(lock == &f.bus.rxctl_lock && !hw.lock); hw.lock = 1; }
static void spin_unlock_bh(unsigned *lock)
{ assert(lock == &f.bus.rxctl_lock && hw.lock == 1); hw.lock = 0; }
static u16 get_unaligned_le16(const void *pointer)
{ const u8 *p = pointer; return p[0] | (u16)p[1] << 8; }
static void put16(u8 *p, u16 value) { p[0] = value; p[1] = value >> 8; }

static struct sk_buff *brcmu_pkt_buf_get_skb(unsigned len)
{
	struct sk_buff *p;
	assert(hw.record_count < 32);
	if (++hw.allocations == hw.alloc_fail_at)
		return NULL;
	p = calloc(1, sizeof(*p)); assert(p);
	p->capacity = len + 128;
	p->storage = calloc(1, p->capacity); assert(p->storage);
	p->data = p->storage + 64; p->len = len;
	hw.records[hw.record_count++] = p;
	return p;
}
static void brcmu_pkt_buf_free_skb(struct sk_buff *p)
{
	if (!p) return;
	assert(!p->freed && !p->owner);
	p->freed = true; hw.frees++;
}
static bool skb_queue_empty(struct sk_buff_head *q) { return q->qlen == 0; }
static struct sk_buff *skb_peek(struct sk_buff_head *q) { return q->first; }
static void skb_queue_tail(struct sk_buff_head *q, struct sk_buff *p)
{
	assert(!p->freed && !p->owner);
	p->owner = q; p->prev = q->last; p->next = NULL;
	if (q->last) q->last->next = p; else q->first = p;
	q->last = p; q->qlen++;
}
static void skb_unlink(struct sk_buff *p, struct sk_buff_head *q)
{
	assert(!p->freed && p->owner == q && q->qlen);
	if (p->prev) p->prev->next = p->next; else q->first = p->next;
	if (p->next) p->next->prev = p->prev; else q->last = p->prev;
	q->qlen--; p->owner = NULL; p->next = p->prev = NULL;
}
#define skb_queue_walk(q, p) for ((p) = (q)->first; (p); (p) = (p)->next)
#define skb_queue_walk_safe(q, p, nextp) \
	for ((p) = (q)->first; (p) && (((nextp) = (p)->next), 1); (p) = (nextp))
static u8 *skb_pull(struct sk_buff *p, unsigned len)
{
	assert(!p->freed && !hw.forbid_packet_pull);
	if (len > p->len) return NULL;
	p->data += len; p->len -= len; return p->data;
}
static u8 *skb_push(struct sk_buff *p, unsigned len)
{
	assert(!p->freed && len <= (unsigned)(p->data - p->storage));
	p->data -= len; p->len += len; return p->data;
}
static void __skb_trim(struct sk_buff *p, unsigned len)
{ assert(!p->freed && len <= p->len); p->len = len; }
static void pkt_align(struct sk_buff *p, int len, int align)
{
	unsigned pad = (uintptr_t)p->data % align;
	if (pad) { assert(skb_pull(p, align - pad)); }
	__skb_trim(p, len);
}
static void *vzalloc(unsigned len)
{
	hw.control_allocs++;
	if (hw.fail_control_alloc) return NULL;
	void *p = calloc(1, len); assert(p); hw.control_live++; return p;
}
static void vfree(void *p)
{
	if (p) { assert(hw.control_live); hw.control_live--; hw.control_frees++; free(p); }
}
static int brcmf_sdio_dcmd_resp_wake(struct brcmf_sdio *bus)
{ assert(bus == &f.bus); hw.responses++; return 0; }
static void brcmf_rx_frame(void *dev, struct sk_buff *p, bool a, bool b)
{
	assert(dev == &f && !a && !b && !hw.host && !p->owner && p->len);
	if (hw.fifo) assert(p->len == 52 && p->data[0] == 0x6b);
	hw.delivered++; brcmu_pkt_buf_free_skb(p);
}
static void brcmf_rx_event(void *dev, struct sk_buff *p)
{ brcmf_rx_frame(dev, p, false, false); }

static void transfer_ok(void)
{
	assert(hw.host == 1);
	if (f.dev.io_error) hw.reads_after_failure++;
	assert(!f.dev.io_error);
}
static int recovery_access(void)
{
	transfer_ok();
	return ++hw.recovery_ops == hw.recovery_fail_at ? hw.recovery_error : 0;
}
static void brcmf_sdiod_func0_wb(struct brcmf_sdio_dev *dev, uint addr, u8 value, int *error)
{
	assert(dev == &f.dev && addr == SDIO_CCCR_ABORT && value == 2);
	int ret = recovery_access(); if (error) *error = ret;
}
static void brcmf_sdiod_writeb(struct brcmf_sdio_dev *dev, uint addr, u8 value, int *error)
{
	assert(dev == &f.dev && addr == SBSDIO_FUNC1_FRAMECTRL && value == SFC_RF_TERM);
	*error = recovery_access(); hw.terms++;
	if (!*error) {
		hw.frame_consumed = true;
		if (hw.fifo) {
			assert(hw.fifo_pos <= hw.fifo_end);
			hw.fifo_pos = hw.fifo_end;
		}
	}
}
static u8 brcmf_sdiod_readb(struct brcmf_sdio_dev *dev, uint addr, int *error)
{
	assert(dev == &f.dev && (addr == SBSDIO_FUNC1_RFRAMEBCHI || addr == SBSDIO_FUNC1_RFRAMEBCLO));
	*error = recovery_access(); return 0; /* Do not trust zero on a failed read. */
}
static void brcmf_sdiod_writel(struct brcmf_sdio_dev *dev, u32 addr, u32 value, int *error)
{
	assert(dev == &f.dev && addr == f.core.base + SD_REG(tosbmailbox) && value == SMB_NAK);
	*error = recovery_access(); hw.naks++;
	if (hw.fifo && !*error) {
		assert(hw.fifo_pos == hw.fifo_end && !hw.nak_pending);
		hw.nak_pending = true;
	}
}
static int receive(void)
{
	transfer_ok(); assert(hw.received < 16);
	return ++hw.received == hw.receive_fail_at ? -EILSEQ : 0;
}
static int fifo_read(u8 *buffer, unsigned len)
{
	assert(hw.fifo && !hw.nak_pending);
	int ret = receive();
	unsigned consumed = ret ? hw.partial_failure_bytes : len;
	assert(consumed <= len && hw.fifo_pos + consumed <= hw.fifo_size);
	memcpy(buffer, hw.frame + hw.fifo_pos, consumed);
	hw.fifo_pos += consumed;
	return ret;
}
static int brcmf_sdiod_recv_buf(struct brcmf_sdio_dev *dev, u8 *buffer, unsigned len)
{
	assert(dev == &f.dev);
	if (hw.fifo) return fifo_read(buffer, len);
	int ret = receive(); if (ret) return ret;
	if (buffer == f.bus.rxhdr) {
		assert(len == BRCMF_FIRSTREAD);
		if (hw.frame_consumed) memset(buffer, 0, len);
		else memcpy(buffer, hw.frame, len);
		hw.frame_consumed = true;
	} else {
		assert(buffer == f.bus.rxbuf && len + BRCMF_FIRSTREAD <= sizeof(hw.frame));
		memcpy(buffer, hw.frame + BRCMF_FIRSTREAD, len);
	}
	return 0;
}
static int brcmf_sdiod_recv_pkt(struct brcmf_sdio_dev *dev, struct sk_buff *p)
{
	assert(dev == &f.dev && !p->freed);
	if (hw.fifo) return fifo_read(p->data, p->len);
	int ret = receive(); if (ret) return ret;
	unsigned offset = hw.readahead ? 0 : BRCMF_FIRSTREAD;
	assert(offset + p->len <= sizeof(hw.frame));
	memcpy(p->data, hw.frame + offset, p->len); hw.frame_consumed = true;
	return 0;
}
static int brcmf_sdiod_recv_chain(struct brcmf_sdio_dev *dev, struct sk_buff_head *q, unsigned len)
{
	assert(dev == &f.dev); int ret = receive(); if (ret) return ret;
	unsigned offset = 0; struct sk_buff *p;
	skb_queue_walk(q, p) {
		assert(offset + p->len <= sizeof(hw.frame));
		memcpy(p->data, hw.frame + offset, p->len); offset += p->len;
	}
	assert(offset == len); hw.frame_consumed = true; return 0;
}

#include "brcmfmac_rx_caller_functions.h"

static void begin(unsigned channel, unsigned length)
{
	memset(&f, 0, sizeof(f)); memset(&hw, 0, sizeof(hw));
	f.f1.num = 1; f.f2.num = 2; f.core.base = 0x18002000;
	f.dev.func1 = &f.f1; f.dev.func2 = &f.f2; f.dev.bus_if = &f.bus_if;
	f.dev.dev = &f; f.dev.state = BRCMF_SDIOD_DATA; f.bus_if.maxctl = 256;
	f.bus.sdiodev = &f.dev; f.bus.sdio_core = &f.core;
	f.bus.rxhdr = f.hdr; f.bus.rxbuf = f.control; f.bus.rxblen = 512;
	f.bus.blocksize = 64; f.bus.head_align = 4; f.bus.sgentry_align = 4;
	hw.recovery_error = -ENOMEDIUM;
	put16(hw.frame, length); put16(hw.frame + 2, (u16)~length);
	hw.frame[5] = channel; hw.frame[7] = SDPCM_HDRLEN;
	hw.frame[9] = 2; /* Valid TX window. */
	memset(hw.frame + SDPCM_HDRLEN, 0x5a, length - SDPCM_HDRLEN);
}
static void finish(void)
{
	assert(!hw.host && !hw.lock && hw.claims == hw.releases && !hw.reads_after_failure);
	assert(!f.bus.glomd && skb_queue_empty(&f.bus.glom));
	assert(hw.frees == hw.record_count && !hw.control_live);
	for (unsigned i = 0; i < hw.record_count; i++) {
		assert(hw.records[i]->freed); free(hw.records[i]->storage); free(hw.records[i]);
	}
}
static void data_case(unsigned kind, bool fatal)
{
	begin(SDPCM_DATA_CHANNEL, 96);
	if (kind == 0) hw.receive_fail_at = 1; /* Header transfer. */
	if (kind == 1) hw.frame[2] ^= 1; /* Header checksum. */
	if (kind == 2) hw.alloc_fail_at = 1;
	if (kind == 3) hw.receive_fail_at = 2; /* Frame body transfer. */
	if (kind == 4) { hw.readahead = true; f.bus.cur_read.len = 96; hw.frame[2] ^= 1; }
	if (kind == 5) { hw.readahead = true; f.bus.cur_read.len = 80; }
	if (kind == 6) { hw.readahead = true; f.bus.cur_read.len = 96; hw.frame[5] = SDPCM_CONTROL_CHANNEL; }
	if (kind == 7) hw.frame[5] = SDPCM_GLOM_CHANNEL; /* Missing descriptor. */
	if (fatal) { hw.recovery_fail_at = 1; hw.frame[6] = 6; }
	brcmf_sdio_readframes(&f.bus, 3);
	assert(f.dev.io_error == (fatal ? -ENOMEDIUM : 0));
	assert(hw.delivered == 0);
	if (fatal) assert(!f.bus.cur_read.len && !f.bus.cur_read.len_nxtfrm && !f.bus.rxpending);
	assert(hw.recovery_ops > 0);
	finish();
}
static void control_case(unsigned kind, bool fatal)
{
	begin(SDPCM_CONTROL_CHANNEL, kind == 1 ? 300 : 96);
	if (kind == 0) hw.receive_fail_at = 2;
	if (fatal) { hw.recovery_fail_at = 1; hw.frame[6] = 6; }
	brcmf_sdio_readframes(&f.bus, 3);
	assert(f.dev.io_error == (fatal ? -ENOMEDIUM : 0));
	assert(!f.bus.rxctl && !f.bus.rxlen && hw.responses == 1);
	if (fatal) assert(!f.bus.cur_read.len && !f.bus.cur_read.len_nxtfrm && !f.bus.rxpending);
	assert(hw.control_allocs == 1 && hw.control_frees == 1);
	finish();
}
enum glom_scenario {
	GLOM_TRANSFER_FAILURE,
	GLOM_BAD_SUPERFRAME_CHECKSUM,
	GLOM_BAD_SUBFRAME_CHECKSUM,
	GLOM_SINGLE_SUCCESS,
	GLOM_DESCRIPTOR_SUCCESS,
	GLOM_EMPTY_HEADER,
	GLOM_SHORT_HEADER,
	GLOM_OVERSIZED_HEADER,
	GLOM_DESCRIPTOR_IN_SUPERFRAME,
	GLOM_WRONG_CHANNEL,
	GLOM_BAD_PAYLOAD_OFFSET,
	GLOM_BAD_SECOND_SUBFRAME,
	GLOM_PAIR_SUCCESS,
};
static void glom_case(enum glom_scenario scenario, bool fatal)
{
	begin(SDPCM_GLOM_CHANNEL, 64);
	bool good = scenario == GLOM_SINGLE_SUCCESS || scenario == GLOM_DESCRIPTOR_SUCCESS ||
		scenario == GLOM_PAIR_SUCCESS;
	if (scenario == GLOM_DESCRIPTOR_SUCCESS) {
		f.bus.glomd = brcmu_pkt_buf_get_skb(2);
		put16(f.bus.glomd->data, 64);
	} else {
		struct sk_buff *p = brcmu_pkt_buf_get_skb(64); skb_queue_tail(&f.bus.glom, p);
	}
	/* Valid superframe followed by a single 52-byte subframe. */
	put16(hw.frame + 12, 52); put16(hw.frame + 14, (u16)~52);
	hw.frame[17] = SDPCM_DATA_CHANNEL; hw.frame[19] = SDPCM_HDRLEN;
	switch (scenario) {
	case GLOM_TRANSFER_FAILURE: hw.receive_fail_at = 1; break;
	case GLOM_BAD_SUPERFRAME_CHECKSUM: hw.frame[2] ^= 1; break;
	case GLOM_BAD_SUBFRAME_CHECKSUM: hw.frame[14] ^= 1; break;
	case GLOM_EMPTY_HEADER: put16(hw.frame, 0); put16(hw.frame + 2, 0); break;
	case GLOM_SHORT_HEADER: put16(hw.frame, 8); put16(hw.frame + 2, (u16)~8); break;
	case GLOM_OVERSIZED_HEADER: put16(hw.frame, 80); put16(hw.frame + 2, (u16)~80); break;
	case GLOM_DESCRIPTOR_IN_SUPERFRAME: hw.frame[5] |= 0x80; break;
	case GLOM_WRONG_CHANNEL: hw.frame[5] = SDPCM_DATA_CHANNEL; break;
	case GLOM_BAD_PAYLOAD_OFFSET: hw.frame[7] = 65; break;
	case GLOM_SINGLE_SUCCESS:
	case GLOM_DESCRIPTOR_SUCCESS:
	case GLOM_BAD_SECOND_SUBFRAME:
	case GLOM_PAIR_SUCCESS: break;
	}
	/* Invalid superframe metadata must never be used to move packet data. */
	if (!good && scenario != GLOM_TRANSFER_FAILURE && scenario != GLOM_BAD_SUBFRAME_CHECKSUM &&
	    scenario != GLOM_BAD_SECOND_SUBFRAME) hw.forbid_packet_pull = true;
	if (scenario == GLOM_BAD_SECOND_SUBFRAME || scenario == GLOM_PAIR_SUCCESS) {
		struct sk_buff *p = brcmu_pkt_buf_get_skb(64); skb_queue_tail(&f.bus.glom, p);
		put16(hw.frame, 128); put16(hw.frame + 2, (u16)~128);
		put16(hw.frame + 64, 64); put16(hw.frame + 66, (u16)~64);
		hw.frame[68] = 1; hw.frame[69] = SDPCM_EVENT_CHANNEL; hw.frame[71] = SDPCM_HDRLEN;
		if (scenario == GLOM_BAD_SECOND_SUBFRAME) hw.frame[66] ^= 1;
	}
	if (fatal) hw.recovery_fail_at = 1;
	brcmf_sdio_readframes(&f.bus, 3);
	assert(f.dev.io_error == (fatal ? -ENOMEDIUM : 0));
	assert(hw.delivered == (good ? (scenario == GLOM_PAIR_SUCCESS ? 2u : 1u) : 0u));
	assert(f.bus.sdcnt.rxglomfail == (unsigned)!good);
	finish();
}
static void descriptor_case(unsigned kind)
{
	begin(SDPCM_GLOM_CHANNEL, 64);
	f.bus.glomd = brcmu_pkt_buf_get_skb(kind == 0 ? 0 : kind == 1 ? 3 : 4);
	put16(f.bus.glomd->data, kind == 2 ? 8 : 64);
	put16(f.bus.glomd->data + 2, kind == 3 ? 8 : 64);
	if (kind == 4) hw.alloc_fail_at = 2;
	if (kind == 5) hw.alloc_fail_at = 3;
	assert(!brcmf_sdio_rxglom(&f.bus, 0));
	assert(!f.dev.io_error && !hw.received && !hw.delivered);
	finish();
}
static void previous_error(void)
{
	begin(SDPCM_DATA_CHANNEL, 96);
	f.dev.io_error = -EIO; f.bus.cur_read.len = 96; f.bus.cur_read.len_nxtfrm = 7;
	assert(!brcmf_sdio_readframes(&f.bus, 3));
	assert(f.dev.io_error == -EIO && !hw.received && !hw.recovery_ops);
	assert(!f.bus.cur_read.len && !f.bus.cur_read.len_nxtfrm && !f.bus.rxpending);
	finish();
}
static void success(unsigned kind)
{
	begin(kind == 1 ? SDPCM_CONTROL_CHANNEL : SDPCM_DATA_CHANNEL, 96);
	if (kind == 2) { hw.readahead = true; f.bus.cur_read.len = 96; }
	brcmf_sdio_readframes(&f.bus, 3);
	assert(!f.dev.io_error && !hw.recovery_ops);
	if (kind == 1) {
		assert(f.bus.rxctl && f.bus.rxlen == 84 && hw.control_live == 1);
		assert(f.bus.rxctl[0] == 0x5a); vfree(f.bus.rxctl_orig);
	} else assert(hw.delivered == 1);
	finish();
}

static void control_fifo_begin(bool short_frame, bool busy, bool hint)
{
	begin(SDPCM_CONTROL_CHANNEL, short_frame ? 16 : 96);
	hw.fifo = true; hw.fifo_end = short_frame ? BRCMF_FIRSTREAD : 96;
	hw.fifo_size = hw.fifo_end + 64;
	hw.frame[6] = hint ? 4 : 0;
	u8 *next = hw.frame + hw.fifo_end;
	put16(next, 64); put16(next + 2, (u16)~64);
	next[4] = 1; next[5] = SDPCM_DATA_CHANNEL; next[7] = SDPCM_HDRLEN;
	next[9] = 2; memset(next + SDPCM_HDRLEN, 0x6b, 64 - SDPCM_HDRLEN);
	if (busy) {
		f.bus.rxctl_orig = vzalloc(32); f.bus.rxctl = f.bus.rxctl_orig + 12;
		f.bus.rxlen = 20; memset(f.bus.rxctl, 0x39, 20);
	}
}
static void consume_response(void)
{
	if (!f.bus.rxctl) return;
	vfree(f.bus.rxctl_orig); f.bus.rxctl_orig = f.bus.rxctl = NULL; f.bus.rxlen = 0;
}
static void pending_response_unchanged(u8 *original)
{
	assert(f.bus.rxctl == original);
	if (original) assert(f.bus.rxlen == 20 && original[0] == 0x39 && original[19] == 0x39);
	else assert(!f.bus.rxlen);
}
static void nak_handled_boundary(void)
{
	/* Firmware replay / mailbox acknowledgement is a scripted boundary here. */
	assert(f.bus.rxskip && hw.nak_pending && !f.dev.io_error);
	f.bus.rxskip = false; hw.nak_pending = false; hw.fifo_pos = 0;
}
static void receive_retry_and_next(bool short_frame)
{
	nak_handled_boundary(); hw.fail_control_alloc = false; f.bus.rxblen = 512;
	hw.receive_fail_at = 0;
	unsigned naks = hw.naks;
	brcmf_sdio_readframes(&f.bus, 1);
	assert(!f.dev.io_error && !f.bus.rxskip && hw.naks == naks);
	assert(hw.fifo_pos == hw.fifo_end && f.bus.rxctl);
	assert(f.bus.rxlen == (short_frame ? 4u : 84u) && f.bus.rxctl[0] == 0x5a);
	consume_response();
	brcmf_sdio_readframes(&f.bus, 1);
	assert(hw.fifo_pos == hw.fifo_size && hw.delivered == 1 && !f.dev.io_error);
}
static void control_fifo_failure(unsigned index, bool body_failure)
{
	bool short_frame = !body_failure && (index & 1);
	bool busy = body_failure ? (index & 1) : (index & 2);
	bool no_buffer = !body_failure && (index & 4);
	unsigned fault = body_failure ? index / 2 : index / 8;
	control_fifo_begin(short_frame, busy, true);
	u8 *original = f.bus.rxctl;
	if (body_failure) {
		hw.receive_fail_at = 2; hw.partial_failure_bytes = 8;
	} else if (no_buffer) f.bus.rxblen = 0;
	else hw.fail_control_alloc = true;
	hw.recovery_fail_at = fault;
	brcmf_sdio_readframes(&f.bus, 1);
	fprintf(stderr, "FIFO=%u/%u next=%u recovery=%u NAK=%u skip=%u errno=%d\n",
		hw.fifo_pos, hw.fifo_end, f.bus.cur_read.len, hw.recovery_ops,
		hw.naks, f.bus.rxskip, f.dev.io_error);
	pending_response_unchanged(original);
	assert(hw.responses == 1 && hw.control_live == (unsigned)busy);
	assert(!hw.delivered);
	assert(f.dev.io_error == (fault ? -ENOMEDIUM : 0));
	assert(!f.bus.cur_read.len && !f.bus.cur_read.len_nxtfrm);
	if (!fault) {
		assert(hw.fifo_pos == hw.fifo_end && hw.naks == 1 && f.bus.rxskip);
		unsigned reads = hw.received, ops = hw.recovery_ops;
		brcmf_sdio_readframes(&f.bus, 1); /* Wait for NAK acknowledgement. */
		assert(hw.received == reads && hw.recovery_ops == ops);
		consume_response(); receive_retry_and_next(short_frame);
	} else {
		assert(!f.bus.rxskip && !f.bus.rxpending && hw.recovery_ops == fault);
		unsigned reads = hw.received;
		brcmf_sdio_readframes(&f.bus, 1);
		assert(hw.received == reads && hw.recovery_ops == fault);
		consume_response();
	}
	assert(f.bus.sdcnt.rxc_errors == 1);
	finish();
}
static void control_fifo_success(unsigned index)
{
	bool short_frame = index & 1, busy = index & 2, hint = index & 4;
	control_fifo_begin(short_frame, busy, hint);
	u8 *original = f.bus.rxctl;
	brcmf_sdio_readframes(&f.bus, 1);
	assert(hw.fifo_pos == hw.fifo_end && hw.responses == 1 && !hw.recovery_ops);
	assert(!f.dev.io_error && !f.bus.sdcnt.rxc_errors && !f.bus.cur_read.len_nxtfrm);
	assert(f.bus.cur_read.len == (hint ? 64u : 0u));
	if (busy) pending_response_unchanged(original);
	else assert(f.bus.rxctl && f.bus.rxctl[0] == 0x5a && f.bus.rxlen == (short_frame ? 4u : 84u));
	consume_response();
	brcmf_sdio_readframes(&f.bus, 1);
	assert(hw.fifo_pos == hw.fifo_size && hw.delivered == 1 && !hw.recovery_ops);
	finish();
}
static void control_fifo_repeated(unsigned index)
{
	bool short_frame = index != 0;
	control_fifo_begin(short_frame, false, true); hw.fail_control_alloc = true;
	for (unsigned i = 0; i < 3; i++) {
		brcmf_sdio_readframes(&f.bus, 1);
		assert(!f.dev.io_error && !f.bus.rxctl && !hw.control_live);
		assert(!f.bus.cur_read.len && !f.bus.cur_read.len_nxtfrm);
		assert(hw.naks == i + 1 && f.bus.rxskip && hw.fifo_pos == hw.fifo_end);
		if (i < 2) nak_handled_boundary();
	}
	assert(f.bus.sdcnt.rxc_errors == 3);
	receive_retry_and_next(short_frame); finish();
}

int main(int argc, char **argv)
{
	static const enum glom_scenario glom_errors[] = {
		GLOM_TRANSFER_FAILURE, GLOM_BAD_SUPERFRAME_CHECKSUM, GLOM_BAD_SUBFRAME_CHECKSUM,
	};
	static const enum glom_scenario glom_valid[] = { GLOM_SINGLE_SUCCESS, GLOM_DESCRIPTOR_SUCCESS };
	static const enum glom_scenario glom_headers[] = {
		GLOM_EMPTY_HEADER, GLOM_SHORT_HEADER, GLOM_OVERSIZED_HEADER,
		GLOM_DESCRIPTOR_IN_SUPERFRAME, GLOM_WRONG_CHANNEL, GLOM_BAD_PAYLOAD_OFFSET,
	};
	assert(argc == 3);
	unsigned index = strtoul(argv[2], NULL, 10);
	if (!strcmp(argv[1], "data")) data_case(index / 2, index & 1);
	else if (!strcmp(argv[1], "control")) control_case(index / 2, index & 1);
	else if (!strcmp(argv[1], "glom")) {
		assert(index < 2 * ARRAY_SIZE(glom_errors)); glom_case(glom_errors[index / 2], index & 1);
	}
	else if (!strcmp(argv[1], "success")) success(index);
	else if (!strcmp(argv[1], "glom_success")) {
		assert(index < ARRAY_SIZE(glom_valid)); glom_case(glom_valid[index], false);
	}
	else if (!strcmp(argv[1], "glom_header")) {
		assert(index < 2 * ARRAY_SIZE(glom_headers)); glom_case(glom_headers[index / 2], index & 1);
	}
	else if (!strcmp(argv[1], "glom_pair")) glom_case(GLOM_BAD_SECOND_SUBFRAME, index & 1);
	else if (!strcmp(argv[1], "glom_pair_success")) glom_case(GLOM_PAIR_SUCCESS, false);
	else if (!strcmp(argv[1], "descriptor")) descriptor_case(index);
	else if (!strcmp(argv[1], "prior_error")) previous_error();
	else if (!strcmp(argv[1], "ctl_oom")) control_fifo_failure(index, false);
	else if (!strcmp(argv[1], "ctl_body")) control_fifo_failure(index, true);
	else if (!strcmp(argv[1], "ctl_success")) control_fifo_success(index);
	else if (!strcmp(argv[1], "ctl_retries")) control_fifo_repeated(index);
	else assert(false);
	printf("%s %u passed\n", argv[1], index);
	return 0;
}
