# brcmfmac asynchronous clock-readiness deadline

12 October 2026 NZDT. NEO-200 continues NEO-58 after the reviewed
[watchdog correction](282-brcmfmac-watchdog-errors.md). This is an isolated
candidate on locked Linux 6.18.54; it is outside the image queue.

## Problem and behavior

`brcmf_sdio_htclk()` can request a clock, enable the clock-available interrupt
filter, publish `CLK_PENDING` and return. The worker preserves pending events
and returns while waiting for the readiness interrupt. There was no deadline
for this asynchronous state. A missing notification or never-ready clock could
therefore leave traffic waiting indefinitely. The board's normal interrupt
mode does not enable the watchdog's ordinary interrupt polling.

[Candidate 0052](../kernel/candidates/0052-brcmfmac-clock-deadline.patch)
records the first request's deadline using the existing
`PMU_MAX_TRANSITION_DLY` budget: 1,000,000 microseconds in this driver. Repeated
pending requests retain it, including a later request for synchronous
completion. Cancellation followed by a new request receives a new budget.
Save/restore mode keeps its existing fast path.

The existing watchdog checks this deadline without adding a timer, thread or
periodic register access. Once due, it claims the SDIO host, rechecks admission,
state and deadline, then publishes pending status and queues the existing
worker under that claim. Existing queued work is retained. The worker reads
actual readiness under the host claim before deciding whether to time out:

- Confirmed readiness clears the clock-only filter and continues normal work,
  including readiness whose interrupt was lost.
- A CSR or filter transfer failure preserves its original error.
- A clock still unavailable at the deadline enters existing once-only failure
  cleanup with `-ETIMEDOUT`: retire traffic/IRQs, stop the watchdog, complete
  pending control/response waiters and preserve the first error.

This bounds the logical pending wait when the existing watchdog and worker
can run and acquire the host. It is not a hard wall-clock bound while the host
is blocked or tasks are frozen. A ready clock is accepted even if scheduling
delayed its check beyond the deadline. Failure quarantine does not implement
automatic reset/reprobe; that remains a separate NEO-58 responsibility.

## Reproduction and saved commands

```sh
# Expected assertion failures without candidate 0052:
task test:brcmfmac-clock-baseline

task test:brcmfmac-clock-deadline
task check:brcmfmac-clock-drivers
```

The commands reuse the combined watchdog/TX/RX/worker runner. They do not
access the GameShell. ARM emulation and complete board/debug objects use the
locked builder with networking disabled. Inputs, generated function bodies,
per-case logs and binaries remain under ignored
`.local/build/brcmfmac-clock-deadline/attempts/`.

Baseline attempt `3859665ce49841bab58439fd15dee495` passed 72/94 normal and
179/201 debug watchdog cases. The 22 clock failures in each mode cover missing
deadline publication, budget renewal, cancellation/new requests, synchronous
handoff, due notifications and host-boundary admission. All pre-existing
watchdog cases passed. Original failing logs remain available; subsequent
fixture additions do not retroactively change this baseline's input inventory.

## Test boundaries

The fixture extracts the actual HT-clock, watchdog, timer, cleanup, console
and RAM helper bodies. It controls SDIO results, jiffies, allocation and host
ownership, including a change between the watchdog's initial check and its
host-held recheck. Clock tests cover ordinary and wrapping deadlines,
before/at/after checks, repeated requests, cancellation, immediate readiness,
save/restore bypass and an expired synchronous handoff.

The worker suite extracts actual ISR, pending-status, worker and DPC bodies,
with scripted clock and packet-call boundaries. It checks unavailable and
ready clocks before/at/after the deadline and across wrap, retained traffic,
error preservation and once-only cleanup. Additional consumer cases start
from a software notification without invoking an ISR, explicitly checking
zero hardware-interrupt count. They cover ready/unavailable clocks and both
IRQ ownership modes; at-deadline read/filter failures must keep their transfer
error rather than become timeout. A watchdog release-boundary injection
checks another claimant retiring the bus immediately after publication.
Watchdog publication and worker consumption remain controlled scheduling
seams; they are not a full kernel scheduler or physical missing-interrupt
experiment. Existing sleep regression
tests execute actual KSO/clock/sleep bodies and retain the original 43-case
successful transfer/delay/state transcript `a2658cef` within 95 scenarios.

Native, sanitizer and ARM checks, mutation controls, full ARM objects and
independent Standards/Spec review are required before closing this offline
ticket. Their final receipts will be recorded below. No hardware result,
energy saving or explanation of an observed Wi-Fi fault is claimed. NEO-58
retains image integration and matching board qualification. NEO-192's clock
fault still blocks live PM; this work does not reopen NEO-154 or attribute
NEO-55's authentication delay.

## Initial qualification and review

Attempt `6fa74489560c4679ae31279b090773d4` completed the full driver Task:
94/201 watchdog, 95 normal/debug sleep, 215 TX, 115 RX and 235/237 worker
scenarios passed natively, under ASan/UBSan and on ARM32. All 26 watchdog,
23 TX, four packet, five control-FIFO and 50 worker mutations failed
assertions as required. Both complete ARM objects passed 182 configuration
assertions. This attempt predates the explicit no-ISR consumer and
release-boundary additions; it does not qualify those later tests.

Independent review used `git diff d47ef98...c73602c`, a single NEO-200 commit.

### Standards

No documented-standard violations. One low-priority possible Primitive
Obsession: unnamed numeric modes made the clock fixtures harder to audit.
Named request and watchdog scenario enums replace those numbers; matrix
indexing remains unchanged.

### Spec

One P2 partial-coverage finding: the initial deadline worker cases all
invoked an ISR, while the watchdog fixture stopped after publication.
The missing-interrupt consumer therefore had no direct no-ISR evidence.
The added software-notification cases cover ready/never-ready clocks and
OOB/in-band IRQ ownership, without claiming a full scheduler simulation.
The initial review found no production correctness or scope-creep defect.

Final validation and follow-up review of these additions remain pending.
