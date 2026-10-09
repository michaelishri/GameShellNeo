# MUSB pending-resume callback retirement

NEO-168, child of NEO-106. Host-only source candidate based on `c21f64d`
(NEO-167), on `work/musb-resume-retirement`, against pinned Linux 6.18.54.
No GameShell/Mac access, image operation, physical test or SSH investigation
is part of this slice. NEO-108 installation remains parked.

## Acceptance contract

Terminal controller teardown must close pending-resume callback admission,
drain callbacks already executing, and release queued callback records before
client/resource cleanup. It must cover immediate execution, queued execution,
and the gadget restart handed to a request completion. No new restart may
begin after closure. Pending USB requests must still receive their normal
cleanup completions, and any deferred-restart PM reference must be balanced.

Ordinary suspend/resume, endpoint disable/re-enable, nested callbacks and
first-error reporting must retain their behavior. Shutdown is permanent for
that controller allocation, idempotent, and distinct from normal suspend.
A fresh allocation starts open. Validate the actual source paths, real Linux
synchronization and relevant ARM configurations, then review before closure.
Do not claim complete removal safety or hardware/performance qualification.

## Source and ownership findings

The audited callers of `musb_queue_resume_work()` are:

| Producer | Borrowed data | Execution/ownership |
| --- | --- | --- |
| Gadget endpoint queue | `struct musb_ep *` embedded in the controller | One coalesced restart; endpoint request list owns the actual requests |
| DSPS OTG timer | `NULL` | Deferred status check; backend owns timer/controller lifetime |

The exported API does not transfer ownership of `data`. Freeing the small
`musb_pending_work` record cannot imply freeing that pointer or completing a
USB request. An out-of-tree caller must retain its own data until execution or
client cleanup; this audit establishes no additional caller ownership model.

The runtime-PM barrier from NEO-167 does not cover direct invocation from
`musb_queue_resume_work()`. The resume-list drainer releases `list_lock` before
calling a callback. Both paths normally hold `musb->lock`, but gadget giveback
releases it while invoking a request completion. Consequently, taking the
controller lock once does not prove every callback has returned.

A further handoff exists: if resume finds an endpoint busy in giveback, the
restart transfers to `musb_ep_finish_restart()` with an extra PM reference.
That later invocation can itself reach another giveback. Both its admission
and its already-running callback must therefore be covered.

## Implementation

Patch `0042-musb-resume-work-retirement.patch` adds a controller-local terminal
gate, callback count and wait queue. The existing controller lock protects
admission and count; list operations keep the existing controller-then-list
lock order.

`musb_invoke_resume_work()` accounts every invocation, including the deferred
gadget handoff. It preserves the callback return value and rejects invocation
after closure. Nested calls increase the count independently. Completion
wakes the teardown waiter only when the final callback exits during shutdown;
ordinary callbacks do not cause a new wait-queue wakeup.

`musb_shutdown_resume_work()` closes admission, waits with the controller lock
released when a callback is still running, then discards pending records.
It runs in process context with no caller-held controller lock and cannot be
called from its own callback. The wait queue is initialized with the pending
list before platform initialization can publish the controller. The allocation
finalizer is an idempotent fallback for early failures.

The list drainer rechecks closure after every callback. A callback which drops
the lock cannot let the drainer start the next record after teardown has
closed the gate. Client cleanup follows closure in normal removal and failed
role registration. PM-enabled failure entries close before the existing PM
barrier; pre-PM failure closes before platform exit. The runtime-PM, IRQ and
work retirement ordering from the preceding slices otherwise remains intact.

Gadget queue admission checks closure in the existing endpoint-disabled
rejection path, before adding a request to the endpoint list. This also covers
coalesced/follower queues which would not call the resume API. The rejection
unmaps the mapping made before taking the controller lock. The unrelated
pre-existing failed-work-allocation mapping issue remains separate.

