# Wi-Fi worker error handling (NEO-68)

1 October 2026, Pacific/Auckland. This implements the offline follow-up to
[report 88](88-wifi-deferred-interrupt-service.md).
[Patch 0018](../kernel/patches/0018-brcmfmac-worker-errors.patch) stops ordinary
Wi-Fi packet work after a reported wake, clock-control or interrupt-status
failure. It preserves the first error, completes pending control requests and
stops interrupt/watchdog producers. It also closes an OOB interrupt rearm race
with teardown. Diagnostic.12 remains installed and unchanged; this candidate
has not been built into an image or exercised on the GameShell.

## Resulting behavior

| Trigger | Before | Candidate behavior |
| --- | --- | --- |
| Packet-worker wake fails | The return value is discarded; status and packet work continue. | Stop before status/packet dispatch, retaining the original error. |
| Pending-clock register access fails | A later access can overwrite the error or clock readiness can be published after a failed write. | Check every access before consuming its value or publishing `CLK_AVAIL`. |
| Interrupt status read fails | Immediate ISR logs the error; deferred DPC can consume pending state without explicit failure ownership. | Latch the error and let the worker perform cleanup in process context. |
| Status acknowledgement fails | Read status is still published; receive dispatch can precede the final error check. | Do not publish the unacknowledged status, and stop before receive/transmit dispatch. |
| Flow-control acknowledgement or follow-up read fails | The next access can replace the first error and processing continues. | Exit at the failing access; register counters count only attempted operations. |
| Clock request legitimately remains pending | Status access can proceed without an available backplane clock. | Preserve pending/leftover work, rearm the clock-only OOB notification if needed, and return until another interrupt schedules work. |
| Teardown retires an OOB IRQ during rearm | The outer registration check can become stale before the interrupt lock is acquired. | Recheck registration inside that lock; teardown retires ownership under the same lock before freeing the IRQ. |

The changes target these entry/refresh operations. They do not claim complete
error handling inside every mailbox, receive, transmit, diagnostic or firmware
download helper.

## Failure ownership and recovery policy

`sdiodev->io_error` records the first fatal I/O error under the SDIO host lock.
It is separate from `pm_failed`; the existing shared access guard now rejects
either latch. This extends the previously tested byte/backplane/packet I/O
guards, watchdog admission, control entry points, PM preflight and reset
rejection to worker faults.

The in-band ISR already owns the host. It records a failed status access and
queues the worker, but does not unregister the interrupt itself: releasing
the last SDIO IRQ can stop its servicing thread, so doing that from the thread
being stopped is unsafe. The worker is allowed to enter for an I/O fault and
checks the latch immediately after claiming the host, before further radio
access. The existing PM-failed worker gate is retained.

The cleanup helper runs once per device lifetime:

1. Preserve the first error and mark cleanup owned.
2. Publish the bus as DOWN and stop the watchdog timer.
3. Discard software interrupt status/pending flags from the failed lifetime.
4. Complete an already-published transmit-control request with the original
   error, publishing it before clearing the completion flag and waking its
   waiter. Wake response waiters; they return the existing `-EHOSTDOWN` result.
5. Mask a registered OOB IRQ or release both registered in-band handlers.
   The MMC core detaches handlers even if its final CCCR register update fails;
   those cleanup errors are logged without replacing the initiating error.
6. Log that the radio is unavailable until cold restart.

New control requests receive `-EHOSTDOWN`. Later queued passes cannot restart
the watchdog, replay an uncertain acknowledgement or repeat cleanup. Existing
queued data buffers retain their normal teardown ownership; this helper does
not introduce a competing packet-freeing path. Controlled MMC IRQ-disable
operations can access card-management registers after the latch, while guarded
radio I/O is rejected.

The tradeoff is deliberate: a reported error at one of these boundaries now
makes Wi-Fi unavailable until a fresh device lifetime. Even a transient error
may therefore require a cold restart. Automatic reset/reprobe, retry budgets
and recovery from uncertain writes remain separate work; no successful
automatic recovery is implied. USB management can be used for later hardware
qualification, but this offline work does not prove recovery of either route.

## Locking, clock waits and teardown

The SDIO host lock serializes fault publication, status accesses, cleanup and
registration-flag updates. No function-device lock is acquired by the worker;
this avoids waiting on a removal callback that may itself be draining that
worker. The existing F2 device-lock ownership for PM/reset/removal remains.

The shared IRQ-quiesce helper is now named `brcmf_sdiod_quiesce_irqs()` because
both PM and worker faults use it. Teardown checks and updates registration
flags while holding the host, so a concurrent worker cannot release the same
in-band handlers twice. OOB rearm and ownership retirement use `irq_en_lock`;
`free_irq()` still runs after releasing the host. The selected MMC
`sdio_card_irq_put()` and abort-aware `__mmc_claim_host()` contracts support
stopping an IRQ thread from another process context while the host is claimed.
This is not a full-kernel lockdep or exhaustive teardown-race proof.

