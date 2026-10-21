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

## Completed qualification

Attempt `8c3d7bc1c0334359874e529af7cccff1` completed the full driver Task:

- 215 TX cases and 115 RX cases pass natively, under ASan/UBSan with leak
  detection, and on ARM32.
- All 23 TX mutations, four packet mutations and five control-FIFO mutations
  fail their intended runtime assertions.
- 211 normal / 213 debug worker cases pass in all three execution modes;
  all 48 worker mutations are rejected.
- Both complete ARM `brcmfmac.o` builds pass, with no compiler errors/warnings;
  each configuration passes the 182 project assertions.
- All 1,362 retained artifacts and both object/configuration hashes were
  rechecked after completion. Nineteen of 20 recorded inputs remain byte-identical.
  The only subsequent input change shortens a patch commit-message line for
  checkpatch. Its entire diff body is byte-identical; the receipt records both
  patch hashes without rewriting the original manifest. Final checkpatch over
  the patch's contents reports zero errors/warnings.

| Artifact | SHA-256 |
| --- | --- |
| Evidence manifest | `672e6e73cfbcd3b450cc458d0d3b09bd18fe48a51247a569261ccbb3419c440d` |
| Compiled patch metadata | `12d721125ae9c9e644c86666c48137f163ff1b11ae3499237d5ec095a6b765f6` |
| Final candidate 0050 | `8717f38d998661e72c049b915dc5f07a73ac40983a556ef673ed9ed8260e828d` |
| Unchanged diff body | `47b3cea74ac181fe536fc7dbc88c37e1cd8012976265651b51a999f07be32c56` |
| Applied source tree | `60f5f6e43088995b526597a7dbe6cb50b150aa3b915a93d0ad9663fbbced928c` |
| Board object | `a5dafe8790cb65bd6fc17dd927ba17203534562112727b195e98e0a6be2244cd` |
| Debug object | `1870adc71b7ad3fd800b5b2959efd56f0e5d329714cbc42b6d137c684b64bfc1` |
| Final verification receipt | `65f06abbe82272972e8dc9c5153549530b52a4ffb6713eca1369bcf0504de897` |

The receipt is `.local/build/brcmfmac-tx-poll/final-verification.json`.

## Standards

The independent review was pinned to
`git diff 49534eb4d6aa9654dab9abb4de75166df5a99a79...f5ec5c74b060343d82cc6b53597e13e4e157419c`.

No documented-standard violations or substantive baseline smells were found.
The candidate fixes driver error ownership, consistent with `AGENTS.md`, and
stays focused on polling admission, error publication and access accounting.
Named scenarios reuse the existing TX runner and cover the changed ordering
boundary without unrelated abstractions. The report distinguishes reproduced
failures, partial runs and pending qualification, including hardware and
concurrency limits. Review was static; execution evidence is recorded above.

**Standards: zero hard violations, zero possible smells; no outstanding finding.**

## Spec

The independent Spec review used the same fixed diff and current NEO-198 ticket.
No Spec findings.

No missing implementation requirement was identified. The polling path
rechecks the existing error under the host claim, latches a new failure before
release, and skips failed-status publication. Relevant error writers are
host-serialized. Existing queue gates prevent further polling, dequeueing and
flow unblocking. Completed packets retain their send results; untouched
packets remain queued. DPC reacquires the host and performs established
quarantine, including pending control completion.

Successful polling, interrupt mode and recoverable TX behavior remain intact.
No unrequested expansion or incorrect implementation was found. Cases and
mutations cover ordering, errno/status variations, batches and worker handoff.
The reviewer conditioned offline closure on the final qualification and
evidence record, both now completed above. Image integration and matching
hardware qualification remain separate.

**Spec: zero findings; no outstanding finding.**

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
