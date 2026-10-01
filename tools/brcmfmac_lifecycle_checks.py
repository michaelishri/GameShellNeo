"""Assertion-based negative controls for the SDIO lifecycle source harness."""


def variants(good, function, mutate_once):
    reset = function(good, 'static int brcmf_sdio_bus_reset(')
    suspend = function(good, 'static int brcmf_sdiod_suspend(')
    wrapper = function(good, 'static int callback_suspend(')
    remove = function(good, 'static void callback_remove(')
    abort = function(good, 'static void brcmf_sdiod_pm_abort(')
    restore = function(good, 'static int brcmf_sdiod_pm_restore(')
    resume = function(good, 'static int callback_resume(')
    cases = {'candidate': good}
    for name, body, before, after in (
        ('lost_irq_deferral', good, 'in_isr || READ_ONCE(bus->sdiodev->pm_irq_blocked)', 'in_isr'),
        ('lost_sleep_gate', suspend, 'WRITE_ONCE(sdiodev->pm_irq_blocked, true);', ''),
        ('lost_wake_ungate', restore, 'WRITE_ONCE(sdiodev->pm_irq_blocked, false);', ''),
        ('lost_reset_trylock', reset, 'if (!device_trylock(f2dev))',
         'if (false && !device_trylock(f2dev))'),
        ('lost_reset_retained_guard', reset, 'sdiodev->pm_suspended || sdiodev->pm_powered_off',
         'sdiodev->pm_powered_off'),
        ('lost_reset_poweroff_guard', reset, 'sdiodev->pm_suspended || sdiodev->pm_powered_off',
         'sdiodev->pm_suspended'),
        ('lost_suspend_lock', wrapper, 'mutex_lock_nested(&f2dev->mutex, SINGLE_DEPTH_NESTING);', ''),
        ('lost_remove_lock', remove, 'mutex_lock_nested(&f2dev->mutex, SINGLE_DEPTH_NESTING);',
         'brcmf_dbg(SDIO, "missing lock");'),
        ('lost_abort', remove, 'brcmf_sdiod_pm_abort(sdiodev);', 'if (false) brcmf_sdiod_pm_abort(sdiodev);'),
        ('lost_abort_thaw', abort, 'brcmf_sdiod_freezer_thaw(sdiodev->freezer);', ''),
        ('lost_abort_quarantine', abort, 'brcmf_sdio_pm_failed(sdiodev->bus);', ''),
        ('lost_poweroff_commit', suspend, 'sdiodev->pm_powered_off = true;',
         'sdiodev->pm_powered_off = false;'),
        ('lost_poweroff_consumption', resume, 'sdiodev->pm_powered_off = false;', ''),
    ):
        cases[name] = mutate_once(good, body, mutate_once(body, before, after))
    return cases