Restart loops check closure before starting another head; completion-owned
handoffs use the common invocation accounting. Endpoint cleanup gives back
requests and releases a deferred restart hold normally, and clears the
coalescing flag for a terminally canceled record. Ordinary endpoint disable
keeps its prior behavior: clearing that flag unconditionally would let an old
pending record overlap a new one after re-enable.

## Reproducible validation

Run the saved tasks sequentially:

```sh
task test:musb-request-resume
task test:musb-probe-roles
task check:musb-irq-drivers
task test:musb-restart-kunit
task check
```

The request suite extracts the current candidate after retaining its original
0037 boundary audit. It exercises 52 scenarios per execution (26 per direction)
on native and ARM32, plus native real-free and negative-control variants. New
cases require rejection of both active and suspended queues without stranding
a DMA mapping or callback record, including a coalesced endpoint queue.

The role suite exercises the current initializer, preserving error/registration
ownership and checking closure before unregistering an owned role. Its retry
models a fresh controller allocation after failed probe, rather than reopening
a terminally closed instance. The teardown suite checks actual removal and
failure tails with a modeled resume barrier; it does not substitute that model
for the real synchronization tests.

The expanded `musb-restart` UML suite compiles the full queued MUSB driver with
KASAN, lockdep and atomic-sleep checks. Its original seven restart/giveback
regressions are joined by ten retirement cases:

- Cancel pending records, retain request ownership, reject completion requeue,
  complete each request once, and allow repeat shutdown.
- Reject active and suspended callback/gadget admission.
- Hold an immediate callback and a queued callback across shutdown; require
  shutdown to wait and reject new work. Queued work behind the held callback
  must never start.
- Retire a not-yet-started giveback handoff, preserving its PM hold until
  giveback returns.
- Hold a restart completion during immediate invocation and during an already
  running giveback handoff; require both to drain.
- Preserve nested invocation accounting/error return and accept work on a
  separate fresh instance.

Only hardware restart is intercepted in the gadget paths. Synthetic callbacks
open a scheduling gap on one UML CPU to expose lock-drop interleavings; these
are not real hard-IRQ timing or SMP tests. Device runtime state is staged and
a baseline PM reference prevents actual hardware power transitions. There is
no DMA engine or physical USB device in UML.

Receipts retain input hashes and outputs under `.local/build/musb-request-resume-tests/`,
`.local/build/musb-probe-roles/`, `.local/build/musb-irq-tests/` and
`.local/build/musb-restart-kunit/`. The UML suite retains the accepted kernel,
configuration, parsed results and raw log. Older separate PM/work/IRQ/sleep
suites are not claimed as executions of this candidate unless rerun.

## Results

Validation and review are in progress; no completion or hardware claim yet.

## Remaining boundaries

This closes the callback operation, not every caller frame or independent
producer which holds a controller pointer. Backend timers/notifiers, role
callbacks, parent PM, independent DMA callbacks and gadget-work ownership
still need their own admission and drain contracts. A late caller still needs
a live controller allocation to observe the gate. In particular, the DSPS
backend must retire its timer before freeing its controller; an API rejection
is not timer lifetime management.

Likewise, the handoff callback count is not a general USB request-giveback
lifetime barrier. Its PM hold can outlive callback admission until giveback or
endpoint cleanup discharges it; surrounding client/IRQ/backend ownership must
keep those frames and resources alive. The gate does not authorize early
resource release.

A platform initializer can already have released resources on its own error
path before core sees its failure. The allocation-finalizer fallback cannot
retroactively protect such backend-internal unwind. Runtime/system resume can
also access registers outside the callback helper. Existing failed-PM-get
hardware accesses, DMA ordering, MediaTek parent/child PM ownership and MPFS
parent-clock ordering remain open under NEO-106.

Separate notifier/backend candidates are not implicitly integrated. Full
image integration, physical rebind/removal and energy/latency measurement
remain future work. This patch adds small gate/count operations on the callback
path; it makes no speed or energy-saving claim.
