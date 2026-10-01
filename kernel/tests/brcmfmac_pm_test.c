/* SPDX-License-Identifier: ISC */
/* Reuse the concurrency fixture and its existing lifecycle scenarios. */
#define NEO_PM_TRANSACTION
#define main freezer_suite
#include "brcmfmac_freezer_test.c"
#undef main

static unsigned pm_scenarios;
static void pm_setup(void)
{
	setup();
	pm_seen = (typeof(pm_seen)){0};
	io_dev = &fixture.dev;
}
static void pm_finish(void)
{
	assert(!fixture.dev.pm_suspended);
	teardown();
	pm_scenarios++;
}
static void oob(void)
{
	fixture.dev.wowl_enabled = true;
	fixture.settings.bus.sdio.oob_irq_supported = true;
	fixture.dev.oob_irq_requested = true;
	fixture.dev.irq_en = true;
}
static void failed_restore_paths(void)
{
	unsigned dpc = seen.dpc, wd = seen.wd_io, queue = seen.trigger;
	assert(fixture.dev.pm_failed && !fixture.dev.pm_suspended);
	assert(!seen.wd_start && !seen.up && !brcmf_sdiod_freezing(&fixture.dev));
	fixture.bus.dpc_triggered = true;
	join(start(data_thread));
	watchdog_mode = 2;
	join(start(watchdog_thread));
	brcmf_sdio_isr(&fixture.bus, true);
	brcmf_sdio_isr(&fixture.bus, false);
	brcmf_sdio_trigger_dpc(&fixture.bus);
	assert(seen.dpc == dpc && seen.wd_io == wd && seen.trigger == queue);
	brcmf_sdiod_change_state(&fixture.dev, BRCMF_SDIOD_DATA);
	assert(fixture.dev.state != BRCMF_SDIOD_DATA);
	assert(brcmf_sdio_bus_reset(&fixture.f1.dev) == -EHOSTDOWN);
	assert(!seen.remove && !seen.probe && !seen.cancel);
	assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EHOSTDOWN);
	fixture.host.caps = MMC_CAP_POWER_OFF_CARD;
	fixture.dev.wowl_enabled = false;
	assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EHOSTDOWN);
	resume();
	assert(!seen.remove && !seen.probe && !seen.cancel);
	assert(!pm_seen.raw);
}

static void rollback(unsigned stage, bool restore_fails)
{
	pm_setup(); oob();
	pm_flags = 8; /* Another function's request must not be cleared. */
	int error = stage == 0 ? -EIO : stage == 1 ? -ENOSPC : -EINVAL;
	if (stage == 0) faults.sleep = error;
	if (stage == 1) faults.enable = error;
	if (stage == 2) faults.flags = error;
	if (restore_fails) faults.wake = -EREMOTEIO;
	pthread_t pm = start_suspend(), data = start(data_thread);
	collect_result(pm, error); join(data);
	assert(!fixture.dev.pm_suspended && !fixture.dev.pm_oob_irq_wake);
	assert(pm_flags == 8 && seen.sleep == 1 && seen.wake == 1);
	assert(seen.irq_on == (stage != 0) && seen.irq_off == (stage == 2));
	assert(seen.flags == (stage == 2));
	assert(seen.up == !restore_fails && seen.wd_start == !restore_fails);
	resume(); assert(seen.wake == 1); /* No second wake after F1-local rollback. */
	if (restore_fails) {
		assert(pm_seen.irq_mask == 1 && !fixture.dev.irq_en);
		failed_restore_paths();
	} else {
		assert(fixture.dev.state == BRCMF_SDIOD_DATA);
		faults = (typeof(faults)){0};
		pm = start_suspend(); data = start(data_thread);
		collect_result(pm, 0); resume(); join(data);
		assert(pm_flags == (8 | MMC_PM_KEEP_POWER));
		assert(seen.up == 2 && seen.wd_start == 2);
	}
	pm_finish();
}

static void wake_failure(bool ib_release_fails)
{
	pm_setup(); fixture.dev.sd_irq_requested = true;
	faults.release_irq = ib_release_fails ? -EIO : 0;
	pthread_t pm = start_suspend(), data = start(data_thread);
	collect_result(pm, 0);
	faults.wake = -ETIMEDOUT;
	assert(brcmf_ops_sdio_resume(&fixture.f2.dev) == -ETIMEDOUT);
	join(data);
	assert(pm_seen.irq_release == 2 && !fixture.dev.sd_irq_requested);
	failed_restore_paths();
	resume(); assert(seen.wake == 1 && pm_seen.irq_release == 2);
	pm_finish();
}

