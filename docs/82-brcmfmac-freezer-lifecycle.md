# brcmfmac worker freezer lifecycle (NEO-61)

1 October 2026, Pacific/Auckland. Second implementation slice of
[NEO-58](80-brcmfmac-suspend-failure-audit.md), following the low-level sleep
error fixes in [report 81](81-brcmfmac-sleep-error-propagation.md).
Patch 0015 bounds worker collection and makes collection-timeout cleanup safe
across subsequent attempts. This is an intermediate driver patch, not a
hardware-qualified suspend implementation. No image or device change is part
of this slice.

## Problem and resulting behaviour

The original suspend callback waits indefinitely for the data worker and
watchdog to park. Their shared frozen count has unprotected updates, and a
watchdog withdrawing from the expected count does not notify the collector.
Adding only a timeout would create another problem: a subsequent suspend
could reset the completion while workers from the previous attempt still
depend on its signal.

[Patch 0015](../kernel/patches/0015-brcmfmac-freezer-lifecycle.patch) gives the
collection protocol one lock and explicit ownership of parked waiters:

| Boundary | Result |
| --- | --- |
| Begin collection | Under the freezer lock, reject an active collection or any outstanding parked waiter with `-EBUSY`. Otherwise reset the completion and admit workers. |
| Worker admission | Check the active flag and increment the frozen count under that same lock, notify the collector, then wait without holding the lock. |
| Expected participant changes | Count and uncount under the lock, notifying the collector after each change. The watchdog also balances its count on both stop and interrupted-wait exit. |
| Collection deadline | `wait_event_timeout()` gets a 5,000 ms budget. On expiry, close admission and signal all admitted workers, then return `-ETIMEDOUT` through F1 suspend. No host claim, radio sleep/wake, state transition, watchdog stop, IRQ-wake operation or host PM-flag request has occurred. |
| Waiter retirement | Decrement the frozen count only after `wait_for_completion()` returns. A signaled worker still contributes to this count until then. |
| Retry while workers retire | Return `-EBUSY` promptly. Never clear their outstanding count or reset their completion. A later attempt can proceed after they return. No retry loop or new background worker is added. |
| F2 resume after failed collection | If no collection remains active, return without a speculative radio-wake operation or another completion signal. |
| Successful collection | The PM callback owns the transition to DOWN and requests radio sleep after collection. The data worker no longer writes DOWN/DATA around its wait. |
| Normal resume | Request radio wake, restore DATA, explicitly restart the watchdog, then thaw workers. The DATA-before-restart ordering avoids the existing timer helper's rejection while DOWN. |

Five seconds is an error-path collection budget, not a deliberate delay on a
successful suspend. It is not a hard bound on Linux scheduling, host claims,
SDIO transactions or the entire PM callback, and it is unrelated to the
subsecond normal-resume target. Expiry is tested by injection; this work does
not measure a five-second wall-clock bound on the board.

The power-off-card remove/probe branch is unchanged. The normal configuration
without `CONFIG_PM_SLEEP` still allocates no freezer and makes the public
count/uncount/try-freeze functions no-ops. There is no board-policy, firmware,
clock-rate, charging, USB-polling or user-interface change.

## Why the completion cannot be reset too early

The admission lock serializes the active flag, both counts, completion reset
and `complete_all()`. An admitted worker remains in `frozen_count` while it
is delayed before entering its wait, blocked in the wait, or signaled but not
yet returned from the wait. The next collection checks that count before
calling `reinit_completion()`. A worker delayed before admission instead sees
either an inactive collector or a later active collector and follows that
current state.

The complete-all operation may wake tasks under the freezer lock; it does not
wait for those tasks to run. The completion wait releases its own internal
lock before the caller takes the freezer lock to retire. The driver holds no
freezer lock across a blocking wait, SDIO operation or timer operation.

Removing the data worker's state writes is necessary for reuse: otherwise an
old worker could return from its wait and publish DATA after a newer suspend
had already started. State changes now belong to the PM callbacks, rather than
to that delayed return path.

An idle watchdog is not counted. If it becomes active after the collector has
observed equality, it counts itself and attempts to freeze **before** watchdog
I/O. Equality is an observation at the collection boundary, not an assertion
that no later participant can arrive. That late-arrival case is tested.

These arguments depend on existing serialized PM callbacks, the ordered data
workqueue, the watchdog's count/checkpoint discipline, and the existing worker
teardown order. This patch does not introduce a general generation protocol
for concurrent reset/reprobe or make device removal race safely with suspend.

## Reproducible verification

```sh
task test:brcmfmac-freezer
task check:brcmfmac-freezer-drivers
task test:brcmfmac-sleep
task check
```

The [checker](../tools/check-brcmfmac-freezer.py) verifies the locked Linux
6.18.54 archive, extracts the source and completion/wait contracts, and applies
patches 0014 and 0015 with zero fuzz. It extracts the actual freezer structure,
attach/detach and lifecycle functions, F1/F2 PM callbacks, data worker and
watchdog thread into the [C harness](../kernel/tests/brcmfmac_freezer_test.c).
It also verifies that patch 0015 leaves the five low-level helper bodies from
report 81 unchanged.

