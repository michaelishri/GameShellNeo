# Permanent MUSB core work and timer retirement

9 October 2026, Pacific/Auckland. NEO-166, a bounded NEO-106 continuation on
`work/musb-core-work-retirement`, based on `0e73b3a`. This work uses the pinned
Linux 6.18.54 source and host tests. NEO-108 installation remains parked;
there are no GameShell/Mac connections, image builds or physical tests.

## Problem and change

[Report 141](141-musb-removal-backend-contracts.md) identified that ordinary
work cancellation is insufficient for terminal teardown. `musb_remove()`
cancels work before client cleanup, but endpoint disable can schedule
`irq_work` again. The core IRQ, timer and backend callbacks also produce work.
The core OTG timer previously had no terminal shutdown. An execution queued
after an ordinary cancel can outlive resources it uses.

[Patch 0040](../kernel/patches/0040-musb-core-work-retirement.patch) adds
`musb_shutdown_work()` after role cleanup and
[NEO-165's core IRQ retirement](227-musb-core-irq-retirement.md), before DMA or
backend resources are released. It permanently shuts down the OTG timer and
disables/drains `finish_resume_work`, `deassert_reset_work` and `irq_work`.
Later queue/rearm attempts are rejected while the objects remain allocated.
All waits occur outside the controller lock.

The initial three cancellation calls in normal remove are retained; the new
final closure handles work queued afterward. Failed probe replaces its three
ordinary cancellations with the same terminal helper. The timer is initialized
alongside those works, before `musb_core_init()`, so every `fail3` entry owns
all four objects. Earlier failure labels never call the helper. Moving timer
initialization does not arm it.

`irq_work` alone maintains the extra runtime-PM reference represented by
`musb->session`. Its session checker uses `pm_runtime_get_sync()`, which adds
a reference even on failure, and records session ownership. After draining
that worker, its hold remains in place through the remaining backend/core PM
puts. Only after `pm_runtime_disable()` returns does `musb_release_session()`
clear the flag and balance exactly that hold with `pm_runtime_put_noidle()`.
This preserves the hold that prevented those later puts from reaching zero
while PM callbacks were still enabled. It leaves unrelated holds alone.
Repeated release calls do not drop another session reference; production calls
it once on each terminal path. This is reference accounting, not a repair of
the existing general runtime-PM/resource teardown ordering.

Ordinary gadget stop and system sleep do not call this helper. Fresh controller
instances receive newly initialized work and timer objects. No normal-transfer
branches, persistent state fields, polling or retry delays are added.

## Saved checks

Run these tasks sequentially:

```sh
task test:musb-irq
task test:musb-work-kunit
task check:musb-irq-drivers
task check
```

The existing IRQ source suite now extracts the new helper as well as the
actual IRQ helpers, remove body and three probe failure tails. It executes
42 scenarios natively and on ARM32: the previous 34 IRQ cases, six work/session
cases and two earlier failure stages with uninitialized work/timer storage.
Client cleanup deliberately queues work after the initial cancellation;
the model also covers a worker acquiring its session hold during the drain.
Repeated terminal calls must preserve unrelated modeled PM holds.

Twenty native negative controls cover the previous nine IRQ defects, ordinary
cancel in place of each permanent work disable, timer delete in place of
shutdown, missing removal/probe closure, missing/foreign/duplicate session
puts, releasing the session before the worker has drained or before runtime PM
has been disabled. Only assertion
failure counts as rejection. Three additional source controls reject missing
or late timer initialization and an extra terminal caller.

The source fixture controls MMIO, clients, DMA, IRQ, PM, work and timer API
boundaries. It does not execute the complete probe or the real scheduler.
The source validator separately binds initialization to every `fail3` entry
and confines the terminal helper to remove/fail3.

The separate UML KUnit suite compiles the full MUSB driver with KASAN, lockdep
and work/timer debug objects. It appends a test fixture without replacing the
production work/session helpers. Its eight cases use real Linux APIs:

- Cancel all pending delayed works and the pending timer, then reject later
  work queues and timer rearm.
- Hold each of the three work callbacks open in turn while another kernel
  thread calls the helper. Observe the pinned workqueue's disable-depth bits
  before releasing the worker, proving cleanup entered the drain. Resources
  must stay live until it returns; a worker's self-requeue must be rejected.
  The held IRQ worker also acquires a session hold before returning.
- Balance present/absent session holds with zero/two unrelated PM references,
  retaining the hold across work shutdown and releasing only after PM disable,
  including repeated cleanup and no queued PM request.
- Execute a modeled Sunxi removal tail through real runtime-PM puts, disable
  and callback dispatch on a synthetic device. Keeping the session hold until
  disable must prevent a suspend callback after modeled clock/reset teardown.
  A separate deliberate early-release control must invoke that callback and
  record its attempted access to the unavailable modeled resource.
- Demonstrate that a fresh instance can run each worker after another instance
  has been permanently closed.

Callbacks model hardware work. This is a single virtual CPU; it does not hold
a timer callback running concurrently with shutdown, exercise physical MMIO
or prove SMP races. Actual workqueue synchronization, usage-count operations
and PM dispatch are tested; the backend's hardware availability is modeled.
This is not a complete controller lifecycle or physical power transition.

The strict suite validator rejects missing, duplicate, skipped or failed cases,
wrong suites and kernel diagnostics. The accepted kernel, config, log and
parsed results are retained independently. Source/ARM evidence remains under
`.local/build/musb-irq-tests/`; kernel evidence is under
`.local/build/musb-work-kunit/`. The ARM matrix checks project gadget, host,
dual-role, combined module and no-PM configurations without building an image.

## Results

Validation and review are in progress. Final results and receipt hashes will
be recorded here before NEO-166 is closed.

Specification review caught a P1 ordering defect in the first candidate: its
passive session put made the subsequent existing core `pm_runtime_put_sync()`
reach zero after Sunxi clock/reset teardown. The first six kernel cases passed
but covered the helper in isolation and missed that outer sequence. The hold
now remains until PM disable, and the added positive/negative PM-tail cases
specifically exercise the discovered regression. The superseded six-case run
is not final-candidate validation.

## Remaining NEO-106 boundaries

These operations prevent future execution of the selected objects; they do
not make it safe for a backend producer to retain a pointer after the controller
allocation is freed. Backend timers, notifiers, role setters, independent IRQs
and DMA callbacks still need their own admission closure and drain. The
separately initialized `gadget_work` retains its existing gadget cleanup path.

Pending resume-list entries are not delayed-work objects. Their producers,
callback data and runtime-PM callbacks need coordinated retirement while
resources remain available. Runtime resume can restore registers and run those
callbacks; work shutdown does not disable runtime PM or fix its current
post-platform-exit ordering. In particular, the existing no-session teardown
case still needs that broader resource-ordering correction. Core masking must ultimately be reconciled with
all remaining producers. Independent DMA destruction/source masking and the
backend-specific resource contracts in report 141 are also still open.

Failed PM acquisition does not establish register accessibility; this patch
does not supply an inaccessible-hardware removal path. The older extcon/Sunxi
candidates remain separate. Complete removal, physical unbind/rebind and any
power or latency benefit require further qualification.
