# brcmfmac retained-power rollback and failed-wake isolation (NEO-62)

1 October 2026, Pacific/Auckland. Third implementation slice of
[NEO-58](80-brcmfmac-suspend-failure-audit.md), following truthful low-level
sleep results in [report 81](81-brcmfmac-sleep-error-propagation.md) and the
bounded worker collector in [report 82](82-brcmfmac-freezer-lifecycle.md).
This slice checks the retained-power transaction and makes an unrecovered
restore leave Wi-Fi unavailable with an explicit error. It does not install
an image, invoke device commands or qualify physical sleep/recovery.

## Resulting behaviour

[Patch 0016](../kernel/patches/0016-brcmfmac-pm-rollback.patch) replaces ignored
PM results with checked stages and records ownership across F1 suspend and
F2 resume. The normal power-off-card branch still removes and reprobes using
its existing lifecycle; no board capability, WoWLAN or radio-power policy is
changed.

| Stage or failure | Behaviour |
| --- | --- |
| Preflight | Reject an active retained transaction, a latched PM failure, a bus that is not DATA, or unsupported host power/wake flags before collection. Retry an outstanding OOB wake-reference cleanup before acquiring another reference. |
| Collection | Preserve patch 0015's bounded wait and outstanding-waiter protection. Collection timeout still performs no radio/host-state transition. |
| Quiesced | Stop the watchdog, claim the host and recheck DATA before taking the bus DOWN. Unexpected loss of state at this boundary does not authorize publishing DATA again. |
| Radio sleep | Check its result. A failure enters local rollback; the uncertain-state handling in patch 0014 makes the subsequent wake reconcile a possibly applied partial sleep. |
| Wake configuration | Check OOB wake-enable and record ownership only on success. Set the host PM flags last. Mark the retained suspend committed only after that setter succeeds. |
| Suspend rollback | Attempt cleanup only for an owned wake reference, request checked radio wake while workers remain parked, and preserve the original suspend errno. Log secondary cleanup/restore errors separately. |
| Normal resume | Consume the committed transaction once, clean up its wake reference and check radio wake. On successful restoration, publish DATA, restart the watchdog and thaw. A cleanup error is still returned. |
| F2 after failed F1 | Retry a still-owned IRQ cleanup if necessary, but do not wake the radio or thaw a second time after F1's local rollback. |
| Failed restoration | Latch the failed-PM condition under the SDIO host lock, keep the bus unavailable, finish pending control requests with an error, stop interrupt producers and release freezer waiters. Do not restart the watchdog or publish DATA. |

A subsequent wake-policy change cannot route a failed device through the
power-off/probe branch. Likewise, an owned retained transaction is resumed
using its recorded ownership even if the current WoWLAN selection has changed.
A duplicate F1 suspend is also rejected before that changed policy can select
the power-off branch.

The host flag setter modifies a shared host-wide field only on success. This
patch never clears that field or attempts to undo another function's request.
The transaction has no later failing step after successfully setting those
flags. Host-core suspend/resume still owns their lifecycle.

An unsuccessful OOB disable retains the driver's ownership bit, because the
IRQ core retains its wake-depth reference on that error. Later F2 cleanup, a
new suspend preflight or IRQ teardown can retry it. A failed enable acquires
no reference and must not be paired with a disable. If the underlying IRQ
controller persistently refuses disable even during final teardown, the
driver logs the failure; this patch cannot promise hardware cleanup in that
case. There is no silent claim that a failed disable balanced the reference.

This ownership covers PM-acquired references. The separate OOB registration
probe still ignores its own disable result; a reference leaked there is a
remaining generic OOB issue recorded in [FOLLOW-UP.md](../FOLLOW-UP.md).
CPI v3.1 uses the in-band path. The tests do not claim to qualify the entire
OOB registration lifecycle.

## Failed-wake I/O boundary

DOWN is not an I/O lock: the original DPC and watchdog can access registers
before their state checks. The new `pm_failed` latch therefore guards actual
access boundaries, not just state publication:

- F0/F1 byte reads and writes check the latch, including callers with no
  error-output pointer. Blocked reads return the accessor's error value and
  report `-EHOSTDOWN` when an error pointer exists.
- Backplane-window selection checks before the cached-window shortcut, so
  32-bit register accesses cannot bypass it. Packet reads/writes and scatter-
  gather request submission also reject a latched failure before submitting
  a transfer. RAM and firmware-debug transfers use these guarded paths.
- A released data worker skips DPC execution after failure. A watchdog skips
  its work after returning from its freeze checkpoint. IRQ and DPC-trigger
  entry points reject an observed failed state. State publication refuses
  DATA while the failure latch remains set. An IRQ already past its early
  check may still queue work; the data-worker and host-serialized accessor
  gates remain responsible for preventing that work's firmware I/O.

