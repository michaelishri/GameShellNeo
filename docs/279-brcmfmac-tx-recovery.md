# brcmfmac transmit FIFO recovery and caller ownership

12 October 2026 NZDT. NEO-197, continuing NEO-58 after the reviewed RX candidates
in [report 278](278-brcmfmac-rx-review.md). The source is locked Linux 6.18.54
with the image queue and isolated mailbox/RX candidates 0039/0046/0047/0048.
This work neither accesses the GameShell nor modifies diagnostic.26.

## Reproduced defect

`brcmf_sdio_txfail()` aborts a failed send, terminates the write frame and polls
the write FIFO count up to three times. It previously ignored the abort result
and passed no error destination to the terminate/count operations. It also
returned normally if all three count pairs remained nonzero. Consequently its
callers could retry a control send, transmit another data packet or poll status
without establishing that recovery succeeded. This remained true after the RX
candidate corrected the abort helper's return value: TX still discarded it.

The saved baseline passes **44/107 scenarios** and fails the remaining **63**.
The failures cover transport errors at every recovery stage, count exhaustion,
earlier latched errors and subsequent control/data I/O. All 32 successful or
recoverable-control scenarios, eight successful/recoverable-data scenarios,
three successful flush timings and the local packet-preparation error pass.
This distinguishes the faulty recovery behavior from the preserved good paths.

The original baseline attempt is
`.local/build/brcmfmac-tx-recovery/attempts/1d83cc437e644827a527ce2b99ec16e6/`.
Its per-case logs retain the ordered send/recovery operations and assertion
failures. The preceding fixture compile attempt `3c9b17bc3c4543c09bcacf8652f9b445`
lacked the `ctrl_frame_stat` member and two transitive constants used by the
actual extracted functions. Those fixture omissions were corrected before the
reproduction; that compile failure is not treated as a driver failure.

## Candidate behavior

[Candidate 0049](../kernel/candidates/0049-brcmfmac-tx-recovery.patch) checks the
abort, terminate and each count read immediately. It preserves an earlier
`io_error`, records the first new recovery error, and records `-ETIMEDOUT` if
the FIFO has not emptied after the original three-pair budget. Register
statistics count attempted accesses. A successful final permitted poll remains
valid; no additional delay or shorter successful-hardware budget is introduced.

The caller changes make that result effective:

- Control transmission rejects prior recovery failure before header work and
  returns a new recovery failure before retrying. The existing successful
  recovery/retry budget and successful sequence advance are retained.
- Data transmission rechecks the error under the SDIO host claim before
  sending. It always releases that claim and performs its established packet
  postprocessing/completion. Failed original sends retain failed completions;
  successfully recovered FIFO state permits the next queued packet.
- The queue stops before status polling or another dequeue after fatal
  recovery. It does not unblock upper-layer transmission while that error is
  latched. Packets not yet dequeued remain owned by the original queue.
- DPC hands control failure directly to its existing cleanup while holding
  the host. After a data batch, it reacquires the host for that cleanup.
  The existing path stops the watchdog, completes pending control waiters,
  wakes response waiters and retires interrupts once. Caller packet cleanup
  finishes before this worker shutdown.

This changes failure handling in the driver rather than adding a userspace
retry. Recovery failure still uses the project's existing unavailable-until-
fresh-lifetime policy; automatic reset/reprobe remains separate work.

## Saved qualification

```sh
# Expected assertion failures against the pre-candidate source:
task test:brcmfmac-tx-recovery-baseline

task test:brcmfmac-tx-recovery
task check:brcmfmac-tx-recovery-drivers
```

The Tasks verify the locked archive, isolate the applied source, and retain
each attempt's source identity, input hashes, generated bodies, binaries and
per-case logs. Docker runs use the pinned builder, `--network=none` and
`--pull=never`. The candidate is rejected if accidentally placed in the image
queue. The baseline remains a reproduction command, not a passing check.

The actual abort, TX recovery, control/data transmit, queue-dispatch and credit
predicate function bodies run through **107 cases**:

