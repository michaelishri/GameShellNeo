# Extcon consumer notifier drain: source candidate

4 October 2026, Pacific/Auckland. NEO-106, branch
`work/musb-removal-lifetime`.

Patch 0031 implements the framework prerequisite identified in
[report 141](141-musb-removal-backend-contracts.md): a consumer can unlink its
extcon notifier and wait for dispatches that already selected it. This is a
source candidate, absent from diagnostic.18. It does not yet switch Sunxi to
the new API, fix the complete MUSB removal sequence or claim an observed CPI
failure has been resolved.

## Why a separate drain is needed

The existing extcon unregister operation removes the block from a raw notifier
chain under the extcon spinlock. Dispatch does not hold that lock while calling
subscribers. The raw notifier loop can already have loaded the block, including
its next-block pointer, before unregister returns. Canceling work at that point
does not prevent the selected callback from subsequently queuing more work.

Counting callbacks only after they enter misses this interval. The candidate
instead enters a per-device SRCU read section before either chain is read and
leaves after both the cable-specific and all-connectors chains return. The
new `extcon_unregister_notifier_sync()` first performs the existing unlink,
releases its spinlock, then waits for that domain if unlink succeeded.

The operation runs in process context. It cannot be called from any callback
in the same extcon domain, or while holding a lock those callbacks need.
It can wait for unrelated connector callbacks on the same device. Registration
and unregistration of the same block must be serialized by its owner. Errors
remain errors; failed unlink does not promise completed retirement.

Existing asynchronous unregister behavior and raw callback contexts remain
unchanged. This uses the SRCU reader API around raw dispatch; it does not turn
the chains into process-context-only SRCU notifier chains. Matching read entry
and exit remain in the original caller's context. No callback is deferred to
another worker.

Allocation initializes the domain before returning the object and propagates
initialization failure with allocation cleanup. Free releases the domain and
preserves NULL-safe behavior, including objects never registered. Domain
teardown requires process context; the pinned in-tree free call site is the
devres release callback in `drivers/extcon/devres.c`. Linux
6.18.54 supplies TREE or TINY SRCU through its existing RCU configuration;
there is no `CONFIG_SRCU` selection to add in this pinned kernel.

## Reproduction

```sh
task test:extcon-notifier
task check:extcon-drivers
task check
```

These tasks do not connect to the GameShell. The first task extracts the locked
archive, applies patch 0031 with zero fuzz and executes actual extcon and raw
notifier functions. The second also builds the full extcon core/devres sources
in isolated ARM outputs. The branch's image-build task includes the source
regression; building an image still requires a distinct image/kernel identity.

Evidence is private in `.local/build/extcon-notifier-tests/evidence.json` or
`compile-evidence.json`; `.local/build/extcon-drivers.log` is the saved task
log. Inputs include archive, patch, harness, checker and source hashes. Failed
intermediate task logs remain in `.local/build/logs/`.

## Source regression coverage

The C harness executes the actual locked-source `extcon_sync()`, allocation,
free, register/unregister and new synchronous unregister functions, plus the
raw notifier registration, unlink and call loop from `kernel/notifier.c`.
It does not substitute a hand-written notifier traversal.

There are 29 scenario groups, executed natively and as a statically linked
ARM32 binary under QEMU. They cover:

- A selected head callback paused before entry; a selected next block removed
  while its predecessor is paused; and an all-connectors callback still inside
  the same protected dispatch after the specific callback returns.
- Callbacks paused inside their body, in both modeled process and IRQ contexts.
- Synchronous removal waiting for the held dispatch while ordinary unregister
  still returns without that wait. Each case requires the selected original
  callback to run, then checks a later dispatch cannot call the removed block.
- Same-block registration after retirement, nested dispatch to another cable,
  preserved callback context constraints and no spinlock held across callbacks
  or the synchronous wait.
- NULL/invalid arguments, absent or duplicate registration, allocation and
  SRCU initialization failures, free of never-registered objects, and sysfs
  allocation failure after the reader section has ended.

Seven native negative controls must fail assertions: missing drain, either
chain outside the reader section, wait under the extcon spinlock, leaked
allocation on initialization failure, omitted domain cleanup, and a changed
failed-unlink path. They are test-only transformations, not driver patches.

SRCU and spinlocks are pthread models; IRQ context is a checked thread-local
condition. The model waits for counted readers and does not implement Linux's
grace-period algorithm, lockdep, IRQ preemption or scheduling. These tests
establish source ordering against the stated boundary contracts, not a
whole-kernel concurrency proof. Native/ARM32 agreement is not physical-board
qualification.

## ARM integration and repository validation

The compile task checks three configurations: the project board configuration,
an isolated extcon module configuration, and an isolated uniprocessor
non-preemptible configuration selecting TINY SRCU. It verifies the requested
Kconfig values instead of accepting a silently different configuration.
The module-only configuration excludes USB support because the hidden boolean
`USB_PHY` otherwise selects built-in extcon. It does not replace the board
configuration or test a modular Sunxi controller.

Built-in configurations compile the complete core and devres objects; the
module configuration also builds their combined `extcon-core.o`. Symbol checks
require a defined global synchronous-unregister API and its unresolved kernel
`synchronize_srcu` reference. This is object compilation/linkage, not a final
kernel/module modpost, boot or load test.

All three configurations pass. Final compile evidence SHA-256 is
`0b01ed17af920f1bb9a930f869fbdb88e0e9e22cf2fd2cd64d9b46d49db5870c`;
all recorded input hashes match the candidate files.
The broader repository suite passes 13 runtime and 487 tooling tests, with two
existing optional skips, compiled current-limit/mount-guard checks and shell
lint. Its log is `.local/neo106-check.log`. Strict patch style checking with
`--no-signoff` passes; no upstream submission or DCO attestation is made.

## Remaining ownership boundaries

The caller must keep the provider registered and alive throughout unlink and
wait. `cleanup_srcu_struct()` is not a substitute for stopping provider event
producers. `extcon_dev_unregister()` can free the notifier-head array, and
`extcon_sync()` continues with sysfs/uevent work after the callback envelope.
This patch does not make concurrent provider destruction safe.

Sunxi still needs explicit child-owned registration, partial-probe failure
cleanup, unregister/drain before final work cancellation, and a verified
provider-lifetime contract. The existing ignored scratch Sunxi prototype is
not part of patch 0031 or accepted evidence. Core IRQ/work/timer, role setters,
parent runtime PM, DMA and backend resource retirement remain the larger
NEO-106 work described in reports 139 and 141.

[Report 145](145-extcon-kernel-lifetime-validation.md) subsequently adds real
Linux UML thread/SRCU/softirq checks under TREE and TINY SRCU with lock debugging.
SMP/hard-IRQ and subsystem-wide lifetime compatibility still need review.
Next, integrate the consumer ownership change and test probe failure/rebind
and producer retirement together. A new image and observed device checks follow
those source gates. No latency, battery-life or standby improvement is claimed
by this prerequisite.
