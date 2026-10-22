# Raw charging-result admission on the host (NEO-226 / NEO-10)

23 October 2026 NZDT. The charging-baseline host previously accepted a final
`completed`/`passed` claim without replaying the raw samples or checking the
claimed charge summary. NEO-226 adds host-only admission after the original
command returns. Focused local qualification passes; final accepted-context
adoption, combined checks, fresh independent review and publication are held
behind NEO-219/220. This does not qualify charging, calibrate telemetry or
change any collector, image, runtime, clock or power setting.

## Original actual-host baseline

The isolated branch starts at published
`0886549200d21d3b899a95083eaa96bad7391d05`. The baseline executes the actual
`check-charge-baseline.main` and real `remote.run`, replacing only the device
connection endpoint with local scripted channels. Normal host imports,
original command construction, source composition, stdin delivery, PM lock,
output/provenance saving and channel cleanup execute. The source sent through
stdin is captured as bytes and never executed. No SSH connection, sysfs read,
collector or device operation occurs.

The original consumer accepts all five representative fixture streams:

| Stream | Result |
| --- | --- |
| Valid 60-second / seven-sample control | Accepted |
| Completion only, with no started event or samples | Incorrectly accepted |
| Changed raw PM counts, unchanged successful completion | Incorrectly accepted |
| Changed raw clock offset, forged unchanged derived bounds | Incorrectly accepted |
| Forged integrated-charge summary | Incorrectly accepted |

Two test methods, five raw/provenance pairs, original source snapshots and the
original zero-exit Task log are retained at ignored
`.local/charge-result-admission/baseline/`. Baseline receipt SHA-256 is
`7223f44d81c565db429cda74c660c8a18d58442813dc30bcffeb3d157328c161`.
The stdin payload SHA-256 is
`7d1e350d29210925f43dc06cc46fc0494c695f87d233b4048b0b8b5cda84ed83`.
The baseline is preserved rather than repeated or relabeled after the fix.
Fixture inventories contain the fields needed for result consistency; they
do not simulate a complete hardware inventory or establish image eligibility.

## Host admission and pure-code reuse

New `tools/charge_result.py` requires an exact stream:
one `started` event, the requested number of consecutive `sample` events,
and one final `completed` event with strict `passed: true`. Missing, repeated,
trailing, failed, malformed or truncated results fail. The expected seconds,
ten-second interval, protocol schema/limits and inventory kernel/image/board
identity must match the host's original request. Every sample index must be
an integer in its expected position.

Each inventory/sample checkpoint must contain a nonempty boot identity,
nonnegative raw integer MONOTONIC-before, BOOTTIME and MONOTONIC-after values,
and decimal-string PM success/failure counts. The host constructs a private
copy and derives offset bounds directly from those three raw integers.
Serialized `offset_low_ns`/`offset_high_ns` fields have no authority and can
neither hide a raw shift nor invalidate otherwise valid raw readings. No raw
timestamp is rounded, clamped, substituted or overwritten.

The unchanged `awake_clock` validator checks all inventory and sample
observations for ordered timestamps, a common raw offset, one boot, stable
PM counts and its existing one-millisecond maximum clock-call bracket. A
separate unchanged `checked_proof` call requires the sample observations
themselves to cover at least the requested duration; the initial inventory
cannot supply missing measurement coverage. This clock-call bracket differs
from the collector's existing two-second budget for the complete sequential
sample read.

After those raw checks, the host calls the unchanged pure
`charge_inventory.validate_continuity` and `sample-charge.summary` functions
on the private records. Their existing state, spacing, read-budget and
whole-trace criteria remain intact, including the two-second summary-duration
tolerance. The summary is independently recomputed from raw samples and must
exactly match the stored summary, including JSON numeric types and limits.
The host prints the recomputed result and writes a separate
`charge-baseline.admission.json` with the raw hash and validation. Original
JSON-lines and provenance bytes remain unchanged; a prior admission receipt
is never overwritten.

