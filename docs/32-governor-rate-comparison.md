# Governor-rate comparison and function attribution

Date: **2026-09-27**. Ticket: **NEO-12**, in progress. Target: the owner's CPI v3.1
with the existing `6.18.54-gameshellneo2` diagnostic kernel.

## Status and purpose

**The hardware comparison and a subsequent function profile both completed.**
Changing the schedutil update limit from 366 to 10,000 µs approximately halved
the worker's reported CPU time; restoring 366 µs returned it to the baseline.
Estimated battery power fell only 2–3%. The function sample directly locates
substantial execution in the NKMP clock-factor search/calculation code.
The original 366 µs setting is restored; no production policy or driver was
changed. The two reusable tasks and the optional ARM `perf` build are described
in the [README](../README.md).

Initially, two SSH attempts failed because the board had shut down. After the
owner reconnected USB, recovered logs established an orderly guard-triggered
low-battery shutdown; see [report 29](29-hardware-qualification.md#first-observed-automatic-low-battery-shutdown).
The current boot is `8b6f1e61-fc3a-45e4-a419-4131297ca94d`. At 09:46:14 UTC,
the gauge reported 41% Charging. The owner unplugged USB; the 09:46:54
preflight reported 42% Discharging, brightness 1 and rate limit 366 µs.

[Report 31](31-awake-power-profile.md) found `sugov:0` using 33.94–35.79% of one
CPU in quiet windows. The inspected schedutil update limit was 366 µs, derived
from the advertised transition latency. The task asks whether limiting how
frequently the governor can request changes materially reduces that overhead.
The later function profile below moves NKMP cost from a source-supported
hypothesis to directly sampled execution. It does not qualify an optimization
or assign all division samples to a specific caller.

## Hardware comparison results

The run started at 09:47:02 UTC and completed at 09:54:36. Each phase settled
for thirty seconds and measured for approximately 120.4 seconds. All phases
used brightness 1, Wi-Fi power save off, USB/AC offline, four online CPUs and
the unchanged 120–1008 MHz OPP policy. `sugov:0` remained PID 63 with start
tick 135. All health/configuration checks passed.

| Measurement | Original before: 366 µs | Slower: 10,000 µs | Original after: 366 µs |
| --- | ---: | ---: | ---: |
| Governor worker CPU seconds | 42.71 | 20.98 | 42.84 |
| Worker % of one CPU, using process accounting | 35.47% | 17.43% | 35.58% |
| Estimated time-weighted battery power | 1.0333 W | 1.0106 W | 1.0419 W |
| Estimated time-weighted discharge current | 275.42 mA | 270.79 mA | 280.75 mA |
| Architectural timer interrupts/s | 219.82 | 136.15 | 222.45 |
| RSB interrupts/s | 38.15 | 22.31 | 43.22 |
| IRQ-work IPIs/s | 65.97 | 25.88 | 68.64 |
| Context switches/s | 487.94 | 289.41 | 503.75 |
| Wi-Fi MMC interrupts/s | 27.32 | 26.64 | 27.14 |
| CPU2 accounting coverage of wall time | 82.89% | 81.32% | 84.92% |
| Aggregate CPU accounting coverage | 95.37% | 95.08% | 95.87% |
| Peak sampled temperature | 41.796 °C | 39.528 °C | 38.880 °C |
| Endpoint Wi-Fi signal | −81 → −79 dBm | −82 → −83 dBm | −83 → −79 dBm |

The middle phase used approximately **51% less governor-worker CPU time** than
the mean of the controls, while the two controls closely agreed. Timer,
IRQ-work and RSB activity also fell and returned afterward. These observations
support an update-rate-dependent overhead. They are not a direct count of
frequency transitions or unique wakeups.

The estimated power reduction was **2.61% against the mean control power**
(2.20% against the first control and 3.01% against the last). There were only
13 battery samples per phase, and post-charge voltage and temperature were
falling. Voltage ranges were 3.7444–3.7642 V, 3.7257–3.7378 V and
3.7059–3.7158 V respectively. Radio signal also varied. These are short,
uncalibrated software estimates, not precise savings or an endurance forecast.
Sampled frequencies varied across all phases and are not residency measurements.

The gauge remained at 42% throughout despite recorded discharge. This does
not imply zero energy use or validate the percentage estimate after charging.
The battery guard remained valid and its configured protection stayed active.

The CPU accounting discrepancy remains unresolved. In this boot it is
concentrated on CPU2, whereas report 31's previous boot showed it on CPU1.
Most timer interrupts were on CPU2 during this run. In the middle phase,
aggregate accounting reports only 0.83% busy while the worker's process
accounting alone records 20.98 CPU seconds. Those figures do not reconcile;
do not interpret the aggregate percentage as precise utilization or proof that
all four CPUs were almost completely idle. The reversible process/interrupt
changes remain useful, with that explicit measurement limitation.

The comparison service exited successfully, reporting 7.453 CPU seconds and
8.4 MiB peak memory for its whole lifetime. Postcheck confirmed 366 µs restored,
the restoration record removed, no failed units and no new kernel journal
entries since the preflight. The following profile ran separately, after the
comparison had finished.

## Kernel function sample

`task build:perf` cross-built Linux 6.18.54's standard tool using the locked
archive and builder container. Optional libraries/features were disabled;
the resulting ARM EABI hard-float executable depends only on `libm.so.6`,
`libc.so.6` and `ld-linux-armhf.so.3`. It was staged temporarily rather than
installed into the image. Binary SHA-256:
`52794666237e2717cc8fe1e6494b46c53be177518051fa0a2e8e98a5696bc6c1`.

`task device:governor-profile ROUTE=wifi SECONDS=30` recorded only PID 63's
kernel instruction pointers using the software `cpu-clock:k` event at a
requested 99 Hz, with a 64-page ring and no callchains. It used the restored
366 µs limit. It captured **1,064 samples, with zero reported lost samples**,
then resolved their addresses using that boot's kernel symbol map.

| Symbol | Samples | Reported sample share |
| --- | ---: | ---: |
| `__udivsi3` | 323 | 30.36% |
| `ccu_nkmp_find_best.constprop.0` | 315 | 29.61% |
| `finish_task_switch` | 164 | 15.41% |
| `ccu_nkmp_calc_rate` | 147 | 13.82% |
| `_raw_spin_unlock_irqrestore` | 26 | 2.44% |
| `ccu_helper_wait_for_lock.part.0` | 7 | 0.66% |
| `ccu_nkmp_set_rate` | 5 | 0.47% |

The factor search and rate-calculation functions directly account for
**462/1,064 samples (43.42%)**. A further 323 samples landed in integer
division. The locked factor-search source repeatedly calls rate calculation,
which divides candidate products, making that a strong explanation for much
of the division cost. Without caller stacks, however, attributing every
division sample to NKMP would be an inference. Software-timer sampling can
also miss interrupt-disabled work and is not exact per-function wall time.
The observed scheduler/context-switch samples are retained, not discarded.

This is direct evidence that NKMP selection consumes a substantial share of
the worker's execution. The small sampled lock-wait share does not establish
that PLL settling has no cost. No electrical constraint, rail sequence or
clock rate was changed for this profile.

The profile service completed, all staged files were removed after download,
and the 09:57:03 postcheck found the same boot, all six expected services
active, zero restarts/failed units, zero kernel taint, USB detached and valid
Discharging monitoring. Brightness remained 1 and the governor interval 366 µs.

## Consequence for implementation

The next change should reduce the clock search's work while preserving selected
factors, rather than making 10,000 µs a production governor default from this
one experiment. A narrow candidate is to stop searching once the existing
strict-improvement branch finds an exact frequency match: no later candidate
can improve on zero error, and retaining the first exact match preserves tie
order. The zero-rate/no-improvement behavior must remain unchanged.

Before adding that to the production patch queue, compare the actual original
and proposed functions across the R16/A33 candidate-rate boundaries, exact OPPs,
between-OPP requests and edge cases, including the chosen N/K/M/P factors.
Then build and qualify the candidate kernel with the original governor interval,
repeating CPU/function/power measurements and load/recovery checks. This run
does not demonstrate a driver fix, sustained energy improvement or a completed
NEO-12 ticket. It supplies the evidence needed to choose the next patch.

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

After adding the optional perf workflow, `task check` passed 13 runtime and
41 tool tests (one additional systemd test skipped in the ordinary suite),
the compiled current-selector tests and shell lint. Four new tool cases cover
worker identity/uniqueness, sampling bounds/target, invalid inputs and refusal
to accept a report without samples. Python compilation and diff checks passed.
The pinned perf build, live comparison/restoration, live function capture and
postchecks all passed. Forced-kill/timeout restoration remains host-tested;
it was not deliberately induced on the GameShell.

## Private evidence

- `.local/diagnostics/20260927T094701.147084Z/governor-comparison.jsonl`:
  complete three-phase raw counters, battery readings and summary.
- `.local/diagnostics/20260927T095512.426562Z/`: governor-profile metadata,
  `perf.data`, `perf-record.txt`, `perf-report.txt` and the boot's `kallsyms.txt`.
- `.local/diagnostics/neo12-comparison/`: preflight, task console captures,
  comparison postcheck, final status and host-check logs. The initial preflight
  queried an absent `axp20x-ac` path; the comparison correctly enumerated the
  actual `axp22x-ac` supply and verified both external inputs offline.
- `.local/diagnostics/20260927T095658.549938Z/status.txt`: full final status.
- `.local/build/perf.log` and `.local/build/perf/`: build log, executable/hash,
  ELF dependency and compiler records.

## Remaining NEO-12 work

1. Implement and validate a minimal selection-preserving NKMP optimization,
   using the directly observed function cost as its justification. Do not adopt
   the withdrawn A64-specific proposal discussed in report 31.
2. Build and qualify the candidate with the original rate policy: worker CPU,
   function samples, timer/RSB activity, responsiveness/load recovery and
   matched software power windows. Keep voltage/OPP and protection policy fixed.
3. Investigate the accounting shortfall; do not claim precise aggregate CPU
   utilization or electrical savings from these counters.

At this report's measurement stage, NEO-12 remained in progress. A temporary
reduction in measured activity was established; a deployed fix was still pending.

Subsequent implementation, native/ARM32 equivalence, diagnostic.3 installation
and successful NEO-12 hardware checks are recorded in
[report 33](33-nkmp-clock-search-optimization.md). It records about 92% lower
governor CPU time with the original timing restored. Precise battery savings
and endurance remain unqualified.
