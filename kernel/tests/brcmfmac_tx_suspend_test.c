/* Actual driver queue/PM functions with pthread-backed queue/flow locks. */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef int32_t s32;
#define BIT(n) (1u << (n))
#define BRCMF_MAX_IFS 4
#define BRCMF_BUS_DOWN 0
#define BRCMF_BUS_UP 1
#define BRCMF_VIF_STATUS_READY 0
#define BRCMF_SCAN_STATUS_BUSY 1
#define BRCMF_FEAT_PNO 1
#define BRCMF_FEAT_WOWL_ARP_ND 2
#define WLAN_REASON_UNSPECIFIED 1
#define brcmf_dbg(...) ((void)0)
#include "brcmfmac_tx_reasons.h"

struct brcmf_if;
struct brcmf_cfg80211_info;
struct net_device {
    struct brcmf_if *ifp;
    pthread_mutex_t tx_lock;
    atomic_bool stopped, active;
    bool carrier;
    unsigned drains, wakes;
};
struct brcmf_bus { struct brcmf_pub *drvr; int state; };
enum brcmf_bus_state { bus_down = BRCMF_BUS_DOWN, bus_up = BRCMF_BUS_UP };
struct brcmf_pub { struct brcmf_bus *bus_if; struct brcmf_if *iflist[BRCMF_MAX_IFS]; };
struct brcmf_cfg80211_vif {
    struct brcmf_if *ifp;
    unsigned long sme_state;
    struct brcmf_cfg80211_vif *next;
};
struct brcmf_if {
    struct brcmf_pub *drvr;
    struct net_device *ndev;
    struct brcmf_cfg80211_vif *vif;
    pthread_mutex_t netif_stop_lock;
    unsigned netif_stop;
};
struct wiphy { struct brcmf_cfg80211_info *cfg; };
struct cfg80211_wowlan { int unused; };
struct brcmf_cfg80211_info {
    struct brcmf_pub *pub;
    struct net_device *ndev;
    struct brcmf_cfg80211_vif *vif_list;
    struct wiphy *wiphy;
    unsigned long scan_status;
    bool regulatory_suspended, regulatory_pending;
    char regulatory_alpha2[2];
    struct { bool active, nd_enabled; int pre_pmmode; } wowl;
};

static struct brcmf_if interfaces[3];
static struct net_device devices[2];
static struct brcmf_cfg80211_vif vifs[3];
static struct brcmf_pub pub;
static struct brcmf_bus bus;
static struct brcmf_cfg80211_info cfg;
static struct wiphy wiphy;
static bool rtnl, ready;
static int replay_error, replays, tests, actions;
static _Thread_local unsigned flow_lock_depth;
static atomic_bool worker_entered;

#define ASSERT_RTNL() assert(rtnl)
#define wiphy_to_cfg(w) ((w)->cfg)
#define cfg_to_ndev(c) ((c)->ndev)
#define netdev_priv(n) ((n)->ifp)
#define list_for_each_entry(v, head, member) \
    for ((v) = *(head); (v); (v) = (v)->next)
