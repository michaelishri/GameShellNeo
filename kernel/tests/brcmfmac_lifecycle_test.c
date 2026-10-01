/* SPDX-License-Identifier: ISC */
#define NEO_SDIO_LIFECYCLE
#include "brcmfmac_pm_test.c"

static unsigned lifecycle_scenarios;
static int reset_result;
static atomic_bool removal_entered, removal_done, irq_entered;
static unsigned removal_function;

bool lifecycle_free(void *ptr)
{
	if (ptr != &fixture.interface && ptr != &fixture.dev)
		return false;
	device_lock_assert(second_dev);
	assert(!fixture.f1.dev.data && !fixture.f2.dev.data);
	assert(!brcmf_sdiod_freezing(&fixture.dev) && !frozen());
	freed_objects++;
	return true; /* Fixture storage stays allocated to detect stale accesses. */
}

static void *reset_thread(void *unused)
{
	(void)unused;
	reset_result = brcmf_sdio_bus_reset(&fixture.f1.dev);
	return NULL;
}

static void lifecycle_cancel_reset(struct brcmf_bus *b)
{
	(void)b;
	device_lock_assert(second_dev);
	if (reset_on_drain) {
		join(start(reset_thread));
		assert(reset_result == -EBUSY);
	}
}

static void lifecycle_drain(struct brcmf_sdio *b)
{
	device_lock_assert(second_dev);
	if (!b) return;
	assert(!brcmf_sdiod_freezing(b->sdiodev));
	if (drain_worker) {
		join(drain_thread);
		drain_worker = false;
	}
}

static void lifecycle_remove(struct brcmf_sdio_dev *d)
{
	device_lock_assert(second_dev);
	assert(!brcmf_sdiod_freezing(d));
	gate_pass(&reset_gate);
	if (destroy_bus) d->bus = NULL;
}

static void *remove_thread(void *unused)
{
	(void)unused;
	struct sdio_func *f = removal_function == 1 ? &fixture.f1 : &fixture.f2;
	removal_entered = true;
	device_lock(&f->dev);
	callback_remove(f);
	device_unlock(&f->dev);
	removal_done = true;
	return NULL;
}

static void life_setup(void)
{
	pm_setup(); reset_result = 999;
	removal_entered = removal_done = irq_entered = false;
	removal_function = 1;
}

static void life_finish(void)
{
	assert(!fixture.dev.pm_suspended);
	teardown(); lifecycle_scenarios++;
}

static void reset_conflict(unsigned mode)
{
	life_setup();
	pthread_t pm = start_suspend();
	/* Collection owns F2, but reset must not wait for that owner. */
	join(start(reset_thread)); assert(reset_result == -EBUSY);
	assert(!seen.remove && !seen.cancel);
	if (mode == 0) {
		force_expiry(); collect_result(pm, -ETIMEDOUT);
		join(start(data_thread));
	} else {
		pthread_t data = start(data_thread);
		collect_result(pm, 0);
		assert(brcmf_sdio_bus_reset(&fixture.f1.dev) == -EBUSY);
		assert(!seen.remove && !seen.cancel);
		resume(); join(data);
	}
	assert(!brcmf_sdio_bus_reset(&fixture.f1.dev));
	assert(seen.remove == 1 && !device_depth);
	life_finish();
}

static void reset_before_suspend(void)
{
	life_setup(); destroy_bus = true; reset_gate.armed = true;
	pthread_t reset = start(reset_thread);
	gate_wait(&reset_gate);
	pthread_t pm = start(suspend_thread);
	UNTIL(nested_waiting);
	assert(!pm_done && !seen.sleep && !seen.trigger);
	gate_release(&reset_gate); join(reset); collect_result(pm, -ENODEV);
	assert(!fixture.dev.bus && !seen.sleep && !seen.trigger);
	assert(brcmf_sdio_bus_reset(&fixture.f1.dev) == -ENODEV);
	assert(brcmf_ops_sdio_resume(&fixture.f2.dev) == -ENODEV);
	assert(!seen.probe);
	life_finish();
}

static void interrupt_during_sleep(bool hard, bool failed)
{
	life_setup();
	pthread_t pm = start_suspend(), data = start(data_thread);
	collect_result(pm, 0);
	assert(fixture.dev.pm_irq_blocked);
	unsigned raw = pm_seen.raw, queue = pm_seen.queue;
	if (!hard) sdio_claim_host(&fixture.f1); /* MMC's handler contract. */
	brcmf_sdio_isr(&fixture.bus, hard);
	if (!hard) sdio_release_host(&fixture.f1);
	assert(pm_seen.raw == raw && fixture.bus.ipend == 1);
	assert(fixture.bus.dpc_triggered && pm_seen.queue == queue + 1);
	if (failed) faults.wake = -EIO;
	assert(brcmf_ops_sdio_resume(&fixture.f2.dev) == (failed ? -EIO : 0));
	join(data);
	assert(fixture.dev.pm_irq_blocked == failed);
	assert(fixture.bus.ipend == !failed);
	sdio_claim_host(&fixture.f1);
	brcmf_sdio_isr(&fixture.bus, false);
	sdio_release_host(&fixture.f1);
	assert(pm_seen.raw == raw + !failed);
	life_finish();
}

static void *irq_thread(void *unused)
{
	(void)unused; irq_entered = true;
	sdio_claim_host(&fixture.f1);
	brcmf_sdio_isr(&fixture.bus, false);
	sdio_release_host(&fixture.f1);
	return NULL;
}

