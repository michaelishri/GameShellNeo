/* Actual Linux reset/SDIO/driver helpers are generated from locked source.
 * Hardware, PM, binding-list changes and destruction are synchronous seams.
 * This fixture does not exercise real kernel scheduling or hardware. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define container_of(ptr, type, member) ((type *)((char *)(ptr) - offsetof(type, member)))
#define SINGLE_DEPTH_NESTING 1
#define MMC_CAP_POWER_OFF_CARD 1
#define MMC_CAP_NEEDS_POLL 2
#define BRCMF_MAX_IFS 1
#define BRCMF_NETIF_STOP_REASON_NONE 0
#define brcmf_dbg(...) ((void)0)
#define pr_warn(...) (seen.warnings++)
typedef struct { int counter; } atomic_t;
static int atomic_read(const atomic_t *a) { return a->counter; }
static void atomic_inc(atomic_t *a) { a->counter++; }
static void atomic_dec(atomic_t *a) { a->counter--; }
struct list_head { void *next, *prev; };
struct kref { unsigned refcount; };
#include "reset-types.h"
struct device_private { struct klist_node knode_driver; };
struct device_driver { const char *name; };
struct device { struct device_driver *driver; void *data; int mutex; struct device_private *p; };
struct delayed_work { int unused; };
struct mmc_host;
struct mmc_card { struct mmc_host *host; atomic_t sdio_funcs_probed; bool removed; unsigned ocr; };
struct mmc_bus_ops { int (*hw_reset)(struct mmc_host *); };
struct mmc_host { struct mmc_card *card; const struct mmc_bus_ops *bus_ops; unsigned caps; int rescan_entered,detect_change; struct delayed_work detect; void *ws; struct device *parent; };
struct sdio_func { struct device dev; struct mmc_card *card; int num,vendor,device; void *irq_handler; };
struct sdio_device_id { int unused; };
struct sdio_driver { struct device_driver drv; const char *name; int (*probe)(struct sdio_func *, const struct sdio_device_id *); void (*remove)(struct sdio_func *); };
struct brcmf_sdio { int unused; };
struct brcmf_pub { void *iflist[1]; };
struct brcmf_sdio_dev;
struct brcmf_bus { struct brcmf_pub *drvr; int state; union { struct brcmf_sdio_dev *sdio; } bus_priv; };
struct brcmf_sdio_dev { struct sdio_func *func1,*func2; struct brcmf_bus *bus_if; struct brcmf_sdio *bus; int state; bool pm_suspended,pm_powered_off,pm_failed; int sgtable,sbwad; void *freezer; };
struct observations { int teardown,irq,probe,reinit,power,detect,warnings,claim,host_calls,lock_get,lock_put,disable,freezer,sg,pm_allow,reinit_result; };
static struct observations seen;
static struct mmc_host host;
static struct mmc_card card;
static struct sdio_func f1,f2;
static struct device_private p1,p2;
static struct brcmf_sdio transport;
static struct brcmf_pub drvr;
static struct brcmf_bus bus;
static struct brcmf_sdio_dev sd;
static bool mmc_card_removed(struct mmc_card *c) { return c->removed; }
static void mmc_card_set_removed(struct mmc_card *c) { c->removed=true; }
static const char *mmc_hostname(struct mmc_host *h) { (void)h; return "fixture"; }
static void mmc_schedule_delayed_work(struct delayed_work *work, unsigned long delay) { (void)work; assert(delay==0); seen.detect++; }
static void __pm_wakeup_event(void *ws,unsigned long duration) { (void)ws;(void)duration;assert(!"unexpected wakeup"); }
static void mmc_power_cycle(struct mmc_host *h,unsigned ocr) { assert(h==&host);(void)ocr;seen.power++; }
static int mmc_sdio_reinit_card(struct mmc_host *h) { assert(h==&host);assert(seen.claim==1);seen.reinit++;return seen.reinit_result; }
static void sdio_claim_host(struct sdio_func *f) { assert(f->card==&card); assert(seen.claim==0);seen.claim++;seen.host_calls++; }
static void sdio_release_host(struct sdio_func *f) { assert(f->card==&card);assert(seen.claim==1);seen.claim--; }
static int sdio_disable_func(struct sdio_func *f) { assert(seen.claim==1);(void)f;seen.disable++;return 0; }
static void sdio_release_irq(struct sdio_func *f) { (void)f;assert(!"unexpected residual irq"); }
static int sdio_set_block_size(struct sdio_func *f,unsigned size) { (void)f;assert(size==0);return 0; }
static struct sdio_driver *to_sdio_driver(struct device_driver *d) { return container_of(d,struct sdio_driver,drv); }
static struct sdio_func *dev_to_sdio_func(struct device *d) { return container_of(d,struct sdio_func,dev); }
static const struct sdio_device_id match_id;
static const struct sdio_device_id *sdio_match_device(struct sdio_func *f,struct sdio_driver *d) { (void)f;(void)d;return &match_id; }
static int dev_pm_domain_attach(struct device *d,bool power) { (void)d;assert(!power);return 0; }
static int pm_runtime_get_sync(struct device *d) { (void)d;return 0; }
static void pm_runtime_put_noidle(struct device *d) { (void)d; }
static void pm_runtime_put_sync(struct device *d) { (void)d; }
static void pm_runtime_allow(struct device *d) { (void)d;seen.pm_allow++; }
static void *dev_get_drvdata(struct device *d) { return d->data; }
static void dev_set_drvdata(struct device *d,void *data) { d->data=data; }
static bool device_trylock(struct device *d) { if(d->mutex)return false;d->mutex=1;seen.lock_get++;return true; }
static void device_unlock(struct device *d) { assert(d->mutex==1);d->mutex=0;seen.lock_put++; }
static void device_lock_assert(struct device *d) { assert(d->mutex==1); }
static void mutex_lock_nested(int *lock,int nesting) { assert(nesting==SINGLE_DEPTH_NESTING);assert(!*lock);*lock=1;seen.lock_get++; }
static bool brcmf_sdiod_io_blocked(struct brcmf_sdio_dev *d) { return d->pm_failed; }
static void brcmf_sdiod_intr_unregister(struct brcmf_sdio_dev *d) { assert(d==&sd);seen.irq++; }
static void brcmf_sdiod_pm_abort(struct brcmf_sdio_dev *d) { assert(!d->pm_suspended); }
static void brcmf_sdio_cancel_datawork(struct brcmf_sdio *t) { (void)t; }
static void brcmf_bus_cancel_reset_work(struct brcmf_bus *b) { (void)b; }
static void brcmf_sdiod_freezer_detach(struct brcmf_sdio_dev *d) { (void)d;seen.freezer++; }
static void sg_free_table(int *table) { (void)table;seen.sg++; }
static void brcmf_sdio_remove(struct brcmf_sdio *t) { assert(t==&transport);seen.teardown++;bus.drvr=NULL; }
static void kfree(void *ptr) { (void)ptr;assert(!"unexpected final F1 free"); }
static void brcmf_txflowblock_if(void *ifp,int reason,bool block) { (void)ifp;(void)reason;(void)block;assert(!"unexpected UP transition"); }
static int callback_probe(struct sdio_func *func,const struct sdio_device_id *id) { (void)func;assert(id==&match_id);seen.probe++;return 0; }

#include "reset-functions.h"

static const struct mmc_bus_ops bus_ops = { .hw_reset = mmc_sdio_hw_reset };
static struct sdio_driver driver = {
	.drv = { .name = "brcmf-fixture" },
	.name = "brcmf-fixture",
	.probe = callback_probe,
	.remove = brcmf_ops_sdio_remove,
};

/* Each setup starts with a fresh card and executes both actual SDIO probes.
 * List insertion is the driver-core binding seam, under its device lock. */
