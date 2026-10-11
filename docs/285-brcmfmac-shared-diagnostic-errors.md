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

Full-driver attempt `154188bbb52047b4b9a2e337db4d15eb` also completed
successfully, repeating those suites and building complete board/debug ARM
objects. Each configuration passed 182 assertions; the compiler log contains
no warnings or errors. Checkpatch on the production patch reports zero
errors, warnings or checks.

Final attempt `74880c6936b34d9288a1a21d213edd65` repeats all native, sanitizer,
ARM and mutation checks successfully with the reviewed named boundary table.
The production patch is unchanged from the completed full-driver build.
No live device or image has changed. NEO-192
still gates live PM work; NEO-154 remains abandoned and this finding does not
attribute NEO-55's observed authentication delay.

## Independent review

The initial reviews used `git diff 4d9efd4...eab9776`, covering the caller audit
and implementation commits.

### Standards

Zero documented-standard violations. One low-priority possible Primitive
Obsession: the seven later-admission test boundaries used positional arithmetic
to select callers, host claims and preceding RAM-read counts. A named boundary
table was recommended to make the coverage easier to audit.

### Spec

Zero findings: no missing requirements, scope creep or incorrect implementation
identified. The review independently checked startup timer/work/waiter
initialization, null interface handling, IRQ registration/lock ownership and
later diagnostic acquisitions. Full objects and final verification were still
pending; the review did not treat those gates as completed.

Named boundaries now explicitly map each caller to its host acquisition and
preceding read count. Follow-up review of `4d9efd4...9c07ffa` confirms the
Standards finding is resolved, preserves the zero-finding Spec conclusion and
identifies no new findings. No production patch changed for this adjustment.

Final totals: **Standards: zero hard violations or remaining smells.
Spec: zero findings.**

## Final verification

After both Tasks terminated successfully, the final suite's 29 inputs and
3,088 artifacts were rehashed. The full-build attempt's 3,088 artifacts,
objects, configurations and full applied source inventory were also verified.
Its one changed input is the diagnostic fixture: the old hash matches
committed `eab9776`, and the final suite validates its reviewed replacement.
The source metadata and production patch are identical across both attempts.
The private receipt is
`.local/build/brcmfmac-shared-diagnostics/final-verification.json`.

| Artifact | SHA-256 |
| --- | --- |
| Final suite manifest | `7dc04355ee7417e3ebcfdd9941cd24d5bf1f83fc66866ac552c226a927ab0be8` |
| Full-build manifest | `1f9cf22a4bf54093074edc60bf2bb37e098f9d05784a54a7a701c8ace99beec6` |
| Candidate 0053 | `54fbbe6ed29994fc6f21afd37808f398582f0af7ba5d0a3748c72ed3fe86a16f` |
| Applied source inventory | `8c34d677e654c5f78648bff7ff25076034c5d92021b55b79e709610e10dbdcef` |
| Board object | `d19fba7e29b8e9739d3d8d75bb8659d2b52ede5164969f2f5769a2a52a186647` |
| Debug object | `ebed6b8c5aac6d5b294904491ccf53c7286b66b27426cfb4389cfe80c809b839` |
| Verification receipt | `7fa3a475519330a6825d7232abc9f7ebeea3f2aa7dc19e45f4517fd4873fe566` |

NEO-201's offline candidate scope is complete. NEO-58 retains integration,
hardware qualification and startup/reset ownership. NEO-202 tracks the
separate console-index and assertion-string output-bounds lead.
