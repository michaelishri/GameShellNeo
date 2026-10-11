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
error preservation and once-only cleanup. Watchdog publication and worker
consumption are controlled scheduling seams; they are not a full kernel
scheduler or physical missing-interrupt experiment. Existing sleep regression
tests execute actual KSO/clock/sleep bodies and retain the original 43-case
successful transfer/delay/state transcript `a2658cef` within 95 scenarios.

Native, sanitizer and ARM checks, mutation controls, full ARM objects and
independent Standards/Spec review are required before closing this offline
ticket. Their final receipts will be recorded below. No hardware result,
energy saving or explanation of an observed Wi-Fi fault is claimed. NEO-58
retains image integration and matching board qualification. NEO-192's clock
fault still blocks live PM; this work does not reopen NEO-154 or attribute
NEO-55's authentication delay.