static void cleanup_failure(bool during_rollback, bool wake_fails)
{
	pm_setup(); oob();
	if (during_rollback) faults.flags = -EINVAL;
	faults.disable = -EAGAIN;
	if (wake_fails) faults.wake = -EREMOTEIO;
	pthread_t pm = start_suspend(), data = start(data_thread);
	collect_result(pm, during_rollback ? -EINVAL : 0);
	if (!during_rollback)
		assert(brcmf_ops_sdio_resume(&fixture.f2.dev) ==
		       (wake_fails ? -EREMOTEIO : -EAGAIN));
	join(data);
	assert(fixture.dev.pm_oob_irq_wake && !fixture.dev.pm_suspended);
	assert(seen.irq_on == 1 && seen.irq_off == 1 && seen.wake == 1);
	unsigned triggers = seen.trigger;
	assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EAGAIN);
	assert(seen.trigger == triggers && seen.irq_on == 1 && seen.wake == 1);
	faults.disable = 0;
	resume();
	assert(!fixture.dev.pm_oob_irq_wake && seen.irq_off == 3 && seen.wake == 1);
	resume(); assert(seen.irq_off == 3);
	pm_finish();
}

static void preflight(unsigned mode)
{
	pm_setup();
	int error = -EINVAL;
	if (mode == 0) fixture.host.pm_caps = 0;
	if (mode == 1) {
		fixture.dev.wowl_enabled = true;
		fixture.host.pm_caps = MMC_PM_KEEP_POWER;
	}
	if (mode >= 2) {
		fixture.dev.state = mode == 2 ? BRCMF_SDIOD_DOWN : BRCMF_SDIOD_NOMEDIUM;
		error = -ENODEV;
	}
	assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == error);
	assert(!seen.trigger && !seen.claims && !seen.sleep && !seen.wd_stop);
	assert(!fixture.dev.pm_failed && !fixture.dev.pm_suspended);
	pm_finish();
}

static void retained_policy_change(void)
{
	pm_setup(); oob(); fixture.host.caps = MMC_CAP_POWER_OFF_CARD;
	pthread_t pm = start_suspend(), data = start(data_thread);
	collect_result(pm, 0);
	fixture.dev.wowl_enabled = false;
	assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EBUSY);
	assert(!seen.remove && !seen.cancel);
	resume(); join(data);
	assert(seen.wake == 1 && seen.irq_off == 1 && !seen.probe);
	assert(!fixture.dev.pm_suspended && !fixture.dev.pm_oob_irq_wake);
	pm_finish();
}

static void lost_state(bool at_resume, enum brcmf_sdiod_state state)
{
	pm_setup();
	if (!at_resume) sdio_claim_host(&fixture.f1);
	pthread_t pm = start_suspend(), data = start(data_thread);
	if (at_resume) {
		collect_result(pm, 0);
		fixture.dev.state = state;
		assert(brcmf_ops_sdio_resume(&fixture.f2.dev) == -ENODEV);
	} else {
		UNTIL(frozen() == 1);
		fixture.dev.state = state;
		sdio_release_host(&fixture.f1);
		collect_result(pm, -ENODEV);
	}
	join(data);
	assert(fixture.dev.pm_failed && !seen.wake && !seen.up);
	assert(fixture.dev.state == state);
	assert(!seen.wd_start);
	pm_finish();
}

static atomic_bool command_entered;
static int command_result;
static unsigned char message[8];
static void *tx_thread(void *unused)
{
	(void)unused; role = TXCONTROL; command_entered = true;
	command_result = brcmf_sdio_bus_txctl(&fixture.f1.dev, message, sizeof(message));
	return NULL;
}
static void *rx_thread(void *unused)
{
	(void)unused;
	command_result = brcmf_sdio_bus_rxctl(&fixture.f1.dev, message, sizeof(message));
	return NULL;
}
static void control_failure(unsigned mode)
{
	pm_setup(); command_entered = false;
	if (mode == 0) sdio_claim_host(&fixture.f1);
	pthread_t command = start(mode == 2 ? rx_thread : tx_thread);
	if (mode == 0) UNTIL(command_entered);
	else {
		UNTIL(atomic_load(mode == 2 ? &fixture.bus.dcmd_resp_wait.sleepers :
				 &fixture.bus.ctrl_wait.sleepers));
		sdio_claim_host(&fixture.f1);
	}
	brcmf_sdio_pm_failed(&fixture.bus);
	sdio_release_host(&fixture.f1);
	join(command);
	assert(command_result == -EHOSTDOWN && !fixture.bus.ctrl_frame_stat);
	assert(pm_seen.ctrl_wake == (mode == 1) && pm_seen.resp_wake == 1);
	assert(!pm_seen.raw);
	assert(brcmf_sdio_bus_txctl(&fixture.f1.dev, message, sizeof(message)) == -EHOSTDOWN);
	assert(brcmf_sdio_bus_rxctl(&fixture.f1.dev, message, sizeof(message)) == -EHOSTDOWN);
	pm_finish();
}

