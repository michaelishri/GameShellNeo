/* Actual driver bodies; finite, scripted wait/firmware seams, no radio access. */
#include <arpa/inet.h>
#include <endian.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint16_t __le16;
typedef uint32_t __le32;
#define ETH_ALEN 6
#define WLAN_MAX_KEY_LEN 32
#define ETH_P_PAE 0x888e
#define cpu_to_le16(value) htole16(value)
#define cpu_to_le32(value) htole32(value)
#define msecs_to_jiffies(value) (value)
#include "eapol_types.h"

struct brcmf_if;
struct brcmf_pub { unsigned errors; };
struct net_device { struct { unsigned tx_errors; } stats; };
struct wait_queue {
    struct brcmf_if *owner;
    bool active;
    unsigned waits, wakes;
};
typedef struct { int value; } atomic_t;
struct brcmf_if {
    struct brcmf_pub *drvr;
    struct net_device *ndev;
    atomic_t pend_8021x_cnt;
    struct wait_queue pend_8021x_wait;
};
struct ethhdr { unsigned char dest[6], source[6]; u16 h_proto; };
struct sk_buff { unsigned char *data; unsigned frees; };
struct packet { struct ethhdr eth; struct sk_buff skb; };

static struct brcmf_if interfaces[2];
static struct brcmf_pub pubs[2];
static struct net_device devices[2];
static struct packet packets[4];
static struct packet *progress[4];
static unsigned progress_count, barriers, firmware_calls;
static int firmware_error;
static bool progress_success;
static struct brcmf_wsec_key_le captured_key;
static const char *current_case;

void brcmf_txfinalize(struct brcmf_if *ifp, struct sk_buff *txp, bool success);
static int atomic_read(atomic_t *value) { return value->value; }
static void __attribute__((unused)) atomic_set(atomic_t *value, int count) { value->value = count; }
static void __attribute__((unused)) atomic_dec(atomic_t *value) { value->value--; }
static void completion_barrier(void) { barriers++; }
#define smp_mb__after_atomic() completion_barrier()
static bool waitqueue_active(struct wait_queue *queue) { return queue->active; }
static void wake_up(struct wait_queue *queue) { queue->wakes++; }
static void brcmu_pkt_buf_free_skb(struct sk_buff *packet)
{
    if (packet->frees++)
        abort();
}
#define bphy_err(driver, ...) ((driver)->errors++)

static void advance_wait(struct wait_queue *queue)
{
    for (unsigned i = 0; i < progress_count; i++)
        brcmf_txfinalize(queue->owner, &progress[i]->skb, progress_success);
    progress_count = 0;
}

/* Evaluate the original predicate both before and after scripted completions.
 * No wall-clock sleep or Linux waitqueue ordering is inferred from this seam.
 */
#define wait_event_timeout(queue, condition, budget) ({ \
    unsigned wait_result; \
    if ((budget) != 950) abort(); \
    (queue).waits++; \
    if (condition) { \
        wait_result = 1; \
    } else { \
        (queue).active = true; \
        advance_wait(&(queue)); \
        wait_result = (condition) ? 1 : 0; \
        (queue).active = false; \
    } \
    wait_result; \
})

static int brcmf_fil_bsscfg_data_set(struct brcmf_if *ifp, const char *name,
                                    const void *data, unsigned length)
{
    if (!ifp || strcmp(name, "wsec_key") || length != sizeof(captured_key))
        abort();
    firmware_calls++;
    memcpy(&captured_key, data, sizeof(captured_key));
    return firmware_error;
}

#include "eapol_functions.h"

static int check(const char *assertion, long expected, long actual)
{
    if (expected == actual)
        return 0;
    printf("FAIL %s %s expected=%ld actual=%ld\n", current_case, assertion, expected, actual);
    return 1;
}
#define CHECK(label, expected, actual) do { \
    if (check((label), (long)(expected), (long)(actual))) return 1; \
} while (0)

