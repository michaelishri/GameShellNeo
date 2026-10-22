# Saved clock publication reconciliation (NEO-228 / NEO-192)

23 October 2026 NZDT. A separate offline report now checks the recorded
publication/reader boundary and explains a comparable regression's arithmetic
components. The existing replay checked individual tuples and deliberately
left changed-tuple transition analysis open. This adds that diagnostic boundary
without changing the recorder, counter read, ABI or original replay.

The original MONOTONIC incident and distinct RAW -750 ns discrepancy remain
unresolved. Neither has the event-time tuple/publication evidence needed for
this analysis. The [MMIO feasibility STOP](305-clock-reference-feasibility.md)
remains valid; this report establishes no independent reference, clock fix or
PM admission. Fresh independent review and serialized publication are pending.

## Primary source and supported ordering

Seven source files were compared byte-for-byte with the freshly hashed locked
Linux6.18.54 archive, SHA
`9df30b02dd8102bbd0be52556288ef6889ddbe7f1ddb96fbf847d0becf3eacac`.
They cover timekeeping, clocksource bounds, POSIX getters, sequence counters,
timekeeper layout, clocksource layout and time namespaces. Only 243,164 bytes
of selected source were copied into private evidence; source caches are
unchanged. The primary-source audit receipt hashes to
`a175238c0ea177c936c60c7aa9e2d366a43072f8e7c8afba69c61f427b8fe1f6`.

