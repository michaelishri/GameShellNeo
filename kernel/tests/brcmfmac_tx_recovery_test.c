/* SPDX-License-Identifier: ISC */
/* Actual TX recovery/callers; synchronous transport and packet-prep seams. */
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
typedef unsigned uint;
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x, y) ((x) = (y))
#define min_t(t, a, b) ((t)(a) < (t)(b) ? (t)(a) : (t)(b))
#define brcmf_dbg(...) ((void)0)
#define brcmf_err(...) ((void)0)
#define brcmf_dbg_hex_dump(...) ((void)0)
#define atomic_set(x, y) (*(x) = (y))
#include "brcmfmac_tx_types.h"

enum { BRCMF_SDIOD_DOWN, BRCMF_SDIOD_DATA };
struct sdio_func { unsigned num; };
struct brcmf_core { u32 base; };
struct sk_buff {
	struct sk_buff *next;
	bool queued, prepared, completed, success;
};
struct sk_buff_head { struct sk_buff *first, *last; unsigned qlen; };
struct pktq { struct sk_buff_head queue; };
struct brcmf_sdio_dev {
	struct sdio_func *func1, *func2;
	void *dev;
	int io_error;
	unsigned state, txglomsz;
};
struct brcmf_sdio {
	struct brcmf_sdio_dev *sdiodev;
	struct brcmf_core *sdio_core;
	struct brcmf_sdio_count sdcnt;
	struct pktq txq;
	unsigned txq_lock, ipend, hostintmask, flowcontrol;
	unsigned tx_hdrlen, head_align, blocksize, roundup;
	u8 tx_seq, tx_max;
	bool txglom, txoff, intr, ctrl_frame_stat;
};
static struct {
	struct brcmf_sdio bus;
	struct brcmf_sdio_dev dev;
	struct brcmf_core core;
	struct sdio_func f1, f2;
	struct sk_buff packets[4];
	u8 control[256];
} f;
static struct {
	unsigned host, claims, releases, locked;
	unsigned operations, current_ops, recoveries, count_reads, empty_poll;
	unsigned fail_at, sends, send_failures, status_reads, packed, hwhdr;
	unsigned preps, postps, completed, unblocked;
	unsigned status_fail_at;
	int error, prep_error, inject_after_prep;
	int status_error, inject_poll_claim;
	u32 status_value;
	bool failed_access;
	u8 failed_value;
} hw;
static void access_ok(void)
{
	assert(hw.host == 1 && !f.dev.io_error);
	if (hw.failed_access) fprintf(stderr, "I/O after recovery transport error\n");
	assert(!hw.failed_access);
}
static int recovery_access(void)
{
	access_ok(); hw.operations++; hw.current_ops++;
	int error = hw.current_ops == hw.fail_at ? hw.error : 0;
	fprintf(stderr, "recovery op=%u error=%d\n", hw.current_ops, error);
	if (error) hw.failed_access = true;
	return error;
}
static void sdio_claim_host(struct sdio_func *func)
{
	assert(func == &f.f1 && !hw.host && !hw.locked); hw.host++; hw.claims++;
	if (hw.inject_poll_claim && hw.claims == 2) f.dev.io_error = hw.inject_poll_claim;
}
static void sdio_release_host(struct sdio_func *func)
{
	assert(func == &f.f1 && hw.host == 1);
	if (hw.failed_access && hw.status_reads) assert(f.dev.io_error == hw.status_error);
	hw.host--; hw.releases++;
}
static void brcmf_sdiod_func0_wb(struct brcmf_sdio_dev *dev, uint reg, u8 val, int *error)
{
	assert(dev == &f.dev && reg == SDIO_CCCR_ABORT && val == f.f2.num);
	hw.current_ops = 0; hw.count_reads = 0; hw.recoveries++;
	int ret = recovery_access(); if (error) *error = ret;
}
static void brcmf_sdiod_writeb(struct brcmf_sdio_dev *dev, uint reg, u8 val, int *error)
{
	assert(dev == &f.dev && reg == SBSDIO_FUNC1_FRAMECTRL && val == SFC_WF_TERM);
	int ret = recovery_access(); if (error) *error = ret;
}
static u8 brcmf_sdiod_readb(struct brcmf_sdio_dev *dev, uint reg, int *error)
{
	assert(dev == &f.dev);
	assert(reg == (hw.count_reads % 2 ? SBSDIO_FUNC1_WFRAMEBCLO : SBSDIO_FUNC1_WFRAMEBCHI));
	int ret = recovery_access(); if (error) *error = ret;
	unsigned poll = hw.count_reads++ / 2 + 1;
	return ret ? hw.failed_value : poll >= hw.empty_poll ? 0 : 1;
}
static u32 brcmf_sdiod_readl(struct brcmf_sdio_dev *dev, uint reg, int *error)
{
	assert(dev == &f.dev && reg == f.core.base + SD_REG(intstatus));
	access_ok(); hw.status_reads++;
	*error = hw.status_reads == hw.status_fail_at ? hw.status_error : 0;
	fprintf(stderr, "status op=%u error=%d value=%u\n", hw.status_reads, *error, hw.status_value);
	if (*error) hw.failed_access = true;
	return hw.status_value;
}
static int send(void)
{
	access_ok(); assert(++hw.sends <= 8);
	fprintf(stderr, "send=%u\n", hw.sends);
	return hw.sends <= hw.send_failures ? -EIO : 0;
}
static int brcmf_sdiod_send_buf(struct brcmf_sdio_dev *dev, u8 *frame, u16 len)
{
	assert(dev == &f.dev && frame >= f.control && frame + len <= f.control + sizeof(f.control));
	assert(hw.packed == 1); return send();
}
static int brcmf_sdiod_send_pkt(struct brcmf_sdio_dev *dev, struct sk_buff_head *queue)
{ assert(dev == &f.dev && queue->qlen); return send(); }
static void brcmf_sdio_hdpack(struct brcmf_sdio *bus, u8 *frame, struct brcmf_sdio_hdrinfo *info)
{
	assert(bus == &f.bus && frame >= f.control && !f.dev.io_error);
	assert(info->channel == SDPCM_CONTROL_CHANNEL && info->seq_num == bus->tx_seq && info->lastfrm);
	assert(info->len >= info->dat_offset && info->dat_offset >= bus->tx_hdrlen); hw.packed++;
}
static void brcmf_sdio_update_hwhdr(u8 *frame, u16 len)
{ assert(frame >= f.control && len <= sizeof(f.control)); hw.hwhdr++; }
static void __skb_queue_head_init(struct sk_buff_head *queue) { memset(queue, 0, sizeof(*queue)); }
static void __skb_queue_tail(struct sk_buff_head *queue, struct sk_buff *packet)
{
	assert(!packet->queued && !packet->completed); packet->queued = true; packet->next = NULL;
	if (queue->last) queue->last->next = packet; else queue->first = packet;
	queue->last = packet; queue->qlen++;
}
static void __skb_unlink(struct sk_buff *packet, struct sk_buff_head *queue)
{
	assert(queue->first == packet && packet->queued && queue->qlen);
	queue->first = packet->next; if (!--queue->qlen) queue->last = NULL;
	packet->next = NULL; packet->queued = false;
}
#define skb_queue_walk_safe(q, p, tmp) \
	for ((p) = (q)->first; (p) && ((tmp) = (p)->next, true); (p) = (tmp))