static void bind_function(struct sdio_func *func)
{
	assert(device_trylock(&func->dev));
	func->dev.driver = &driver.drv;
	assert(sdio_bus_probe(&func->dev) == 0);
	func->dev.p->knode_driver.n_klist = &driver;
	device_unlock(&func->dev);
}

static void setup(void)
{
	memset(&seen, 0, sizeof(seen));
	memset(&host, 0, sizeof(host));
	memset(&card, 0, sizeof(card));
	memset(&f1, 0, sizeof(f1));
	memset(&f2, 0, sizeof(f2));
	memset(&p1, 0, sizeof(p1));
	memset(&p2, 0, sizeof(p2));
	memset(&sd, 0, sizeof(sd));
	memset(&bus, 0, sizeof(bus));
	memset(&drvr, 0, sizeof(drvr));
	host.card = &card;
	host.bus_ops = &bus_ops;
	host.rescan_entered = 1;
	card.host = &host;
	card.ocr = 1;
	f1.card = f2.card = &card;
	f1.num = 1;
	f2.num = 2;
	f1.dev.p = &p1;
	f2.dev.p = &p2;
	f1.dev.data = f2.dev.data = &bus;
	sd.func1 = &f1;
	sd.func2 = &f2;
	sd.bus = &transport;
	sd.bus_if = &bus;
	bus.bus_priv.sdio = &sd;
	bus.drvr = &drvr;
	bus.state = BRCMF_BUS_UP;
	bind_function(&f1);
	bind_function(&f2);
	assert(card.sdio_funcs_probed.counter == 2);
	assert(seen.probe == 2 && seen.claim == 0);
	/* Exclude provisioning lock/host calls, retaining the two actual probes. */
	seen.host_calls = seen.lock_get = seen.lock_put = 0;
}

