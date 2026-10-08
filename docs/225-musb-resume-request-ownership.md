# Owning deferred MUSB endpoint restarts

9 October 2026. NEO-108 and review follow-up NEO-163, on
`work/musb-request-resume`, based on diagnostic.24 integration. No image,
board or hardware change is included or claimed.

## Original candidate and review

Commit `ad5becd` changed deferred restart data from a raw request pointer to
its endpoint, coalesced work with `restart_pending`, and removed pending work
before invoking callbacks without `list_lock`. This addressed the previously
recorded source finding without attributing a fault to CPI hardware.

The review found a progress regression: if resume ran while giveback had
set the endpoint busy and dropped the controller lock, the callback cleared
`restart_pending` and returned. The original queue head could remain queued
with neither a hardware start nor another pending restart. The old busy test
cancelled that head afterward, so it did not require eventual progress.

The original evidence also needs correction: **36 scenarios total per binary,
18 per endpoint direction**, repeated on ARM32, were recorded. They were not
36 per direction or 72 per binary. The earlier first-error sleep tests used
pre-0037 sources, and the standalone fixture did not complete requests from
inside its restart boundary. The previous blanket “no stranded-head” claim
is withdrawn. Original native and compile receipts/logs are preserved locally
under `.local/review-evidence/ad5becd/`.

## Revised ownership

[Patch 0037](../kernel/patches/0037-musb-resume-request-ownership.patch) keeps
`restart_pending` true until its obligation is discharged. If resume meets a
busy endpoint, it hands the obligation to the outermost giveback through
`restart_deferred` and takes one controller runtime-PM reference. This keeps
the hardware available until giveback restores the endpoint's prior busy
state. The giveback tail restarts the current head, then releases the reference.
If the endpoint is being disabled, `nuke()` retires the deferred obligation
and releases its reference instead. Ordinary completions do not take this
extra runtime-PM reference.

The handoff also covers an empty queue that is refilled by its still-running
completion callback. During an owned restart, completing the current head
sets `restart_again`; the outer restart loop then inspects the current queue
again. This permits same-endpoint requeue and already-queued follower progress
without recursively starting the endpoint from inside its busy callback.
Other-endpoint requeues use the normal pending-work list. List entries remain
removed before their callbacks, and the first callback error is preserved
while later work is drained.

The duplicate Python `splice()` helper has been removed. The extractor now
skips forward declarations, and evidence validation rejects incorrect or
incomplete scenario counts.

## Repeatable validation

Run these tasks sequentially on the build host:

```sh
task test:musb-request-resume
task test:musb-restart-kunit
task check:musb-sleep-configs
task check
```

The request fixture extracts the patched queue, dequeue, giveback, free,
restart, handoff and pending-work functions. It requires **48 scenarios per
execution, 24 per direction** and runs natively, with real request frees, and
under ARM32 qemu. Ten deliberately defective variants check coalescing,
dropped work, callback locking, busy restart, flag restoration, failed queue,
lost busy handoff, missing giveback handoff, missed follower and first-error
retention. These are modeled boundaries, not hardware or concurrency results.

The KUnit task compiles the full MUSB driver in Linux UML with KASAN and
lockdep. It uses real spinlocks, device-managed pending allocations, USB
completion calls and runtime-PM reference accounting. Seven cases cover
busy giveback, empty-queue requeue, same/other-endpoint completion requeue,
follower progress, endpoint shutdown and first-error retention. A test-only
hook replaces the hardware restart; production ownership functions are not
reimplemented in the fixture. Hooks are generated only into an isolated
kernel queue, never `kernel/patches` or an image.

The existing sleep/callback fixture now applies 0037. Its first-error control
therefore checks the changed work drainer. Its configuration task compiles
project gadget, host-only, dual-role, module, no-system-sleep and no-PM ARM
alternatives. The host suite additionally checks KUnit receipt rejection,
scenario totals, forward-declaration extraction and hook-anchor uniqueness.

Validation receipts and final results are recorded below once all checks finish.

## Limits and remaining work

UML uses one virtual CPU with deterministic synchronous interleavings. The
controller's runtime-resume state is staged; a baseline PM reference prevents
real power transitions. Neither this nor ARM object compilation establishes
SMP, DMA, physical USB timing, system sleep or board reliability. Native
completion-inside-restart cases intentionally inject a boundary event; they
are not evidence that the PIO hardware normally completes synchronously there.

General dequeue progress outside an owned deferred restart, failed-queue DMA
mapping, and complete controller removal remain separate work. NEO-106's
integration dependency must not be declared resolved from source or fixture
results alone. This candidate still needs a separately identified image and
appropriate hardware qualification before integration into the device baseline.