static unsigned brcmu_pktq_mlen(struct pktq *queue, uint mask)
{ assert(mask); return queue->queue.qlen; }
static unsigned pktq_len(struct pktq *queue) { return queue->queue.qlen; }
static struct sk_buff *brcmu_pktq_mdeq(struct pktq *queue, uint map, int *prec)
{
	assert(map && hw.locked); *prec = 0;
	struct sk_buff *packet = queue->queue.first;
	if (packet) __skb_unlink(packet, &queue->queue);
	return packet;
}
#define spin_lock_bh(lock) do { (void)(lock); assert(!hw.locked); hw.locked++; } while (0)
#define spin_unlock_bh(lock) do { (void)(lock); assert(hw.locked == 1); hw.locked--; } while (0)
static int brcmf_sdio_txpkt_prep(struct brcmf_sdio *bus, struct sk_buff_head *queue, uint channel)
{
	assert(bus == &f.bus && channel == SDPCM_DATA_CHANNEL && !hw.host);
	hw.preps++;
	for (struct sk_buff *p = queue->first; p; p = p->next) {
		assert(!p->prepared && !p->completed); p->prepared = true;
	}
	if (hw.inject_after_prep) f.dev.io_error = hw.inject_after_prep;
	return hw.prep_error;
}
static void brcmf_sdio_txpkt_postp(struct brcmf_sdio *bus, struct sk_buff_head *queue)
{
	assert(bus == &f.bus && !hw.host); hw.postps++;
	for (struct sk_buff *p = queue->first; p; p = p->next) {
		assert(p->prepared && !p->completed); p->prepared = false;
	}
}
static void brcmf_proto_bcdc_txcomplete(void *dev, struct sk_buff *packet, bool success)
{
	assert(dev == &f && !hw.host && !packet->prepared && !packet->queued && !packet->completed);
	packet->completed = true; packet->success = success; hw.completed++;
}
static void brcmf_proto_bcdc_txflowblock(void *dev, bool blocked)
{ assert(dev == &f && !blocked && !f.dev.io_error); hw.unblocked++; }

