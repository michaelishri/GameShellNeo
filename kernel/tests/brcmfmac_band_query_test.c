/* Actual bandwidth/setup functions with deterministic firmware failures. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef int32_t s32;
#define NL80211_BAND_2GHZ 0
#define NL80211_BAND_5GHZ 1
#define WLC_BAND_2G 2
#define WLC_BAND_5G 1
#define WLC_BW_20MHZ_BIT 1
#define WLC_BW_40MHZ_BIT 2
#define WLC_N_BW_20ALL 0
#define WLC_N_BW_40ALL 1
#define WLC_N_BW_20IN2G_40IN5G 2
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define fallthrough __attribute__((fallthrough))
#define brcmf_dbg(...) ((void)0)
#define bphy_err(...) ((void)0)
#define bphy_info_once(...) ((void)0)
#define WARN_ON(x) assert(!(x))
struct brcmf_pub { int unused; };
struct brcmf_if { struct brcmf_pub *drvr; };
struct ieee80211_supported_band {
    unsigned band, ht_updates, vht_updates;
    u32 nchain, bw, streams, bfe, bfr;
};
struct wiphy { struct ieee80211_supported_band *bands[3]; };
struct brcmf_cfg80211_info { struct brcmf_pub *pub; struct wiphy *wiphy; };
#define cfg_to_wiphy(c) ((c)->wiphy)
static struct brcmf_pub pub;
static struct brcmf_if interface = {&pub};
static struct ieee80211_supported_band bands[2];
static struct wiphy wiphy = {{&bands[0], &bands[1], NULL}};
static struct brcmf_cfg80211_info cfg = {&pub, &wiphy};
static struct brcmf_if *brcmf_get_ifp(struct brcmf_pub *p, int index)
{ assert(p == &pub && index == 0); return &interface; }
enum query { VHT, NMODE, BW2, BW5, MIMO, RXCHAIN, STREAMS, BFE, BFR, QUERIES };
static int errors[QUERIES], chan_error, calls[QUERIES], channels, tests;
static u32 values[QUERIES], last_bw[2];
static enum query order[32];
static unsigned norder;
static int read_value(enum query q, u32 *value)
{
    assert(norder < ARRAY_SIZE(order));
    order[norder++] = q; calls[q]++;
    /* fwil copies the reply only on success. */
    if (!errors[q]) *value = values[q];
    return errors[q];
}
static int brcmf_fil_iovar_int_get(struct brcmf_if *ifp, const char *name, u32 *value)
{
    assert(ifp == &interface);
    const char *names[QUERIES] = {"vhtmode", "nmode", NULL, NULL, "mimo_bw_cap",
                                 "rxchain", "txstreams", "txbf_bfe_cap", "txbf_bfr_cap"};
    for (unsigned i = 0; i < QUERIES; i++)
        if (names[i] && !strcmp(name, names[i])) return read_value(i, value);
    assert(false); return -EINVAL;
}
static int brcmf_fil_iovar_int_query(struct brcmf_if *ifp, const char *name, u32 *value)
{
    assert(ifp == &interface && !strcmp(name, "bw_cap"));
    assert(*value == WLC_BAND_2G || *value == WLC_BAND_5G);
    return read_value(*value == WLC_BAND_2G ? BW2 : BW5, value);
}
static int brcmf_construct_chaninfo(struct brcmf_cfg80211_info *c, u32 bw[])
{
    assert(c == &cfg); channels++;
    memcpy(last_bw, bw, sizeof(last_bw));
    return chan_error;
}
static void brcmf_update_ht_cap(struct ieee80211_supported_band *band, u32 bw[], u32 chain)
{
    assert(channels == 1 && !chan_error && chain <= 8);
    band->ht_updates++; band->nchain = chain; band->bw = bw[band->band];
}
static void brcmf_update_vht_cap(struct ieee80211_supported_band *band, u32 bw[], u32 chain,
                                 u32 streams, u32 bfe, u32 bfr)
{
    assert(channels == 1 && !chan_error && chain <= 8);
    /* The real update function ignores 2.4 GHz VHT. */
    if (band->band == NL80211_BAND_2GHZ) return;
    band->vht_updates++; band->nchain = chain; band->bw = bw[band->band];
    band->streams = streams; band->bfe = bfe; band->bfr = bfr;
}
#include "brcmfmac_band_functions.h"
static void reset(void)
{
    memset(errors, 0, sizeof(errors)); memset(calls, 0, sizeof(calls));
    memset(bands, 0, sizeof(bands)); memset(last_bw, 0, sizeof(last_bw));
    for (unsigned i = 0; i < 2; i++) bands[i].band = i;
    u32 defaults[] = {1, 1, 3, 3, WLC_N_BW_40ALL, 3, 2, 1, 1};
    memcpy(values, defaults, sizeof(values));
    chan_error = channels = 0; norder = 0; tests++;
}
static void expect_no_mutation(void)
{
    assert(channels == 0);
    for (unsigned i = 0; i < 2; i++)
        assert(bands[i].ht_updates == 0 && bands[i].vht_updates == 0);
}
int main(void)
{
    reset(); assert(brcmf_setup_wiphybands(&cfg) == 0);
    assert(channels == 1 && norder == 8 && !calls[MIMO]);
    assert(bands[0].ht_updates == 1 && bands[1].vht_updates == 1);
    assert(bands[1].streams == 2 && bands[1].nchain == 2);
    const int transport_errors[] = {-ETIMEDOUT, -EIO, -ENODEV, -ENOMEM};
    for (unsigned q = 0; q < QUERIES; q++) {
        for (unsigned e = 0; e < ARRAY_SIZE(transport_errors); e++) {
            reset();
            if (q == MIMO) errors[BW2] = -EBADE;
            errors[q] = transport_errors[e];
            assert(brcmf_setup_wiphybands(&cfg) == transport_errors[e]);
            assert(order[norder - 1] == (enum query)q && calls[q] == 1);
            expect_no_mutation();
        }
    }
    reset(); errors[NMODE] = -EBADE;
    assert(brcmf_setup_wiphybands(&cfg) == -EBADE && norder == 2);
    expect_no_mutation();
    /* Optional generic firmware-rejection fallbacks remain deterministic. */
    const enum query optional[] = {VHT, RXCHAIN, STREAMS, BFE, BFR};
    for (unsigned i = 0; i < ARRAY_SIZE(optional); i++) {
        reset(); errors[optional[i]] = -EBADE;
        assert(brcmf_setup_wiphybands(&cfg) == 0 && channels == 1);
        if (optional[i] == VHT) assert(!bands[1].vht_updates && !calls[STREAMS]);
        if (optional[i] == RXCHAIN) assert(bands[0].nchain == 1);
        if (optional[i] == STREAMS) assert(bands[1].streams == 0);
        if (optional[i] == BFE) assert(bands[1].bfe == 0);
        if (optional[i] == BFR) assert(bands[1].bfr == 0);
    }
    for (u32 legacy = 0; legacy < 3; legacy++) {
        reset(); errors[BW2] = -EBADE; values[MIMO] = legacy;
        assert(brcmf_setup_wiphybands(&cfg) == 0 && calls[MIMO] == 1 && !calls[BW5]);
        assert(last_bw[0] == (legacy == WLC_N_BW_40ALL ? 3u : 1u));
        assert(last_bw[1] == (legacy == WLC_N_BW_20ALL ? 1u : 3u));
    }
    reset(); errors[BW2] = errors[MIMO] = -EBADE;
    assert(brcmf_setup_wiphybands(&cfg) == 0 && last_bw[0] == 1 && last_bw[1] == 1);
    reset(); errors[BW5] = -EBADE;
    assert(brcmf_setup_wiphybands(&cfg) == 0 && last_bw[0] == 3 && last_bw[1] == 1);
    reset(); errors[BW2] = -EBADE; values[MIMO] = 99;
    assert(brcmf_setup_wiphybands(&cfg) == -EINVAL); expect_no_mutation();
    for (unsigned count = 0; count <= 32; count++) {
        reset(); values[RXCHAIN] = count == 32 ? UINT32_MAX : (1u << count) - 1;
        int err = brcmf_setup_wiphybands(&cfg);
        if (count > 8) { assert(err == -EINVAL); expect_no_mutation(); }
        else assert(err == 0 && bands[0].nchain == count);
    }
    reset(); values[NMODE] = values[VHT] = 0;
    assert(brcmf_setup_wiphybands(&cfg) == 0 && channels == 1);
    assert(!bands[0].ht_updates && !bands[1].vht_updates);
    reset(); chan_error = -EIO;
    assert(brcmf_setup_wiphybands(&cfg) == -EIO && channels == 1);
    assert(!bands[0].ht_updates && !bands[1].vht_updates);
    /* An early failure leaves no advertised mutation; a later call can work. */
    reset(); errors[STREAMS] = -ETIMEDOUT;
    assert(brcmf_setup_wiphybands(&cfg) == -ETIMEDOUT); expect_no_mutation();
    errors[STREAMS] = 0;
    assert(brcmf_setup_wiphybands(&cfg) == 0 && channels == 1);
    printf("%d band query scenarios passed\n", tests);
    return 0;
}
