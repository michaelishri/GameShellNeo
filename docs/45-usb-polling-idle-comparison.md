# USB polling idle comparison

Date: **29 September 2026 NZDT**. Hardware qualification: **NEO-22**.
Target: the owner's **CPI v3.1**, diagnostic.5 / Linux
`6.18.54-gameshellneo5`. Status: **completed with recorded retries; fewer RSB
interrupts, no resolved energy saving**.

## Question and scope

After the [functional USB checks](44-diagnostic5-hardware-validation.md),
compare the stock 50 ms absent-state policy with the experimental 250 ms
policy. Repeated experimental windows bracket the stock window to expose
drift. This is an exploratory software-telemetry comparison, not calibrated
electrical measurement, a direct count of USB poll callbacks or an endurance
test. Small reductions in recurring work remain useful even if the battery
readings cannot resolve their energy effect.

## Repeatable protocol

Use the checked-in orchestration task below. Keep the Mac awake and on the same
enabled hotspot as the GameShell, with Wi-Fi SSH routed through the Mac's
configured tailnet endpoint.
Connection details and credentials remain in `.env`.

```sh
task device:usb-idle-compare
```

This takes roughly 45 minutes, including two automatic software reboots. The
sequence below defines its protocol; do not run these constituent commands
concurrently with the orchestration. An exclusive host lock prevents another
copy of the comparison. It does not prevent unrelated manual diagnostics.

1. Check `task device:status ROUTE=wifi` and
   `task device:usb-policy ROUTE=wifi`. Verify experimental activation and
   stop any earlier detailed USB recorder. Preserve brightness 1, unblanked
   console, schedutil governor, 120–1008 MHz limits, 366 microsecond schedutil
   interval and Wi-Fi power saving off. Check these again around each phase.
2. Unplug USB once, leave controls untouched and keep the board in the same
   location. Allow five minutes to cool after charging. Check valid battery
   monitoring, discharge, Wi-Fi and temperature before starting.
3. Run the following **sequentially**, without concurrent device diagnostics:

   ```sh
   task device:idle-sample ROUTE=wifi SECONDS=300 BACKLIGHT=keep
   task device:power-profile ROUTE=wifi SECONDS=120
   ```

   The idle task includes 60 seconds settling and ten-second samples. The
   counter task includes 30 seconds settling, endpoint counters and subsequent
   diagnostic snapshots. Their observers differ; do not combine their readings
   as if measured simultaneously.
4. Select stock with
   `task device:usb-policy ROUTE=wifi MODE=stock`, then separately request
   `task device:exec ROUTE=wifi -- sudo -n systemctl reboot`. Reconnect through
   Wi-Fi, verify a new boot and actual stock policy, check health/settings, and
   allow five minutes to settle before repeating step 3.
5. Select experimental, separately reboot, verify the new boot and actual
   experimental policy, settle five minutes and repeat step 3. Leave the
   experimental policy selected unless a failure justifies rollback.

Both tasks stop on external power, invalid/stale battery monitoring, capacity
at or below 20%, excessive temperature, lost Wi-Fi, kernel taint or changes to
their checked settings. The ordinary battery guard remains active. Preserve
failed and incomplete captures separately; only completed windows are used.
Retain raw private captures under `.local/diagnostics/` and record their paths,
boot identities, policy checks and outcomes below.

The orchestration requires the source lock's kernel and original Wi-Fi firmware,
preserves the network configuration digest, and checks that no new firmware
crash or SDIO removal messages appear during either measurement. Configuration
checks exclude naturally changing frequency residency and signal strength.
`comparison.json` is saved before each phase's measurements, after each completed
phase and on exit. Failure does not select another policy or issue another reboot.

After a reboot, the wrapper restores Wi-Fi power saving to the baseline `off`
setting if the driver returns to `on`; it rejects other configuration changes.
This happens before the five-minute cooling interval and is recorded in the
phase's `boot_setup` state. It is not a radio power-saving comparison.

`RESUME=<comparison-directory>` accepts a recent interrupted phase boundary,
requiring every saved phase to be complete and its raw summaries unchanged. It
preserves the pre-resume report and prior logs, verifies current settings and the
active policy, and restarts cooling before the next measurement. It refuses
partial measurement phases or a last profile more than thirty minutes old.
An explicit `RETRY_INCOMPLETE=1` additionally allows discarding one incomplete
final phase after completed phases, retaining it in `discarded_phases` and
repeating that whole phase after fresh settling. It never fills gaps in an old
sample series. Resolve the cause of interruption before requesting this retry.