The module loads the existing collector's definitions without invoking its
entry point. Only pure functions receive supplied records; no inventory,
capture, sampling, clock-read or other collector I/O executes on the host.
Tests make collector I/O entry points fail if called during admission.
`sample-charge.py`, `charge_inventory.py` and `awake_clock.py` stay byte-identical.

## Preserved transport and interpretation

The existing helper-source composition and exact stdin payload are unchanged.
The host retains its PM lock, USB route, remote `timeout` duration of requested
seconds plus twenty, five-second termination grace and forty-second response
timeout. The original `remote.run` closes its channel and preserves partial
raw output; original command-exit/transport errors propagate before result
parsing. The PM lock releases on success, proof refusal and original errors.
There is no remote helper stage or new persistent service to remove, and no
automatic retry, recovery, setting restoration or device action is introduced.

Raw consistency is not independent current-device/image/source admission.
The initial inventory's boot is an identity within the saved stream.
Existing sub-bracket sleep and pending final PM-counter limitations remain.
Sequential software telemetry does not observe between-sample current,
calibrate the ADC, establish pack limits or qualify charging safety. The
recomputed result retains the existing uncalibrated sampled-charge wording
and explicitly does not measure charge gained during sleep.

The unchanged inventory profile map enumerates historical diagnostic.20–23.
This correction does not widen that producer admission or qualify the current
diagnostic.27 directory. All original NEO-121 live captures and their independent
recomputation remain historical and unchanged. NEO-10's electrical/pack-limit
questions, NEO-101's physical/observer-cost gates and NEO-192/PM remain open.

## Focused qualification and pending final gates

The saved host-only Task uses actual host control flow and real imports with
local scripted channels:

```sh
task test:charge-result-admission
```

Current qualification passes **14 methods / 39 actual-host cases**:

| Family | Cases |
| --- | ---: |
| Valid raw stream | 1 |
| Forged stored bounds, valid raw control and raw shifts | 3 |
| Missing/raw-free/legacy streams | 5 |
| Changed PM counters | 2 |
| Wrong boot | 2 |
| Missing/duplicate/trailing/failed/truncated samples | 6 |
| Forged stored summary | 5 |
| Expected operation identity | 6 |
| Invalid/order/width/short-coverage raw brackets | 7 |
| Original command exit and response timeout | 2 |

Two accepted controls and 37 expected refusals retain exact raw/provenance
bytes. Assertions verify the unchanged actual stdin bytes, complete original
remote command, response/remote deadlines, held/released PM lock and channel
closure. Pure tests verify nonmutation, ignored stored bounds, direct reuse
of the existing summary without collector I/O, and separate receipt retention.
The short-coverage control has a consistent 59.4-second summary, within its
existing tolerance, but cannot satisfy the new explicit sixty-second raw
measurement floor.

The original Task PID `1199140` exited zero with all nine input pins unchanged.
Its evidence is at
`.local/charge-result-admission/qualification/83db31195c674f7e8cd9f01986c0241f/`;
receipt SHA-256
`1f472131efe2bc2acda1fe6c3158001189b1d306b69c5713cc821efcf8bae310`,
log SHA-256
`aff2e24e28226d94e7cd80cb27a377fe4e47e436946880f3c3b770d24fd7e76b`.
The earlier 13-method/38-case run remains at
`qualification/17cd28d4eb6f45398648988d023942ca/`, receipt
`0ae5a8a6a3712067f20d839f57eccb56a791f7bc79a55361caac95a5cfec9358`.
Adding the explicit coverage negative control changed only tests.

Source/transport preservation receipt SHA-256
`062fc2c8a33618d692dceb779b8ef2cfb4b7e7d280e6116b1ad86afca2ddc074`
pins seven unchanged files, the original payload function bytes and original
command/lock/provenance AST. All 39 current wire observations match the
original baseline payload hash. These are host-only source and scripted
transport results, not native/ARM kernel, image or hardware qualification.

Final accepted-base adoption and required combined checks are deliberately
held until NEO-219/220 finish their settled-context refreshes. Entirely fresh
independent Standards/Spec review and publication are still required before
closing this focused child. No main/device lease is held.