Pthreads provide real concurrent callers. Controlled gates pause workers
before waiting and after signaling, and hold the watchdog around its timer
wait. Queue sequence tracking prevents lost notifications in the test shim;
the withdrawal case waits until earlier admission notifications have been
consumed before changing the expected count. Spinlock, completion, timer,
device and SDIO shims record or enforce their modeled contracts. The bus
sleep/wake shim succeeds; failure of those hardware operations is outside
this suite's claim. The watchdog timer shim checks DATA-before-start ordering,
not real kernel timer execution.

The suite contains **44 lifecycle scenarios**, including:

- Normal retained-power cycles, WoWLAN using in-band or OOB wake, callback
  function selection, duplicate suspend rejection and idempotent F2 resume.
- An absent worker, a late queued worker joining a later attempt, and sixteen
  partial-collection timeout/retry scenarios. These hold admitted workers
  both before their wait and after its completion signal.
- Participant withdrawal after the collector has slept on a false predicate,
  and sixteen watchdog arrival scenarios before or after collection.
- Thirty-three successful cycles through one freezer instance, rejection
  while a signaled waiter is delayed, all three modeled watchdog exit paths,
  and the untouched power-off-card branch. Allocation failure is checked too.

The PM-disabled build separately checks no allocation or freezer access.
Ten native negative controls deliberately remove admission accounting,
withdrawal notification, timeout thaw, outstanding-waiter protection,
retirement, the F2 guard, centralized state ownership, resume ordering,
watchdog exit uncount or collection-error propagation. A negative control must
compile and fail by assertion; success, process timeout and compiler failure
are not accepted as evidence that the suite caught it.

**Final results:** all 44 scenarios and the separate PM-disabled checks pass
both natively and on emulated ARM32. All ten native negative controls fail by
assertion. Both complete changed translation units, `bcmsdh.c` and `sdio.c`,
compile to ARM objects against the full project patch queue, locked builder
and kernel headers; the configuration check passes 164 assertions. Kernel
`checkpatch.pl` reports no errors, warnings or checks for patch 0015.

The prior sleep regression also passes its 95 native/ARM32 scenarios, native
DEBUG build, 43 matching original successful transcripts and twelve negative
controls. The shared `task check` passes 13 runtime tests, 276 tool tests
(one optional skip), both compiled helper checks and shell lint.

These modeled schedules are not exhaustive concurrency verification, kernel
lockdep/KCSAN evidence or a firmware/hardware timing measurement.

## Evidence and source identity

Final authoritative evidence is
`.local/build/brcmfmac-freezer-tests/compile-evidence.json`. It records input,
archive, original/patched source and contract hashes, native/ARM32 results,
builder identity, configuration hash and both ARM-object hashes. Per-variant
text results and extracted helper inputs are in the same directory. The final
full-source scratch build is `kernel-af5ae55842d2ec7e/` under that directory.
The earlier `evidence.json` records the preliminary 43-scenario harness; use
the final compile evidence for the completed 44-scenario suite.

Logs: `.local/build/brcmfmac-freezer-drivers.log`,
`.local/build/brcmfmac-sleep.log` and `.local/build/neo61-check.log`.
The source lock remains Linux 6.18.54 at upstream commit
`1b357ecb321392158d507b04672ffee57bfa071d`; verified archive SHA-256 is
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`.

| Patched file under `drivers/net/wireless/broadcom/brcm80211/brcmfmac/` | SHA-256 |
| --- | --- |
| `bcmsdh.c` | `f5e2e376b09776f0a3c2fb740f1b44e3617bc4b7512159497b8249659725f64a` |
| `sdio.c` | `1b114b1f46697b57ec7d2f99356e710a0d287df473cdcd26a586fea9af0279d4` |
| `sdio.h` | `17ce534cc5fe6c22d35689d4067c66dc9442fe988f505d4caeaa8d395e4a9ae8` |

The local primary-source contracts read for this work are
`kernel/sched/completion.c`, `include/linux/completion.h` and
`include/linux/wait.h` from that verified archive. In particular, complete-all
does not establish that all completion waiters have returned. The earlier
[source audit](80-brcmfmac-suspend-failure-audit.md) gives the pinned driver,
workqueue and PM ownership references. These tests preserve those source
identities rather than relying on an unpinned development branch.

## Remaining PM failure work

This slice fixes collection failure **before a hardware transition starts**.
It intentionally does not claim general suspend rollback: the callbacks still
ignore radio sleep/wake errors, OOB wake-enable errors and host PM-flag failure
as described in report 80. Normal resume still publishes DATA and releases
workers even if its radio-wake request failed; the new explicit watchdog
restart must be included in the next slice's failed-wake I/O gate. Do not
interpret the normal-resume ordering test as proof of safe failed-wake recovery.

Next, NEO-58 needs callback transaction ownership, checked sleep/OOB/host-flag
results, rollback after partial transitions, and an explicit policy for a wake
failure that cannot be reconciled. A state flag alone cannot exclude all
worker/interrupt I/O. Reset/reprobe ownership must be established rather than
calling the existing asynchronous firmware-crash reset path from suspended
callbacks. Then build and qualify an image with repeatable PM tests and both
network recovery routes.

No physical action was needed for this slice. The existing device/image and
recovery artifacts are preserved. There is no demonstrated causal connection
to NEO-55's authentication delay, and no measured latency or energy saving.
The new lock does add bookkeeping to worker checkpoints; its cost has not been
benchmarked.