If cooling was already observed, `COOLING_STARTED` accepts its ISO-8601 timestamp
with a timezone, at most thirty minutes old, and waits any remaining part of the
initial five minutes. This does not change later phases' cooling periods.

## Interpretation

Report time-weighted current/power estimates, voltage and temperature ranges,
signal context, network traffic, CPU accounting coverage and RSB IRQ rates.
Compare both experimental windows with stock before interpreting differences.
Flag thermal, voltage, signal or workload mismatch explicitly; repeating a
window does not remove unmeasured confounders. Aggregate interrupts are not
unique wakeups or direct USB poll invocations. Any actual poll-count claim
requires the separate lightweight instrumentation work.

Inspect current and power separately: as the battery discharges, a lower supply
voltage can reduce the calculated power even without lower reported current.
An experimental result on either side of the stock result is evidence of drift
or unresolved variation, rather than a consistent improvement. Do not average
the two experimental windows to hide opposite outcomes. Ten-second samples from
one window are correlated observations, not independent repetitions of the
whole experiment; this three-window run does not establish statistical
significance or an endurance gain.

Regenerate a completed comparison's table without device access:

```sh
task report:usb-idle CAPTURE=.local/diagnostics/COMPARISON_DIRECTORY
```

The reporter verifies that each accepted summary matches its raw capture,
checks boot identities and measurement lengths, and writes `summary.json` and
`summary.md`. It shows each experimental-minus-stock difference separately.
Its percentages describe this recorded experiment; they are not a causal model
or an automatic decision to enable the policy broadly.

## Evidence and results

Earlier preflight Wi-Fi status: `20260929T054253.347046Z/`; experimental
policy verification via USB: `20260929T054305.246521Z/`. Battery monitoring was
valid and reporting 100% while charging; no failed units or kernel taint were
reported. Only the normal USB, readiness and battery GameShellNeo services
remained active. Wi-Fi power saving was verified off separately.

Before battery sampling started, the owner changed Wi-Fi networks and reconnected
USB. The hotspot connection was restored and the bounded
[candidate firmware test](49-connected-firmware-validation.md) completed. The
original firmware was restored before this comparison; the candidate's effect
is not mixed into the polling-policy experiment.

The owner confirmed USB unplugged at about 07:00 UTC. Battery-only preflight at
`20260929T070025.662254Z/` established the start of cooling; the orchestration was
started with `COOLING_STARTED=2026-09-29T07:00:25+00:00`. Master capture:
`20260929T070443.553713Z/`. Earlier charging and network-transition readings are
excluded. This first orchestration attempt inherited Task's outer environment
defaults, so its first idle task selected 600 seconds despite a nested
`SECONDS=300` argument. It was stopped before any policy change and is excluded
from the matched comparison. The raw longer window is retained separately.

The wrapper now removes inherited `NEO_*` task variables from nested Task
invocations, allowing each explicit argument to resolve through the Taskfile.
A host regression runs the real Task runner against this repository's env
mapping and verifies duration, route and policy selection. Measurement acceptance
also checks the recorder's declared duration and actual elapsed duration. Results
will be recorded after a fresh run completes three matching phases.

Corrected master capture: `20260929T071655.453996Z/`. Its first recorder declares
300 seconds, with the original unplug/cooling period retained because the
device remained continuously on battery in the same location. Both first-phase
measurements completed. Selection of the next stock policy succeeded, but the
wrapper initially interpreted the selection receipt as the following status
object and stopped before rebooting. Selection now receives a separate status
readback; a regression covers the two-record output. The completed first phase
was validated and retained, and the run resumed at 07:29 UTC with fresh stock
cooling. Neither interruption is hidden or counted as a completed comparison.

The first final-experimental attempt lost network access when the hotspot moved
away. Capture `20260929T075023.119421Z/` ends at a sample, with no successful
completion record, and is excluded. The Mac had moved back to its router; the
owner restored the hotspot and Mac connection. At 08:00 UTC the explicit retry
retained the two completed phases, archived the interrupted phase, verified the
experimental policy and restarted five minutes of settling. The larger elapsed
gap and changed battery voltage further limit energy interpretation.
The original firmware's crash and SDIO-removal counts each increased from zero
to four during this gap, consistent with the already observed unavailable-AP
problem. The replacement phase starts from those new baseline counts and must
have no further events. A cached battery-status read requested by the owner at
08:01 UTC reported 84%, during settling and outside the measurement windows.