static void control_success(bool receive)
{
	pm_setup();
	pthread_t command = start(receive ? rx_thread : tx_thread);
	if (receive) {
		UNTIL(atomic_load(&fixture.bus.dcmd_resp_wait.sleepers));
		spin_lock_bh(&fixture.bus.rxctl_lock);
		fixture.bus.rxctl = malloc(4); assert(fixture.bus.rxctl);
		fixture.bus.rxctl_orig = fixture.bus.rxctl;
		memcpy(fixture.bus.rxctl, "TEST", 4); fixture.bus.rxlen = 4;
		spin_unlock_bh(&fixture.bus.rxctl_lock);
		brcmf_sdio_dcmd_resp_wake(&fixture.bus);
	} else {
		UNTIL(atomic_load(&fixture.bus.ctrl_wait.sleepers));
		sdio_claim_host(&fixture.f1);
		fixture.bus.ctrl_frame_err = 0;
		fixture.bus.ctrl_frame_stat = false;
		brcmf_sdio_wait_event_wakeup(&fixture.bus);
		sdio_release_host(&fixture.f1);
	}
	join(command);
	assert(command_result == (receive ? 4 : 0));
	if (receive) assert(!memcmp(message, "TEST", 4));
	pm_finish();
}

static void accessors(bool failed, bool cached_window)
{
	pm_setup();
	fixture.dev.sbwad = cached_window ? 0x10000 : 0;
	sdio_claim_host(&fixture.f1);
	if (failed) brcmf_sdio_pm_failed(&fixture.bus);
	for (unsigned nullable = 0; nullable < 2; nullable++) {
		int ret = 0, *error = nullable ? NULL : &ret;
		assert(brcmf_sdiod_readb(&fixture.dev, 1, error) == (failed ? 0xff : 0x55));
		assert(nullable || ret == (failed ? -EHOSTDOWN : 0));
		ret = 0;
		assert(brcmf_sdiod_func0_rb(&fixture.dev, 2, error) == (failed ? 0xff : 0x55));
		assert(nullable || ret == (failed ? -EHOSTDOWN : 0));
		brcmf_sdiod_writeb(&fixture.dev, 3, 4, error);
		assert(nullable || ret == (failed ? -EHOSTDOWN : 0));
		brcmf_sdiod_func0_wb(&fixture.dev, 4, 5, error);
		assert(nullable || ret == (failed ? -EHOSTDOWN : 0));
		assert(brcmf_sdiod_readl(&fixture.dev, 0x10004, error) == (failed ? 0 : 0x12345678));
		assert(nullable || ret == (failed ? -EHOSTDOWN : 0));
		brcmf_sdiod_writel(&fixture.dev, 0x10004, 1, error);
		assert(nullable || ret == (failed ? -EHOSTDOWN : 0));
	}
	struct sk_buff skb = { .len = sizeof(message), .data = message };
	assert(brcmf_sdiod_skbuff_read(&fixture.dev, &fixture.f1, 4, &skb) == (failed ? -EHOSTDOWN : 0));
	assert(brcmf_sdiod_skbuff_read(&fixture.dev, &fixture.f2, 4, &skb) == (failed ? -EHOSTDOWN : 0));
	assert(brcmf_sdiod_skbuff_write(&fixture.dev, &fixture.f2, 4, &skb) == (failed ? -EHOSTDOWN : 0));
	struct mmc_data md = {0}; struct mmc_command mc = {0}; struct mmc_request mr = {0};
	u32 addr = 4;
	assert(mmc_submit_one(&md, &mr, &mc, 1, 16, 4, &addr, &fixture.dev, &fixture.f1, 1) ==
	       (failed ? -EHOSTDOWN : 0));
	assert(addr == (failed ? 4 : 20));
	if (failed) assert(!pm_seen.raw && !md.sg_len && !mc.arg);
	else assert(pm_seen.raw > 0 && md.sg_len == 1 && md.blocks == 4);
	sdio_release_host(&fixture.f1);
	pm_finish();
}

static void assert_info_cleanup(unsigned fail_at)
{
	pm_setup(); pm_seen.ram_fail_at = fail_at;
	struct sdpcm_shared sh = { .flags = SDPCM_SHARED_ASSERT_BUILT | SDPCM_SHARED_ASSERT,
		.assert_file_addr = 1, .assert_exp_addr = 2 };
	assert(brcmf_sdio_assert_info(NULL, &fixture.bus, &sh) == (fail_at ? -EHOSTDOWN : 0));
	assert(seen.claims == 1 && seen.releases == 1 && !host_claimed);
	assert(pm_seen.ram_reads == (fail_at ? fail_at : 2));
	pm_finish();
}

