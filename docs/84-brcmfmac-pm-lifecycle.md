# brcmfmac PM, reset, removal and IRQ ordering (NEO-63)

1 October 2026, Pacific/Auckland. This follows the checked transitions and
failed-wake isolation in [report 83](83-brcmfmac-pm-rollback.md).
[Patch 0017](../kernel/patches/0017-brcmfmac-pm-lifecycle.patch) closes the
shared callback/reset boundary and defers interrupt register reads across
retained sleep. It also retires parked workers before removal waits for them.
No device access, image build or physical sleep test was performed.

## Findings and resulting behaviour

| Boundary | Source finding | Change |
| --- | --- | --- |
| Reset versus suspend | Reset can tear down the bus/freezer while F1 collects or uses them. The existing reset-work scheduling mutex does not exclude PM. | F1 suspend takes the existing F2 device lock for the callback. Reset must acquire that lock without waiting and rejects an owned retained or power-off transaction. |
| Reset finishes first | Reset removes the bus before requesting MMC reset. Subsequent card removal/reprobe can be asynchronous. | Suspend and resume reject a missing bus instead of accessing its old freezer/settings. No speculative reprobe is introduced. |
| F1 final removal versus F2 resume | Shared state is freed by F1 removal, but the real resume callback runs under F2's device lock. The two function locks alone are independent. | F1 final removal also takes F2's lock; it clears both drvdata pointers before freeing shared state. F2 resume checks drvdata while its device lock is held. |
| Removal while retained-suspended | Synchronous work cancellation or watchdog shutdown can wait for a worker parked until resume. | Before unregistering IRQs or draining work, removal latches failed PM, quiesces interrupt producers, releases the owned wake reference and thaws the freezer. Released workers are forbidden from firmware I/O. |
| Power-off resume selection | Re-evaluating the current policy can choose probe even when that callback never removed the bus, or skip probe after a policy change. | A successful power-off removal records ownership. F2 consumes that ownership once before probing. Retained and power-off transactions are both protected from reset and duplicate suspend. |
| In-band IRQ during retained sleep | MMC stops card IRQ processing after function suspend, and restarts it before function resume. The function's handler can read radio status in either gap. | Set an IRQ-deferral flag under the SDIO host lock before radio sleep; clear it under that lock only after successful wake and DATA restoration. A handler in the interval records pending status and queues work instead of reading registers. |

Normal active IRQ handling still reads/acknowledges status immediately. The
existing hard-IRQ/OOB path already defers status reading; it keeps that
behaviour. On successful restoration, pending work can run after thaw. The
existing DPC wakes the bus and consumes `ipend` before reading status. Failed
restoration keeps IRQ deferral set and patch 0016's failure latch suppresses
firmware I/O and new work. Collection failures before radio sleep never set
the deferral flag.

## Lock and lifetime argument

The selected kernel's driver core holds a function's device mutex while
calling its ordinary suspend, resume and remove callbacks. F2 is already the
probe/allocation owner, so its existing device mutex is the shared lifecycle
lock. There is no new mutex held across system sleep and no need for one
thread to unlock a mutex acquired by a different PM callback.

| Entry | Locking and exit |
| --- | --- |
| F1 suspend | Core holds F1; callback takes F2 with `SINGLE_DEPTH_NESTING`, runs collection and the checked transaction, then releases F2. Ownership flags protect the interval between callbacks. |
| F2 resume | Core holds F2. Check drvdata before dereferencing shared state, consume recorded ownership and finish restoration before returning. |
| F1 final removal | Core holds F1; callback takes F2 with the same nesting annotation, aborts any retained transaction, drains work, clears drvdata, frees shared state and releases F2. |
| F2 removal | Core already holds F2. Abort retained PM and unregister IRQs; preserve the existing rule that F1 performs final shared cleanup. |
| Reset worker | Attempt F2 with `device_trylock()`. If another callback owns it, return `-EBUSY` immediately. Under the lock, reject failed PM, committed suspend/power-off or a missing bus before destructive work. Release F2 on every exit. |

F1-to-F2 is the only nested function-device lock order introduced. F2 resume
and F2 removal do not acquire F1. The firmware-error bus-remove helper releases
the two drivers in separate calls, rather than holding F2 while acquiring F1.
The MMC card-removal loop removes F1 before F2, while manual F2 driver unbind
does not destroy its device object. These existing device-lifetime contracts
keep the F2 device available to F1's callback. This is a targeted argument for
the selected two-function brcmfmac lifecycle, not a replacement for driver-core
or MMC lifetime management.

The nonblocking reset acquisition is essential. Removal can hold F2 while
`cancel_work_sync()` waits for reset work. Making the worker wait for F2 would
deadlock that drain. If reset acquired F2 first, suspend/removal waits outside
the transaction until reset releases it; suspend then checks the resulting
bus state. The worker's pre-lock bus/device pointers retain their existing
lifetime through reset-work cancellation before final shared-state freeing.

SDIO access still uses the separate host lock. An in-band handler is called
with that host claimed, so a handler either finishes its status read before
PM sets deferral or observes the flag afterward. The hard-IRQ path never
requires that lock or reads radio status. The callback ordering is device
locks, then host lock; workers/IRQs do not acquire the device locks to make
progress during collection.

## Error and recovery limits

- A conflicting reset returns `-EBUSY`; it is not queued for replay. The
  existing generic reset work callback ignores the bus callback's return
  value. This patch does not claim automatic recovery or user-visible delivery
  of that errno. A deliberate recovery policy remains separate work.
