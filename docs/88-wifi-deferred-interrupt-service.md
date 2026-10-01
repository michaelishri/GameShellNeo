# Deferred Wi-Fi interrupt service (NEO-67)

1 October 2026, Pacific/Auckland. Offline continuation while the owner is away.
The new saved test executes the locked driver's actual interrupt-status and
packet-worker bodies. **23 scenarios pass on native x86 and emulated ARM32;
14 deliberately broken variants fail by assertion.** Four passing scenarios
characterize existing error-handling limitations; they are not recovery passes.

No driver, image, firmware or live-device setting changed. No command was sent
to the GameShell or Mac. The physical input/cable checks following
[report 87](87-diagnostic12-pm-validation.md) remain pending.

The subsequent source fix and its separate tests are in
[report 89](89-wifi-worker-error-handling.md); this report remains the
diagnostic.12 baseline characterization.

## Why extend the tests

[Report 84's lifecycle harness](84-brcmfmac-pm-lifecycle.md) executes the real
suspend/resume, freezer, reset/removal and interrupt entry functions, but uses
substitutes for `brcmf_sdio_intr_rstatus()` and the DPC packet worker. It proves
selected deferral/ownership behavior, not consumption of the deferred status.
The passing hardware cycles demonstrate useful network recovery, while their
cumulative counters do not isolate the short deferral interval.

The new harness closes part of that source-test gap by extracting unchanged
bodies for:

- `brcmf_sdiod_io_blocked()` and `brcmf_sdio_isr()`;
- `brcmf_sdio_intr_rstatus()` and the complete `brcmf_sdio_dpc()`;
- `brcmf_sdio_trigger_dpc()` and `brcmf_sdio_dataworker()`;
- `brcmf_sdio_clrintr()`, including its OOB rearm condition.

Register definitions and offsets come from the same verified source. Only
padding-member names in the register structure are expanded for host C.
The actual packet reads, mailbox contents, clocks, SDIO register transport,
workqueue scheduling and freezer are modeled seams. Unexpected clock-pending
byte access or packet-transmit dispatch fails an assertion instead of silently
succeeding. The harness selects an available clock and receive/mailbox work;
it does not qualify every branch of the complete DPC body.

## Interrupt handoff in this board's source stack

| Layer | Locked-source behavior | Consequence |
| --- | --- | --- |
| Sunxi MMC controller | The common handler processes command/DMA completion and the SDIO interrupt flag, clears controller status, then calls `mmc_signal_sdio_irq()` for SDIO. | The GIC ID 93 counter in report 87 counts host interrupts, not exclusively radio interrupt assertions. |
| MMC signal helper | Disables host SDIO interrupt delivery, marks pending and wakes the SDIO IRQ thread. | Masking at this point belongs to MMC; patch 0017 does not directly manage the controller mask. |
| MMC IRQ thread | Claims the host, processes pending function interrupts, releases it, then reenables host delivery before waiting. | If a radio interrupt condition remains asserted, another delivery is possible. Deferring its status read is not proof of a quiet IRQ line. |
| MMC card PM | Marks the card suspended after child-function suspend, and clears that mark before function resume. Pending-function processing returns early while the card is marked suspended. | The gaps before card suspend and after card resume still require the driver deferral gate. |
| brcmfmac in-band handler | Registers F1's real handler and F2's dummy handler. With both registrations present, the MMC single-handler shortcut is not applicable. | MMC can read its CCCR pending register even when brcmfmac defers its own backplane status read. |
| brcmfmac deferral | With the host claimed, a blocked in-band handler sets `ipend`, marks the DPC triggered and queues work without reading radio status. | Repeated events coalesce as pending state; they are not a count of distinct packets. |
| Restored worker | PM restores DATA and clears the gate before thaw. The queued DPC wakes the bus, consumes `ipend`, reads/masks/acknowledges status, and services receive/mailbox work. | This source sequence is covered in two complementary harnesses, not one full-kernel simulation. |

The saved source-contract hashes include `sunxi-mmc.c`, MMC `host.h`,
`sdio_irq.c`, `sdio.c`, `sdio_bus.c`, driver-core callback code and
`kernel/workqueue.c`. Those contracts are inspected source; the new harness
does not execute the MMC controller or Linux scheduler.

## Covered scenarios

| Group | Cases | Assertions |
| --- | ---: | --- |
| Deferred delivery | 12 | Bursts of 1, 8 or 64 in-band or hard-IRQ calls, followed by modeled successful or failed PM restore. No status I/O while parked; successful restore services receive/mailbox work; failed restore blocks work and further IRQ queueing. |
| Immediate/leftover work | 2 | Active in-band delivery reads status immediately; already-saved status is serviced without a redundant register read. Duplicate DPC triggers coalesce in the modeled queue. |
| Arrival during service | 1 | A new hard IRQ after the first status consumption publishes new pending state, gets another status read and services its mailbox indication. |
| Empty interrupt | 1 | One status read, no unnecessary acknowledgement or packet work. |
| Read failures | 2 | Both immediate and deferred reads reject poisoned returned data when the transport reports failure; no acknowledgement or receive dispatch. Existing lack of local retry/recovery is recorded. |
| Wake/acknowledgement failures | 2 | Characterize the current worker continuing after a failed wake or status acknowledgement; see below. |
| Failed-PM gate | 1 | Queued worker and new IRQ/trigger entries issue no hardware accesses after the existing failure latch is set. |
| OOB rearm | 1 | Pending status prevents reenable; consuming it permits one reenable, without repeated enable calls. This is generic source coverage, not CPI OOB wiring qualification. |
| Mailbox-generated receive | 1 | Mailbox-returned frame indication reaches receive dispatch. |

The receive seam keeps a frame indication pending across two DPC passes to
check preservation of leftover status. A modeled work item can be queued again
while running but cannot execute concurrently with itself. Register seams
assert host ownership and reject I/O while PM-blocked, parked or failed.
Loop bounds make accidentally spinning mutants fail an assertion.

Negative controls remove IRQ deferral, pending publication/consumption/clear,
status masking/acknowledgement/publication, the status-read error return,
frame/mailbox dispatch, leftover-status preservation, worker/ISR failure gates
or the OOB pending check. All compile and fail assertions; a compiler failure,
timeout or unexpected successful run is not accepted as validation.

## Concrete error-path follow-ups

The DPC still discards the result of `brcmf_sdio_bus_sleep(bus, false, true)`.
Injecting `-ETIMEDOUT` at that call does not stop the subsequent status read,
acknowledgement and receive dispatch. This is distinct from the PM resume
callback, which patches 0014–0017 now check and isolate. A future fix must
handle asynchronous clock availability, pending work and control waiters;
simply returning in a retriggered worker could create a busy loop or lose work.

When a status acknowledgement reports `-EIO`, `intr_rstatus()` still publishes
the read status and returns the error. The DPC dispatches receive work before
its final error check. The scripted failure leaves hardware status uncleared;
software pending/status is consumed and the PM failure latch remains clear.
An actual failed write may have taken effect despite its error, so the harness
does not establish the electrical acknowledgement outcome.

For a status-read error, the read helper correctly avoids publishing poisoned
data, but the current path has no explicit local retry or recovery ownership.
An immediate ISR error is logged; a deferred DPC error reaches its final error
handling after clearing `ipend`. Later hardware interrupts or watchdog work
are outside these scenarios, so this is not proof that recovery is impossible.

These observations justify a focused packet-worker error-handling slice, saved
in `FOLLOW-UP.md`. They do not establish the cause of NEO-55's intermittent
authentication delay, a regression from the PM patches, or measured wasted
energy. No extra retry or delay has been added to the installed system.

## Reproduce and evidence

```sh
task test:brcmfmac-irq
task test:brcmfmac-pm
task test:brcmfmac-lifecycle
task check
```

The new task is also included in `task build`. It reuses the source verification,
zero-fuzz patch application, native compilation, negative-control runner and
pinned Docker ARM32 toolchain in [the PM checker](../tools/check-brcmfmac-pm.py).
Extraction/mutations are in [the IRQ helper](../tools/brcmfmac_irq_checks.py);
the scenarios and explicit seams are in
[the C harness](../kernel/tests/brcmfmac_irq_test.c).

Evidence is `.local/build/brcmfmac-irq-tests/evidence.json`, with individual
variant outputs beside it and `.local/build/brcmfmac-irq.log`. It records
archive, patched source, harness/tool and source-contract hashes plus native
and ARM32 outcomes. The Linux 6.18.54 archive remains SHA-256
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`.
The patched driver hashes match reports 84/85 and diagnostic.12.

The shared runner's existing PM mode passed 89 native/ARM32 scenarios and 25
negative controls; its lifecycle mode passed 102 native/ARM32 scenarios and 13
negative controls. These totals overlap. `task check` passed 13 runtime and
276 tool tests (one optional skip), compiled-helper checks and Bash/ShellCheck.
Host logs are `.local/neo67-regression.log` and `.local/neo67-check.log`;
individual PM/lifecycle results remain under their existing build directories.

No complete kernel rebuild is required for this test-only change. Native and
emulated ARM32 results do not reproduce physical IRQ timing, weak-memory
concurrency, firmware/AP behavior, actual sleep, energy use or automatic reset
recovery. Hardware input/cable qualification and focused IRQ measurements
remain separate from these deterministic source tests.
