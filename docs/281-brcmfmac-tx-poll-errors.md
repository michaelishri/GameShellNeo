# brcmfmac queued-TX polling error ownership

12 October 2026 NZDT. NEO-198 continues NEO-58 after
[NEO-197's reviewed TX recovery](280-brcmfmac-tx-review.md). The source is
locked Linux 6.18.54 with the image queue and isolated mailbox/RX/TX candidates
0039/0046/0047/0048/0049. No GameShell or diagnostic.26 change is part of this work.

## Defect and correction

In polling mode, `brcmf_sdio_sendfromq()` reads interrupt status between queued
transmissions. It previously broke its local loop when that read failed, but
returned only the number of completed packets. The caller could not see the
error; queue deflow and later worker dispatch remained possible. Status bytes
returned with an error cannot establish device state.

[Candidate 0050](../kernel/candidates/0050-brcmfmac-tx-poll-errors.patch) latches
the read error while still holding the SDIO host. The established caller gates
then prevent queue deflow or another dequeue, and DPC reacquires the host for
the existing quarantine path. Already-completed packets keep their original
send result; packets still queued remain owned by that queue. The failed read's
value is not published as pending status.

The poll also rechecks `io_error` after claiming the host. An IRQ may have
latched an error between the outer check and this claim. In that case it skips
the read, preserves the earlier error and does not count an unattempted access.
Successful polling and interrupt-driven traffic retain their existing behavior.
No retry or userspace workaround is added.

## Reproduction and saved tests

```sh
# Expected assertion failure against the source before 0050:
task test:brcmfmac-tx-poll-baseline

task test:brcmfmac-tx-poll
task check:brcmfmac-tx-poll-drivers
```

These commands reuse the TX runner, source extraction and locked offline
builder. Candidate 0050 must remain outside the image queue. The baseline
attempt `b62aeb98bb134ce693aa316b4361d98f` passes **137/215** cases; all 72
poll-read failures and six prior-error cases fail. The original 107 TX cases
plus 30 successful-poll/interrupt cases pass. Its ordered per-case logs remain
under `.local/build/brcmfmac-tx-poll/attempts/`.

The expanded actual-source TX suite contains the original 107 cases plus:

| Added cases | Coverage |
| --- | --- |
| 72 failed polls | Three errno values; zero, all-ones and valid-looking status; first or second poll; single/glom packets; successful send or successful FIFO recovery after a send error. |
| 12 successful polls | Three status values, both batch modes and successful/recovered sends. Valid status notification remains observable. |
| Six prior errors | Three errors arriving at the polling host claim, both batch modes; zero status reads and preserved first error. |
| 18 interrupt-mode cases | Configured poll faults do not affect interrupt-driven transmission or cause status reads. |

Assertions check host ownership/balance, statistics, completed packet results,
retained queue contents, pending-status publication, suppressed deflow and a
second dispatch after fatal failure. Six new broken variants remove the error
latch, under-host admission, failed-status gate, successful notification or
statistics, or move the latch after host release. The previous 17 TX mutations
remain included.

The worker suite adds 32 combinations to its previous 179 normal / 181 debug
cases: four error values, hard/threaded entry, in-band/out-of-band interrupts,
and a control request already completed versus one becoming pending during
data transmission. It checks exactly-once cleanup of the latter, retained
first error, host ownership, IRQ retirement and suppression of pending/new
work after quarantine. The existing RX caller regressions also run against
the combined source.

The first candidate attempt, `8a81153588f8499a8a9482d2f23d39e3`, passes all 215
native and sanitizer cases, then correctly stops because an old mutation no
longer triggers an assertion: the new inner poll guard prevents I/O even if
the earlier outer guard is removed. The fixture now also asserts the outer
guard avoids an unnecessary host reacquisition after known TX recovery failure.
This retains a meaningful check for both guards; the failed attempt is preserved.

The next attempt, `d96110e8a7294ab79c3eff04efdb75b0`, also passes all positive
native/sanitizer cases, then stops because the notification mutation leaves
`intstatus` unused and fails compilation. The mutation now retains the operand
in a false condition so it must fail the intended runtime assertion. Compiler
failure is not counted as successful fault detection.

## Qualification boundaries

Packet preparation/postprocessing, transport and queue primitives are scripted
seams around actual driver caller bodies. The worker suite models the packet
call's error publication separately. Injecting an error at host acquisition
tests the identified ordering boundary; it does not prove complete-kernel
concurrency. Header packing, SG/DMA behavior and electrical SDIO failure remain
outside this fixture. Compiler success is not RF or energy qualification.

Deliberate image integration and matching board validation remain with NEO-58.
This source defect is not attributed to NEO-55's authentication delay. The live
clock fault is not bypassed, and NEO-154 remains abandoned.
