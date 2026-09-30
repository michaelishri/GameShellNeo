# AXP USB polling across suspend (NEO-38)

30 September 2026. Linux 6.18.54, CPI v3.1. This change is implemented and
cross-compiled; it is not installed on the GameShell yet. Diagnostic.7 remains
the running image. Actual sleep remains disabled for normal use.

## Problem and change

The AXP USB driver polls PMIC registers through RSB on a nonfreezable workqueue.
Its original suspend callback masks selected IRQs but neither drains nor
prevents rescheduling that work. A later RSB noirq callback resets and gates the
bus. Passing the devices debug stage does not prove the polling work is safe
across that later transition.

Patch `0010-axp-usb-suspend-work.patch` disables and drains the delayed work
before returning from the driver's ordinary suspend callback. It uses Linux's
`disable_delayed_work_sync()` API: an IRQ or the running poll's own retry cannot
requeue the work while it is disabled. Cancellation alone would leave that race.
Resume enables the work and requests the existing 50 ms check. This adds no
branch or lock to the ordinary polling path and changes neither polling
intervals nor charge settings.

The callback records whether the VBUS wake IRQ was actually armed. Resume
balances that state even if the requested wake policy changed. Failure to arm
wake aborts suspend and restores polling. Failure to disarm wake is reported,
but normal IRQ delivery and polling are restored; the next suspend first retries
releasing the outstanding wake reference rather than stacking another one.
The previous nested-IRQ selection is preserved.

## Repeatable checks

```sh
task test:usb-suspend
task check:usb-suspend-driver
```

Both verify the locked Linux archive and apply the relevant patches to a
separate test copy. The harness compiles the actual driver suspend, resume and
IRQ functions with deterministic workqueue/IRQ API shims. It passed 2,052
scenarios natively and under ARM32 emulation, covering two/four IRQ variants,
wake enabled/disabled, pending/running polls, arrivals during transition,
repeated cycles, policy changes and wake setup/teardown failures. Negative
controls reproduce failures for the original callbacks, cancellation without
disabling, missing rearm, rereading wake policy and ignoring wake-enable errors.

The compile task also builds the complete patched ARM driver with the full
project patch queue and kernel configuration in isolated scratch. It passed.
Evidence and exact input/object hashes are in
`.local/build/usb-suspend-tests/compile-evidence.json`; logs are under
`.local/build/`. These tasks preserve the installed image's build artifacts.
The source regression is included in `task build`.

## Limits and next hardware checks

The harness checks callback behavior against API contracts. It does not execute
kernel concurrency, physical wake delivery or RSB transactions. Repeat the
saved freezer/devices sequence on the next image, checking PM results, polling
recovery and fresh USB/Wi-Fi connections. Do not promote that result to a real
sleep or power-saving claim.

This fix covers the driver's delayed polling work. Separately, its IRQ handler
calls `power_supply_changed()`, which can queue power-supply notification work
on the ordinary system workqueue. Before late/noirq or actual sleep, trace and
qualify this notification chain and other PMIC users, including wake arrivals
and supplier ordering. A drained polling worker alone does not establish
exclusive RSB ownership. That remaining gate is recorded in `FOLLOW-UP.md`.

The experimental slow-poll and diagnostic controls retain their `PM_SLEEP`
refusal. Removing that guard, enabling another debug stage or enabling normal
sleep is separate work. No energy saving or wake latency has been measured for
this patch.

## Source basis

The hash-locked Linux archive in `build/sources.lock.json` supplies
`drivers/power/supply/axp20x_usb_power.c`, the disable/enable work APIs in
`kernel/workqueue.c`, power-supply notifications in
`drivers/power/supply/power_supply_core.c`, and RSB PM callbacks in
`drivers/bus/sunxi-rsb.c`. Patch 0010 is a project change to that source;
equivalent upstream behavior can replace it after verification.
