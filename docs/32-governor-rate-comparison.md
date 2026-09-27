# Temporary governor-rate comparison

Date: **2026-09-27**. Ticket: **NEO-12**, in progress. Target: the owner's CPI v3.1
with the existing `6.18.54-gameshellneo2` diagnostic kernel.

## Status and purpose

The reusable comparison task is implemented and its restoration behavior is
tested on the Intel host. **No comparison has run on the GameShell yet.** Two
Wi-Fi SSH attempts during this work failed before remote command execution,
starting around 09:09 UTC. No device files or settings were changed. The owner
was asked to check whether the dim login console is still visible, leaving USB
unplugged. A disconnected host does not establish that the battery guard shut
the device down; that remains unknown until inspection or recovered logs.

[Report 31](31-awake-power-profile.md) found `sugov:0` using 33.94–35.79% of one
CPU in quiet windows. The inspected schedutil update limit was 366 µs, derived
from the advertised transition latency. The task asks whether limiting how
frequently the governor can request changes materially reduces that overhead.
It does not yet identify the expensive kernel function. The NKMP factor search
remains a source-supported hypothesis, and no clock algorithm is changed.

## Repeatable experiment

```sh
task device:governor-compare ROUTE=wifi SECONDS=120 RATE_US=10000
```

| Phase | Update interval | Settling | Measurement |
| --- | --- | --- | --- |
| Original before | Value read from this boot | 30 s | 120 s |
| Slower | 10,000 µs in the example | 30 s | 120 s |
| Original after | Exact saved value | 30 s | 120 s |

The default lasts about 7½ minutes, plus capture/cleanup overhead. `SECONDS`
can be 60–300 in multiples of thirty. `RATE_US` can be 1,000–100,000 and must be
greater than the starting value; this task never selects a faster update rate.
It supports the global or policy0 schedutil path, requiring exactly one to
exist. A different starting value is recorded rather than overwritten with an
assumed 366 µs baseline.

The last original phase helps distinguish a reversible setting effect from
battery discharge, temperature or radio drift. It is still a short sequential
experiment, not a randomized power study or an endurance measurement. If the
first and final controls disagree substantially, do not average away the
difference or claim the middle phase caused it.

The task reuses [the counter profiler](../tools/profile-power.py) and
[the software battery sampler](../tools/sample-idle.py). Each phase records:

- CPU/process accounting with wall-time coverage, interrupts, softirqs,
  network counters and peripheral state at both endpoints;
- software battery current, voltage, percentage, temperature and sampled CPU
  frequency every ten seconds;
- radio signal and power-save state, with raw samples and complete counter
  results retained privately under `.local/diagnostics/`.

These samples add PMIC reads, frequency queries, health checks and `iw`
processes. Their cadence is the same in all three phases; it differs from
report 31's lighter observer. Compare the phases within this experiment before
comparing against earlier absolute numbers. Sampled frequency is not residency,
and the existing accounting shortfall remains visible in the output. No stack
or function tracing is enabled by this task.

## Preconditions and restoration

Use Wi-Fi with USB unplugged, controls untouched and no concurrent diagnostics.
The existing battery guard remains active. Valid and fresh discharging readings
above 20%, a connected radio, temperature below 80 °C and zero kernel taint are
required. The task rejects changes to the boot, CPU set, display configuration,
governor, frequency limits, Wi-Fi power-save state or expected rate limit.
Supply presence/current checks reuse the existing battery sampler.

Only `rate_limit_us` is written. OPPs, voltages, charger/gauge programming,
backlight and radio configuration retain their existing settings.

Before any setting write, the helper exclusively creates a mode-0600 record
with the original value, path and boot ID at
`/run/gameshellneo-governor-comparison.json`. Existing unfinished state prevents
a new measurement. A `finally` block restores and reads back the original value;
the final success record is emitted only afterward.

The remote wrapper stages three tracked helpers and starts the fixed transient
`gameshellneo-governor-comparison.service`. Its runtime limit is
`3 × (SECONDS + 30) + 60` seconds, with a fifteen-second stop timeout. Its
`ExecStopPost` runs the restoration entry point in a separate Python process,
even if the measurement process was killed. This use follows the documented
service cleanup behavior. [systemd v257 service documentation](https://raw.githubusercontent.com/systemd/systemd/v257/man/systemd.service.xml)

Restoration does not require a healthy battery reading or live SSH. It validates
the saved path/value and boot identity, checks sysfs readback, and removes the
record only after success. A transport error leaves the staged helper files
available for systemd or manual recovery. A service failure or missing final
record is not reported as a successful comparison. A kernel hang or loss of
power prevents userspace cleanup; no persistent configuration is changed, so
the diagnostic setting does not survive a reboot.

The [README](../README.md) documents stopping the transient service, verifying
the saved value and invoking the retained helper's `--restore` entry point if
the independent cleanup failed. Do not run manual restoration alongside an
active experiment or delete its helpers before it stops.

## Validation completed

- `task check`: 13 runtime and 37 tool tests passed, with the optional
  user-systemd case skipped in the ordinary suite. The compiled current-limit
  regression checks, Bash syntax checks and ShellCheck passed.
- `task test:governor-recovery`: all eight test methods passed, including actual
  user-systemd service lifecycles for normal exit, Python error, SIGTERM,
  SIGKILL and runtime timeout. Each verified that a temporary stand-in changed
  from 366 to 10,000 and returned to 366. Host systemd: `259.5-0ubuntu3.4`.
- Unit/process checks also cover stored state before mutation, rejecting stale
  records and invalid candidates, failed readback, retaining failed-restore
  evidence, wrong-boot/path/value rejection, and fresh-process recovery after
  SIGKILL. No host CPU setting was used as a fixture.
- Python compilation, Taskfile discovery and `git diff --check` passed.

These checks establish host behavior, not successful operation on the target's
systemd, sysfs or battery hardware. Live comparison and postcheck remain open.

## Remaining NEO-12 work

1. Recover connectivity and inspect fresh battery/guard/service status. If the
   board has rebooted, collect the previous boot's ending logs where available;
   do not infer a critical-battery shutdown from the SSH timeout.
2. Run the bounded comparison if battery-only preconditions hold. Compare the
   governor worker, CPU accounting coverage, timer/RSB activity, radio conditions
   and software power in all three phases. Verify the original interval and
   healthy services afterward.
3. If an effect is clear, test repeatability and responsiveness/load recovery
   before proposing a persistent rate policy. A different frequency mix can
   affect power and performance independently of transition overhead.
4. Attribute the costly function before choosing a driver optimization. If the
   NKMP path is responsible, preserve its rounding, selected factors, tie order
   and clock constraints, and validate against the existing algorithm before
   building a candidate. This task does not adopt the withdrawn A64-specific
   proposal discussed in report 31.

NEO-12 remains in progress. No efficiency improvement, new kernel, battery
endurance result or production governor setting is claimed by this preparation.