static void reset(void)
{
    memset(interfaces, 0, sizeof(interfaces));
    memset(pubs, 0, sizeof(pubs));
    memset(devices, 0, sizeof(devices));
    memset(packets, 0, sizeof(packets));
    memset(&captured_key, 0, sizeof(captured_key));
    for (unsigned i = 0; i < 2; i++) {
        interfaces[i].drvr = &pubs[i];
        interfaces[i].ndev = &devices[i];
        interfaces[i].pend_8021x_wait.owner = &interfaces[i];
    }
    for (unsigned i = 0; i < 4; i++) {
        packets[i].eth.h_proto = htons(ETH_P_PAE);
        packets[i].skb.data = (unsigned char *)&packets[i].eth;
    }
    progress_count = barriers = firmware_calls = 0;
    firmware_error = 0;
    progress_success = true;
}

static void observation(int result)
{
    printf("OBSERVE %s result=%d pending=%d other_pending=%d firmware_calls=%u "
           "frees=%u barriers=%u wakes=%u tx_errors=%u\n", current_case, result,
           interfaces[0].pend_8021x_cnt.value, interfaces[1].pend_8021x_cnt.value,
           firmware_calls, packets[0].skb.frees, barriers,
           interfaces[0].pend_8021x_wait.wakes, devices[0].stats.tx_errors);
}

static struct brcmf_wsec_key key_data(void)
{
    /* Synthetic values; compare only fields initialized by the real converter,
     * not its pre-existing unused padding. No real network/key data is used.
     */
    struct brcmf_wsec_key key = { .index = 0x12345678, .len = 16,
        .algo = 0x10203040, .flags = 0x50607080, .iv_initialized = 1,
        .rxiv = { .hi = 0x88776655, .lo = 0xaa99 } };
    for (unsigned i = 0; i < sizeof(key.data); i++)
        key.data[i] = (u8)(i ^ 0xa5);
    for (unsigned i = 0; i < sizeof(key.ea); i++)
        key.ea[i] = (u8)(i + 0x20);
    return key;
}

static int empty_wait(void)
{
    int result = brcmf_netdev_wait_pend8021x(&interfaces[0]);
    observation(result);
    CHECK("empty_success", 0, result);
    CHECK("empty_count", 0, interfaces[0].pend_8021x_cnt.value);
    CHECK("one_wait", 1, interfaces[0].pend_8021x_wait.waits);
    CHECK("no_error", 0, pubs[0].errors);
    return 0;
}

static int drained_wait(void)
{
    interfaces[0].pend_8021x_cnt.value = 2;
    progress[0] = &packets[0];
    progress[1] = &packets[1];
    progress_count = 2;
    int result = brcmf_netdev_wait_pend8021x(&interfaces[0]);
    observation(result);
    CHECK("genuine_completion", 0, interfaces[0].pend_8021x_cnt.value);
    CHECK("drained_success", 0, result);
    CHECK("both_freed", 2, packets[0].skb.frees + packets[1].skb.frees);
    CHECK("ordered_completions", 2, barriers);
    CHECK("enrolled_wakes", 2, interfaces[0].pend_8021x_wait.wakes);
    CHECK("no_error", 0, pubs[0].errors);
    return 0;
}

static int timeout(unsigned count)
{
    interfaces[0].pend_8021x_cnt.value = (int)count;
    int result = brcmf_netdev_wait_pend8021x(&interfaces[0]);
    observation(result);
    CHECK("pending_preserved", count, interfaces[0].pend_8021x_cnt.value);
    CHECK("timeout_errno", -ETIMEDOUT, result);
    CHECK("one_error", 1, pubs[0].errors);
    CHECK("not_freed", 0, packets[0].skb.frees);
    CHECK("no_synthetic_wake", 0, interfaces[0].pend_8021x_wait.wakes);
    return 0;
}
static int timeout_single(void) { return timeout(1); }
static int timeout_multiple(void) { return timeout(3); }

