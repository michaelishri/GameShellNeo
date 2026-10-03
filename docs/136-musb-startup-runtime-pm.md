# MUSB startup power failures and teardown boundaries

4 October 2026, Pacific/Auckland. NEO-102.

The separate [work/musb-startup-pm](https://github.com/michaelishri/GameShellNeo/tree/work/musb-startup-pm) candidate checks controller power-up
before continuing MUSB probe or publishing a newly started gadget driver.
It extends the NEO-98 wake-ownership branch; staged diagnostic.18 and the
installed diagnostic.17 are unchanged. This is source-level robustness work,
not a measured boot-time or battery improvement.

## What was wrong

The pinned Linux 6.18.54 MUSB core calls `pm_runtime_get_sync()` during
`musb_init_controller()` without checking its result. It then initializes
the USB PHY, creates DMA resources and writes controller registers. Gadget
start likewise ignores its get result, installs the function-driver pointer,
changes peripheral state and starts the controller.

`pm_runtime_get_sync()` increments the usage count even when resume fails.
Ignoring a negative return therefore has two distinct consequences: code
continues without a successful power-up contract, and cleanup must still
account for that reference. The return is not simply a powered/unpowered
boolean: the underlying resume operation can return positive success.

The Sunxi backend explicitly retains a runtime-PM reference to prevent
unsupported controller runtime suspend. That makes this a shared-driver
error-handling finding, not evidence that the GameShell has experienced this
particular power-up failure. Its backend reference is separate from the core
reference acquired around probe or gadget start.

## Candidate behavior

[Patch 0029](https://github.com/michaelishri/GameShellNeo/blob/work/musb-startup-pm/kernel/patches/0029-musb-startup-runtime-pm.patch) makes two
bounded changes:

| Entry | Successful power-up | Failed power-up |
| --- | --- | --- |
| Controller probe | Preserve the existing PHY, DMA, IRQ, role and wake setup; release the temporary core reference normally. | Preserve the error, disable runtime PM, clear autosuspend use, exit the initialized platform backend and free the allocated instance. Do not enter core USB-PHY initialization, DMA allocation or register setup. |
| Gadget start | Preserve existing gadget ownership, role, controller start and reference release. | Return the original error before changing connection intent, the gadget-driver pointer, active state or peripheral role; UDC core leaves its `started` flag clear. |

Both use `pm_runtime_resume_and_get()`. Its actual inline implementation
balances a negative resume result with `pm_runtime_put_noidle()` and
normalizes both successful lower-level return values to zero. No later put
is owed for its failed acquisition.

On failed probe, runtime PM is disabled **before** clearing autosuspend use.
This ordering matters: `__pm_runtime_use_autosuspend()` calls
`update_autosuspend()`, which can call `rpm_idle()`. Unlike the existing
post-acquisition unwind, the failed-get path has no temporary core reference
protecting it from an idle callback. Disabling first closes that path. Normal
post-acquisition cleanup retains its existing ordering and counted reference.

The USB PHY initialized by the core has not been acquired at the failed-get
point. The path therefore skips `usb_phy_shutdown()` while still exiting the
already initialized platform backend. On Sunxi, that backend owns its generic
PHY, clocks/reset and retained runtime reference; those are separate resources.

The runtime-resume comment is updated to name the new acquisition helper.
There are no new retries, timers, delays, charging settings or live controls.
Patch numbers 0027–0028 belong to the separate WFI candidate and are not
dependencies of this branch.

## Reproducible source checks

Run these existing tasks from the candidate branch:

```sh
task test:musb-sleep
task check:musb-wake-configs
task check
```

The first task reads the SHA-256-locked Linux archive, applies MUSB patches
0011/0025/0026/0029 with zero fuzz, and extracts actual functions. In addition
to the MUSB/IRQ functions already covered by NEO-98, it now executes
`pm_runtime_get_active()`, `pm_runtime_resume_and_get()` and the UDC class's
`usb_gadget_udc_start_locked()`. The runtime-PM engine, allocation, hardware
access and backend calls remain controlled test boundaries.

The expanded probe harness tests host, peripheral and dual-role startup,
with and without a backend-held reference. It injects `-EIO`, `-EBUSY`,
`-EACCES`, `-EPROBE_DEFER` and `-ETIMEDOUT`, plus zero and positive success.
On failure it checks the exact error, no retained core/backend reference,
disabled runtime PM, no core PHY/MMIO/DMA/IRQ setup, and a successful later
reprobe. Existing wake failures, foreign ownership and ordinary remove paths
remain covered. Failed-power removal itself is not covered.

The new gadget-start harness tests the same return values with a generic PHY,
a legacy transceiver without ID, and a legacy transceiver reporting ID; each
runs with zero or one preexisting reference. It checks no state publication
or hardware boundary calls after failure, UDC's clear `started` flag, successful
retry, one success-side put, expected VBUS behavior, already-started rejection
and invalid-speed rejection before any power acquisition.

| Source group | Native and ARM32 scenarios |
| --- | ---: |
| Existing sleep, connection, IRQ wake and per-IRQ PM | 106 |
| Probe/remove and extended startup failures | 141 |
| Gadget startup through the actual UDC wrapper | 42 |
| Total | 289 |

The negative controls deliberately remove checks or reference releases,
publish failed starts, skip backend cleanup, clear autosuspend before disabling
PM, or treat positive resume success as failure. They must fail assertions;
a compiler failure does not count as a successful negative control.

All 289 scenarios pass natively and under ARM32 emulation. All 32 native
negative controls fail the intended assertions. The complete changed ARM
MUSB objects also compile in six configurations: the unchanged board
configuration, host-only, dual-role, module, no system sleep and no PM.
Alternate configurations are compile-only and do not replace the board
configuration. The PM-disabled header's resume stub returns positive success;
the helper's normalization preserves successful startup in that build.

`task check` passes 13 runtime and 466 tooling tests (two existing skips),
the compiled current-limit and Mac mount-guard checks, Bash syntax and
ShellCheck. Kernel checkpatch with `--no-tree --no-signoff` reports zero
errors and warnings. The signoff exclusion does not claim an upstream
submission or maintainer review.

Local evidence, relative to the candidate worktree:

- `.local/build/musb-sleep-tests/matrix-evidence.json`: native controls,
  ARM32 results, input hashes, pinned builder, configurations and object hashes.
  SHA-256: `8dc85c961dac103c12e75341487135c13343eb154e74b96ac09a83d22087adad`.
- `.local/build/musb-wake-configs.log`: complete final run; earlier fixture
  compile failures and the superseded ordering run are not passing evidence.
- `.local/startup-repository-check.log`: repository regression/lint results.
- Patch 0029 SHA-256:
  `6c2193b516144840cc0d367161dd1a454eeb92c0472fee7ef26d576ddcb7a54b`.

All six configuration/object records and the input hashes were checked against
the retained files after the run. The obsolete scratch for the interrupted
ordering candidate was removed before rebuilding; recovery images, live-device
captures and the staged diagnostic.18 were not changed.

## Why stop and remove need a separate fix

`musb_gadget_stop()` still ignores its PM-get result before HNP handling,
controller stop, PHY mode changes and pull-up access. However, changing it
to return early on error is unsafe: `usb_gadget_udc_stop_locked()` ignores
the integer callback result and clears its own `started` flag. The unbind
path subsequently clears class-driver ownership, while an early-returning
MUSB stop could retain its pointer to that driver.

Platform removal is a `void` callback. `musb_remove()` cancels core work,
gets runtime PM, removes host/gadget clients, masks controller interrupts,
exits the backend and releases DMA/PHY/IRQ resources. Its get is unchecked.
A failed get does not give remove permission to abandon all these owned
resources; simply skipping a few direct writes also does not prove that host,
endpoint, PHY or DMA cleanup avoids inaccessible hardware.

The next design must distinguish logical detachment, callback retirement,
request completion, hardware quiescence and final resource release. It must
cover failed resume and subsequent unbind, not just ordinary teardown. Backend
reset/clock behavior and shared IRQ ownership need explicit treatment. This
candidate intentionally makes no stop/remove recovery claim.

## Additional unbind lifetime finding

UDC core documents and calls an `udc_async_callbacks` operation before the
function driver's unbind, then synchronizes the gadget IRQ when `gadget->irq`
is set. MUSB's pinned operations table supplies no such callback and its
gadget setup does not assign that IRQ field.

MUSB's suspend, resume and disconnect paths inspect `gadget_driver`, drop
the controller spinlock and invoke it; endpoint-zero setup similarly forwards
to the function driver after dropping the lock. The current implementation
does not provide UDC's requested suppression/synchronization mechanism for
this interval. The queued pull-up disconnect is not a substitute for a proven
callback-lifetime barrier. This is a source-identified concurrency gap; no
board crash has been reproduced or attributed to it.

A future fix needs to prevent new callbacks after suppression and drain any
already-running callbacks before unbind while preserving request completions.
It must avoid waiting under the controller spinlock or disabling unrelated
shared-IRQ users. Adding a boolean check or assigning an IRQ number by itself
does not establish that contract. This is tracked in `FOLLOW-UP.md` alongside
the failed-stop/remove work.

Other unchecked gets remain in ULPI read/write and `vbus_show()`. Session
tracking logs a failed `get_sync()` but retains its counted reference until
session clear; replacing that helper mechanically would change its ownership
semantics. Those paths are recorded separately and unchanged here.

## Limits and integration gates

These tests validate extracted C functions and deterministic boundaries, not
the complete Linux runtime-PM state machine, concurrent binding, interrupt
delivery, real register accessibility or electrical USB timing. In particular,
runtime disable may service a pending resume before disabling the device;
the tests do not model all parent/backend callback interleavings. The unchanged
initial-resume guard skips core context restoration before initialization.

There is no hardware fault injection, complete kernel link, new image or live
startup qualification for patch 0029. The branch inherits patch 0026's open
wake-ownership qualification gates and terminal-disarm limitation. Later
integration requires a new image/kernel identity, full build/offline checks,
fresh ordinary startup and PM prerequisites, then the agreed attended tests.
Diagnostic.18 remains the next isolated USB sleep-recovery trial.

## Primary-source audit

This audit uses the local, checksum-locked Linux 6.18.54 archive and the
candidate patch queue. Relevant upstream file paths and functions are:

- `drivers/usb/musb/musb_core.c`: `musb_init_controller`, `musb_remove`,
  `musb_free`, `musb_runtime_resume`, `musb_hnp_stop`, `musb_stop`, ULPI I/O,
  `vbus_show`, `musb_pm_runtime_check_session`.
- `drivers/usb/musb/musb_gadget.c`: setup/start/stop/cleanup, the operations
  table, `musb_g_suspend`, `musb_g_resume`, `musb_g_disconnect`.
- `drivers/usb/musb/musb_gadget_ep0.c`: `forward_to_driver`.
- `drivers/usb/musb/musb_host.c`: `musb_host_cleanup`, `musb_host_free`.
- `drivers/usb/musb/sunxi.c`: `sunxi_musb_init`, `sunxi_musb_exit`.
- `drivers/usb/gadget/udc/core.c`: UDC start/stop, asynchronous callback
  enable/disable, `gadget_bind_driver`, `gadget_unbind_driver`.
- `include/linux/pm_runtime.h`: `get_sync`, `get_active`, `resume_and_get`,
  and PM-disabled stubs.
- `drivers/base/power/runtime.c`: `__pm_runtime_disable`,
  `__pm_runtime_use_autosuspend`, `update_autosuspend`, `rpm_check_suspend_allowed`.

The pinned archive hash and builder identity are in
[sources.lock.json](../build/sources.lock.json). Existing wake and sleep
boundaries are documented in [report 131](131-musb-wake-irq-ownership.md) and
[report 126](126-musb-system-sleep-design.md).