static void irq_cleanup(void)
{
	pm_setup(); oob(); fixture.dev.pm_oob_irq_wake = true;
	faults.disable = -EIO;
	assert(brcmf_sdiod_pm_disarm(&fixture.dev) == -EIO && fixture.dev.pm_oob_irq_wake);
	faults.disable = 0;
	test_intr_unregister(&fixture.dev);
	assert(!fixture.dev.pm_oob_irq_wake && seen.irq_off == 2 && pm_seen.irq_free == 1);
	test_intr_unregister(&fixture.dev);
	assert(seen.irq_off == 2 && pm_seen.irq_free == 1);
	pm_finish();
}

static void *oob_thread(void *unused)
{
	(void)unused;
	assert(brcmf_sdiod_oob_irqhandler(0, &fixture.f1.dev) == IRQ_HANDLED);
	return NULL;
}
static void irq_after_failure(bool concurrent)
{
	pm_setup(); oob();
	sdio_claim_host(&fixture.f1);
	brcmf_sdio_pm_failed(&fixture.bus);
	pthread_t irq = start(oob_thread);
	if (!concurrent) join(irq);
	brcmf_sdiod_pm_quiesce_irqs(&fixture.dev);
	sdio_release_host(&fixture.f1);
	if (concurrent) join(irq);
	assert(pm_seen.irq_mask == 1 && !seen.trigger && !pm_seen.raw);
	pm_finish();
}

static void parked_watchdog_failure(void)
{
	pm_setup(); watchdog_mode = 2; watchdog_gate.armed = true;
	pthread_t wd = start(watchdog_thread);
	gate_wait(&watchdog_gate);
	pthread_t pm = start_suspend(), data = start(data_thread);
	collect_result(pm, 0);
	gate_release(&watchdog_gate);
	UNTIL(frozen() == 2);
	faults.wake = -EIO;
	assert(brcmf_ops_sdio_resume(&fixture.f2.dev) == -EIO);
	join(data); join(wd);
	assert(!seen.wd_io && !fixture.bus.sdcnt.tickcnt && !frozen());
	assert(fixture.dev.pm_failed && !seen.wd_start);
	pm_finish();
}

static void delayed_failed_thaw(void)
{
	pm_setup(); return_gate.armed = true;
	pthread_t pm = start_suspend(), data = start(data_thread);
	collect_result(pm, 0);
	faults.wake = -EIO;
	assert(brcmf_ops_sdio_resume(&fixture.f2.dev) == -EIO);
	gate_wait(&return_gate);
	assert(frozen() == 1);
	assert(brcmf_ops_sdio_suspend(&fixture.f1.dev) == -EHOSTDOWN);
	resume(); assert(seen.wake == 1);
	gate_release(&return_gate); join(data);
	pm_finish();
}

static void *access_thread(void *unused)
{
	(void)unused; command_entered = true;
	sdio_claim_host(&fixture.f1);
	brcmf_sdiod_readl(&fixture.dev, 0x10004, &command_result);
	sdio_release_host(&fixture.f1);
	return NULL;
}
static void queued_access_failure(void)
{
	pm_setup(); command_entered = false;
	sdio_claim_host(&fixture.f1);
	pthread_t access = start(access_thread);
	UNTIL(command_entered);
	brcmf_sdio_pm_failed(&fixture.bus);
	sdio_release_host(&fixture.f1); join(access);
	assert(command_result == -EHOSTDOWN && !pm_seen.raw);
	pm_finish();
}

#ifdef NEO_SDIO_LIFECYCLE
static int pm_suite(void)
#else
int main(void)
#endif
{
	assert(!freezer_suite()); /* Also rerun all 44 original lifecycle scenarios. */
	for (unsigned stage = 0; stage < 3; stage++) {
		rollback(stage, false); rollback(stage, true);
	}
	wake_failure(false); wake_failure(true);
	for (unsigned i = 0; i < 4; i++) cleanup_failure(i & 1, i & 2);
	for (unsigned i = 0; i < 4; i++) preflight(i);
	retained_policy_change();
	lost_state(false, BRCMF_SDIOD_DOWN);
	lost_state(false, BRCMF_SDIOD_NOMEDIUM);
	lost_state(true, BRCMF_SDIOD_NOMEDIUM);
	for (unsigned i = 0; i < 3; i++) control_failure(i);
	control_success(false); control_success(true);
	for (unsigned i = 0; i < 4; i++) accessors(i & 1, i & 2);
	for (unsigned i = 0; i < 3; i++) assert_info_cleanup(i);
	irq_cleanup();
	irq_after_failure(false);
	for (unsigned i = 0; i < 8; i++) irq_after_failure(true);
	parked_watchdog_failure(); delayed_failed_thaw(); queued_access_failure();
	printf("%u PM failure/control/I/O scenarios passed\n", pm_scenarios);
	return 0;
}