static int late_completion(bool success)
{
    interfaces[0].pend_8021x_cnt.value = 1;
    int result = brcmf_netdev_wait_pend8021x(&interfaces[0]);
    brcmf_txfinalize(&interfaces[0], &packets[0].skb, success);
    observation(result);
    CHECK("late_count_balanced", 0, interfaces[0].pend_8021x_cnt.value);
    CHECK("one_free", 1, packets[0].skb.frees);
    CHECK("one_barrier", 1, barriers);
    CHECK("late_not_enrolled", 0, interfaces[0].pend_8021x_wait.wakes);
    CHECK("completion_success_independent", !success, devices[0].stats.tx_errors);
    CHECK("original_timeout_errno", -ETIMEDOUT, result);
    return 0;
}
static int late_successful_completion(void) { return late_completion(true); }
static int late_failed_completion(void) { return late_completion(false); }

static int old_plus_new_outstanding(void)
{
    interfaces[0].pend_8021x_cnt.value = 1;
    int result = brcmf_netdev_wait_pend8021x(&interfaces[0]);
    /* Modeled new EAPOL submission; original TX completion remains actual. */
    interfaces[0].pend_8021x_cnt.value++;
    brcmf_txfinalize(&interfaces[0], &packets[0].skb, true);
    observation(result);
    CHECK("new_frame_still_owned", 1, interfaces[0].pend_8021x_cnt.value);
    CHECK("second_wait_refuses", -ETIMEDOUT, brcmf_netdev_wait_pend8021x(&interfaces[0]));
    brcmf_txfinalize(&interfaces[0], &packets[1].skb, true);
    CHECK("all_genuine_completions", 0, interfaces[0].pend_8021x_cnt.value);
    CHECK("both_freed", 2, packets[0].skb.frees + packets[1].skb.frees);
    return 0;
}

static int wait_after_genuine_drain(void)
{
    interfaces[0].pend_8021x_cnt.value = 1;
    int original = brcmf_netdev_wait_pend8021x(&interfaces[0]);
    brcmf_txfinalize(&interfaces[0], &packets[0].skb, true);
    int result = brcmf_netdev_wait_pend8021x(&interfaces[0]);
    observation(result);
    CHECK("subsequent_wait_succeeds", 0, result);
    CHECK("no_new_timeout", 1, pubs[0].errors);
    CHECK("original_timeout_errno", -ETIMEDOUT, original);
    return 0;
}

static int key_timeout(bool deletion)
{
    struct brcmf_wsec_key key = key_data();
    if (deletion) {
        key.len = 0;
        key.algo = 0;
    }
    interfaces[0].pend_8021x_cnt.value = 1;
    int result = send_key_to_dongle(&interfaces[0], &key);
    observation(result);
    CHECK("no_key_write", 0, firmware_calls);
    CHECK("key_timeout_errno", -ETIMEDOUT, result);
    CHECK("key_pending_preserved", 1, interfaces[0].pend_8021x_cnt.value);
    brcmf_txfinalize(&interfaces[0], &packets[0].skb, false);
    CHECK("completion_after_refusal", 0, interfaces[0].pend_8021x_cnt.value);
    return 0;
}
static int key_install_timeout_refused(void) { return key_timeout(false); }
static int key_delete_timeout_refused(void) { return key_timeout(true); }

