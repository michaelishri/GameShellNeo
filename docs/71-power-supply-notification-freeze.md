# Power-supply notification freeze and replay (NEO-51)

1 October 2026, Pacific/Auckland; private evidence timestamps use UTC.
Linux 6.18.54, CPI v3.1. This closes the notification-worker source gap from
[report 68](68-pmic-suspend-ordering-audit.md) for the project's freezer-enabled
suspend configuration. Patch 0013 and the earlier PHY patch 0012 are included
in the prepared diagnostic.11 image in [report 72](72-diagnostic11-preparation.md).
Neither has been physically qualified in this slice.

## Change and scope

[Patch 0013](../kernel/patches/0013-power-supply-freezable-notifications.patch)
changes the queue used by `power_supply_changed()` from `system_wq` to
`system_freezable_wq`. Its existing `changed_lock`, `changed` flag, wake hold
and notification worker are unchanged. There is no new timer, allocation,
per-notification lock, driver flag or suspend callback.

This is a power-supply **core** change: it applies to all supplies in the
kernel, including the AXP USB, AC and battery devices. It is not an AXP-only
IRQ workaround. Validation here is for this board and pinned configuration;
unrelated platforms and hibernation are not qualified. A kernel built without
the suspend freezer would not gain this exclusion. The config fragment now
explicitly requests `CONFIG_SUSPEND_FREEZER=y`, and diagnostic configuration
checks require both that option and `CONFIG_FREEZER=y`.

The full resolved configuration already had both options enabled, so making
the requirement explicit does not itself change the running feature set.
Normal systemd sleep remains disabled; the power button still shuts down.

## Why this closes the notification path

The original worker calls linked consumers, updates LED triggers, calls the
blocking notifier and formats a uevent. These operations can read volatile
PMIC properties. The bus read happens in kernel context even when userspace
is frozen. A wake hold or late runtime-PM disable alone cannot exclude that
read; report 68 traces the active-RSB exception.

The pinned workqueue implementation gives the replacement a stronger ordering:

1. `suspend_prepare()` calls `suspend_freeze_processes()`. That freezes userspace
   and then kernel threads/workqueues **before** device suspension starts.
2. `freeze_workqueues_begin()` sets freezable queues' active limit to zero.
   Work already counted as active, including work waiting for a worker, is
   allowed to finish. New work goes to the inactive list.
3. `freeze_workqueues_busy()` includes active/running work. Successful freezing
   therefore cannot precede completion of a notification that was already
   active. An unfinished callback blocks or fails freezing; it does not permit
   supplier shutdown to overtake it.
4. Once freezing completes, a USB/AC IRQ may still call `power_supply_changed()`.
   It records the change and wake hold, but the queued notification cannot run.
   Its LED/uevent getters therefore cannot overlap device or RSB noirq shutdown.
5. `suspend_devices_and_enter()` runs `dpm_resume_end()` before returning to
   `suspend_finish()`. Only then does `thaw_processes()` thaw workqueues. The
   saved notification can run after suppliers' resume callbacks have finished.

This ordering also covers an ordinary/late/noirq failure followed by device
unwind. A freezer-only test or failure before device suspension thaws while
devices are still available. No new cleanup path is introduced.

