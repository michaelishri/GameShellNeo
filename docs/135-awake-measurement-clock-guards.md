# Rejecting sleep in awake power comparisons (NEO-101)

4 October 2026, Pacific/Auckland. Source implementation, simulated failures and
two read-only clock checks on diagnostic.17. No image build, installed service
change, power-setting change or sleep request.

The [candidate branch](https://github.com/michaelishri/GameShellNeo/tree/work/awake-sample-clock)
extends the [NEO-100 battery-clock candidate](133-battery-boottime.md).
Awake-only measurements now reject observed sleep or system-PM activity before
reporting a successful comparison. This is needed before using the proposed
[CPU-idle/timekeeping changes](134-cpi-wfi-s2idle-candidate.md) for power work.
Diagnostic.18 remains staged on the Mac with its original matching tools.

## Why the measurement tools need their own check

Battery observation age and measurement duration have different jobs. BOOTTIME
can expose an old battery reading after sleep, but a fresh reading after resume
does not establish that a benchmark stayed awake. MONOTONIC can omit suspended
time when timekeeping freezes. Integrating awake endpoint current samples over
BOOTTIME instead would invent current consumption during an unobserved interval.
The candidate therefore keeps the existing awake integration/rate calculations
and rejects disturbed intervals rather than changing their denominator.

The first RTC sleep experiments also show why the clock difference alone is
insufficient: device suspend and an s2idle loop occurred without full timekeeping
freeze. See [report 123](123-sleep-measurement-criteria.md). A completed PM attempt
is therefore an independent rejection signal, including debug tests and failures
that may never have reached actual sleep.

## Observation contract

`tools/awake_clock.py` is shared by the collectors and offline validators.
An observation records schema version, boot ID, suspend success/failure counts,
and one BOOTTIME nanosecond read bracketed by two MONOTONIC nanosecond reads.
Suspend counters are read both before and after that clock bracket; a change
rejects the observation. Missing counters, invalid timestamps, a reversed clock,
or a bracket wider than **1 millisecond** fail closed. There is no retry that
discards a suspicious observation.

For each observation, the possible BOOTTIME-minus-MONOTONIC offset is:

```text
[boottime - monotonic_after, boottime - monotonic_before]
```

All observations must admit one common offset, have the same boot and unchanged
PM counts, and appear in time order. The validator intersects the entire set;
pairwise overlap alone could hide successive small changes. A prior sleep offset
before the measurement is allowed. A new incompatible offset during it rejects.

Individual battery/counter snapshots have `awake_window` bookends. Their
measurement timestamps must lie inside those bounds. Completed runs include
the raw `awake_proof` observations, covering settling, collection and final
checks. Comparison admission recomputes validation from those observations and
checks duration/boot coverage; it does not trust a stored validation summary.

## Where it applies

| Tool | Enforcement |
| --- | --- |
| `sample-idle.py` | Brackets each sample, validates all integration windows, watches settling/collection, and checks again after brightness restoration |
| `profile-power.py` | Brackets counter snapshots, rejects invalid rate intervals and checks the whole run through final diagnostics |
| `compare-governor.py` | Watches the whole original/candidate/original sequence, including settling and phase gaps; existing recovery restores the saved rate on rejection |
| `profile-governor.py` | Checks while perf records and at completion; rejection terminates a remaining recorder through the existing cleanup path |
| `compare-rsb.py` | Brackets residency reads and all comparison phases; restores the saved autosuspend delay on rejection |
| `compare-usb-idle.py` | Checks remote state windows and complete per-phase clock evidence; rejects legacy or disturbed captures for a new/resumed comparison |
| `report-usb-idle.py` | Revalidates new raw windows/proofs; still renders historical captures with an explicit “legacy: sleep observation absent” label |

Remote standalone commands embed the clock helper alongside the battery parser.
SFTP bundles for governor/perf/RSB tools include it, including the modules needed
by independent restoration commands. Restore-only actions do not require a
successful clock observation, fresh battery reading or network health check.

## Repeatable checks and evidence

From the candidate checkout:

```sh
task test:awake-clock
task check
task device:awake-clock-check ROUTE=wifi
```

The first two commands are local. The last is a separate read-only device check:
21 clock/PM observations over approximately one second, with no battery reads,
driver settings, suspend command or software deployment. Its JSON capture and
source hashes are saved under `.local/diagnostics/`.

**17 focused fault/transport tests pass.** Coverage includes an hour of suspended
BOOTTIME with frozen MONOTONIC, PM activity without clock freeze, changed boot,
malformed/uncertain observations, cumulative changes hidden by pairwise overlap,
legacy/short/altered proof rejection, and standalone helper transport. Actual
measurement control-flow tests reject sleep while settling, in the changed
governor/RSB phase and during perf recording. They verify restoration of temporary
settings, recorder termination and the absence of a success result. Additional
report tests distinguish historical data from incomplete new evidence.

`task check` passes **16 runtime and 486 tooling tests**, with the existing two
skips: opt-in user-systemd recovery and the check requiring a prepared locked
Armbian source. Bash/ShellCheck and existing native helper tests pass. Logs are
`.local/build/awake-clock.log` and `.local/awake-repository-check.log` in the
candidate worktree. Tests use simulated clock/sysfs/process boundaries; they do
not intentionally suspend the host or GameShell.

Two read-only board checks passed through Wi-Fi via the Mac. The final check,
with all embedded helper hashes saved before execution, recorded:

| Evidence | Recorded value |
| --- | --- |
| Kernel / Python | `6.18.54-gameshellneo17` / `3.13.5` |
| Boot | `4ffd75dc-2dae-4164-8bd2-90ad08ed1885` |
| Observations / elapsed | 21 / 1.194826985 seconds |
| Suspend counters | success 8, failure 0, unchanged |
| Widest clock bracket | 221,585 ns, approximately 222 microseconds |
| Common offset bounds | −3,291 to +4,917 ns; this includes zero |

Private capture:
`.local/diagnostics/20261003T134107.786380Z/awake-clock.json` in the candidate
worktree. SHA-256:
`0922c97c8341e3ec924043b510a530091585e4ebfbb1d59b6e2d88ff1f896eaa`.
Its adjacent `clock-sources.json` matches the checked-in recorder/helper/transport
sources. This establishes a short successful run on the installed Python/kernel,
not worst-case clock-read latency or end-to-end power-comparison qualification.
The earlier 21-observation check had a 51,917 ns widest bracket and the same
unchanged counters; both results remain saved separately.

## Limits and remaining qualification

These are observations, not exclusive ownership of system sleep. In the pinned
Linux 6.18.54 source, `kernel/power/suspend.c:pm_suspend()` calls `enter_state()`
before `dpm_save_errno()` updates the counters in `kernel/power/main.c`. Userspace
can resume before that final counter update. A sufficiently short sleep can also
fit inside clock-read uncertainty. Consequently a sub-bracket interruption plus
a still-pending counter update at the final boundary can escape detection. The
report carries this limitation; it does not certify absolute uninterrupted awake
execution. Product sleep-controller coordination/inhibition remains necessary.

The current 1 ms observation limit is conservative; scheduling delays may reject
an otherwise usable run. The helper adds clock/sysfs reads and validation work at
the existing sample boundaries. The board check does not quantify that observer
cost during long comparisons or calibrate software current readings.

Before using these tools for new optimization claims, integrate the matching
NEO-100 producer/tools into a newly identified image, qualify longer ordinary
runs and controlled interruptions, and verify cleanup on the installed system.
Other diagnostic timeout/capture protocols need their own clock audit when
automatic sleep is introduced; actual sleep recorders must continue to measure
and attribute sleep explicitly. NEO-101 remains in progress.