static int successful_key_bytes(void)
{
    struct brcmf_wsec_key key = key_data();
    interfaces[0].pend_8021x_cnt.value = 1;
    progress[0] = &packets[0];
    progress_count = 1;
    int result = send_key_to_dongle(&interfaces[0], &key);
    observation(result);
    CHECK("key_success", 0, result);
    CHECK("one_key_write", 1, firmware_calls);
    CHECK("wire_index", key.index, le32toh(captured_key.index));
    CHECK("wire_length", key.len, le32toh(captured_key.len));
    CHECK("wire_algo", key.algo, le32toh(captured_key.algo));
    CHECK("wire_flags", key.flags, le32toh(captured_key.flags));
    CHECK("wire_iv_initialized", key.iv_initialized, le32toh(captured_key.iv_initialized));
    CHECK("wire_iv_hi", key.rxiv.hi, le32toh(captured_key.rxiv.hi));
    CHECK("wire_iv_lo", key.rxiv.lo, le16toh(captured_key.rxiv.lo));
    CHECK("wire_data", 0, memcmp(key.data, captured_key.data, sizeof(key.data)));
    CHECK("wire_peer", 0, memcmp(key.ea, captured_key.ea, sizeof(key.ea)));
    CHECK("key_after_completion", 0, interfaces[0].pend_8021x_cnt.value);
    return 0;
}

static int firmware_errno_after_drain(void)
{
    struct brcmf_wsec_key key = key_data();
    firmware_error = -EIO;
    int result = send_key_to_dongle(&interfaces[0], &key);
    observation(result);
    CHECK("firmware_errno", -EIO, result);
    CHECK("one_attempt", 1, firmware_calls);
    CHECK("firmware_error_logged", 1, pubs[0].errors);
    return 0;
}

static int unrelated_frame_completion(void)
{
    interfaces[0].pend_8021x_cnt.value = 1;
    packets[0].eth.h_proto = htons(0x0800);
    brcmf_txfinalize(&interfaces[0], &packets[0].skb, false);
    observation(0);
    CHECK("unrelated_count", 1, interfaces[0].pend_8021x_cnt.value);
    CHECK("no_eapol_barrier", 0, barriers);
    CHECK("unrelated_free", 1, packets[0].skb.frees);
    CHECK("unrelated_failure_stat", 1, devices[0].stats.tx_errors);
    brcmf_txfinalize(NULL, &packets[1].skb, true);
    CHECK("null_interface_free", 1, packets[1].skb.frees);
    CHECK("null_interface_no_count", 1, interfaces[0].pend_8021x_cnt.value);
    return 0;
}

static int interface_isolation(void)
{
    interfaces[0].pend_8021x_cnt.value = 1;
    interfaces[1].pend_8021x_cnt.value = 1;
    int result = brcmf_netdev_wait_pend8021x(&interfaces[0]);
    brcmf_txfinalize(&interfaces[1], &packets[1].skb, true);
    observation(result);
    CHECK("first_interface_owned", 1, interfaces[0].pend_8021x_cnt.value);
    CHECK("second_interface_balanced", 0, interfaces[1].pend_8021x_cnt.value);
    CHECK("second_no_error", 0, pubs[1].errors);
    brcmf_txfinalize(&interfaces[0], &packets[0].skb, true);
    CHECK("first_later_balanced", 0, interfaces[0].pend_8021x_cnt.value);
    return 0;
}

int main(int argc, char **argv)
{
    static const struct { const char *name; int (*run)(void); } cases[] = {
        {"empty_wait", empty_wait}, {"drained_wait", drained_wait},
        {"timeout_single", timeout_single}, {"timeout_multiple", timeout_multiple},
        {"late_successful_completion", late_successful_completion},
        {"late_failed_completion", late_failed_completion},
        {"old_plus_new_outstanding", old_plus_new_outstanding},
        {"wait_after_genuine_drain", wait_after_genuine_drain},
        {"key_install_timeout_refused", key_install_timeout_refused},
        {"key_delete_timeout_refused", key_delete_timeout_refused},
        {"successful_key_bytes", successful_key_bytes},
        {"firmware_errno_after_drain", firmware_errno_after_drain},
        {"unrelated_frame_completion", unrelated_frame_completion},
        {"interface_isolation", interface_isolation},
    };
    if (argc != 2)
        return 2;
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        if (strcmp(argv[1], cases[i].name))
            continue;
        current_case = cases[i].name;
        reset();
        int result = cases[i].run();
        if (!result)
            printf("PASS %s\n", current_case);
        return result;
    }
    return 2;
}
