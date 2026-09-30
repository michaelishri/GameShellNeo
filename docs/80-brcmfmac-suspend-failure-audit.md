# Retained-power brcmfmac suspend failure audit (NEO-58)

1 October 2026, Pacific/Auckland. Source-only research for the approved
retained-power suspend hardening task. **The audit establishes defects and a
candidate implementation sequence; it does not establish a complete, tested
repair.** NEO-58 remains in progress. No device command, network configuration,
firmware change, image build or hardware qualification was performed for this
audit.

A bounded freezer wait is useful, but adding a timeout and returning existing
errors is insufficient. The current freezer has shared-counter and completion
reuse hazards; bus state and watchdog restoration have different owners; and
lower-level sleep/clock helpers can suppress hardware failures. Those concerns
need explicit boundaries before implementation can claim reliable rollback.

## Sources and provenance

The source lock selects Linux **6.18.54**, upstream commit
`1b357ecb321392158d507b04672ffee57bfa071d`. The analysis read the local extracted
source at `.local/sources/linux-6.18.54/`, and verified the downloaded archive
against its locked SHA-256:
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`.
All five brcmfmac files below were compared byte for byte with that verified
archive and matched. The directory is an extracted tree, not a separate Git
checkout: `git -C` there ascends to the project repository and must not be used
to identify the kernel commit. [Source lock](../build/sources.lock.json).

| Verified file under `drivers/net/wireless/broadcom/brcm80211/brcmfmac/` | SHA-256 |
| --- | --- |
| `bcmsdh.c` | `c426bf7e8e18cdd763fb7e6b2c346254ff2d48f2d11d2d965a1733704e96e82c` |
| `sdio.c` | `9b35fe8d215b76c3f2e95acf37aff46e9623ff9ba35911cc732ffedb0dae5b78` |
| `sdio.h` | `245881dce2fc3a9765a547ed29a56c0761ccfbaf6d7406ad43081e0d509a2d1b` |
| `core.c` | `80b1c7ce93aa9f33bf18e836ee5e7b43ee2e8a8613efd5a4f96c289a8aed9c6e` |
| `bus.h` | `5c99cbafa3c881ea96ccdf8fd9f693e070da39a953c6e658d6c6f4634f73eab4` |

Source references below give file names and line numbers in this verified
baseline. Linked upstream files are first-party references pinned to the same
tag; the local source, rather than a current development branch, determined
the findings. No external secondary account was used.

[Report 54](54-staged-pm-diagnostic.md) records the board's retained-power
capability and earlier unbounded-freezer follow-up. [Report
76](76-wifi-resume-authentication-source-audit.md) separates those source gaps
from the observed post-association authentication delay: there is no evidence
here that these driver failures occurred in the recorded Wi-Fi outage.
[Report 68](68-pmic-suspend-ordering-audit.md) explains why worker lifetime and
PM phase ordering must be audited independently. This repair must not widen
normal sleep policy or reinterpret existing devices-stage qualification as
late/noirq or real-sleep qualification.

## Existing ownership and sequence

The real SDIO suspend callback runs for **function 1**; function 2 returns
success without performing that work. The real resume callback runs for
**function 2**. Retained-power suspend is selected when WoWLAN is enabled or
`MMC_CAP_POWER_OFF_CARD` is absent. Its sequence is freezer-on, watchdog stop,
optional OOB wake enable and host PM flags. The other branch unregisters
interrupts, cancels data/reset work and removes the device; its resume probes
again. [bcmsdh.c, lines 1179–1253][bcmsdh].

Freezer-on resets `frozen_count`, reinitializes a completion, sets `freezing`,
triggers the data worker and waits until `thread_count == frozen_count`.
It then requests bus sleep. The ordered data worker supplies one persistent
thread-count registration. The watchdog is counted while active and uncounted
while waiting for its timer completion. Both call `brcmf_sdiod_try_freeze()`.
[bcmsdh.c, lines 816–866][bcmsdh]; [sdio.c, lines 3757–3774, 4098–4122,
4475–4484][sdio].

The data worker currently owns the transition to DOWN immediately before its
freeze attempt and the unconditional transition to DATA after that attempt.
The PM callback separately owns bus wake and completion signaling. A transition
from SDIOD_DOWN to SDIOD_DATA calls `brcmf_bus_change_state(..., BRCMF_BUS_UP)`,
which wakes stopped netdev queues. Changing where DATA is restored therefore
changes when transmission can resume; it is not just bookkeeping.
[sdio.c, lines 3770–3773][sdio]; [bcmsdh.c, lines 199–220][bcmsdh];
[core.c, lines 1559–1583][core].

## Defects established by the source

| Finding | Source evidence | Consequence and limit |
| --- | --- | --- |
| Suspend discards freezer/bus-sleep failure. | `brcmf_sdiod_freezer_on()` returns the sleep error at 830, but suspend discards it at 1199. [bcmsdh.c][bcmsdh] | The retained-power callback can return zero after this operation failed. This is not evidence that it failed on the board. |
| The freezer wait is unbounded. | `wait_event()` at 825–826 has no deadline. [bcmsdh.c][bcmsdh] | A missing participant or accounting race can prevent callback return. A userspace recorder timeout cannot repair a stuck callback. |
| Two participants increment a plain `u32` without mutual exclusion. | `frozen_count++` at 852; callers are the data worker and watchdog. [bcmsdh.c][bcmsdh], [sdio.c, lines 3772 and 4113][sdio] | Concurrent read-modify-write increments can be lost. Making only this field atomic would not fix generation/lifetime races. |
| Uncount changes the wait condition without waking its queue. | `freezer_uncount()` at 863–866 only decrements `thread_count`. [bcmsdh.c][bcmsdh] | A waiter can sleep after observing two expected participants and one frozen participant; the active watchdog can stop its own timer and become uncounted, satisfying the condition without another wake. Watchdog idle stop is at sdio.c 3739–3747, uncount at 4110. |
| OOB wake enable failure is discarded. | Suspend calls `enable_irq_wake()` without checking its return at 1206. [bcmsdh.c][bcmsdh] | Suspend can continue without the requested wake source. The initial IRQ-registration wake probe at 120–125 does not guarantee that this later operation succeeds. |
| Host PM-flag failure is logged but not returned. | The result at 1211–1212 does not update `ret`. [bcmsdh.c][bcmsdh] | The host may not retain power despite apparent function-suspend success. |
| Resume discards bus-wake failure. | Freezer-off ignores `brcmf_sdio_sleep(..., false)` at 836 and always releases workers. [bcmsdh.c][bcmsdh] | DATA can be republished despite a failed wake operation. |
| Watchdog restart is attempted while the state is DOWN. | Bus wake calls `wd_timer(true)` at sdio.c 1009; that helper rejects start unless state is DATA at 4633–4634; worker restores DATA only after freezer-off signals it. [sdio.c][sdio] | The intended restart can be skipped. Later activity may restart it, so this is not proof that every resume leaves it permanently stopped. |

The atomics on `freezing` and `thread_count` do not provide the missing
multi-field publication protocol. Linux documents non-RMW atomic operations
and RMW operations without return values as unordered against other locations.
A lock protecting admission, counts and retirement is clearer than adding
isolated barriers to the existing plain counter. [Atomic API documentation,
lines 160–180][atomic-doc].

## Timeout and next-cycle race

The existing `complete_all()` leaves a completion permanently signaled until
reinitialization. Its implementation explicitly requires all waiters to have
finished before `reinit_completion()`; `completion_done()` cannot establish
that drain. [completion.c, lines 56–81][completion]; [completion documentation,
lines 78–100][completion-doc].

A timeout-only patch admits this schedule:

1. A worker observes `freezing`, then is delayed before incrementing or waiting.
2. Suspend times out, clears `freezing`, signals `resumed` and returns.
3. A new suspend resets the counter and completion.
4. The old worker increments the new cycle's counter or waits on the reset
   completion. Its eventual DATA transition can also occur in the new cycle.

There is also a race for a worker already signaled but not yet scheduled after
`complete_all()`. Merely changing `frozen_count` to an atomic does not distinguish
which cycle owns it. Merely adding a generation-number wait condition prevents
an old waiter blocking on the wrong signal, but does not prevent its subsequent
unconditional DATA write or watchdog work from crossing into a new cycle.
These are inferences from the cited control flow and completion contract, not
observed hardware traces.

A minimal completion-based candidate is:

- Protect `freezing`, `thread_count` and the outstanding frozen-waiter count
  with one spinlock. Admission tests `freezing` and increments the waiter count
  in the same critical section. Predicate snapshots use that lock too.
- Each admitted waiter decrements its outstanding count **after** its
  `wait_for_completion()` has returned, under the same lock, and wakes the
  predicate/drain queue. Count and uncount also wake that queue.
- Clear `freezing` and call `complete_all()` while holding the admission lock.
  Do not hold that lock over SDIO host acquisition, I/O, timer deletion or a
  wait. Completion waits release their internal lock before the decrement,
  so that operation need not invert the freezer/completion lock order.
- A new freeze may reinitialize the completion only while holding the lock
  and only if `!freezing && outstanding_waiters == 0`. Otherwise return
  `-EBUSY`, or first use a separate bounded drain wait and fail if it expires.
  Never reset a nonzero outstanding count.
- Move the data worker's DOWN/DATA writes to the central PM owner. The worker
  retains its freeze checkpoint but performs no stale state write after it.

This preserves the completion API with a concrete reuse proof. A generation
waitqueue is an alternative, but still needs participant retirement and bus
state ownership. The candidate requires actual concurrency tests; this audit
does not treat the pseudocode as implemented or verified.

## Candidate retained-power transaction

The following order makes rollback boundaries explicit. It is a design
recommendation, conditional on resolving the lower-level error and failed-wake
issues in the next sections.

| Stage | Owner and required behavior |
| --- | --- |
| Preflight | Establish a DATA-state precondition and that this callback owns no earlier suspend transaction. Compute flags. Reject unsupported host capabilities before freezing when possible, while still checking the real setter result. |
| Collect participants | Publish freezing under the lock, trigger DPC and wait with a finite deadline. A five-second bound is a proposed policy, not a measured hardware requirement. An outstanding previous-generation waiter prevents reuse. |
| Collection timeout | Clear admission and signal all admitted waiters under the lock; return `-ETIMEDOUT`. Do not acquire the SDIO host or issue a speculative wake: no PM bus sleep or watchdog stop has occurred yet. |
| Quiesced | After the count condition is satisfied, the central owner changes DATA to DOWN, stops the watchdog and attempts bus sleep. An uncounted watchdog that wakes must count and enter the freeze checkpoint before touching hardware, as its existing loop already does. |
| Wake configuration | Check OOB enable and remember ownership only after success. Set host PM flags last among operations that can fail, checking and returning their error. Mark a retained suspend transaction committed only after these stages succeed. |
| Suspend rollback | Disarm only an OOB wake reference successfully acquired by this transaction. If bus sleep was attempted, perform a wake that cannot be skipped by stale sleep-state caching. Keep workers parked during that attempt. Preserve the primary suspend error and separately log any rollback error. |
| Successful restoration | Restore DATA centrally, explicitly restart the watchdog **after DATA**, then retire the freeze and wake participants. Do not rely on the too-early restart inside bus sleep. Avoid restoring DATA over NOMEDIUM or an unrelated teardown state. |
| Failed restoration | Return the error, release freezer waiters, and do not claim a working DATA bus. A separate I/O gate and recovery policy are required; setting DOWN/NOMEDIUM alone is insufficient. |
| Normal retained resume | Act only on a transaction actually owned by this suspend. Disarm the owned wake reference, perform checked wake, restore the valid bus/timer state and retire the freeze exactly once. |

Centralizing DOWN after all participants park shifts the transmission cutoff
from the worker's freeze checkpoint to the PM callback's successful collection
boundary. Packets can still arrive during collection; queued work must resume
correctly after thaw. This timing change needs tests and must not be described
as behaviorally identical to the original pair of worker state writes.

The collection deadline does **not** bound SDIO host acquisition, every MMC
request, timer synchronization or firmware recovery. A patch should name the
bounded stage precisely. Introducing an unbounded waiter drain or workqueue
flush into the timeout unwind would defeat that specific guarantee.

### Host flags, OOB references and cross-function resume

`sdio_set_host_pm_flags()` rejects unsupported bits **before** modifying
`host->pm_flags`, and on success ORs bits into a host-wide field. A failed setter
therefore needs no host-flag clear. Passing zero does not clear earlier flags;
blindly restoring the whole field risks another function's requests. Keep the
setter last or explicitly design any later host-wide rollback. [sdio_io.c,
lines 709–738][sdio-io].

`irq_set_irq_wake()` maintains `wake_depth`. A failed first enable restores the
count to zero, so calling disable after that failure is unbalanced. A failed
last disable restores the count to one; clearing an ownership bit despite that
error loses a live reference. Preserve that error and ownership until a later
successful cleanup. [IRQ manage.c, lines 839–893][irq-manage].

F1-local rollback must not assume the PM core will call its resume: the core
sets `is_suspended` only after a successful suspend and skips resume otherwise.
Conversely F2's no-op suspend may already have succeeded, so F2 resume may run
during unwind after F1 failed and rolled itself back. Track explicit PM
transaction ownership so that this callback does not wake, disable an IRQ
reference, restore DATA or complete the same freezer twice. [PM main.c,
lines 1030–1046 and 1953–1957][pm-main]; [bcmsdh.c, lines 1188–1191,
1235–1250][bcmsdh].

## Lower-level failures limit the first patch's claim

Three additional findings prevent treating a zero `brcmf_sdio_sleep()` result
as comprehensive hardware-success evidence:

1. `brcmf_sdio_clkctl()` discards `brcmf_sdio_htclk()` failures in its state
   branches and returns zero. `brcmf_sdio_bus_sleep()` in turn ignores its
   clock-control result before setting `bus->sleeping`. Fixing only one call
   layer cannot propagate the original failure. [sdio.c, lines 784–900,
   916–1016][sdio].
2. `brcmf_sdio_kso_control()` can exhaust its retry limit with successful reads
   whose bits never match the target. It logs maximum attempts but returns the
   last access error, which can be zero. It needs a separate target-achieved
   condition and a timeout error when the condition was not established.
   Polling cleanup must still balance retune control. [sdio.c, lines
   699–778][sdio].
3. The sleep path reads CHIPCLKCSR and may write an ALP request, but proceeds
   to KSO control without checking those errors, overwriting `err`. This is
   another distinct error site. [sdio.c, lines 980–991][sdio].

Partial sleep failure also makes ordinary rollback incorrect. With SR enabled,
a KSO sleep write can have taken effect before a later read fails. On that
error, `bus->sleeping` retains its old false value. A subsequent ordinary wake
request matches that cached false value and skips KSO control, despite the
hardware state being uncertain. [sdio.c, lines 974–999 and 1011–1016][sdio].

Concrete alternatives are a PM-specific forced-wake operation, or a separate
validity flag for cached sleep state that is invalidated before a transition
and restored only when success is established. Do not simply invent a
successful hardware state to force a branch. If the initial patch intentionally
propagates only errors already returned by the existing helper, say that
explicitly and keep the deeper silent-success repairs as separately tested
slices. Correct partial-operation rollback remains required even for that
narrow claim.

## Failed wake and recovery are a separate lifecycle decision

Changing SDIOD state to NOMEDIUM does **not** suppress all worker I/O. DPC
claims the host and accesses registers before its later state check. The
watchdog's polling branch also lacks an initial DATA-state guard. Byte-access
macros call SDIO directly. A stopped timer does not cancel a watchdog thread
that has already received a completion. Any fail-closed design must gate those
actual paths, including a watchdog released from the freezer, and decide how
pending control requests are failed or resumed. [sdio.c, lines 2585–2627,
2726–2745, 3672–3754, 4111–4118][sdio]; [sdio.h, lines 291–304][sdio-h].

NOMEDIUM is terminal for `brcmf_sdiod_change_state()`, which refuses subsequent
state changes from it. Permanently setting it on a transient wake error would
therefore require a deliberate removal/reprobe recovery path. DOWN alone is
also not an I/O exclusion barrier. [bcmsdh.c, lines 199–220][bcmsdh].

There is an existing asynchronous reset route, but it is not a ready-made PM
recovery API:

- `brcmf_fw_crashed()` logs a firmware crash and takes a coredump before queuing
  reset. A sleep/wake error is not evidence of a firmware crash, and the
  coredump itself performs bus access. Do not call this helper to disguise a
  PM failure. [core.c, lines 1440–1467][core]; [sdio.c, lines 3605–3635][sdio].
- The internal reset scheduler uses ordinary `schedule_work()` under its
  removal lock. The lifetime guard is useful, but this queue does not provide
  a post-PM execution boundary. The reset callback unregisters IRQs, removes
  the brcmfmac SDIO object and invokes `mmc_hw_reset()`, ignoring its result.
  [core.c, lines 1172–1206][core]; [sdio.c, lines 4160–4178][sdio].
- MMC performs asynchronous removal/rescan when more than one SDIO function
  is probed; with a single function it power-cycles and reinitializes the card
  synchronously. Thus this is not an unconditional driver-reprobe guarantee.
  [MMC sdio.c, lines 1151–1180][mmc-sdio].

A possible later extension is to expose a reset request without coredump and
queue it on a freezable workqueue, retaining the existing removal gate.
For the ordinary suspend path audited here, `dpm_resume_end()` precedes process
and workqueue thaw, so such newly queued work would wait until device resume
has finished. The callback must first release and retire freezer participants,
then ensure that reset teardown cannot race live PM accesses; the reset result
must be handled. This remains a proposed design requiring separate lifecycle
validation, including aborts, removal and repeated failures. [suspend.c,
lines 529–555 and 607–612][suspend]; [process.c, lines 179–212][process].

An initial hardening change must state whether recovery is best-effort retry,
explicitly deferred reset or a reported unavailable bus requiring intervention.
It must not simultaneously claim fail-closed behavior and rely on ungated
workers to retry I/O. This audit does not select a fully proven automatic
recovery implementation.

## Preserve the card-power-off path

Keep the branch condition `!wowl_enabled && cap_power_off`, its interrupt and
work cancellation, device removal, reprobe and reset-work re-enable behavior
intact. Do not make it enroll in the retained-power freezer or restore a stale
retained-power timer, completion or IRQ reference. On successful reprobe,
firmware initialization publishes DATA independently. [bcmsdh.c, lines
1198–1250][bcmsdh]; [sdio.c, lines 4371–4383][sdio].

Do not add or remove board `cap-power-off-card`, `keep-power-in-suspend`, WoWLAN
or OOB capability as part of this failure-handling patch. The host core's
retained-power decision controls whether it powers the card off, so dropping
KEEP_POWER is not an innocuous alternative rollback. [MMC sdio.c, lines
1046–1068 and 1071–1125][mmc-sdio]; [board DTS](../kernel/overlay/arch/arm/boot/dts/allwinner/sun8i-r16-clockworkpi-cpi3.dts).

## Ordered implementation and validation slices

No code or test was added by this research task. The smallest reviewable order
is to establish the following contracts, without labeling the whole design
complete after the first slice:

1. **Freezer lifecycle and ownership.** Add locked enrollment/counting,
   wake-on-count-change, bounded collection, drained-before-reuse completion,
   central bus-state ownership and explicit committed-suspend tracking.
   Exercise actual extracted driver helpers with controlled interleavings:
   simultaneous participant entry; count decrease satisfying the predicate;
   timeout just before entry; timeout after entry but before wait; delayed
   waiter after completion; immediate next suspend; and repeated success/abort.
   Assert no host acquisition or timer stop on collection timeout, no stale
   DATA write and no completion reuse with an outstanding waiter.
2. **Retained-power error unwind.** Inject failures at sleep, OOB enable and
   PM flags. Verify original errno, single thaw, correct wake-reference
   ownership, and watchdog restart only after DATA. Include F2 resume after
   F1-local rollback, failure after successful OOB setup, disable failure and
   unrelated later-device suspend failure. Verify the power-off branch still
   removes and reprobes without touching retained-state bookkeeping.
3. **Hardware-helper return semantics.** Test KSO target mismatch until its
   deadline separately from SDIO read/write failure; clock enable/disable
   failures through both call layers; preliminary CHIPCLKCSR/ALP failures;
   and sleep write success followed by status-read failure. A forced wake
   must perform the required hardware operation despite a formerly false
   `bus->sleeping`. Assert retune cleanup and that failed operations never
   publish a successful clock/sleep state.
4. **Failed-wake I/O gate and recovery.** Choose and test a recovery contract.
   Include a queued DPC, an already-completed watchdog wake, IRQ arrivals,
   pending control requests, delayed thaw retirement, reset/removal races,
   both MMC reset modes and recovery failure. Do not let a modeled state flag
   substitute for observing whether the real access helpers were invoked.
5. **Compilation and qualification.** Compile the changed driver against the
   locked configuration and inspect lock ordering; meaningful native and
   ARM32 execution can check race/state logic but cannot prove kernel
   scheduling or hardware behavior. Subsequent owner-authorized PM testing
   must retain error/journal and independent network-recovery checks. An
   improved PM return value alone does not qualify radio recovery.

Prefer harnesses that execute the actual patched C helpers with controlled
wait, lock, timer and SDIO seams over a separate state machine that merely
repeats the intended design. A fault-injection seam must preserve the real
ordering it claims to test. The first three slices can establish bounded
collection and truthful, owned rollback; full failed-wake recovery still needs
its explicit fourth-slice decision.

## Primary source index

[bcmsdh]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/bcmsdh.c?h=v6.18.54
[sdio]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/sdio.c?h=v6.18.54
[sdio-h]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/sdio.h?h=v6.18.54
[core]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/core.c?h=v6.18.54
[sdio-io]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mmc/core/sdio_io.c?h=v6.18.54
[mmc-sdio]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/mmc/core/sdio.c?h=v6.18.54
[irq-manage]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/irq/manage.c?h=v6.18.54
[pm-main]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/base/power/main.c?h=v6.18.54
[completion]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/sched/completion.c?h=v6.18.54
[completion-doc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/Documentation/scheduler/completion.rst?h=v6.18.54
[atomic-doc]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/Documentation/atomic_t.txt?h=v6.18.54
[suspend]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/power/suspend.c?h=v6.18.54
[process]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/power/process.c?h=v6.18.54