/* Actual F2 remove and SDIO bookkeeping run before the modeled driver-core
 * cleanup. Both pointer clears and list removal match device_unbind_cleanup()
 * and __device_release_driver(), while this same F2 lock remains held. */
static void unbind_f2(void)
{
	assert(device_trylock(&f2.dev));
	sdio_bus_remove(&f2.dev);
	f2.dev.driver = NULL;
	f2.dev.data = NULL;
	f2.dev.p->knode_driver.n_klist = NULL;
	device_unlock(&f2.dev);
}

static int invoke_mmc(void)
{
	int ret;

	sdio_claim_host(&f1);
	ret = mmc_hw_reset(&card);
	sdio_release_host(&f1);
	return ret;
}

/* Output every observation before checking any contract assertion. The shared
 * metric list fixes both grammar and first-failure order for compiling controls. */
#define METRICS(X) \
	X(ret, reset_errno) \
	X(teardown, transport_retirement) \
	X(irq, irq_retirement) \
	X(host, host_balance) \
	X(lock, f2_lock) \
	X(lock_get, lock_acquisitions) \
	X(lock_put, lock_releases) \
	X(bound, bound_functions) \
	X(removed, card_removed) \
	X(rescan, rescan_requests) \
	X(power, power_cycles) \
	X(reinit, reinitializations) \
	X(warnings, mmc_warnings) \
	X(transport, transport_present) \
	X(drvr, driver_state_present) \
	X(f2_bound, f2_binding) \
	X(f2_driver, f2_driver_pointer) \
	X(f2_data, f2_driver_data) \
	X(f1_data, f1_driver_data) \
	X(host_calls, host_claims) \
	X(probes, successful_probes) \
	X(disable, function_disables) \
	X(freezer, freezer_detaches) \
	X(sg, sg_releases) \
	X(pm_allow, runtime_pm_allows)

struct metrics {
#define FIELD(field, label) int field;
	METRICS(FIELD)
#undef FIELD
};

static struct metrics unbound_metrics(void)
{
	return (struct metrics) {
		.ret = -ENODEV, .irq = 1, .lock_get = 2, .lock_put = 2,
		.bound = 1, .transport = 1, .drvr = 1,
		.f1_data = 1, .probes = 2,
	};
}

static int finish(const char *name, int ret, struct metrics expected)
{
	struct metrics actual = {
		.ret = ret, .teardown = seen.teardown, .irq = seen.irq,
		.host = seen.claim, .lock = f2.dev.mutex,
		.lock_get = seen.lock_get, .lock_put = seen.lock_put,
		.bound = atomic_read(&card.sdio_funcs_probed),
		.removed = mmc_card_removed(&card), .rescan = seen.detect,
		.power = seen.power, .reinit = seen.reinit,
		.warnings = seen.warnings, .transport = sd.bus != NULL,
		.drvr = bus.drvr != NULL, .f2_bound = device_is_bound(&f2.dev),
		.f2_driver = f2.dev.driver != NULL, .f2_data = f2.dev.data != NULL,
		.f1_data = f1.dev.data != NULL, .host_calls = seen.host_calls,
		.probes = seen.probe, .disable = seen.disable,
		.freezer = seen.freezer, .sg = seen.sg, .pm_allow = seen.pm_allow,
	};

	printf("OBSERVE case=%s", name);
#define PRINT(field, label) printf(" " #field "=%d", actual.field);
	METRICS(PRINT)
#undef PRINT
	putchar('\n');
#define CHECK(field, label) \
	if (actual.field != expected.field) { \
		printf("FAIL case=%s assertion=" #label " expected=%d observed=%d\n", \
		       name, expected.field, actual.field); \
		return 1; \
	}
	METRICS(CHECK)
#undef CHECK
	printf("PASS case=%s\n", name);
	return 0;
}

