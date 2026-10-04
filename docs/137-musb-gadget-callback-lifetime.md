# MUSB gadget callback lifetime

4 October 2026, Pacific/Auckland. NEO-103.

The [work/musb-callback-lifetime](https://github.com/michaelishri/GameShellNeo/tree/work/musb-callback-lifetime)
candidate implements the USB device-controller class's asynchronous-callback
contract in MUSB. It prevents new function-driver callbacks during unbind and
waits for callbacks already admitted before allowing the function driver's
private state to be torn down. Staged diagnostic.18 and installed diagnostic.17
remain unchanged; this candidate builds on the separate startup/wake branches.

## The lifetime gap

[Report 136](136-musb-startup-runtime-pm.md) identified that MUSB supplies
neither `udc_async_callbacks` nor a gadget IRQ field for the UDC core's
conditional IRQ synchronization. Its suspend, resume, disconnect, reset and
setup paths can invoke the function driver while the controller lock is
dropped. Checking the pointer before unlocking does not protect its later use
or the function driver's private state against concurrent unbind.

UDC core explicitly calls its asynchronous-callback disable operation before
the function driver's `unbind()`. The driver must stop issuing those five
notifications until callbacks are enabled again. Request-completion callbacks
are different: they must remain available so endpoint cancellation and cleanup
can finish. This is a source-identified contract gap, not a reproduced GameShell
crash or an explanation proven for the earlier sleep-related USB failure.

An IRQ-only barrier is insufficient for this MUSB implementation. The OTG timer
calls `musb_g_disconnect()`, and `musb_hnp_stop()` can also call disconnect from
the gadget-stop path. The candidate therefore tracks callback ownership at the
call sites rather than relying solely on interrupt delivery or masking a shared
interrupt line.

## Candidate design

[Patch 0030](https://github.com/michaelishri/GameShellNeo/blob/work/musb-callback-lifetime/kernel/patches/0030-musb-gadget-callback-lifetime.patch)
adds an admission flag, an active-callback count and a wait queue to MUSB.
Gadget setup initializes them before registering the UDC. Admission begins
closed; the UDC class opens it after successful controller start.

All five notification paths follow this sequence:

1. With the controller lock held, reject a callback if admission is closed or
   no function driver is installed.
2. Increment the count and retain the selected driver pointer locally.
3. Drop the controller lock, invoke the selected driver, and reacquire the lock.
4. Decrement the count; if admission is closed and this was the last callback,
   wake the drainer.

Optional suspend/resume/disconnect hooks can remain absent. Mandatory setup
and reset callbacks preserve their existing return/state behavior. Setup returns
`-EOPNOTSUPP` when no callback can be admitted. The reset path still avoids
notifying a driver before a speed has been established, and continues its
controller-state work when notification is suppressed.

UDC core serializes its admission changes with `connect_lock`, so another
enable operation cannot reopen admission while disable is draining callbacks.
The MUSB counter itself remains protected by the controller lock.

The UDC disable operation closes admission under the same lock, then uses
`wait_event_lock_irq()` until the count is zero. That Linux primitive checks
the condition with the lock held, drops the lock while sleeping, and reacquires
it before rechecking/returning. No callback is asked to finish while its caller
holds the controller lock against it.

This also supplies the ordering between callback completion and unbind through
the existing lock. It avoids depending on a wake operation to provide ordering
when the drainer never sleeps; Linux documents that a wake which wakes no task
cannot be relied on for that barrier. [Linux memory-barrier documentation](https://www.kernel.org/doc/html/latest/core-api/wrappers/memory-barriers.html#sleep-and-wake-up-functions).

No additional atomic reference counter, normal-path memory barrier, polling
interval, hardware register access or runtime-PM acquisition is added for this
ownership mechanism. These are implementation properties, not measured latency
or battery savings. The callback code still uses the existing controller lock.

## Bind, stop and completion behavior

The UDC class's bind path starts the controller, enables asynchronous callbacks,
then allows connection. A failed connect closes admission before stop/unbind.
Normal unbind closes admission before the function driver's unbind, then stops
the controller. Both orderings are exercised by the source harness.

The diagnostic sysfs soft-connect path is different: it stops/starts the
controller without calling the UDC asynchronous enable hook again. The candidate
therefore does not reset admission in ordinary gadget start/stop. While stop has
cleared `gadget_driver`, new callback acquisitions fail. A previously admitted
callback retains its local pointer; a soft-stop alone has not unbound the
function driver. Reconnection uses the admission state retained by UDC.
Pointer retention does not, by itself, serialize every controller register or
endpoint-state effect against a soft stop/restart; that belongs to the separate
stop/quiescence work. The fixture checks the logical pointer boundary.

`musb_g_giveback()` is unchanged and is exercised with admission closed. Request
completion is not counted as an asynchronous notification, blocked behind the
drain, or silently dropped. Function-driver endpoint/request cancellation still
has its own USB lifetime contract.

The drain has no arbitrary timeout that would let unbind free private state
while a callback is still using it. A function driver that never returns can
therefore block unbind. That failure must be diagnosed; returning apparent
success after a timeout would violate the lifetime contract. Gadget callbacks
retain their existing non-sleeping API requirements; only the process-context
UDC suppression operation can wait.

## Reproducible checks

From the candidate branch:

```sh
task test:musb-sleep
task check:musb-wake-configs
task check
```

The source task verifies the locked Linux 6.18.54 archive and applies patches
0011/0025/0026/0029/0030 with zero fuzz. It compiles the actual MUSB functions,
the actual UDC bind/unbind/reset and callback-enable/disable helpers, and the
actual `wait_event_lock_irq`, `__wait_event_lock_irq`, `___wait_event` and
interruptibility macros from the pinned kernel header.

The wait-entry/scheduler and hardware boundaries are controlled shims. Pthread
locks and condition variables provide real concurrent execution and explicit
handshakes. They do not run the kernel scheduler or reproduce IRQ masking.
The harness asserts that the controller lock is dropped before the simulated
schedule and reacquired before wait completion. A source mutation that retains
the lock or omits reacquisition fails these checks.

Coverage includes:

- Independent gating and re-enabling of all five callback types; absent optional
  hooks and a missing driver pointer; setup return propagation.
- Existing event predicates across eight OTG states, and reset combinations for
  known/unknown speed, OTG/fixed-peripheral role, B-device indication and HR.
- One, two and four simultaneous admitted callbacks, nested callbacks, mixed
  event types and reverse completion order. Unbind remains blocked until the
  last callback retires.
- An unrelated wake while callbacks are still outstanding. The drainer goes
  back to sleep rather than treating wakeup itself as completion.
- A pointer-clear window after admission but before invocation, demonstrating
  use of the retained pointer; logical soft restart without a fresh enable hook.
- Actual UDC bind, bind failure, controller-start failure, connect failure and
  repeated bind/unbind, including their differing stop/unbind order.
- Actual request giveback while notifications are suppressed, including DMA
  mapping branches, preserved completed status, cancellation status and endpoint
  busy-state restoration.

Deliberately broken variants remove admission, acquisition, drain, wakeup,
setup release, UDC suppression or request-completion behavior; retire the
callback too early; or break the lock-wait primitive's unlock/relock sequence.
They must fail assertions. A compiler failure is not passing negative evidence.

The final suite passes natively and under ARM32 emulation:

| Group | Source scenarios |
| --- | ---: |
| Sleep, connection and IRQ wake | 106 |
| Probe/remove and startup failures | 141 |
| Gadget startup through UDC | 42 |
| Callback lifetime, wait macros and bind/unbind | 132 |
| Total | 421 |

All 42 native negative controls fail the intended assertions. Six complete ARM
driver configurations pass: unchanged board, host-only, dual-role, module,
no system sleep and no PM. Endpoint-zero compilation is included wherever
gadget code is present. The module configuration also links `musb_hdrc.o`;
the task uses the pinned toolchain's symbol reader to verify that both new
cross-object helpers are defined global functions in the combined object.
This is a relocatable module-object link, not a complete kernel link or a
loaded `.ko` qualification.

`task check` passes 13 runtime and 466 tooling tests, with two existing skips,
plus the compiled current-limit/Mac mount-guard checks and shell lint.
Checkpatch with `--no-tree --no-signoff` reports zero errors and warnings;
this does not constitute an upstream submission or maintainer review.

Local evidence, relative to the candidate worktree:

- `.local/build/musb-sleep-tests/matrix-evidence.json`: source tests, native
  negative controls, ARM32 output, six configuration/object records and symbol
  verification. SHA-256:
  `b09f63932f00eb0f29cbdc0211211c42449c8c3738e80bada1bf51d5ee0392d8`.
- `.local/build/musb-sleep-tests/module-symbols.txt`: combined-module symbols.
  SHA-256: `ee713f8502dabdbc46132f4af9dbe96cd82a06b386dc2fabf02cc9ec5ccea357`.
- `.local/build/musb-wake-configs.log` and `.local/callback-repository-check.log`:
  full final execution logs.
- Patch 0030 SHA-256:
  `bd1e7875d690d6af360392a152ca49f5972145156549e282c91ec256f29d2f80`.

The recorded input, harness, configuration, object and symbol hashes were
checked against the retained files after the final run.

## Remaining boundaries

The callback count protects the function driver's asynchronous callback lifetime.
It does not retire the entire MUSB controller, its DMA engine, all IRQ handlers,
the OTG timer or every worker. The existing failed-power gadget-stop and void
platform-remove paths still need the separate quiescence/recovery design from
report 136. The new gate is not a substitute for that resource teardown.

Request completion and endpoint ownership remain governed by their existing
contracts. Controller-state changes after notification suppression are not
automatically forbidden. No synthetic disconnect/reset notification is added,
and the patch does not promise that every host/cable event produces a callback
before unbind closes admission.

The tests do not establish full-kernel lockdep/KCSAN results, real interrupt or
timer concurrency, electrical USB behavior, hardware reconnection, PM energy
savings or recovery from a hung callback. The callback bodies and wait macros
are actual source; the scheduler, queue primitives, MMIO and function-driver
implementations at their boundaries are controlled substitutes.

A later image needs a new kernel/image identity, a complete kernel/link and
offline image check, a fresh board baseline, and hardware qualification of
ordinary connection, bind/unbind, control requests and the agreed PM sequence.
The inherited wake/startup candidates retain their own qualification gates.
Diagnostic.18 remains the next isolated sleep-reconnection trial.

## Source map

- `drivers/usb/musb/musb_gadget.c`: new admission/drain helpers and UDC operation;
  gadget setup, five notification sites except endpoint-zero setup, and unchanged
  request giveback.
- `drivers/usb/musb/musb_gadget_ep0.c`: `forward_to_driver()` uses admitted
  ownership and preserves the function driver's return value.
- `drivers/usb/musb/musb_core.h`, `musb_gadget.h`: state and cross-object helpers.
- `drivers/usb/musb/musb_core.c`: audited IRQ, OTG timer and HNP callers.
- `drivers/usb/gadget/udc/core.c`: bind/unbind, callback policy, reset forwarding,
  controller start/stop and the separate sysfs soft-connect sequence.
- `include/linux/wait.h`: actual locked-condition wait macros.
- `include/linux/usb/gadget.h`: callback context, mandatory reset/setup and
  request-completion contracts.
- `Documentation/memory-barriers.txt`: lock ordering and sleep/wakeup ordering
  limits, checked against the same pinned source.

The source archive, builder and board configuration remain pinned in
[sources.lock.json](../build/sources.lock.json). No firmware binary, battery
policy, charger setting or installed-device configuration was changed.

## Subsequent candidate, 4 October 2026

[Report 154](154-usb-sleep-session-retirement.md) records diagnostic.19 preparation:
patch 0030 is selected unchanged as the callback-lifetime dependency for logical
session retirement. Other prepared optimizations remain separate. Actual regmap
source also reproduces masked removal acknowledgement without handler dispatch,
leading to an explicitly versioned prospective diagnostic policy. No historical
hardware result is reclassified; the stale USB failure remains failed and new
hardware qualification is required.
