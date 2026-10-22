# Standalone host awake-result admission (NEO-224 / NEO-101)

23 October 2026 NZDT. Five standalone host consumers previously trusted a
successful completion without independently recomputing its raw awake-clock
proof. NEO-224 adds this check before host success or removal of the owned
helper stage. This is a host-only result-consumer correction; it neither
changes the collectors nor qualifies the unresolved clock fault or PM.
The focused checks below pass. Required combined checks and fresh independent
Standards/Spec review remain pending before publication and closure.

## Reproduced original behavior

The retained baseline uses actual `remote.device_action`,
`check-rsb-runtime.main` and `remote.run` from published
`7120990023cb17ecc152eadefa57f37c19309ed9`. Scripted local channels and SFTP
replace the connection endpoints, while normal host imports, command
construction, output saving and cleanup execute. No SSH connection, collector
execution, sysfs access or device operation occurs. Fixtures contain artificial
result fields; they are not captured hardware data.

All five consumers accepted both a missing proof and disturbed raw PM
observations accompanied by a forged successful stored validation summary:

| Host consumer | Original handling | Invalid cases accepted | Helper stage deleted |
| --- | --- | --- | --- |
| `device:idle-sample` | No post-capture proof admission | 2 | 0 |
| `device:power-profile` | Last row complete/passed | 2 | 0 |
| `device:governor-compare` | Deleted helpers before last-row check | 2 | 2 |
| `device:governor-profile` | Last row complete/passed | 2 | 2 |
| `device:rsb-compare` | Last row complete/passed | 2 | 2 |

The two baseline test methods, ten raw result streams, original source
snapshots and receipt remain under ignored
`.local/awake-result-admission/baseline/`. Receipt SHA-256 is
`4c0bb87d5cd797675b0b8d8b863c7a12e3279de2931d0a708aea02e2902a0fed`.
The baseline was not repeated or relabeled after implementation. Its host
consumer and validator bytes also match published `7e6a081` before this fix;
the explicit source/context adoption receipts preserve that distinction.

## Admission and retained recovery context

New host module `tools/awake_result.py` requires one ready row and one final
complete row, strict `passed: true`, no failed row, and the expected requested
duration and operation fields. It matches the idle backlight mode; comparison
candidate, original/restored values and three phase identities; governor
profiling event and worker PID/start identity; and relevant result boot IDs.

The existing, unchanged `awake_clock.checked_proof` recomputes validation from
the raw observations. The stored proof `validation` summary has no authority:
valid raw data with a false stored summary passes, and disturbed raw data
with a forged successful summary fails. All observations must match the
ready-row boot identity and cover at least the requested duration, plus the
operation's fixed settling intervals. A longer reported duration raises this
coverage requirement. Reported durations retain a one-second rounding
tolerance, which never reduces the raw proof's requested coverage floor.

Before launching the original measurement command, the host saves a private
`awake-result-context.json` with the exact owned helper directory, fixed unit,
operation and requested duration. It rejects foreign stage paths and never
overwrites that context. Raw `.jsonl` bytes remain unchanged on success or
refusal. Successful admission writes a separate `.admission.json` containing
the raw hash, derived coverage requirement and recomputed validation. Missing,
legacy, malformed, truncated or failed evidence cannot produce that receipt
or cause the host to delete its helper stage.

Admission follows the original command's successful return. Existing command
exit/transport errors propagate before proof parsing, preserving partial raw
bytes and the owned context. Independent systemd bounds and `ExecStopPost`
restoration are unchanged. The governor-profile host still downloads all
available perf artifacts in its original `finally` block before admission;
the collector's own cleanup is unchanged. The RSB restore-only command remains
available before any result admission. A rejected result is not proof that an
interrupted original unit has stopped: inspect that original unit and retained
stage, and use its existing recovery procedure rather than automatically
starting another measurement.

The ready boot is a consistency identity inside this result stream, not an
independent measurement of the current device boot. This check does not admit
an image/deployment or establish source integrity. Existing image/runtime,
health, device-lease and physical preparation gates still apply. The raw
proof's existing limitations also remain: sub-bracket sleep and a pending
final PM-counter update can escape detection. A result can be consistent
without establishing clock reliability, exclusive sleep ownership, calibrated
energy or a causal fix.

## Focused qualification

Run the saved host-only Task in the normal authorized host environment:

```sh
task test:awake-result-admission
```

The local fixtures import real host dependencies, exercise the five actual
consumer routes and actual `remote.run`, fragment channel output, and model
SFTP uploads/removal/downloads. Assertions check exact raw and partial output,
owned context, no stage deletion on refusal, the original command and response
deadlines, original exit/timeout identity and governor-profile artifact
downloads even when proof fails. Pure checks cover nonmutation, invalid
numeric durations and context ownership/reuse.

The finite set passes **15 methods / 130 actual host cases**:

| Family | Cases |
| --- | ---: |
| Valid proof | 5 |
| Missing/legacy proof variants | 25 |
| Changed PM success/failure counters | 10 |
| Changed BOOTTIME–MONOTONIC offset | 5 |
| Wrong boot in one/all observations | 10 |
| Short coverage and rounding boundary controls | 15 |
| Forged stored validation in both directions | 10 |
| Incomplete, repeated, trailing and truncated streams | 30 |
| Expected duration/operation identity | 10 |
| Original command exit and response-timeout behavior | 10 |

There are 15 accepted controls and 115 expected refusals. The original saved
Task PID `1171226` exited zero; before/after source hashes match. Its retained
attempt is
`.local/awake-result-admission/qualification/6f1084cef0e440b0b5d2dc7f8c71ebbb/`,
receipt SHA-256
`d3f25028673f29a45234d915d8ab1d3dd7eaf8d681ed6a473d406f4e5052ab72`,
test log SHA-256
`38a9ff7ace300dddc448002bc4db158b0bbe81b60a0f7cec82881a32262834d8`.

The first 13-method/120-case candidate qualification remains preserved at
`qualification/c1b5576480d7448d813200a9bd470cd4/`. A subsequent pure local audit
found that accepting a slightly rounded-down reported duration could also
lower the candidate raw-coverage requirement in four consumers. Original
audit SHA-256
`c0755239894841441ba86afe2ef43b7239f3585e042e34798b4c34fe86fd175f`
is retained. The correction derives coverage from the greater of the request
and validated reported duration, without altering any raw observation or
`checked_proof` semantics. Five new boundary refusals and five full-coverage
rounding positives account for the additional ten cases above. Earlier
candidate results do not qualify this later source.

## Source and remaining acceptance

Static preservation evidence compares the original published consumers and
all unchanged top-level helper functions. It verifies identical collector,
`awake_clock.py`, battery parser and source-lock bytes; identical transport,
staging/upload, RSB service command and restore-only branch; and the original
governor-profile `finally` block. The only changed functions in the existing
host files are `remote.device_action` and `check-rsb-runtime.main`. Raw proof
semantics, all collector restoration and image/runtime sources remain as
before. No ARM, kernel or image build is relevant to this host-only correction.

Final published-base adoption, required combined host checks and entirely
fresh independent Standards/Spec review remain pending. Publication and
closing this focused child require those gates. NEO-101's matching-image long
runs, controlled physical interruptions and observer cost remain open, as do
NEO-192 and dependent PM gates. No new physical run is performed or claimed.