static void host_serializes_irq(void)
{
	life_setup();
	sdio_claim_host(&fixture.f1);
	pthread_t irq = start(irq_thread);
	UNTIL(irq_entered);
	/* The callback can set deferral while this handler waits for its host. */
	fixture.dev.pm_irq_blocked = true;
	sdio_release_host(&fixture.f1); join(irq);
	assert(!pm_seen.raw && fixture.bus.ipend == 1);
	fixture.dev.pm_irq_blocked = false;
	life_finish();
}

static void remove_retained(unsigned func, bool during_collection)
{
	life_setup(); oob(); removal_function = func;
	pthread_t pm = start_suspend();
	pthread_t removal = 0;
	if (during_collection) {
		removal = start(remove_thread); UNTIL(removal_entered);
		assert(!removal_done && !seen.cancel);
	}
	pthread_t data = start(data_thread);
	collect_result(pm, 0);
	if (!during_collection) {
		if (func == 1) { drain_thread = data; drain_worker = true; }
		reset_on_drain = true;
		removal = start(remove_thread);
	}
	join(removal);
	if (func != 1 || during_collection) join(data);
	assert(!fixture.dev.pm_suspended && fixture.dev.pm_failed);
	assert(!brcmf_sdiod_freezing(&fixture.dev) && !frozen());
	assert(seen.irq_off == 1 && !fixture.dev.pm_oob_irq_wake);
	assert(!seen.wake && !seen.up && !seen.wd_start && !pm_seen.raw);
	if (func == 1) {
		assert(freed_objects == 2 && !fixture.f2.dev.data);
		assert(brcmf_ops_sdio_resume(&fixture.f2.dev) == -ENODEV);
		assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -ENODEV);
	} else {
		assert(!freed_objects && !seen.remove);
		resume();
		assert(brcmf_sdio_bus_reset(&fixture.f1.dev) == -EHOSTDOWN);
	}
	life_finish();
}

static void poweroff_ownership(void)
{
	life_setup(); fixture.host.caps = MMC_CAP_POWER_OFF_CARD;
	assert(!brcmf_ops_sdio_suspend(&fixture.f1.dev));
	assert(fixture.dev.pm_powered_off);
	assert(brcmf_sdio_bus_reset(&fixture.f1.dev) == -EBUSY);
	assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EBUSY);
	fixture.dev.wowl_enabled = true;
	resume(); resume();
	assert(!fixture.dev.pm_powered_off && seen.probe == 1 && seen.remove == 1);
	life_finish();
}

static void no_unowned_probe(void)
{
	life_setup(); fixture.host.caps = MMC_CAP_POWER_OFF_CARD;
	resume(); assert(!seen.probe);
	fixture.dev.bus = NULL;
	assert(brcmf_ops_sdio_resume(&fixture.f2.dev) == -ENODEV);
	assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -ENODEV);
	assert(!seen.probe);
	life_finish();
}

#ifdef NEO_WORKER_ERRORS
static void worker_error_waiter(unsigned mode)
{
	life_setup(); command_entered = false;
	if (mode == 0) sdio_claim_host(&fixture.f1);
	pthread_t command = start(mode == 2 ? rx_thread : tx_thread);
	if (mode == 0) UNTIL(command_entered);
	else {
		UNTIL(atomic_load(mode == 2 ? &fixture.bus.dcmd_resp_wait.sleepers :
				 &fixture.bus.ctrl_wait.sleepers));
		sdio_claim_host(&fixture.f1);
	}
	brcmf_sdio_dpc_failed(&fixture.bus, -ETIMEDOUT);
	sdio_release_host(&fixture.f1); join(command);
	assert(command_result == (mode == 1 ? -ETIMEDOUT : -EHOSTDOWN));
	assert(fixture.dev.io_error == -ETIMEDOUT && !fixture.dev.pm_failed);
	assert(pm_seen.ctrl_wake == (mode == 1) && pm_seen.resp_wake == 1);
	assert(!fixture.bus.ctrl_frame_stat && !pm_seen.raw);
	assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EHOSTDOWN);
	assert(brcmf_sdio_bus_reset(&fixture.f1.dev) == -EHOSTDOWN);
	assert(brcmf_sdio_bus_txctl(&fixture.f1.dev, message, sizeof(message)) == -EHOSTDOWN);
	assert(brcmf_sdio_bus_rxctl(&fixture.f1.dev, message, sizeof(message)) == -EHOSTDOWN);
	sdio_claim_host(&fixture.f1);
	int err = 0;
	assert(brcmf_sdiod_readb(&fixture.dev, 1, &err) == 0xff && err == -EHOSTDOWN);
	brcmf_sdiod_readl(&fixture.dev, 0x10004, &err);
	assert(err == -EHOSTDOWN && !pm_seen.raw);
	sdio_release_host(&fixture.f1);
	life_finish();
}
#endif

int main(void)
{
	assert(!pm_suite());
	reset_conflict(0); reset_conflict(1); reset_before_suspend();
	for (unsigned mode = 0; mode < 4; mode++)
		interrupt_during_sleep(mode & 1, mode & 2);
	host_serializes_irq();
	remove_retained(1, false); remove_retained(2, false);
	remove_retained(2, true);
	poweroff_ownership(); no_unowned_probe();
#ifdef NEO_WORKER_ERRORS
	for (unsigned mode = 0; mode < 3; mode++) worker_error_waiter(mode);
#endif
	printf("%u reset/removal/IRQ scenarios passed\n", lifecycle_scenarios);
	return 0;
}