The latch is set while the PM owner holds the same host lock required by SDIO
accessors. An earlier host-locked transfer must finish before it is set; a
later host-locked transfer sees the latch before reaching the SDIO operation.
Fast worker/IRQ checks avoid unnecessary processing, while the accessor checks
provide the final boundary for a caller that passed an earlier check.

On an unrecovered failure, OOB is masked once under `irq_en_lock`. The OOB
handler now uses that same lock, preventing competing handler/PM masks from
both incrementing IRQ-disable depth. In-band handlers are released through
the SDIO core; that core detaches each software handler before attempting the
card's IENx update, and shuts down host IRQ delivery when the last handler is
removed. Errors from the IENx update are logged. These core IRQ-management
commands, and later normal function-disable teardown, are deliberate card
management operations; the firmware register/packet I/O ban does not pretend
that absolutely no MMC command can occur.

### Control requests and debug cleanup

TX control publication now holds the SDIO host lock from its state check
through publishing the pending request. A PM failure under that lock either
finds the published request and completes it with `-EHOSTDOWN`, or rejects a
later producer before publication. Response waiters include the failure latch
in their wait predicate and are awakened when it is set. RX cleanup disposes
of its saved response buffer before returning the failure.

The error-path review also found two early returns in the debug assertion
reader that leaked its host claim when a RAM read failed. New I/O rejection
could expose that existing defect between a successful shared-data read and
a later assertion read. Both exits now release the host before returning.
The normal and debug configurations are compiled separately so this fix is
not validated solely as extracted C.

## Recovery policy and remaining boundaries

Successful rollback restores service and permits another suspend attempt.
If the wake needed for rollback, or the wake during ordinary resume, fails,
the policy for this slice is **reported unavailability until a cold restart
creates a new device lifetime**. The failure latch is not cleared by a later
suspend/resume request, an interface toggle or the existing debug reset path.
The latter returns `-EHOSTDOWN` before teardown when the latch is already set.
No firmware crash is fabricated, no coredump is requested and no new recovery
worker or retry loop is introduced.

This is deliberate failure containment, not automatic Wi-Fi recovery. A
fresh driver object alone does not prove the physical radio was reset;
module reload/unbind is not qualified as the recovery procedure. Even the
cold-restart outcome still needs hardware qualification after fault injection
can be performed safely. USB management remains the intended independent
access path for those later tests.

As in report 82, this work relies on the existing serialized PM callbacks,
stable device ownership and ordered worker lifecycle. It does not establish
that an already-running reset/removal operation can race safely with PM.
The new reset guard rejects entry after the latch; it is not a drain or a
lock against a reset that entered earlier. Audit and test that ownership
boundary before introducing automatic recovery or calling this complete
PM hardening. The existing reset helper also has host-reset result/reprobe
limitations documented in report 80.

Normal in-band IRQ delivery during the sleep-to-wake interval also needs a
separate ordering check: its status read is independent of the collected data
worker and watchdog. The host lock serializes transfers but does not by itself
prohibit a transfer between the PM sleep and wake operations. This patch's
failed-restore latch is not a proof of normal IRQ quiescence throughout the
transaction. That source investigation is tracked before hardware qualification.

Collection retains its five-second wait budget. Hardware sleep/wake, SDIO
host acquisition, IRQ teardown and scheduling do not gain a hard wall-clock
bound from that collector timeout. No latency or energy reduction is claimed.
The gates add small checks to accessors, and control publication adds a host
claim; their cost has not been benchmarked.

## Reproducible checks

```sh
task test:brcmfmac-pm
task check:brcmfmac-pm-drivers
task test:brcmfmac-freezer
task test:brcmfmac-sleep
task check
```

The [checker](../tools/check-brcmfmac-pm.py) verifies the locked archive and
applies patches 0014–0016 with zero fuzz. It extracts the actual PM/freezer,
worker, IRQ, control-request, debug-cleanup and access-boundary bodies into
the [test harness](../kernel/tests/brcmfmac_pm_test.c). The original freezer
fixture is shared; its successful/timeout/lifetime cases run against the new
callbacks as well. The teardown function is given a separate test entry name
without changing its body; the legacy power-off test retains its removal seam.
The checker also verifies that patch 0016 leaves all five previously tested
sleep/clock helper bodies unchanged.