Host validation after these workflow fixes: 13 runtime tests and 146 tool tests
pass, with one optional systemd test skipped; current-limit, mount-guard, Bash
and ShellCheck checks also pass. The on-device measurement payloads are unchanged.

## Completed comparison

All three accepted phases completed their 300-second battery window and
120-second counter window. Both software reboots produced verified new boot
identities and the requested policy. No new firmware-crash or SDIO-removal
events occurred within the accepted phases; their respective counters stayed
at 137, 0 and 4. Those existing counts include events outside the accepted
measurements, including the hotspot interruption described above.

The table below is generated by `task report:usb-idle` from the master capture
and its referenced raw records. Power estimates are uncalibrated, and the
battery and counter measurements are sequential, with different observers.

| Metric | Experimental 1 | Stock | Experimental 2 |
| --- | ---: | ---: | ---: |
| Current estimate (mA) | 255.42 | 255.78 | 258.38 |
| Power estimate (mW) | 1016.85 | 1007.90 | 999.95 |
| CPU busy, all CPUs (%) | 0.20 | 0.19 | 0.20 |
| CPU accounting coverage (%) | 99.45 | 99.32 | 99.38 |
| RSB IRQs/s | 5.060 | 17.752 | 4.895 |
| Voltage range (V) | 3.9765–3.9853 | 3.9336–3.9468 | 3.8610–3.8775 |
| Temperature range (°C) | 37.75–38.88 | 37.10–38.56 | 37.10–38.23 |
| Reported charge start/end (%) | 94 / 93 | 90 / 88 | 82 / 80 |
| Idle signal start/end (dBm) | -45 / -45 | -45 / -46 | -45 / -48 |
| Profile signal start/end (dBm) | -44 / -51 | -47 / -50 | -50 / -50 |
| Profile rx bytes | 272 | 108 | 80 |
| Profile tx bytes | 282 | 108 | 0 |
| Profile rx packets | 6 | 3 | 2 |
| Profile tx packets | 5 | 2 | 0 |

RSB interrupt rates were **71.49% and 72.43% lower** in the two experimental
windows than stock. That repeated reduction supports retaining the experiment
as a reduction in recurring PMIC bus activity. It is not a direct count of USB
poll callbacks, unique CPU wakeups or a measurement of component power.

Power was **0.89% higher** than stock in the first experimental window and
**0.79% lower** in the second. Current differences also changed sign:
**−0.14%** and **+1.02%**. Voltage fell across the run, temperature and signal
varied, and interruptions extended the elapsed gaps. These observations do not
establish an energy saving or regression. Averaging the experimental readings
would obscure that drift. CPU accounting similarly shows no consistent busy-time
improvement at the available resolution.

The policy remains an **opt-in experiment**. Actual poll counts and bounded
read-error/IRQ recovery qualification remain outstanding under NEO-28/NEO-22;
see [the implementation notes](50-usb-diagnostic-implementation-notes.md).
No minimum battery-saving percentage is imposed on useful reductions in recurring
work, but this result must not be advertised as a battery-life gain.

At completion, experimental polling was active and selected for the next boot.
A post-test read at approximately 08:14 UTC reported **78%**, valid battery
monitoring and no consecutive low samples; `systemctl --failed` listed no failed
units. The owner was told USB could be reconnected. These are software readings,
not qualification of battery capacity or charging voltage.

### Accepted private captures

| Phase | Boot identity | Idle capture | Counter capture |
| --- | --- | --- | --- |
| Experimental 1 | `73a1cbd0-0b12-4137-bdb1-7965671bab5d` | `20260929T071710.072215Z/` | `20260929T072316.469545Z/` |
| Stock | `c5bff221-9785-456b-b1b1-60a8e3f31b94` | `20260929T073545.161998Z/` | `20260929T074151.288721Z/` |
| Experimental 2 | `2e455e8a-eb1a-4300-b670-9c2e5ba11be0` | `20260929T080542.708179Z/` | `20260929T081150.646120Z/` |

All directories are under `.local/diagnostics/`. Master capture:
`20260929T071655.453996Z/`, with `passed: true`, three accepted phases and one
explicitly discarded interrupted phase. Its `summary.json` and `summary.md`
can be regenerated without device access. The earlier wrong-duration attempt
remains separately recorded in `20260929T070443.553713Z/` and is not included.