A successful asynchronous clock request can return with `CLK_PENDING` after
arming the clock-available-only interrupt filter. That is not a transport
error. The worker leaves `ipend`/saved status intact and returns without
retriggering itself. The OOB path may reenable its IRQ in this state despite
pending status, so the clock notification can arrive. In-band handlers also
defer their backplane status read while the clock remains pending. Once ready,
the normal worker consumes the preserved status. A clock notification that
never arrives is not assigned a new timeout/recovery policy in this patch.

## Reproducible validation

```sh
task test:brcmfmac-worker
task check:brcmfmac-worker-drivers
task test:brcmfmac-irq
task check
```

The worker task is included in `task build`. It runs the IRQ/DPC suite and the
concurrent PM/lifecycle suite against patches 0014–0018. The original
`test:brcmfmac-irq` task retains diagnostic.12's patch-0017 baseline, including
its four explicit error-characterization cases, for comparison.

The IRQ harness executes actual ISR, status reader, DPC, worker, cleanup and
IRQ-quiesce bodies. Its scenarios cover immediate/deferred failures, first
error preservation, no packet dispatch after the failing entry operation,
single cleanup, failed IRQ-release reporting, queued control completion,
clock-pending-to-ready transitions and an OOB ownership change between the
outer check and lock acquisition. The latter is an injected ordering seam,
not concurrent execution of real `free_irq()`.

The lifecycle harness additionally runs actual transmit/response waiters on
pthreads against the real failure helper: a caller waiting for host ownership,
a published transmit request and a waiting response. It checks future
control/access/PM/reset rejection and retains the prior PM/teardown regressions.
Hardware, clock/packet transport, IRQ release and kernel scheduling remain
modeled; emulated ARM32 does not reproduce weak-memory interleavings.

Evidence directories are `.local/build/brcmfmac-irq-worker-tests/` and
`.local/build/brcmfmac-lifecycle-worker-tests/`. Their JSON records contain
archive, patch/source, harness/tool and source-contract hashes. The complete
normal/debug ARM driver builds use isolated scratch trees and leave the
installed-image source/output untouched. Checkpatch reports zero errors,
warnings and checks.

Final validation passed:

- **49 normal and 51 DEBUG IRQ/worker scenarios**, each natively and on
  emulated ARM32. **31 native negative controls** compile and fail assertions;
  compiler failures, timeouts and unexpected passes are rejected.
- **105 native/ARM32 PM/lifecycle/control scenarios**, with 13 native negative
  controls. This includes the earlier 102 scenarios and three actual waiting
  command cases. These totals overlap the earlier suites.
- The preserved diagnostic.12 IRQ baseline passes its 23 native/ARM32
  scenarios and 14 negative controls.
- Complete composite `brcmfmac.o` builds pass for normal ARM and isolated
  `CONFIG_BRCMDBG=y` configurations. The normal resolved configuration remains
  SHA-256 `d370205bf2e4eed5e35483f15372a6785e7d96252d40c343dfee0b2dde37a017`.
- `task check` passes 13 runtime and 276 tool tests (one optional skip), compiled
  helpers and Bash/ShellCheck.

Authoritative driver evidence is
`.local/build/brcmfmac-irq-worker-tests/compile-evidence.json`; current source
test evidence remains in each suite's `evidence.json`. Patch 0018 SHA-256 is
`b5a4905a63cdfcce17c6157e2f78b49885e1dce758e3717811e63864058e6d18`.
The final normal/debug scratch directories end in `kernel-a0125e801a2f02ad`
and `kernel-0accba0cfca4e977`, respectively. Host logs are
`.local/neo68-worker.log`, `.local/neo68-final-driver.log` and
`.local/neo68-check.log`, plus the named stage logs under `.local/build/`.

## Remaining work

- Build a separately versioned candidate image only after preserving the
  diagnostic.12 recovery evidence; do not silently change its identity.
- Qualify normal networking, observed driver stages, input/cable recovery and
  any justified controlled fault test on hardware. Actual sleep remains masked.
- Design automatic radio recovery separately, including MMC reset results,
  reprobe lifetime, bounded retries and user-visible unavailable/recovering
  states. Neither a repeated DPC nor a guessed acknowledgement replay is a
  recovery policy.
- Audit nested mailbox/receive/transmit transport failures separately. The
  first-entry error fixes do not make every packet helper transactional.
- Preserve NEO-55's unexplained authentication evidence. This patch does not
  establish its cause or resolution and makes no energy or latency claim.