Primary code: [workqueue freeze/thaw and active accounting][workqueue],
[process freezer][process], [suspend freezer wrapper][power-header],
[system suspend sequence][suspend]. The upstream
[workqueue documentation](https://docs.kernel.org/core-api/workqueue.html)
describes freezable queues as draining active work and postponing new execution
until thaw. The [freezer documentation](https://docs.kernel.org/power/freezing-of-tasks.html)
explains the separation of userspace and kernel freezing.

This deliberately uses the existing global freezer boundary. A one-time flush
would allow new IRQ arrivals to restart work. Driver-local flags would need a
new replay and wake-accounting contract and would not cover the framework's
initial deferred-registration notification. The latter still calls
`power_supply_changed()` and now reaches the same freezable queue; it does not
itself read properties. Its queue is unchanged.

## Events, wake holds and the PHY

Multiple pending changes retain the existing coalescing semantics: clients
receive the current state, not a guaranteed record of every cable edge. The
patch does not clear `changed`, discard queue attempts, synthesize a cable
state or release the wake hold early. When another change arrives during
delivery, the existing lock/flag logic keeps the hold until subsequent work
has processed it. Queueing after the producer releases `changed_lock` is safe
across the freeze boundary: the workqueue lock decides whether that arrival
is active or deferred.

With wake-count checking armed, an arrival whose notification is deferred can
abort suspend. The work runs after abort/unwind thaws the queue and then
releases its hold. That is preservation of an event requiring attention, not
a reason to force `pm_relax()` during suspension. The current direct-write PM
debug helper does not arm `wakeup_count`; bus exclusion still follows from
the freezer independently of that wake-event policy.

A notifier that ran before freezing can already have queued the PHY's
nonfreezable delayed scan. Patch 0013 does not retroactively freeze that scan.
[Patch 0012](69-usb-phy-suspend-work.md) independently drains/disables it during
ordinary device suspend and reconciles cable state on resume. Both patches
are therefore included in the next candidate. Neither replaces patch 0010's
drain of the AXP driver's private polling worker.

Both the old and new system queues are per-CPU queues in the pinned source;
the new queue adds the freezer flag. No awake polling frequency, charger
setting or IRQ wake selection changes. No latency, energy or endurance saving
is claimed from source inspection.

## Reproducible verification

```sh
task test:power-supply-suspend
task check:power-supply-driver
task check
```

[The checker](../tools/check-power-supply-suspend.py) verifies the locked source
archive, applies the patch without fuzz and extracts the actual
`power_supply_changed()` and `power_supply_changed_work()` functions.
[The harness](../kernel/tests/power_supply_suspend_test.c) uses deterministic
workqueue, freezer, wake and downstream-callback shims. It does not execute
a kernel scheduler, physical IRQ controller or PMIC bus.

**68 modeled scenarios passed natively and on emulated ARM32**, covering awake
coalescing, already-active work at freeze entry, arrivals while frozen, a
producer interrupted between unlocking and queueing, new changes during
consumer/LED/notifier/uevent delivery, group-update failure, early abort,
post-resume state delivery, wake enabled/disabled and four consecutive cycles
on the same supply instance. Assertions require no downstream access while
suppliers are unavailable, eventual current-state delivery, and balanced wake
holds without losing a concurrent change.

Five native negative controls compiled and failed their intended assertions:
the original nonfreezable queue, removed queueing, lost change flag, missing
wake hold, and unconditional early relaxation. The original reached a modeled
property-reading callback while suppliers were unavailable. These are modeled
failure demonstrations, not observations of a fault on the GameShell.

The complete ARM power-supply core compiled with the whole project patch queue
and locked configuration in isolated scratch. Its object SHA-256 was
`5fb76e3f5f2bca7dea20dd64d2f30c099482720b8c0203831dae3e3ebc67325b`.
This isolated check preceded the diagnostic.11 version bump; full image build
evidence is recorded separately. The host suite passed 266 tool tests (one
optional skip), 13 runtime tests, compiled helper checks and Bash/ShellCheck.
Linux checkpatch reported zero errors and warnings.

Private evidence is under `.local/build/power-supply-suspend-tests/`, including
`compile-evidence.json`, each negative-control assertion, audited freezer-source
hashes and isolated `kernel-1cb4a5c244d9a163/` source/output. Build logs are
`.local/build/power-supply-driver.log` and `.local/neo51-check.log`.
`task build` now includes the source regression. The underlying archive is
Linux v6.18.54, SHA-256
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`.

## Remaining qualification

First repeat the saved freezer/devices tests, both network recovery checks,
ordinary cable detection and keypad/input recovery on the candidate image.
The source proof establishes this worker's ordering, not absence of every
possible PMIC client or a successful physical suspend.

Before progressing to later PM stages, record the actual supplier topology
and bus cutoff/restore order and finish the ADC/regulator/client inventory.
Before real sleep, resolve nested-to-parent wake-error propagation, power-key
event consumption and critical-battery policy. The radio suspend-error and
firmware/rail-restoration follow-ups also remain. Successful ordinary debug
tests do not establish actual sleep current or wake reliability.

A separate lifetime question found during this audit is recorded in
`FOLLOW-UP.md`: `power_supply_unregister()` cancels `changed_work` before
joining deferred registration, whose callback can queue a change. Establish
whether a late deferred callback can outlive the first cancellation before
changing that unrelated teardown path. No teardown defect is claimed as
reproduced or fixed here.

[workqueue]: ../.local/build/power-supply-suspend-tests/patched/kernel/workqueue.c
[process]: ../.local/build/power-supply-suspend-tests/patched/kernel/power/process.c
[power-header]: ../.local/build/power-supply-suspend-tests/patched/kernel/power/power.h
[suspend]: ../.local/build/power-supply-suspend-tests/patched/kernel/power/suspend.c
