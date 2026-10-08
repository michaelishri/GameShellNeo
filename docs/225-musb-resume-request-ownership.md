# Owning deferred MUSB endpoint restarts

9 October 2026. NEO-108; host-source candidate on `work/musb-request-resume`,
based on the diagnostic.24 integration branch. No image, board or hardware
change is included or claimed.

## Finding

`musb_gadget_queue()` passed a raw `struct musb_request *` as the deferred
data of `musb_queue_resume_work()` while runtime-suspended. Between queuing
and runtime resume that request can be dequeued, given back to its
completion callback and freed, but the pending entry still held the raw
pointer. `musb_ep_restart_resume_work()` then restarted freed or detached
memory, missed the queue head that actually needed starting, and
double-restarted requests re-queued while suspended. `musb_run_resume_work()`
also held `list_lock` across every callback, so a callback that re-entered
`musb_gadget_queue()` for a suspended endpoint deadlocked on the very list
it iterated. This was a pinned Linux 6.18.54 source finding, recorded in
[FOLLOW-UP.md](../FOLLOW-UP.md); no CPI fault is attributed to it.

## Driver changes

[Patch 0037](../kernel/patches/0037-musb-resume-request-ownership.patch) makes
the endpoint, not the request, own its deferred restart. The pending entry now
carries the `struct musb_ep`, embedded in the controller with the same lifetime,
and the restart callback restarts whatever request heads `req_list` at resume
time, checking `busy` and `desc` first. A per-endpoint `restart_pending` flag
coalesces repeated head queues into one deferred restart; it is cleared when
the work runs and when queuing fails so a later queue can retry.

`musb_run_resume_work()` removes each entry and frees it before invoking its
callback, releases `list_lock` around callbacks, and re-acquires it before the
next entry. First-error reporting from the preceding callback-lifetime patch
(0030) is preserved. A callback may now queue further pending work — for
example a completed request re-queued from its completion callback — without
self-deadlocking.

Endpoint restart ownership is all that changes: request completion,
DMA mapping on failed queues, runtime-PM policy and system-sleep paths are
untouched. The known failed-queue DMA mapping issue remains a separate
recorded item.

## Evidence

`tools/check-musb-request-resume.py` extracts the actual
`musb_queue_resume_work`/`musb_run_resume_work` and gadget
restart/queue/dequeue/giveback/free functions from the locked Linux 6.18.54
archive, first applies the prior MUSB queue patches (0011, 0025, 0030, 0033)
so the audit baseline is the real pre-patch state 0037 applies to, then
applies 0037. `kernel/tests/musb_request_resume_test.c` models DMA mapping,
MMIO, completion callbacks, allocation failure and runtime-PM boundaries
under one fixture thread.

* The candidate passes 36 native scenarios per endpoint direction (72 total),
  repeated on ARM32 under qemu, covering suspended and awake restarts,
  cancel-free restart, direct restart after resume, dequeued-but-not-freed
  heads, stale heads not blocking followers, non-head cancels, cross-endpoint
  isolation, caller re-queues, completion-callback re-queues, completion
  callbacks that run resume work themselves, disabled-endpoint drains,
  companion work, re-entrant callback queueing, failed-work retry,
  `-ESHUTDOWN`/`-EIO` completions and busy-endpoint resumes.
* The candidate also passes with real request lifetimes (`REAL_FREE`): no
  stale, detached, duplicate, stranded-head or self-deadlocking restart remains.
* The unpatched baseline and six negative controls each fail an assertion on
  their discriminating scenario: ignoring the coalescing flag, dropping
  pending work, holding `list_lock` through callbacks, restarting while
  busy, skipping the flag reset and keeping the flag after a failed queue.
* `check:musb-request-resume-drivers` compiles `musb_core.o` and
  `musb_gadget.o` from the full patched queue for ARM with the recorded
  builder.
* Kernel `checkpatch.pl --no-tree --no-signoff --strict` reports zero errors,
  zero warnings and zero checks for patch 0037.

## Limits

One fixture thread; not SMP, hard-IRQ, ARM driver concurrency or hardware
qualification. A completion re-queued from inside a deferred restart lands in
the endpoint's busy window and waits for the next queue event — the same
stranding class as the pinned dequeue path; both are recorded separately in
FOLLOW-UP.md rather than fixed here. NEO-106 remains blocked on the ownership
decision this patch records, not on this code.