The actual [hook](../kernel/candidates/clock-provenance/hooks.patch) records a
publication before the timekeeper copy and sequence end. The accepted
[reader](../kernel/candidates/clock-provenance/neo-clock-diag.c) records its
insertion inside the successful sequence attempt, before the retry decision.
Linux's sequence-counter protocol protects the data copied within that
accepted section. This supports a software ordering comparison; diagnostic
lock insertion is **not counter-instruction time**.
[Linux6.18 sequence counters](https://docs.kernel.org/6.18/locking/seqlock.html),
[locked publication source](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n708).

The fixed kernel.org/GitHub source pages were unavailable to the web reader;
the verified local archive supplies the implementation evidence. The official
versioned documentation was read separately. No moving source was substituted.

Two qualifications matter. `tk_update_leap_state_all()` changes the sequence
while updating only the unserialized leap-state field. A sequence gap with
unchanged protected fields is therefore legal and cannot prove a missing
publication. Also, `max`, `max_raw` and `source_id` come through the external
clocksource pointer. The analyzer preserves their conversion evidence but
excludes them from its protected-timekeeper projection.
[Leap-state writer](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n656),
[clocksource bound updates](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/clocksource.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n982).

## Report contract

```sh
task test:clock-transitions
task report:clock-transitions FILE=<saved-kernel.ndjson>
```

The report uses unchanged `clock_provenance.loads`, `replay` and `conversion`,
with the original 16 MiB input bound and 1024-call/2048-writer capacities.
It reads one saved stream and prints a separate JSON report. It never edits
the input, previous summaries or device state. The producer contract is an
explicit analysis assumption; `source_attested:false` prevents a saved label
from becoming independent source/device attestation.

Each consecutive publication's new projection is compared with the following
old projection. An accepted reader is compared with the latest preceding
publication's new state; the initial segment can use the first following
publication's old state. The projection includes six timekeeper-owned fields
per read base and seven scalar fields, listed explicitly in the output.

The output distinguishes:

| Result | Meaning |
| --- | --- |
| `consistent:true` | Complete recorded coverage and supported projection/sequence checks agree |
| `consistent:null` | Unknown coverage, anchor, sequence context or comparability remains |
| `consistent:false` | A protected projection contradicts the declared record/source contract |

An inconsistent stream retains its exact findings; it is not repaired or
attributed to silicon. A publication between read insertion and syscall end,
discarded-attempt insertion gaps and U32 publication wrap remain legal. No
publication anchor, loss and incomplete calls remain unknown. SETUP contains
an unfinished seed; nonpublication writer transitions are not reconstructed.
Writer site/action tags do not independently name an NTP, idle or PM cause.

For comparable same-clock regressions, the old tuple evaluated at the second
consumed count supplies a **hypothetical arithmetic** counter contribution.
Subtracting that and the observed namespace-offset contribution from the
returned delta leaves the tuple-transition contribution. The sum preserves
the exact returned delta; it adds no measurement. Conversion branches remain
visible. Source-generation/identity/mask changes, intervening SETUP,
inconsistent records or unqualified coverage prevent this decomposition.
The POSIX RAW getter uses the monotonic namespace offset in this locked tree.
[Original conversion](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/timekeeping.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n378),
[POSIX namespace addition](https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/kernel/time/posix-timers.c?id=1b357ecb321392158d507b04672ffee57bfa071d#n229).

`record_complete` remains the old replay's flag. It cannot grant the stronger
publication-coverage claim. In particular, CLOSED stops writer admission
before draining a possible active call, and normal export is unavailable
after release. CLOSED streams remain unknown even when all final call flags
are complete. This avoids diagnosing a later unrecorded publication as a
corrupted reader. No counter-read timestamp or stop timestamp is invented.

## Qualification and preserved checkpoints

Accepted published base is
`d5d67790668f4cb2b3d308a5b60da03c26b04911`. The first clean checkpoint
`bb3f26a05838a39263499b414dea3e4202876b73` passed its original 24 cases and
combined host check. Its sources, results and original sessions36581/81845
remain unchanged. Subsequent source audit added the conservative CLOSED
guard. The coordinator explicitly approved an independently named complete
CLOSED variant while preserving the original unfinished-call probe.

Current tests execute clean source
`d2a9891f4867358e547554eeb8de3c9f39202f79`:

| Fixed family | Original cases | Current variants |
| --- | ---: | ---: |
| Anchored controls | 6 | 6 |
| Legal ambiguity/interleaving | 5 | 5 |
| Projection consistency negatives | 3 | 3 |
| Regression components | 4 | 4 |
| Malformed/incomplete/CLOSED | 6 | 7 |
| Total | 24 | 25 |

The saved focused Task passes **five methods / 25 actual CLI variants**:
21 parsed reports and four expected parser/structure refusals. Three
arithmetically valid but inconsistent streams retain explicit findings;
legitimate unknowns are not relabeled corruption. The complete CLOSED
fixture has complete original replay and a regression, but no qualified
reader/decomposition result. The unfinished-call fixture remains separate.
The unchanged-tuple synthetic -750 ns fixture uses its original 125/4
conversion and 24-tick difference; it does not establish the historical
hardware event's counter magnitude.

Every case saves its raw input/stdout/stderr/observation before assertions,
including unexpected failures. The actual CLI and direct module agree;
raw/object immutability, actual import paths and unchanged replay reuse are
checked. All **946 tracked inputs** match before/after both saved Tasks.
The actual Task import trace and complete committed input manifests include
the fixture's dynamically loaded checker; no unrecorded runtime alias-origin
event is claimed.

Current focused original session67312 / Task1312277 / wrapper1312264 exits0.
Receipt SHA `d861921c119abfbd7e06be974a79326cf083e5c6fa3fb628f731cb060077b9ef`;
log `16e86936aaa2ce863114e35896c94a6257ded0e71f0e2448c9c54682b5d85920`.
Current combined original session19258 / Task1312519 / wrapper1312506 exits0:
**24 runtime /1443 tooling tests, nine expected skips**, both C guards and
Bash/ShellCheck. Receipt
`5a6734d192911cbc3d88f83a6cfde9ee44865a82ca0024a6f801548535f5b71c`;
log `f4b156c7352c4a07b162a4fd12c6bbc87847e22d415dc659a526d2e46a7b857f`.
Attempts are under ignored `.local/clock-next-reference/focused/` and `full/`.
The second checks are required by the actual source correction; no failed
qualification is retried or relabeled. All original jobs are terminal.

Host Tasks use one host CPU; this changes no hardware measurement affinity.
Largest observed child RSS is 131,624 KiB for the current combined check.
Evidence occupies under100MiB. No new ARM/guest/kernel/image build, runtime
replacement, device/Mac operation, PM, policy, counter reset or barrier change
occurs. Original producer/reader/ABI and all existing Tasks remain unchanged.

## Retrospective application, not another capture

Versioned current report Tasks run once on the unchanged original streams:

| Historical capture | Calls/publications/writers | Current report SHA-256 |
| --- | --- | --- |
| NEO-213 | 384 /1 /2 | 2dbdd78868223198c86fd3aaf9e31bedacd6a04b4434cee16e4ea71d54d6b403 |
| NEO-217 | 256 /223 /458 | 9fedcb399f46dbf56add891aaf80ef32f828886fcbc2ff8b7a24311aeeb3436c |

Both recorded windows reconcile without findings, unknowns or regressions.
Their raw hashes remain `aa40f8c5…` and `0285ba8b…`, with full digests in the
new reports/index. Actual capture-host sources remain reviewed23c4133 and
6524aea, as documented in [report296](296-development-clock-admission.md) and
[report302](302-scheduled-clock-boundaries.md). The new analysis executed d2a9891;
it is never relabeled as source executed during those captures. Kernel/image
provenance remains the original preserved evidence.

Current report Task PIDs1312485/1312494, wrapper1312473, exit0. The first
bb3 reports also remain preserved; their PIDs14/22 are executor-local from a
different offline invocation context. No historical PID is represented as a
current host or device process. No capture or ancestor ABI qualification is
repeated.

Only own report/README/FOLLOW-UP/navigation prose changes after current
qualification. Complete final source/spec/evidence requires fresh additional
Standards and Spec reviews, then a separate integration grant. NEO-192 and
dependent NEO-191/182 PM gates stay open. A future recurrence with valid
event-time records can use this diagnostic boundary; these clean historical
windows cannot establish its cause or exclude an intermittent fault.
