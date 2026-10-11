# brcmfmac shared diagnostic error handling

12 October 2026 NZDT. NEO-201 continues NEO-58's isolated driver hardening.
The [caller audit](284-brcmfmac-shared-diagnostic-audit.md) records the original
source behavior and separate startup/output-bounds leads. Candidate 0053 is
outside the image queue; hardware qualification remains separate.

## Change and ownership

The DEBUG shared reader previously ignored a failed wake before reading RAM.
It also copied shared fields to its caller before rejecting an unsupported
version. Console discovery discarded diagnostic failures, and `checkdied()`
discarded a failed trap read.

[Candidate 0053](../kernel/candidates/0053-brcmfmac-shared-diagnostics.patch)
uses a common diagnostic RAM reader. Under the SDIO host claim it checks, in
order, an existing I/O error, failed PM and removed media. Rejected admission
returns the original error without accessing the device or repeating another
owner's cleanup. Successful admission must also complete wake before RAM
access. New wake or transport errors enter the existing once-only failure
cleanup while the host remains claimed. Local RAM allocation failures stay
`-ENOMEM`; invalid shared addresses/versions remain local metadata failures.

The shared reader retains its outer claim across both reads; the helper and
RAM transfer use the SDIO core's recursive host ownership. Shared fields are
published only after version validation. Console discovery publishes its
address only on success. It allows normal traffic to continue after local
diagnostic failures, but propagates unavailable-bus errors through the actual
mailbox/DPC caller. The non-DEBUG discovery stub returns success.

Assertion, trap and console-dump reads use the same admission and wake checks.
This matters after the original shared-reader claim has been released: PM or
another I/O owner may retire the bus before a later diagnostic acquisition.
`checkdied()` now returns a failed trap read instead of reporting success.

Startup failure diagnostics can execute before F2/IRQ/interface registration
completes. The audited probe initializes work, watchdog timer and both control
wait queues before submitting the asynchronous firmware request. Existing
IRQ cleanup checks its registration flags, and bus-state publication tolerates
an absent interface driver. Diagnostic retirement therefore uses initialized
cleanup primitives; the firmware callback retains driver-release/free ownership.
Repeated DPC/unwind cleanup preserves the first error and does not retire IRQs,
complete waiters or delete the timer twice. This does not qualify the other
discarded startup transfer results or reset/reprobe behavior.

## Reproduction and saved tasks

```sh
# Expected failures on the prior candidate stack, without 0053:
task test:brcmfmac-shared-baseline

task test:brcmfmac-shared-diagnostics
task check:brcmfmac-shared-drivers
```

The first baseline, `33efa3dc0f814c049b3e33f696ddbf24`, passed 28 of 86
diagnostic cases and failed 58: ignored wake, blocked admission, transport
retirement, premature version-error publication and caller error handling.
Its original logs and exact input inventory remain preserved. Later fixture
extensions do not retroactively change this reproduction.

The first candidate attempt exposed a harness extraction error: the extractor
selected a forward declaration and the following unrelated body. Definition
matching now skips prototypes, with a direct reproduction check. The next
attempt passed all 86 native cases but its sanitizer processes were rejected
by the sandbox's ptrace restrictions; that attempt is not sanitizer evidence.

## Controlled test boundaries

The 194 diagnostic scenarios execute actual shared, console-discovery,
assertion, trap, dump, RAM-helper and retirement function bodies. Lower SDIO,
wake, allocation and kernel synchronization operations are controlled seams.
They cover successful RAM-base/save-restore offsets, nested host ownership,
failed wake, prior errors, PM/media rejection, pointer/structure transfers,
metadata publication, allocation failures, actual diagnostic callers, every
later host acquisition and transfer, and startup timer/control ownership.

The worker suite separately executes actual mailbox, ISR, DPC and retirement
bodies. Its diagnostic-return seam covers errors both before and after
diagnostic-owned retirement, with OOB/in-band IRQs and deferred/hard IRQ
origins. The successful non-DEBUG path remains covered. These two suites do
not claim a full kernel scheduler or firmware-startup simulation.

Eighteen diagnostic mutations remove admission, wake, cleanup, classification,
publication or later-reader guarantees. They must compile and fail assertions;
a compilation failure is not an accepted negative control. A separate worker
mutation drops the new console-discovery error gate. Existing clock, watchdog,
sleep, packet and worker regressions remain part of the saved commands.

## Qualification status

Attempt `82f3b30cc4d44e119a5ad8489351603c` completed the saved diagnostic Task
successfully. Native, ASan/UBSan and ARM32 runs pass 194 diagnostic cases,
95/202 normal/debug watchdog cases, 95 normal/debug sleep cases (the original
happy transcript remains `a2658cef`), 215 TX, 115 RX and 263/289 normal/debug
worker cases. All 18 diagnostic, 28 watchdog, 23 TX, four packet, five control
and 51 worker mutations compile and fail assertions as intended.

Complete board/debug ARM compilation, independent review and a final
artifact/input rehash remain required before closing NEO-201.
No live device or image has changed. NEO-192
still gates live PM work; NEO-154 remains abandoned and this finding does not
attribute NEO-55's observed authentication delay.
