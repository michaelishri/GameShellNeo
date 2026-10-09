# Battery clock-fault handling

10 October 2026. NEO-192, following the preserved failure and bounded awake
observation in [reports 256](256-camera-pm-preflight.md) and
[257](257-awake-clock-regression-investigation.md).

The candidate guard now handles an unusable clock observation without exiting
and leaving its previous battery sample as the latest published state. It saves
the original readings, publishes a degraded observation and resets consecutive
low-battery history. Offline tests pass. **The original clock regression is not
explained or fixed, and this candidate has not replaced the live guard.**

## Producer behavior

The existing MONOTONIC → BOOTTIME → MONOTONIC bracket is retained. A typed
`ClockFault` carries original integer readings or the partial readings obtained
before a clock API failed. The guard also checks ordering between the previous
sample's finish and the next start, and between the start and finish of the
battery read. Equal clock values remain allowed. Negative/non-integer values,
decreasing values and failed reads cannot become valid battery timestamps.

| Condition | Published behavior |
| --- | --- |
| Bad start or finish bracket, clock API failure, or decreasing consecutive observations | `monitoring=degraded`; capacity/status omitted; sample timestamps and duration null; consecutive low count reset; no shutdown from this sample |
| Subsequent valid sample | Current battery values may become valid; low count starts again; original incident remains attached |
| Three new valid, properly spaced low discharging readings | Existing orderly-poweroff policy can operate again; incident retention does not permanently disable battery protection |
| Another clock fault | First event preserved, latest event replaced, event count incremented; low count reset again |
| Service restart in the same boot | Retained incident loaded before sampling; low history starts empty |
| Unreadable, malformed or wrong-boot persisted state | Startup fails without overwriting that evidence with a clean record |
| Publication failure | Error propagates; the guard does not claim successful publication or request poweroff from the failed iteration |

The incident includes its sampling phase, reason, original observations, boot
identity and count. One event contains at most two clock observations. The
record keeps first/latest events rather than an ever-growing sample list;
intermediate events are logged when they occur. No retry, timestamp clamping,
extra polling or clocksource change is introduced.

`/run/gameshellneo/battery.json` remains the single atomic publication, using
the existing temporary-file/rename sequence. It now also holds the incident
latch. The existing `RuntimeDirectoryPreserve=yes` keeps it through service
restarts; no new persistence file, service or timer is needed. Normal boots
clear `/run`, so this is **boot-local evidence**, not durable storage across
power loss. Host evidence collection and saved reports remain necessary.

The first incident cannot be reconstructed for the already-installed old
guard: its traceback lacked raw values and its restart predated this change.
The original saved journal and `NRestarts=1` remain the evidence for that boot.
No synthetic raw values have been manufactured for it.

## Admission and compatibility

The producer emits schema 3, keeping the sleep-inclusive CLOCK_BOOTTIME age
contract. The matching tools continue to understand existing schema-2 records
from diagnostic.25, as well as new schema-3 records. Older strict schema-2 age
consumers reject the new producer instead of overlooking incident metadata.

`sample_age()` rejects the presence of a `clock_fault` field even if the current
sample is valid and fresh. False, null or malformed fault fields are not a way
to opt out. The PM validator rejects retained incidents independently of the
image's optional feature fields, and boot-cycle health checks also reject them.
Other age consumers inherit the shared rejection, including battery profiles,
USB cable diagnostics and extended sleep entry checks.

Read-only PM inspection still preserves the raw battery state when its age
cannot qualify: `battery_age_seconds` becomes null with an explicit
`battery_age_error`. This makes the evidence retrievable; it does not admit PM.
The validator continues to reject an unqualified age or retained incident.

The installed-source hash check in `device:battery-check` remains strict. With
this uninstalled candidate in the checkout, that task must reject diagnostic.25's
older installed producer. Do not weaken the check, replace historical evidence,
or reboot/reset service counters to make the pending PM sequence pass.

## Repeatable validation

```sh
task check
```

The full check passes **24 runtime tests and 913 tooling tests**, with one
existing optional skip, both compiled C checks, Bash syntax and ShellCheck.
Private output is `.local/neo192-guard-check-final.log` in the active worktree.
The initial sandboxed full run encountered five existing local-socket fixture
errors; the authorized unrestricted offline run passes. These are host tests,
not a new SSH-stall investigation or a device connection.

Eight new runtime cases exercise the real main loop with fake sysfs, clocks and
poweroff delivery. They cover both bracket failures, all six clock API call
positions, invalid integers, inter-sample/read-window regressions, restart
retention, first/latest incident bookkeeping, recovery of low-battery protection,
unreadable/malformed state and failed publication. Existing tests continue to
cover suspend boundaries, slow samples, ordinary telemetry failures, charging,
capacity recovery and failed poweroff delivery.

Consumer tests cover recovered-but-faulted records, schema compatibility,
inspectable invalid age, and PM/boot rejection even with healthy services and
fresh current readings. The tests intercept every poweroff request; no host or
GameShell power action is performed.

Source identities for this candidate:

- `battery_guard.py`: `7e6e16d6fcd4b76321f5b3a77c120a23cccc4f58de0c1d2330edd81e9071b4e1`
- `test_battery.py`: `f280d53418dc33ca73f05a1ce993d98ac87e7c7dafccaebb7f3587971d30c553`
- `battery_sample.py`: `a6be8647b71a0a6ea7290bead1018a5dee7aba996e7c8b9b424245db7d057379`

## Remaining work

NEO-192 remains in progress. Source inspection identifies a useful comparison:
the normal clock API can use the ARM vDSO path or a system-call fallback; the
ARM vDSO reads CNTVCT, while the architecture timer driver selects its counter
reader during initialization. This does not establish which path produced the
failure. A bounded normal-API versus explicit-syscall comparison needs verified
ARM time structures and CPU context before drawing conclusions.

The first 60,000-sequence capture did not reproduce the incident. Better fault
retention enables future diagnosis; it does not establish clock correctness or
justify a speculative timer workaround. Controlled candidate deployment and
hardware validation remain separate work. NEO-191's camera-observed PM checks
and NEO-182's battery sleep trial remain pending. No device service, PM setting,
charger control, installed kernel or image was changed in this slice, and no
physical input is required for the next source/measurement investigation.