[Hardware/API seams](../kernel/tests/brcmfmac_pm_shims.h) provide scripted
results and count attempted transfers. Pthreads, controlled pauses and a
recursive host mutex exercise selected real concurrent schedules. The IRQ
release seam models the core's handler-detach contract; it does not execute
the MMC core, IRQ controller or physical card. TX/RX protocol processing,
electrical state and kernel scheduler/weak-memory behaviour are not reproduced.
Tests therefore establish the stated source contracts, not exhaustive race
freedom or hardware recovery.

**89 scenarios pass natively and on emulated ARM32:** 44 existing freezer
lifecycle scenarios and 45 additional PM/control/I/O scenarios. The latter
cover:

- Failure at sleep, OOB enable and host flags, each with successful or failed
  rollback; preservation of the primary error and another function's flags.
- Normal wake failure, failed in-band IRQ cleanup, persistent OOB cleanup
  errors, idempotent F2 handling and prevention of duplicate wake references.
- Unsupported capability/state preflight, state loss during collection or
  before wake, and a changed wake policy with an owned or failed transaction.
- TX publication racing host-locked failure, pending TX/RX completion,
  successful control handling and a raw-access caller waiting for the host.
- Byte/register/packet/scatter-gather access with the latch clear or set,
  cached or changed windows, and nullable error pointers.
- Both debug assertion-read errors and success, IRQ teardown cleanup,
  competing OOB masks, a parked watchdog released after failed wake and an
  immediate retry while a failed-restore waiter is still retiring.

**25 negative controls fail by assertion**, including discarded transition
errors, lost primary errno, missing transaction/wake ownership, discarded
disable ownership, missing failure latch, worker/watchdog/IRQ/trigger/access
gate removal, missing TX publication serialization, lost control error/wakeup,
lost IRQ quiescence or OOB serialization, and a reintroduced debug host leak.
The checker rejects compilation failure, process timeout and an unexpectedly
successful negative control.

The complete `brcmfmac.o` composite ARM driver compiles against the full patch
queue in both the locked diagnostic configuration and an isolated
`CONFIG_BRCMDBG=y` configuration. Both pass the 164 diagnostic configuration
assertions; the helper also verifies that the requested debug option survived
configuration resolution. This checks all driver translation units consuming
the changed header. It is not a kernel/image build or module-load test.
Kernel `checkpatch.pl` reports no errors, warnings or checks for patch 0016
(read on standard input so its tracked-file autodetection does not inspect
the patch container as source).

The shared `task check` passes 13 runtime tests, 276 tool tests (one optional
skip), both compiled helper checks and shell lint. The separate legacy freezer
regression passes its 44 native/ARM32 cases, PM-disabled case and 10 negative
controls. The sleep regression passes 95 native/ARM32 cases, including 43
unchanged successful transfer transcripts, its debug configuration and 12
negative controls. Their final reruns are recorded in the logs below.

## Evidence and provenance

Final authoritative evidence is
`.local/build/brcmfmac-pm-tests/compile-evidence.json`, including archive,
original/patched source, tool/harness and contract hashes; per-variant native
results; ARM32 results; and both configurations' compiler/object identities.
Per-variant text outputs are saved beside it. Final complete-driver scratch:

- Normal: `.local/build/brcmfmac-pm-tests/kernel-5a41292445c1ec6e/`.
- Debug: `.local/build/brcmfmac-pm-tests/kernel-aeb4c3aed147e720/`.

Logs: `.local/build/brcmfmac-pm-drivers.log`,
`.local/build/brcmfmac-freezer.log`, `.local/build/brcmfmac-sleep.log` and
`.local/build/neo62-check.log`. Existing images, installed modules, diagnostic
kernel objects and recovery artifacts are not replaced.

The unchanged source lock selects Linux 6.18.54, upstream commit
`1b357ecb321392158d507b04672ffee57bfa071d`, archive SHA-256
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`.

| Patched file under `drivers/net/wireless/broadcom/brcm80211/brcmfmac/` | SHA-256 |
| --- | --- |
| `bcmsdh.c` | `7be3fe625fae5efd50574a23195951984fa56e35cf627e61b4bda6cca60abff0` |
| `sdio.c` | `886a3ee8dd7d3baf4d21e2352b081a712599da7029f4e1fa14ef8d9cbd569dba` |
| `sdio.h` | `83525822f01a204c11270cf7a34332fd60043b75d97fbfc767e81d79a7f901b4` |

Local primary contracts inspected from the verified source are
`drivers/mmc/core/sdio_io.c` (host flags and accessor conventions),
`drivers/mmc/core/sdio_irq.c` (IRQ detach/host-delivery ordering),
`kernel/irq/manage.c` (wake-reference errors) and the driver files above.
Report 80 provides pinned source links and the earlier ownership audit.
The test checker records these contract hashes rather than relying on a
moving upstream branch.
