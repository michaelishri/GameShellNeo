# Verified repeat RTC-wake testing (NEO-107)

4 October 2026, Pacific/Auckland. The test runner now supports up to four
attended actual-sleep cycles per command, with independently verified recovery
before each next submission. This prepares repeatability testing after
[diagnostic.18's first success](142-diagnostic18-first-rtc-wake-success.md).
Source tests and a read-only on-device import/clock inspection pass. The new
admission path and batch still need attended hardware qualification; no new
sleep, kernel image or production power policy is included in this change.

## Evidence and ownership

The original seven-debug prerequisite sequence remains mandatory. A repeat
receipt adds the complete ordered history of successful actual sleeps to that
anchor; it does not reset counters or treat a consumed baseline as unused.
Every run retains the same source/image/boot and original awake rehearsal.

The host requires independent USB and Wi-Fi proof in every saved result. It
recomputes wake/restoration checks without modifying the original record and
builds a receipt containing its run identity and digest. The device reads its
own original results and checks those identities/digests before revalidating
the same evidence. Validation covers actual RTC wake, PM generation, full
late/noirq/s2idle traces, unchanged SDIO ownership, input retention, memory,
audio/display policy, USB configuration/carrier, trace restoration and clean
power-key/RTC/control handback. Stored success flags are insufficient.

Adjacent sleeps must have continuous PM statistics and RTC interrupt counts,
strictly ordered snapshot times and matching ancestry. Changed sources, a
different image/boot, missing/reordered records, unrecorded PM/RTC activity,
failed cleanup or an unknown result stop admission. The first sleep binds the
original awake rehearsal's alarm count; later attempts bind the last accepted
sleep's count. No new rehearsal is inserted midway through a repeat chain.
The chain is bounded to 16 actual sleeps; larger soak workflows need a separate
review rather than an unbounded in-memory history.

Before alarm or PM mutation, the device exclusively creates and fsyncs a
`sleep-successor.json` claim in the parent result's directory, then fsyncs the
directory. The first parent is the final debug result; subsequent parents are
successful actual-sleep results. Each parent can have only one successor.
Claims survive failures and interruptions and are not removed by diagnostic
cleanup. A later request must collect/review the claimed original attempt,
not overwrite its claim. The existing device PM lock serializes admission.

Each host cycle submits one transient service with its own run ID. A lost
submission response leads only to collection of that same ID. After complete
device evidence and both independent SSH proofs, the host atomically saves
`qualification-next.json`. A failed/incomplete cycle does not publish a new
continuation or start another cycle. The twenty-second interval between
accepted cycles is for awake observation, not evidence of resume latency.

## Saved workflow

```sh
# Fresh same-boot seven-debug history and current helper sources required.
task device:sleep-rehearse QUALIFICATION=<current-history.json>
# Fresh observer readiness for the whole batch is required.
task device:sleep-batch QUALIFICATION=<current-history.json> \
  REHEARSAL=<awake-run-id> CYCLES=4 ATTENDED=1
# A subsequent attended batch uses the last accepted continuation and
# the original awake rehearsal ID, with unchanged sources/image/boot.
task device:sleep-batch QUALIFICATION=<qualification-next.json> \
  REHEARSAL=<same-awake-run-id> CYCLES=4 ATTENDED=1
# Uncertain outcome: collect the original run; never resubmit the batch.
task device:sleep-collect RUN=<original-run-id>
```

The existing single-attempt `device:sleep-rtc` also publishes an accepted
continuation. `batch.json` records requested/completed cycles, the latest
accepted continuation and a terminal error if the batch stops. All evidence,
including failed collection/submission transcripts, remains private under
`.local/diagnostics/`; settings and secrets remain in `.env`.

The original diagnostic.18 success predates this runner source and has no
successor ledger. It remains valid historical evidence and is not rewritten
or accepted as a new-source predecessor. Establish a fresh seven-debug
sequence and new-source awake rehearsal once before using the new repeat
chain. No card reflash is required. Normal sleep stays masked.

## Validation and limits

`tools/tests/test_sleep_chain.py` exercises valid chains of zero, one, four and
sixteen prior sleeps, with rejection of altered sources, ownership, wake
assessment, trace/USB evidence, identity, ancestry, ordering and PM/RTC counts.
It checks device-side original result hashes, single-successor claims and
rehearsal continuity. Native filesystem fixtures exercise exclusive claims;
the PM snapshot acquisition is modeled, not performed on a live PM device.

Host transport tests simulate a lost submission response, transient collection
errors, a started-but-incomplete result, a timeout and failed Wi-Fi proof. They
require exactly one service submission and collection of the same original ID.
Batch tests cover all four sequential attempts, invalid counts, failure of the
second attempt and incomplete route proof without a subsequent submission.
The existing sleep suite retains the single wakeup-counter/state write,
alarm restoration and failure ownership checks. Attended-flag rejection is
tested for both the single and batch commands before credential/network access.

The focused sleep suites pass **53 tests**. `task check` passes **13 runtime
tests and 498 tooling tests**, with one existing optional skip, plus compiled
current-limit/mount-guard checks and Bash/ShellCheck. Logs are
`.local/neo107-sleep-tests.log` and `.local/neo107-check.log`. A subsequent
test-only extension checks both attended CLI modes; the focused suite passes
again. No driver rebuild is needed for this host/uploaded-helper change.

The updated helper's `device:sleep-clock-inspect` passes on diagnostic.18,
boot `e419f334-0a16-4b04-96d2-d97a2e4d5d0b`. Sources match the upload; PM counts
stay 8/0 and controls stay none/async 1. CPU-idle remains `none` with CPUs 0–3
and `arch_sys_counter`. Evidence:
`.local/diagnostics/20261003T172356.679408Z/clock-inspection.json`. A separate
read-only PM inspection is saved at `20261003T172448.871179Z`.

This checks import/execution and unchanged awake state, not live repeat
admission or successful batches. Fresh observer readiness is required for the
new-source baseline, awake rehearsal and subsequent actual sleep qualification.
No performance, CPU-retention or battery-life improvement is claimed by a
diagnostic workflow change.