| Cases | Coverage |
| --- | --- |
| 31 helper | Four failure stages × three errno values × zero/all-ones failed read data; success on each allowed poll; exhaustion; three prior errors; repeated cleanup preserves the first error. |
| 10 control failure | Each recovery failure/exhaustion with both failed-data values; no next send. |
| 32 control success | Zero to three failed sends, normal/glom header mode and four alignments; final-poll recovery, existing retry limit and sequence behavior. |
| Three prior control errors | Rejected before packing or transport. |
| 20 data failure | Each recovery failure/exhaustion with interrupt/poll mode and single/glom batches; owned packet completions, retained queue, no later status access or deflow. |
| Eight data success | Normal sends or one successfully recovered error across both modes/batch sizes. |
| Three local data failures | Preparation failure, prior error, or error arriving during preparation; host balance and completion without a send. |

Seventeen deliberately broken variants must fail assertions. They remove
individual error gates, the first-error latch, exhaustion, prior-error
admission, queue/poll/deflow gates, completion or postprocessing; shorten the
successful flush budget; or break successful sequence advancement.

The actual worker/IRQ bodies separately cover **179 normal / 181 debug cases**,
including 32 new TX completion/shutdown combinations for control versus data,
successful versus three fatal results, in-band versus out-of-band interrupts
and hard versus threaded entry. The 48 worker mutations include lost TX
shutdown and missing host reacquisition. Existing **115 RX cases**, four packet
mutations and five control-FIFO mutations run against the same combined source.
Native runs, native ASan/UBSan with leak detection and ARM32 executions cover
all three suites. Complete board/debug ARM object compilation is a separate
additional stage of the driver Task.

The initial TX-only candidate run `2b33057f777c4874bf3707913ad9c899` passes all
107 cases in those three execution modes. The extended run
`81c8b0af13984f1e81b27f21a608c6d5` additionally passes the RX and worker suites,
all mutations and the combined ARM executions.

The final driver Task, attempt `8768ac9b2c0948c9a1e906dec290bdc9`, repeats that
complete qualification and builds both full ARM `brcmfmac.o` configurations
without compiler errors or warnings. Checkpatch reports zero errors/warnings.
All 19 recorded current inputs, 1,014 retained artifacts, both object hashes
and their kernel configuration hashes were verified after completion.

| Final artifact | SHA-256 |
| --- | --- |
| Evidence manifest | `7295cb68910543cf576670fde8fb0505c30da0fa60aea2eb29580b20a556ef40` |
| Candidate 0049 | `a002a98e3eff6a34ab06ecaecff7ac30a8d8a3f28ca93142abe7d6ef9f472854` |
| Applied source tree | `d4338bce838ba7c1228000e87afbdb1d66846744bcd61c7f6586752d2b52a930` |
| Board `brcmfmac.o` | `3b5027b711a5a831893729059a86d487f08999966cf9446ed134d4b1d102236b` |
| Debug `brcmfmac.o` | `be2eb4820367cc8465b90aa41325a9d4b7c62bcc1b9a8d85d434c9d56d7f0bae` |
| Final verification receipt | `ba47f5288b175e216877e08a5c0caf7c79b87463d07b5fe41e08f599aa77aa14` |

The receipt is `.local/build/brcmfmac-tx-recovery/final-verification.json`.
The isolated offline candidate completed independent review and a fixture
cleanup rerun in [report 280](280-brcmfmac-tx-review.md).

## Evidence boundaries and remaining work

The source functions are real; synchronous SDIO results, packet queues,
header packing and packet preparation/postprocessing are controlled seams.
The worker suite uses scripted packet-call boundaries to check error handoff;
the packet suite exercises the actual callers separately. These checks do not
establish complete-kernel concurrency, SG/DMA alignment correctness, physical
FIFO behavior, RF stability, energy savings or the cause of NEO-55.

Deliberate image integration and matching board qualification remain separate
from the completed offline review. The GameShell clock fault still blocks live PM
qualification; it is not bypassed. NEO-154's abandoned SSH-stall work remains
abandoned.

One adjacent source lead remains outside this correction: `sendfromq()` breaks
on a failed polling-mode `intstatus` read but does not pass that result to DPC;
the helper returns a packet count. This patch prevents that poll after failed
TX recovery, but does not claim to fix a distinct error in the polling access
itself. The lead is retained in `FOLLOW-UP.md` under NEO-58.