- The reset helper still discards `mmc_hw_reset()`'s result. The MMC contract
  distinguishes synchronous success, asynchronous rescan and error. Those
  outcomes and recovery/reprobe failure handling must be addressed before
  using reset as automatic PM recovery. A missing bus is now rejected safely.
- Removing an asleep function deliberately abandons the retained transaction;
  it does not wake and briefly advertise a healthy radio before teardown.
  A function that remains bound after partial unbind stays unavailable.
- IRQ deferral prevents the driver's backplane status read in the gap. It
  does not disable the host IRQ line or prevent MMC's own card-management
  commands. A level interrupt may be delivered again before the card core
  pauses delivery. Hardware tests must check IRQ rate, pending-status service,
  CPU activity and latency across the gap; no energy saving is claimed.
- Firmware loading/probe callbacks and generic reset scheduling have their
  existing lifecycle contracts. These tests do not establish exhaustive race
  freedom for every asynchronous firmware callback, bus or debugfs operation.
  The generic OOB registration wake-probe issue from report 83 remains open.

The failed-restore policy remains unavailability until a cold restart creates
a fresh device lifetime. Neither this patch nor its offline tests qualify
module reload as recovery or establish that NEO-55's authentication outage
had any of these causes. NEO-58 remains open for image and hardware qualification.

## Reproducible validation

```sh
task test:brcmfmac-lifecycle
task check:brcmfmac-lifecycle-drivers
task test:brcmfmac-pm
task test:brcmfmac-freezer
task check
```

The lifecycle mode of [the checker](../tools/check-brcmfmac-pm.py) verifies the
locked archive, applies patches 0014–0017 with zero fuzz, and extracts the
actual callbacks, reset, abort, freezer, worker, IRQ and access-boundary bodies.
The unchanged low-level sleep helpers are compared with their previous source.
Callback names alone are changed to invoke them through a harness adapter
that models the driver core's held device lock. Pthread device/host mutexes,
controlled gates and scripted hardware results exercise selected schedules.

**102 scenarios pass natively and on emulated ARM32:** 44 original collector
cases, 45 PM/control/I/O cases and 13 additional reset/removal/IRQ cases.
The latter cover reset during collection, after committed suspend, ahead of
suspend, after power-off, IRQ arrival while asleep and behind a claimed host,
successful/failed wake, F1/F2 removal of parked workers, removal waiting for
collection, ownership across policy changes and rejection of unowned reprobe.

**13 negative controls fail by assertion.** They remove IRQ deferral or its
set/clear, reset trylock/transaction checks, suspend/removal exclusion,
removal abort/thaw/failure isolation or power-off ownership. Compilation failure,
timeout and unexpected success are rejected as negative-control evidence.

The harness substitutes final resource freeing and SDIO remove/probe with
asserting seams. It executes the outer remove callback and its actual abort
helper, and models worker draining with a real thread join. It does not run
the full kernel driver core, MMC reset, firmware download, electrical card
removal or the full DPC packet-processing body. Pending-status preservation and
queueing are asserted; their physical delivery and service still need hardware
qualification. Native pthread results also do not reproduce ARM weak-memory
behaviour or replace kernel lockdep/KCSAN coverage.

The complete composite `brcmfmac.o` compiles in normal and debug ARM
configurations, each passing 164 diagnostic configuration assertions. The
debug build uses an isolated `CONFIG_BRCMDBG=y` fragment and verifies its
resolved setting; image configuration is unchanged. Kernel `checkpatch.pl`
reports zero errors, warnings or checks for patch 0017 (read on standard input).
The shared `task check` passes 13 runtime and 276 tool tests (one optional
skip), compiled helper checks and shell lint.
The independent patch-0016 PM regression passes its 89 native/ARM32 cases and
25 negative controls. The patch-0015 freezer regression passes 44 native/ARM32
cases, the PM-disabled case and ten negative controls after the fixture changes.

## Evidence and source contracts

Local evidence:

- `.local/build/brcmfmac-lifecycle-tests/compile-evidence.json`: archive,
  source/harness/tool/contract hashes, native variants, ARM32 and complete
  driver build identities.
- `.local/build/brcmfmac-lifecycle-drivers.log`: authoritative full run.
- `.local/build/brcmfmac-pm.log` and `.local/build/brcmfmac-freezer.log`:
  independent older-patch regressions after the shared harness changes.

Complete-driver scratch: normal
`.local/build/brcmfmac-lifecycle-tests/kernel-d06ba11a4f517f52/`, debug
`.local/build/brcmfmac-lifecycle-tests/kernel-2c3b636755a97147/`.

| Patched file in brcmfmac | SHA-256 |
| --- | --- |
| `bcmsdh.c` | `7bfaf6cb7ff21443432dbedc67a4daa281018b0870c797934a019891826c39ee` |
| `sdio.c` | `8b376dc9d100a7afa5f56e85eb03e3b56a53402aa494a6eccccc63d030b1921b` |
| `sdio.h` | `85c2bf14accd96e9a4188a422f5a49365a357cd23e85d8203b0d021e804c344e` |

The unchanged lock selects Linux 6.18.54, commit
`1b357ecb321392158d507b04672ffee57bfa071d`, archive SHA-256
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`.
The checker records the exact source contracts read: `drivers/base/power/main.c`
and `drivers/base/dd.c` for callback device locks; `include/linux/device.h`
for locking APIs; `drivers/mmc/core/sdio.c`, `sdio_irq.c` and `sdio_bus.c` for
card/IRQ/reset ordering; brcmfmac `core.c`/`bus.h` for scheduling/draining reset;
and the patched `bcmsdh.c`, `sdio.c`, `sdio.h` for driver ownership and DPC use.
All are read from the verified local archive, not a moving source branch.