#include "brcmfmac_tx_functions.h"

static void begin(void)
{
	memset(&f, 0, sizeof(f)); memset(&hw, 0, sizeof(hw));
	f.f1.num = 1; f.f2.num = 2; f.core.base = 0x18002000;
	f.dev.func1 = &f.f1; f.dev.func2 = &f.f2; f.dev.dev = &f;
	f.dev.state = BRCMF_SDIOD_DATA; f.dev.txglomsz = 2;
	f.bus.sdiodev = &f.dev; f.bus.sdio_core = &f.core; f.bus.tx_max = 16;
	f.bus.tx_hdrlen = 12; f.bus.head_align = 4; f.bus.blocksize = 64;
	f.bus.roundup = 32; f.bus.intr = true; f.bus.hostintmask = HOSTINTMASK;
	hw.error = -EILSEQ; hw.empty_poll = 1; hw.status_value = I_HMB_FRAME_IND;
}
static void finish(void)
{
	assert(!hw.host && !hw.locked && hw.claims == hw.releases && hw.preps == hw.postps);
}
enum recovery_fault {
	RECOVERY_NONE,
	RECOVERY_ABORT,
	RECOVERY_TERMINATE,
	RECOVERY_COUNT_HIGH,
	RECOVERY_COUNT_LOW,
	RECOVERY_EXHAUSTED,
};
static const enum recovery_fault recovery_failures[] = {
	RECOVERY_ABORT, RECOVERY_TERMINATE, RECOVERY_COUNT_HIGH,
	RECOVERY_COUNT_LOW, RECOVERY_EXHAUSTED,
};
static int recovery_error(enum recovery_fault fault)
{ return fault == RECOVERY_EXHAUSTED ? -ETIMEDOUT : fault != RECOVERY_NONE ? hw.error : 0; }
static void choose_fault(enum recovery_fault fault)
{
	hw.fail_at = 0; hw.empty_poll = 1;
	switch (fault) {
	case RECOVERY_NONE: break;
	case RECOVERY_ABORT: hw.fail_at = 1; break;
	case RECOVERY_TERMINATE: hw.fail_at = 2; break;
	case RECOVERY_COUNT_HIGH: hw.fail_at = 3; break;
	case RECOVERY_COUNT_LOW: hw.fail_at = 4; break;
	case RECOVERY_EXHAUSTED: hw.empty_poll = 4; break;
	default: assert(false);
	}
}
static void check_helper(int expected, unsigned operations)
{
	sdio_claim_host(&f.f1); brcmf_sdio_txfail(&f.bus); sdio_release_host(&f.f1);
	fprintf(stderr, "latched=%d expected=%d ops=%u\n", f.dev.io_error, expected, hw.operations);
	assert(f.dev.io_error == expected);
	assert(hw.operations == operations);
	assert(f.bus.sdcnt.tx_sderrs == (unsigned)(operations != 0));
	assert(f.bus.sdcnt.f1regdata == (hw.operations ? hw.operations - 1 : 0));
	if (expected) {
		unsigned previous = hw.operations;
		sdio_claim_host(&f.f1); brcmf_sdio_txfail(&f.bus); sdio_release_host(&f.f1);
		assert(hw.operations == previous && f.dev.io_error == expected);
	}
	finish();
}
static void helper_failure(unsigned index)
{
	begin(); assert(index < 24);
	const int errors[] = {-EIO, -ETIMEDOUT, -EILSEQ};
	choose_fault(recovery_failures[index / 6]); hw.error = errors[index / 2 % 3];
	hw.failed_value = index & 1 ? 0xff : 0;
	check_helper(hw.error, hw.fail_at);
}
static void helper_success(unsigned index)
{
	begin(); assert(index < 3); hw.empty_poll = index + 1;
	check_helper(0, 2 + 2 * hw.empty_poll);
}
static void helper_exhaustion(unsigned index)
{
	begin(); assert(index == 0); choose_fault(RECOVERY_EXHAUSTED);
	check_helper(-ETIMEDOUT, 8);
}
static void helper_prior(unsigned index)
{
	begin(); assert(index < 3); f.dev.io_error = -(int)(index + 1);
	check_helper(f.dev.io_error, 0);
}
static void control_failure(unsigned index)
{
	begin(); assert(index < 10); enum recovery_fault fault = recovery_failures[index / 2];
	choose_fault(fault); hw.failed_value = index & 1 ? 0xff : 0;
	hw.send_failures = 1;
	sdio_claim_host(&f.f1);
	int ret = brcmf_sdio_tx_ctrlframe(&f.bus, f.control + 32, 32);
	sdio_release_host(&f.f1);
	assert(f.dev.io_error == recovery_error(fault) && ret == f.dev.io_error);
	assert(hw.sends == 1 && hw.recoveries == 1 && !f.bus.tx_seq);
	finish();
}
static void control_success(unsigned index)
{
	begin(); assert(index < 32);
	hw.send_failures = index / 8; f.bus.txglom = index & 4; unsigned alignment = index & 3;
	hw.empty_poll = 3;
	sdio_claim_host(&f.f1);
	int ret = brcmf_sdio_tx_ctrlframe(&f.bus, f.control + 32 + alignment, 80);
	sdio_release_host(&f.f1);
	unsigned failures = hw.send_failures;
	assert(!f.dev.io_error && ret == (failures == 3 ? -EIO : 0));
	assert(hw.sends == (failures == 3 ? 3 : failures + 1));
	assert(hw.recoveries == failures && hw.operations == failures * 8);
	assert(f.bus.tx_seq == (failures < 3) && hw.hwhdr == (unsigned)f.bus.txglom);
	finish();
}
static void control_prior(unsigned index)
{
	begin(); assert(index < 3); f.dev.io_error = -(int)(index + 1);
	sdio_claim_host(&f.f1);
	assert(brcmf_sdio_tx_ctrlframe(&f.bus, f.control + 32, 32) == f.dev.io_error);
	sdio_release_host(&f.f1); assert(!hw.packed && !hw.sends && !hw.operations); finish();
}
static void data_case(unsigned index, bool fatal)
{
	begin(); assert(index < (fatal ? 20u : 8u));
	f.bus.intr = !(index & 1); f.bus.txglom = index & 2; f.bus.txoff = true;
	enum recovery_fault fault = fatal ? recovery_failures[index / 4] : RECOVERY_NONE;
	choose_fault(fault); hw.send_failures = fatal ? 1 : index / 4;
	if (!fatal) hw.empty_poll = 3;
	for (unsigned i = 0; i < 3; i++) __skb_queue_tail(&f.bus.txq.queue, &f.packets[i]);
	unsigned count = brcmf_sdio_sendfromq(&f.bus, 3), batch = f.bus.txglom ? 2 : 1;
	assert(f.dev.io_error == recovery_error(fault));
	assert(count == (fatal ? batch : 3) && hw.completed == count);
	assert(f.bus.txq.queue.qlen == 3 - count);
	assert(hw.sends == (fatal ? 1 : f.bus.txglom ? 2 : 3));
	assert(hw.recoveries == hw.send_failures);
	assert(hw.status_reads == (!fatal && !f.bus.intr ? hw.sends : 0));
	if (fatal) assert(hw.claims == 1 && hw.releases == 1);
	assert(hw.unblocked == (unsigned)!fatal && f.bus.txoff == fatal);
	unsigned successes = 0;
	for (unsigned i = 0; i < 3; i++) {
		assert(f.packets[i].completed == (i < count));
		assert(f.packets[i].queued == (i >= count));
		assert(!f.packets[i].prepared);
		assert(f.packets[i].success == (i < count && (!hw.send_failures || i >= batch)));
		successes += f.packets[i].success;
	}
	assert(f.bus.tx_seq == successes);
	if (fatal) {
		assert(!brcmf_sdio_sendfromq(&f.bus, 3));
		assert(hw.completed == batch && hw.sends == 1 && !hw.status_reads);
	}
	finish();
}
static void data_local(unsigned index)
{
	begin(); assert(index < 3);
	struct sk_buff_head queue; __skb_queue_head_init(&queue);
	__skb_queue_tail(&queue, &f.packets[0]);
	if (index == 0) hw.prep_error = -ENOMEM;
	if (index == 1) f.dev.io_error = -EILSEQ;
	if (index == 2) hw.inject_after_prep = -ENOMEDIUM;
	int ret = brcmf_sdio_txpkt(&f.bus, &queue, SDPCM_DATA_CHANNEL);
	assert(ret == (index == 0 ? -ENOMEM : index == 1 ? -EILSEQ : -ENOMEDIUM));
	assert(!hw.sends && !hw.operations && !queue.qlen && hw.completed == 1);
	assert(!f.packets[0].success && !f.bus.tx_seq); finish();
}
enum poll_scenario { POLL_FAILURE, POLL_SUCCESS, POLL_PRIOR, POLL_INTERRUPT };
static void poll_case(unsigned index, enum poll_scenario scenario)
{
	const int errors[] = {-EIO, -ETIMEDOUT, -EILSEQ};
	const u32 status[] = {0, UINT32_MAX, I_HMB_FRAME_IND};
	begin(); f.bus.intr = scenario == POLL_INTERRUPT; f.bus.txoff = true;
	f.bus.txglom = index & 1;
	unsigned batch = f.bus.txglom ? 2 : 1, expected_polls;
	if (scenario == POLL_FAILURE) {
		assert(index < 72);
		hw.send_failures = index / 2 % 2; hw.status_fail_at = index / 4 % 2 + 1;
		hw.status_value = status[index / 8 % 3]; hw.status_error = errors[index / 24];
	} else if (scenario == POLL_SUCCESS) {
		assert(index < 12); hw.send_failures = index / 2 % 2;
		hw.status_value = status[index / 4];
	} else if (scenario == POLL_PRIOR) {
		assert(index < 6); hw.inject_poll_claim = errors[index / 2];
	} else {
		assert(index < 18); hw.status_error = errors[index / 6];
		hw.status_value = status[index / 2 % 3]; hw.status_fail_at = 1;
	}
	unsigned poll_failure_at = hw.status_fail_at;
	hw.empty_poll = 3;
	for (unsigned i = 0; i < 3; i++) __skb_queue_tail(&f.bus.txq.queue, &f.packets[i]);
	unsigned count = brcmf_sdio_sendfromq(&f.bus, 3);
	bool fatal = scenario == POLL_FAILURE || scenario == POLL_PRIOR;
	unsigned expected = scenario == POLL_FAILURE ? min_t(unsigned, 3, batch * poll_failure_at) :
			    scenario == POLL_PRIOR ? batch : 3;
	expected_polls = scenario == POLL_PRIOR || scenario == POLL_INTERRUPT ? 0 :
			 scenario == POLL_FAILURE ? poll_failure_at : f.bus.txglom ? 2 : 3;
	int error = scenario == POLL_FAILURE ? hw.status_error :
		    scenario == POLL_PRIOR ? hw.inject_poll_claim : 0;
	assert(f.dev.io_error == error && count == expected && hw.completed == expected);
	assert(hw.status_reads == expected_polls && hw.sends == (count + batch - 1) / batch);
	assert(f.bus.sdcnt.f2txdata == hw.sends + hw.status_reads);
	assert(hw.recoveries == hw.send_failures);
	assert(f.bus.txq.queue.qlen == 3 - expected && hw.unblocked == (unsigned)!fatal && f.bus.txoff == fatal);
	assert(f.bus.ipend == (unsigned)(!!(hw.status_value & HOSTINTMASK) &&
		(expected_polls > (scenario == POLL_FAILURE ? 1u : 0u))));
	unsigned successes = 0;
	for (unsigned i = 0; i < 3; i++) {
		assert(f.packets[i].completed == (i < expected) && f.packets[i].queued == (i >= expected));
		assert(!f.packets[i].prepared);
		assert(f.packets[i].success == (i < expected && (!hw.send_failures || i >= batch)));
		successes += f.packets[i].success;
	}
	assert(f.bus.tx_seq == successes);
	if (fatal) {
		unsigned claims = hw.claims, sends = hw.sends;
		assert(!brcmf_sdio_sendfromq(&f.bus, 3));
		assert(hw.claims == claims && hw.sends == sends && hw.completed == expected);
	}
	finish();
}
int main(int argc, char **argv)
{
	assert(argc == 3); unsigned index = strtoul(argv[2], NULL, 10);
	if (!strcmp(argv[1], "helper_failure")) helper_failure(index);
	else if (!strcmp(argv[1], "helper_success")) helper_success(index);
	else if (!strcmp(argv[1], "helper_exhaustion")) helper_exhaustion(index);
	else if (!strcmp(argv[1], "helper_prior")) helper_prior(index);
	else if (!strcmp(argv[1], "control_failure")) control_failure(index);
	else if (!strcmp(argv[1], "control_success")) control_success(index);
	else if (!strcmp(argv[1], "control_prior")) control_prior(index);
	else if (!strcmp(argv[1], "data_failure")) data_case(index, true);
	else if (!strcmp(argv[1], "data_success")) data_case(index, false);
	else if (!strcmp(argv[1], "data_local")) data_local(index);
	else if (!strcmp(argv[1], "poll_failure")) poll_case(index, POLL_FAILURE);
	else if (!strcmp(argv[1], "poll_success")) poll_case(index, POLL_SUCCESS);
	else if (!strcmp(argv[1], "poll_prior")) poll_case(index, POLL_PRIOR);
	else if (!strcmp(argv[1], "poll_interrupt")) poll_case(index, POLL_INTERRUPT);
	else assert(false);
	printf("%s %u passed\n", argv[1], index); return 0;
}