int main(int argc, char **argv)
{
	struct metrics expected = {
		.bound = 2, .transport = 1, .drvr = 1, .f2_bound = 1,
		.f2_driver = 1, .f2_data = 1, .f1_data = 1, .probes = 2,
	};
	int ret = 0;
	const char *name;

	assert(argc == 2);
	name = argv[1];
	setup();
	if (!strcmp(name, "mmc_multifunc_schedule") ||
	    !strcmp(name, "mmc_multifunc_already_removed")) {
		if (!strcmp(name, "mmc_multifunc_already_removed"))
			card.removed = true;
		ret = invoke_mmc();
		expected.ret = 1;
		expected.removed = 1;
		expected.rescan = strcmp(name, "mmc_multifunc_already_removed") != 0;
		expected.host_calls = 1;
	} else if (!strcmp(name, "mmc_after_f2_unbind_sync") ||
		   !strcmp(name, "mmc_after_f2_unbind_eio") ||
		   !strcmp(name, "mmc_after_f2_unbind_timeout")) {
		unbind_f2();
		if (!strcmp(name, "mmc_after_f2_unbind_eio"))
			seen.reinit_result = -EIO;
		if (!strcmp(name, "mmc_after_f2_unbind_timeout"))
			seen.reinit_result = -ETIMEDOUT;
		ret = invoke_mmc();
		expected = unbound_metrics();
		expected.ret = seen.reinit_result;
		expected.lock_get = expected.lock_put = 1;
		expected.host_calls = expected.power = expected.reinit = 1;
		expected.warnings = seen.reinit_result != 0;
	} else if (!strcmp(name, "reset_bound_async") ||
		   !strcmp(name, "reset_bound_already_removed")) {
		if (!strcmp(name, "reset_bound_already_removed"))
			card.removed = true;
		ret = brcmf_sdio_bus_reset(&f1.dev);
		expected.transport = expected.drvr = 0;
		expected.teardown = expected.irq = 1;
		expected.lock_get = expected.lock_put = 1;
		expected.host_calls = 2;
		expected.removed = 1;
		expected.rescan = strcmp(name, "reset_bound_already_removed") != 0;
		expected.disable = 2;
		expected.freezer = expected.sg = expected.pm_allow = 1;
	} else if (!strcmp(name, "reset_unbound_f2_sync_refused") ||
		   !strcmp(name, "reset_unbound_f2_eio_refused") ||
		   !strcmp(name, "reset_unbound_f2_timeout_refused")) {
		unbind_f2();
		if (!strcmp(name, "reset_unbound_f2_eio_refused"))
			seen.reinit_result = -EIO;
		if (!strcmp(name, "reset_unbound_f2_timeout_refused"))
			seen.reinit_result = -ETIMEDOUT;
		ret = brcmf_sdio_bus_reset(&f1.dev);
		expected = unbound_metrics();
	} else if (!strcmp(name, "f2_remove_preserves_shared")) {
		unbind_f2();
		expected = unbound_metrics();
		expected.ret = 0;
		expected.lock_get = expected.lock_put = 1;
	} else if (!strcmp(name, "reset_lifecycle_busy")) {
		f2.dev.mutex = 1;
		ret = brcmf_sdio_bus_reset(&f1.dev);
		f2.dev.mutex = 0;
		expected.ret = -EBUSY;
	} else if (!strcmp(name, "reset_pm_failed") ||
		   !strcmp(name, "reset_pm_retained") ||
		   !strcmp(name, "reset_pm_powered_off") ||
		   !strcmp(name, "reset_no_transport")) {
		expected.ret = -EBUSY;
		if (!strcmp(name, "reset_pm_failed")) {
			sd.pm_failed = true;
			expected.ret = -EHOSTDOWN;
		} else if (!strcmp(name, "reset_pm_retained")) {
			sd.pm_suspended = true;
		} else if (!strcmp(name, "reset_pm_powered_off")) {
			sd.pm_powered_off = true;
		} else {
			sd.bus = NULL;
			expected.transport = 0;
			expected.ret = -ENODEV;
		}
		expected.lock_get = expected.lock_put = 1;
		ret = brcmf_sdio_bus_reset(&f1.dev);
	} else {
		fprintf(stderr, "Unknown case\n");
		return 2;
	}
	return finish(name, ret, expected);
}