static void lock_flow(pthread_mutex_t *lock)
{
    assert(flow_lock_depth == 0);
    assert(pthread_mutex_lock(lock) == 0);
    flow_lock_depth++;
}
static void unlock_flow(pthread_mutex_t *lock)
{
    assert(flow_lock_depth == 1);
    flow_lock_depth--;
    assert(pthread_mutex_unlock(lock) == 0);
}
#define spin_lock_irqsave(lock, flags) do { (flags) = 0; lock_flow(lock); } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); unlock_flow(lock); } while (0)
static void netif_stop_queue(struct net_device *dev)
{
    atomic_store(&dev->stopped, true);
}
static bool netif_queue_stopped(struct net_device *dev) __attribute__((unused));
static bool netif_queue_stopped(struct net_device *dev) { return atomic_load(&dev->stopped); }
static void netif_wake_queue(struct net_device *dev)
{
    assert(dev->ifp->drvr->bus_if->state == BRCMF_BUS_UP);
    assert(dev->ifp->netif_stop == 0);
    dev->wakes++;
    atomic_store(&dev->stopped, false);
}
static void netif_tx_disable(struct net_device *dev)
{
    /* Kernel netif_tx_disable takes the transmit lock and stops the queue.
     * Never invert it with the flow lock taken by ndo_start_xmit.
     */
    assert(flow_lock_depth == 0);
    assert(pthread_mutex_lock(&dev->tx_lock) == 0);
    assert(!atomic_load(&dev->active));
    netif_stop_queue(dev);
    dev->drains++;
    assert(pthread_mutex_unlock(&dev->tx_lock) == 0);
}
static bool netif_carrier_ok(struct net_device *dev) { return dev->carrier; }
static void netif_carrier_on(struct net_device *dev) { dev->carrier = true; }
static void netif_carrier_off(struct net_device *dev) { dev->carrier = false; }
static bool test_bit(int bit, const unsigned long *p) { return !!(*p & (1ul << bit)); }
static bool check_vif_up(struct brcmf_cfg80211_vif *v) { (void)v; return ready; }
static bool brcmf_feat_is_enabled(struct brcmf_if *ifp, int feature)
{ (void)ifp; (void)feature; return false; }
static void action(void)
{
    assert(rtnl && bus.state == BRCMF_BUS_UP);
    for (unsigned i = 0; i < 2; i++) {
        assert(interfaces[i].netif_stop & BRCMF_NETIF_STOP_REASON_SUSPEND);
        assert(devices[i].drains > 0);
    }
    actions++;
}
#define brcmf_report_wowl_wakeind(...) action()
#define brcmf_fil_iovar_int_set(...) action()
#define brcmf_config_wowl_pattern(...) action()
#define brcmf_configure_arp_nd_offload(...) action()
#define brcmf_fil_cmd_int_set(...) action()
#define brcmf_cfg80211_sched_scan_stop(...) action()
#define brcmf_fweh_unregister(...) action()
#define brcmf_fweh_register(...) action()
#define brcmf_abort_scanning(...) action()
#define brcmf_bus_wowl_config(...) action()
#define brcmf_link_down(...) action()
#define brcmf_delay(...) action()
#define brcmf_set_mpc(...) action()
#define brcmf_configure_wowl(...) action()
#define brcmf_keepalive_start(...) action()
static int brcmf_cfg80211_apply_country(struct wiphy *w, char alpha2[2])
{
    assert(w == &wiphy && alpha2 == cfg.regulatory_alpha2 && rtnl);
    assert(bus.state == BRCMF_BUS_UP);
    for (unsigned i = 0; i < 2; i++) {
        assert(atomic_load(&devices[i].stopped));
        assert(interfaces[i].netif_stop & BRCMF_NETIF_STOP_REASON_SUSPEND);
    }
    replays++;
    return replay_error;
}
#include "brcmfmac_tx_functions.h"

