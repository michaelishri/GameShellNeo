/* Actual cfg80211 callbacks with modeled firmware, RTNL and PM ordering. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef int32_t s32;
typedef uint32_t u32;
#define BRCMF_COUNTRY_BUF_SZ 4
#define BRCM_CC_43430_CHIP_ID 43430
#define BRCM_CC_4345_CHIP_ID 4345
#define BRCM_CC_4356_CHIP_ID 4356
#define BRCM_CC_43602_CHIP_ID 43602
#define BRCMF_FEAT_WOWL_ARP_ND 1
#define BRCMF_FEAT_PNO 2
#define BRCMF_C_SET_PM 3
#define BRCMF_E_PFN_NET_FOUND 4
#define BRCMF_VIF_STATUS_READY 0
#define BRCMF_SCAN_STATUS_BUSY 1
#define WLAN_REASON_UNSPECIFIED 1
#define cpu_to_le32(x) (x)
#define brcmf_dbg(...) ((void)0)
#define bphy_err(drvr, ...) ((void)(drvr))
struct brcmfmac_pd_cc_entry { char iso3166[4], cc[4]; int rev; };
struct brcmfmac_pd_cc { int table_size; struct brcmfmac_pd_cc_entry table[2]; };
struct settings { bool trivial_ccode_map; struct brcmfmac_pd_cc *country_codes; };
struct bus { int chip; };
struct brcmf_cfg80211_info;
struct brcmf_pub { struct settings *settings; struct bus *bus_if; };
struct brcmf_cfg80211_vif { unsigned long sme_state; };
struct net_device { struct brcmf_if *ifp; };
struct brcmf_if { struct brcmf_pub *drvr; struct brcmf_cfg80211_vif *vif; struct net_device *ndev; };
struct wiphy { struct brcmf_cfg80211_info *cfg; };
struct cfg80211_wowlan { int unused; };
struct brcmf_fil_country_le { char country_abbrev[4]; int rev; char ccode[4]; };
struct regulatory_request { char alpha2[2]; int initiator; };
struct brcmf_cfg80211_info {
    struct wiphy *wiphy;
    struct brcmf_pub *pub;
    struct net_device *ndev;
    struct brcmf_cfg80211_vif *vif_list;
    unsigned long scan_status;
    struct { bool active, nd_enabled; int pre_pmmode; } wowl;
#include "brcmfmac_regulatory_fields.h"
};
static bool rtnl, transport_awake, vif_up, missing_ifp;
static int gets, sets, bands, get_error, set_error, band_error, actions, tests;
static struct brcmf_fil_country_le firmware;
static struct brcmf_if interface;
static struct net_device netdev;
static struct brcmf_cfg80211_vif vif;
static struct brcmf_pub pub;
static struct settings settings;
static struct bus bus;
static struct brcmf_cfg80211_info cfg;
static struct wiphy wiphy;
#define ASSERT_RTNL() assert(rtnl)
#define wiphy_to_cfg(w) ((w)->cfg)
#define cfg_to_ndev(c) ((c)->ndev)
#define netdev_priv(n) ((n)->ifp)
#define list_for_each_entry(v, head, member) for ((v) = *(head); (v); (v) = NULL)
static bool test_bit(int bit, const unsigned long *p) { return !!(*p & (1ul << bit)); }
static bool check_vif_up(struct brcmf_cfg80211_vif *v) { (void)v; return vif_up; }
static bool brcmf_feat_is_enabled(struct brcmf_if *ifp, int feature) { (void)ifp; (void)feature; return false; }
static struct brcmf_if *brcmf_get_ifp(struct brcmf_pub *p, int index) { assert(p == &pub && index == 0); return missing_ifp ? NULL : &interface; }
static void action(void) { assert(rtnl && transport_awake); actions++; }
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
static int brcmf_fil_iovar_data_get(struct brcmf_if *ifp, const char *name, void *data, size_t size)
{
    assert(ifp == &interface && !strcmp(name, "country") && size == sizeof(firmware));
    assert(rtnl && transport_awake); gets++;
    if (!get_error) memcpy(data, &firmware, size);
    return get_error;
}
static int brcmf_fil_iovar_data_set(struct brcmf_if *ifp, const char *name, const void *data, size_t size)
{
    assert(ifp == &interface && !strcmp(name, "country") && size == sizeof(firmware));
    assert(rtnl && transport_awake); sets++;
    if (!set_error) memcpy(&firmware, data, size);
    return set_error;
}
static int brcmf_setup_wiphybands(struct brcmf_cfg80211_info *c)
{
    assert(c == &cfg && rtnl && transport_awake); bands++; return band_error;
}
#include "brcmfmac_regulatory_functions.h"
static void reset(void)
{
    memset(&cfg, 0, sizeof(cfg)); memset(&firmware, 0, sizeof(firmware));
    gets = sets = bands = actions = 0; get_error = set_error = band_error = 0;
    rtnl = transport_awake = vif_up = true; missing_ifp = false;
    settings = (struct settings){0}; bus.chip = BRCM_CC_43430_CHIP_ID;
    pub = (struct brcmf_pub){&settings, &bus};
    vif.sme_state = 1; interface = (struct brcmf_if){&pub, &vif, &netdev};
    netdev.ifp = &interface;
    wiphy.cfg = &cfg; cfg.wiphy = &wiphy; cfg.pub = &pub;
    cfg.ndev = &netdev; cfg.vif_list = &vif;
    tests++;
}
static void notify(const char *country)
{
    struct regulatory_request req = {.alpha2 = {country[0], country[1]}, .initiator = 1};
    brcmf_cfg80211_reg_notifier(&wiphy, &req);
}
static void suspend_radio(bool ready, bool wowlan)
{
    struct cfg80211_wowlan w = {0};
    vif_up = ready;
    assert(brcmf_cfg80211_suspend(&wiphy, wowlan ? &w : NULL) == 0);
    assert(cfg.regulatory_suspended);
    transport_awake = false;
}
static int resume_radio(void)
{
    transport_awake = true;
    int err = brcmf_cfg80211_resume(&wiphy);
    assert(!cfg.regulatory_suspended && !cfg.regulatory_pending);
    return err;
}
int main(void)
{
    reset(); notify("NZ"); assert(gets == 1 && sets == 1 && bands == 1);
    assert(!memcmp(firmware.ccode, "NZ", 2));
    notify("NZ"); assert(gets == 2 && sets == 1 && bands == 1);
    for (int ready = 0; ready < 2; ready++) for (int wowlan = 0; wowlan < 2; wowlan++) {
        reset(); suspend_radio(ready, wowlan);
        notify("AU"); notify("NZ"); notify("00"); notify("99"); notify("nZ");
        assert(cfg.regulatory_pending && !memcmp(cfg.regulatory_alpha2, "NZ", 2));
        assert(gets == 0 && sets == 0 && bands == 0);
        assert(resume_radio() == 0);
        assert(gets == 1 && sets == 1 && bands == 1 && !memcmp(firmware.ccode, "NZ", 2));
        assert(resume_radio() == 0 && gets == 1);
        notify("AU"); assert(gets == 2 && sets == 2 && bands == 2);
    }
    reset(); suspend_radio(true, false); assert(resume_radio() == 0 && gets == 0);
    reset(); notify("00"); notify("99"); notify("nZ"); assert(gets == 0);
    for (int phase = 0; phase < 4; phase++) {
        reset(); suspend_radio(true, false); notify("AU");
        if (phase == 0) get_error = -ETIMEDOUT;
        if (phase == 1) set_error = -EIO;
        if (phase == 2) band_error = -ERANGE;
        if (phase == 3) missing_ifp = true;
        int expected[] = {-ETIMEDOUT, -EIO, -ERANGE, -ENODEV};
        assert(resume_radio() == expected[phase]);
        assert(gets == (phase != 3)); assert(sets == (phase == 1 || phase == 2));
        assert(bands == (phase == 2));
        int old = gets; assert(resume_radio() == 0 && gets == old);
    }
    reset(); suspend_radio(true, false); notify("AU");
    memcpy(firmware.country_abbrev, "AU", 2);
    assert(resume_radio() == 0 && gets == 1 && sets == 0 && bands == 0);
    reset(); suspend_radio(true, false); notify("NZ");
    bus.chip = 1; assert(resume_radio() == -EINVAL && gets == 1 && sets == 0);
    reset(); suspend_radio(true, false); notify("NZ");
    struct brcmfmac_pd_cc table = {.table_size = 1, .table = {{{'N','Z',0,0}, {'N','Z',0,0}, 7}}};
    settings.country_codes = &table;
    assert(resume_radio() == 0 && firmware.rev == 7);
    reset(); suspend_radio(true, false); notify("AU");
    cfg.wowl.active = cfg.wowl.nd_enabled = true;
    assert(resume_radio() == 0 && !cfg.wowl.active && !cfg.wowl.nd_enabled);
    reset();
    for (int i = 0; i < 16; i++) {
        suspend_radio(true, false); notify(i % 2 ? "NZ" : "AU");
        assert(resume_radio() == 0);
    }
    assert(gets == 16 && sets == 16 && bands == 16);
    printf("%d regulatory callback scenarios passed\n", tests);
    return 0;
}
