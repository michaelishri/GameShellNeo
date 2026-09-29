# Direct USB polling diagnostics: implementation notes

Date: **29 September 2026 NZDT**. Ticket: **NEO-28**.
Status: **source review and design; not implemented or hardware-qualified**.

Subsequent implementation and verification are recorded in
[report 51](51-diagnostic6-preparation.md). The status above describes this
design checkpoint, not a later build or hardware result.

## Purpose

The [battery comparison](45-usb-polling-idle-comparison.md) can compare software
power estimates and aggregate activity. It cannot establish how many times the
AXP USB polling callback actually ran. The next diagnostic image should expose
that count and let a bounded test exercise the callback's status-read error
branch without changing a PMIC register or making the shared register bus fail.

This remains diagnostic support for the explicitly opted-in CPI v3.1 experiment.
It does not widen the supported board, USB-role or suspend configuration.

## Relevant source and constraints

Reviewed the locked Linux **6.18.54** source and the repository's applied
[lifetime patch](../kernel/patches/0006-axp-usb-work-lifetime.patch),
[polling patch](../kernel/patches/0008-axp-usb-absent-poll.patch),
[board gate](../kernel/overlay/drivers/power/supply/axp20x_usb_gameshellneo.h),
and [actual-source test runner](../tools/check-usb-policy.py). Kernel API details
below come from that locked tree's `include/linux/debugfs.h` and
`fs/debugfs/file.c`, rather than an assumed API from a different kernel.

- `axp20x_usb_power_poll_vbus()` begins with one
  `regmap_read(AXP20X_PWR_INPUT_STATUS)`. This call site is the narrow injection
  boundary. USB property reads, IRQ handling and other PMIC consumers must
  continue to use the real register map.
- A failed initial read jumps to scheduling without replacing `old_status`
  or `online`. The experimental branch requests a fast retry even if the last
  good state was online. Stock scheduling uses the historical
  `vbus_needs_polling && !online` condition. An online stock read error does not
  itself establish a retry; tests must not accidentally assert experimental
  behavior for stock.
- IRQ work uses `mod_delayed_work(..., 50 ms)`. The experimental callback uses
  `queue_delayed_work()` so it does not postpone an already queued IRQ deadline.
  Counting and reads of diagnostic state must not schedule work or change these
  decisions.
- The running image's generated configuration has `CONFIG_HZ=100` and
  `CONFIG_DEBUG_FS=y`. Count actual callbacks and record elapsed time; do not
  promise exactly 20 or 4 calls per second from nominal delays. Worker execution
  and scheduling add to intervals.
- Existing devres order gives IRQ release, work cancellation, then supply
  removal. A diagnostic file must stop exposing the device before its memory
  can be freed, without weakening that existing lifetime order.

## Proposed interface and implementation boundaries

Use an independent, read-only-at-runtime diagnostic boot opt-in, default off.
Counting should also default off after an opted-in boot. This separates image
availability from active observation and leaves a cheap disabled path in normal
polling. Keep diagnostic opt-in identical in stock and experimental boot variants
when preparing matched count tests.

Factor the existing complete hardware/topology check so diagnostic availability
can be checked in stock mode too. Its current wrapper returns early when slow
polling is disabled; accepting that return as hardware verification would be
incorrect. Preserve the existing policy wrapper and its default-off behavior.
With both opt-ins disabled, avoid new probe-time PMIC reads. Both interfaces
must reject unsupported boards, PMICs, roles, sleep builds and topology changes.

Expose a root-readable snapshot and root-writable controls under one per-device
debugfs directory. Require an exact, bounded grammar and reject unknown commands
or out-of-range values. Suggested controls are count enable/disable, disarm,
and a separate bounded error-test request. Final file names and grammar belong
with the implementation and task documentation; these notes are not a supported
userspace ABI.

The counter snapshot should include:

- Actual callback entries and completed status reads, with in-flight work
  explicitly represented if an endpoint overlaps a callback.