static void reset(unsigned reasons)
{
    memset(&cfg, 0, sizeof(cfg));
    memset(&pub, 0, sizeof(pub));
    pub.bus_if = &bus; bus.drvr = &pub; bus.state = BRCMF_BUS_UP;
    rtnl = ready = true; replay_error = replays = actions = 0;
    cfg.pub = &pub; cfg.ndev = &devices[0]; cfg.wiphy = &wiphy;
    wiphy.cfg = &cfg; cfg.vif_list = &vifs[0];
    for (unsigned i = 0; i < 3; i++) {
        interfaces[i].drvr = &pub; interfaces[i].vif = &vifs[i];
        interfaces[i].netif_stop = 0; interfaces[i].ndev = i < 2 ? &devices[i] : NULL;
        vifs[i] = (struct brcmf_cfg80211_vif){&interfaces[i], 1, i < 2 ? &vifs[i + 1] : NULL};
        pub.iflist[i] = &interfaces[i];
        if (i < 2) {
            devices[i].ifp = &interfaces[i]; devices[i].carrier = true;
            devices[i].drains = devices[i].wakes = 0;
            atomic_store(&devices[i].stopped, false);
            atomic_store(&devices[i].active, false);
            if (reasons) brcmf_txflowblock_if(&interfaces[i], reasons, true);
        }
    }
    atomic_store(&worker_entered, false);
    tests++;
}
static void expect_stopped(unsigned reasons)
{
    for (unsigned i = 0; i < 2; i++) {
        assert(interfaces[i].netif_stop == reasons);
        assert(atomic_load(&devices[i].stopped) == !!reasons);
    }
}
static void *inflight_transmit(void *arg)
{
    struct net_device *dev = arg;
    assert(pthread_mutex_lock(&dev->tx_lock) == 0);
    atomic_store(&dev->active, true);
    atomic_store(&worker_entered, true);
    while (!atomic_load(&dev->stopped)) sched_yield();
    /* Reproduce the ndo transmit -> flow-control lock order while suspend
     * waits for this transmitter. A flow completion must not reopen it.
     */
    brcmf_txflowblock_if(dev->ifp, BRCMF_NETIF_STOP_REASON_FLOW, false);
    assert(atomic_load(&dev->stopped));
    atomic_store(&dev->active, false);
    assert(pthread_mutex_unlock(&dev->tx_lock) == 0);
    return NULL;
}
int main(void)
{
    for (unsigned i = 0; i < 3; i++)
        assert(pthread_mutex_init(&interfaces[i].netif_stop_lock, NULL) == 0);
    for (unsigned i = 0; i < 2; i++)
        assert(pthread_mutex_init(&devices[i].tx_lock, NULL) == 0);
    const unsigned suspend = BRCMF_NETIF_STOP_REASON_SUSPEND;
    /* All combinations of existing flow/disconnected owners. */
    for (unsigned reasons = 0; reasons < 8; reasons++) {
        reset(reasons);
        brcmf_bus_change_state(&bus, BRCMF_BUS_DOWN);
        expect_stopped(reasons);
        brcmf_bus_change_state(&bus, BRCMF_BUS_DOWN);
        expect_stopped(reasons);
        brcmf_bus_change_state(&bus, BRCMF_BUS_UP);
        expect_stopped(reasons);
        for (unsigned bit = 0; bit < 3; bit++) {
            for (unsigned i = 0; i < 2; i++)
                brcmf_txflowblock_if(&interfaces[i], BIT(bit), false);
        }
        expect_stopped(0);
    }
    for (unsigned reasons = 0; reasons < 8; reasons++)
    for (int is_ready = 0; is_ready < 2; is_ready++)
    for (int wowlan = 0; wowlan < 2; wowlan++)
    for (int failure = 0; failure < 3; failure++) {
        reset(reasons); ready = is_ready;
        struct cfg80211_wowlan w = {0};
        assert(brcmf_cfg80211_suspend(&wiphy, wowlan ? &w : NULL) == 0);
        expect_stopped(reasons | suspend);
        assert(devices[0].drains == 1 && devices[1].drains == 1);
        assert(cfg.regulatory_suspended);
        /* Parent transition/rollback must not release wiphy ownership. */
        brcmf_bus_change_state(&bus, BRCMF_BUS_DOWN);
        expect_stopped(reasons | suspend);
        brcmf_bus_change_state(&bus, BRCMF_BUS_UP);
        expect_stopped(reasons | suspend);
        cfg.regulatory_pending = failure != 0;
        replay_error = failure == 2 ? -EIO : 0;
        cfg.wowl.active = cfg.wowl.nd_enabled = wowlan;
        assert(brcmf_cfg80211_resume(&wiphy) == replay_error);
        unsigned expected = reasons | (failure == 2 ? BRCMF_NETIF_STOP_REASON_DISCONNECTED : 0);
        expect_stopped(expected);
        assert(replays == (failure != 0));
        assert(!cfg.regulatory_pending && !cfg.regulatory_suspended);
        assert(!cfg.wowl.active && !cfg.wowl.nd_enabled);
        if (failure == 2) {
            assert(!devices[0].carrier && !devices[1].carrier);
            for (unsigned i = 0; i < 2; i++) brcmf_net_setcarrier(&interfaces[i], true);
            expect_stopped(reasons & ~BRCMF_NETIF_STOP_REASON_DISCONNECTED);
        }
    }
    /* Parent rejects suspend before changing state: unwind still releases. */
    reset(0); assert(brcmf_cfg80211_suspend(&wiphy, NULL) == 0);
    assert(brcmf_cfg80211_resume(&wiphy) == 0); expect_stopped(0);
    /* A failed transport resume cannot reopen the network. */
    reset(0); assert(brcmf_cfg80211_suspend(&wiphy, NULL) == 0);
    brcmf_bus_change_state(&bus, BRCMF_BUS_DOWN);
    assert(brcmf_cfg80211_resume(&wiphy) == 0);
    expect_stopped(BRCMF_NETIF_STOP_REASON_DISCONNECTED);
    /* A flow/disconnect completion cannot release suspend ownership. */
    reset(7); assert(brcmf_cfg80211_suspend(&wiphy, NULL) == 0);
    brcmf_bus_change_state(&bus, BRCMF_BUS_DOWN);
    for (unsigned i = 0; i < 2; i++) brcmf_txflowblock_if(&interfaces[i], 7, false);
    expect_stopped(suspend);
    brcmf_bus_change_state(&bus, BRCMF_BUS_UP); expect_stopped(suspend);
    assert(brcmf_cfg80211_resume(&wiphy) == 0); expect_stopped(0);
    /* Drain a real concurrent in-flight transmitter, including lock ordering. */
    reset(0); pthread_t thread;
    assert(pthread_create(&thread, NULL, inflight_transmit, &devices[0]) == 0);
    while (!atomic_load(&worker_entered)) sched_yield();
    assert(brcmf_cfg80211_suspend(&wiphy, NULL) == 0);
    assert(pthread_join(thread, NULL) == 0);
    assert(!atomic_load(&devices[0].active) && devices[0].drains == 1);
    expect_stopped(suspend);
    assert(brcmf_cfg80211_resume(&wiphy) == 0); expect_stopped(0);
    reset(0); bus.drvr = NULL;
    brcmf_bus_change_state(&bus, BRCMF_BUS_DOWN);
    assert(bus.state == BRCMF_BUS_UP);
    brcmf_txflowblock_if(NULL, suspend, true);
    printf("%d transmit admission scenarios passed\n", tests);
    return 0;
}
