# Battery observations across sleep (NEO-100)

4 October 2026, Pacific/Auckland. The separate `work/battery-boottime` branch
prepares the battery-timestamp prerequisite identified in
[report 129](129-cpi31-wfi-s2idle-design.md). Source and simulated runtime checks
pass. **No candidate image has been built and no live service has changed.**
Diagnostic.18 remains staged with its original producer, tools and source lock.
Assign a new image/kernel identity before assembling this candidate.

## Problem and clock contract

The previous guard stamped readings and measured consecutive-sample spacing
with MONOTONIC. Five diagnostic consumers used that timestamp for freshness:
PM stages, idle sampling, power profiling, USB detection and the RSB comparison.
Linux MONOTONIC excludes suspended time; BOOTTIME includes it. After timekeeping
freeze becomes effective, a cached pre-sleep reading could appear young, and
samples across a long sleep could be joined into one low-battery sequence.
This is a source-level issue, not an observed new hardware failure.
[Linux clock definitions](https://man7.org/linux/man-pages/man2/clock_gettime.2.html),
[Python clock API](https://docs.python.org/3/library/time.html#time.CLOCK_BOOTTIME).

The candidate uses the following `/run/gameshellneo/battery.json` contract:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer `2`; unknown/legacy versions are rejected by new live readers. |
| `sample_clock` | Exactly `CLOCK_BOOTTIME`. |
| `boot_id` | Kernel boot ID captured when the guard starts; consumers require the current boot. |
| `boottime_seconds` | Timestamp before the power-supply read, used for conservative sample age. |
| `sample_monotonic_seconds` | Separate correlation metadata; never the age clock. |
| `sample_duration_seconds` | BOOTTIME interval around the read. |
| Existing monitoring/policy fields | Valid/degraded status, valid telemetry, consecutive count and provisional threshold. |

The old `monotonic_seconds` key is deliberately absent. Old consumers fail
rather than silently assigning the wrong meaning to the new record. Historical
results retain their original bytes and interpretation; they are not migrated.

## Producer behavior

The guard still samples every ten seconds, requires three valid Discharging
readings at or below 10%, resets for invalid/non-discharging/recovered readings,
and retries a rejected shutdown request on a later eligible sample. No charge
or gauge registers are written. State remains in `/run`, and no new polling
timer or service is introduced.

Consecutive spacing now uses BOOTTIME with the existing 8–15-second accepted
window. The guard also brackets each BOOTTIME read with MONOTONIC nanosecond
reads, recording lower/upper bounds on their offset. A non-overlapping increase
establishes elapsed time that MONOTONIC did not count. That detected suspend
resets the sequence, including a short sleep that otherwise fits the spacing
window. Overlapping offset bounds are not mistaken for evidence of suspend.

A power-supply read taking more than two seconds, reporting a negative duration,
or crossing a detected suspend publishes degraded monitoring without telemetry
and resets the count. The two-second bound is a diagnostic read budget, not a
measured hardware limit. Timestamping at read start avoids making an old or
slow observation look newer than it is.

These checks do not make the userspace read/decision/poweroff sequence atomic
with system suspend. An interruption after the final clock observation, a
transition hidden within measurement uncertainty, and asleep low-battery
protection still require coordination with the eventual sleep controller and
hardware qualification. The guard remains an awake diagnostic policy, not a
PMIC protection mechanism or a qualified wake-to-shutdown system.

## Consumers and deployment

`tools/battery_sample.py` centralizes age calculation. It rejects missing or
unknown schema/clock, another boot, future timestamps, negative/nonfinite values
and boolean/string timestamps. All five age consumers call it. Their existing
freshness limits and power/status admission rules remain unchanged.

The source lock records `features.battery_sample_clock="CLOCK_BOOTTIME"`.
PM snapshots retain the BOOTTIME observation used to calculate age; validation
for this feature recomputes it from the record and rejects a mismatch or missing
clock evidence. Older saved PM results without this feature keep their older
validation path; new live collection requires schema 2.

The helper is included in uploaded diagnostic bundles and sleep source hashes.
Standalone `python -c` profiles embed the same checked-in helper through
`remote.device_source()`. No remote path depends on the developer's checkout
being importable. USB recorder cleanup removes its helper too. Existing
fresh-process recovery fixtures now explicitly model the script directory on
the Python import path, matching normal on-device script execution.

Offline verification requires both the feature declaration and the exact
tracked producer bytes. This prevents labeling an image BOOTTIME-aware while
shipping the old guard. The verifier's fixture passes; there is no new assembled
image verification result yet.

## Reproducible evidence

```sh
task test
task check
# After installing a later image whose guard matches this branch:
task device:battery-check ROUTE=wifi
```

Local `task check` passes **16 runtime tests and 467 tooling tests**. Two
explicit skips remain: the opt-in user-systemd recovery test and the prepared
Armbian journal fixture, whose source tree is absent in this isolated worktree.
Compiled selector/mount-guard checks, Bash syntax and ShellCheck also pass.
Private execution logs are in `.local/battery-check.log` and
`.local/battery-consumers-check.log` in the worktree.

New simulations cover a one-hour BOOTTIME jump with MONOTONIC stopped, a
one-second sleep within otherwise acceptable sample spacing, slow sysfs reads,
short/long sleep during a read, offset uncertainty and restarted low-reading
confirmation. Shutdown commands remain intercepted; no real poweroff occurs.

Consumer tests execute the actual age paths with healthy and stale fixtures,
reject clock/schema/boot/numeric errors, recompute PM age, run standalone
transport in an unrelated isolated Python process, and reject an image fixture
with a missing feature or wrong producer. These prove software behavior and
packaging, not the board's suspended clock accuracy or battery reserve.

NEO-100 remains open for later-image integration and installed-source simulations,
then actual stopped-timekeeping/resume qualification alongside NEO-96. The
broader awake-only profilers still use MONOTONIC for workload durations; before
automatic sleep is enabled, add explicit rejection of intervening system sleep
so an awake energy estimate cannot span an unobserved sleep interval. Percentage
accuracy, charging limits, asleep alarms and physical shutdown reserve remain
separate existing work.