- Successful reads, real read failures and injected failures as separate counts.
- Last good status and the selected stock/experimental policy.
- Counting state, pending injection budget and a measurement generation or
  equivalent identity that prevents mixing a reset with an earlier window.
- A monotonic timestamp taken at snapshot time. Normal counting does not need
  a high-resolution timestamp, event allocation or printk for every callback.

Use synchronization appropriate for coherent 64-bit values on ARM32. Never hold
a spinlock across regmap access, debugfs formatting or user copies. Initialization
must be complete before any IRQ-triggered callback can observe enabled state.
Counting enabled/disabled transitions and callbacks crossing a snapshot need
defined semantics, rather than silently losing or double-counting outcomes.

The locked kernel's normal `debugfs_create_file()` proxy protects active reads
and writes against removal. Use that lifetime support; avoid an unsafe creator
with an unprotected pointer into devm-managed device memory. Register diagnostic
cleanup after IRQ resources so it runs first during reverse unwind, then retain
IRQ release → work cancellation → supply removal. Open-file behavior during
removal still needs a regression and an explicit code review.

## Bounded error test

Simulate failure only in the polling callback's initial status-read wrapper.
An injected result skips that one read and returns a documented error such as
`-EIO`. It does not model electrical timing, a failing RSB controller or an IRQ
that never arrives. Those limits must appear in the hardware report.

Permit at most **four** injected failures per request with a **one-second**
expiration checked at the callback. A pending budget must expire before a later
cable event could unexpectedly consume it. Disarming must clear the pending
budget; disabling diagnostics must also disarm. Track injected failures separately
even when the chosen errno matches a real bus failure. A second request must
not silently extend an active request or turn a finite test into recurring faults.

Because online polling normally stops, an online error test may need an explicit
one-shot work request. Keep that action separate from count enable and status
reads, label it as synthetic work, and exclude such windows from natural polling
rate comparisons. It must not pretend to be a physical plug/removal interrupt.
Only this explicit test command may request the extra callback.

A bounded event record around an error request can expose read outcome, retained
status and selected retry delay. Do not create a continuous per-poll trace for
ordinary count windows. After the budget is consumed or expires, real status
reads resume without requiring the host connection to remain alive.

## Verification before an image is called ready

Extend the existing tests against extracted, patched driver source, using native
and ARM32 runs and the real compiled device-tree fixture. Required cases include:

| Area | Required evidence |
| --- | --- |
| Default path | Diagnostics off preserve callbacks, scheduling and probe-time reads. |
| Hardware gate | Stock diagnostics and experimental diagnostics both enforce the full gate. |
| Counts | Entries/completions/errors remain coherent across enable, disable, snapshots and an in-flight callback. |
| Fault bounds | Zero/disarm, accepted range, rejected oversized requests, expiration and overlapping requests. |
| Isolation | Injection affects only the poll status read; no shared-regmap faults or PMIC writes. |
| Recovery | Last good status is retained, experimental errors retry quickly, and stock behavior remains documented. |
| IRQ races | A slow requeue cannot replace an IRQ's fast deadline, including during an injected failure. |
| Lifetime | Partial probe, diagnostic creation failure, active/open files, IRQ teardown and pending work unwind safely. |
| Negative controls | Tests fail if the bound, state retention, IRQ deadline or cleanup order is deliberately broken. |

Compile the full driver in the locked ARM environment and inspect the resulting
image, not only the extracted callback harness. Shims do not prove kernel
concurrency or physical timing. Preserve diagnostic.4/5 recovery artifacts and
use a new image/kernel identity so tooling cannot confuse availability with the
currently installed diagnostic.5.

Provide checked-in tasks for count windows and error tests. Record boot identity,
active policy, exact diagnostic settings and before/after snapshots. Count windows
must avoid concurrent fast observers. Error tests must restore the diagnostic
controls on normal exit, interruption and host failure; the kernel-enforced
budget and expiration remain the final bound if userspace disappears.

Hardware deployment, matched natural counts and actual cable IRQ recovery remain
NEO-22 qualification steps. None of these source notes represents a completed
instrumentation implementation, a successful error-recovery hardware test or a
measured energy saving.
