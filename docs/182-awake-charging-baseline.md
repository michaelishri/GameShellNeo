# Bounded awake charging baseline

6 October 2026. NEO-121, supporting the charging measurement plan in
[report 180](180-sleep-charge-measurement-design.md).

## Repeatable measurement

```sh
task device:charge-baseline SECONDS=120
```

The saved USB-only task accepts multiples of ten seconds from 60 to 600. It
starts with [NEO-120's inventory](181-charge-inventory-validation.md), then reads
battery status/current/voltage/percentage and both external-power supplies once
every ten seconds. Each sample brackets the sequential reads with BOOTTIME and
MONOTONIC observations, boot identity and PM counters. It records brightness,
backlight power, temperature via the existing thermal interface, kernel
taint and unchanged charger/input-limit readbacks. Temperature is the existing
thermal-zone reading, not battery-pack temperature.

The helper writes no charger, gauge, display, PM, radio or policy controls.
It rejects detected suspend, a new boot or PM count, reads taking over two
seconds, missed/late/duplicate samples, external-power loss, Discharging status,
invalid/low-capacity readings, taint, temperature at or above 80°C, and observed
display or charging-setting changes. The original observation is emitted before
eligibility checks, so a rejected sample remains in the JSON-lines evidence.
It checks whole-trace duration separately from adjacent sample spacing.

BOOTTIME is used for elapsed integration; detected sleep invalidates the trace
rather than joining awake samples across it. A sub-bracket transition with a
still-pending PM counter update cannot be excluded absolutely. Readings are
sequential and conditions between samples remain unobserved. These bounds are
diagnostic acceptance criteria, not evidence of continuous electrical stability.

The host retains original output and both helper hashes with source-lock and
payload hashes. The shared local PM lock rejects simultaneous saved PM work.
The remote process is limited to requested duration plus 20 seconds, with a
five-second termination grace; this bound does not depend on SSH collection.
Transport failure or partial output fails the command without automatic retry.
No device helper is installed and there is no new persistent sampling service.

## Interpretation

The summary includes current min/max, first/last percentage, elapsed time and
a trapezoidal **sampled net-charge estimate in µAh**:

`sum(mean(adjacent current samples) × elapsed seconds / 3600)`

Each sample's time is the midpoint of its read bracket. This is an awake,
uncalibrated estimate with unmeasured current variation between samples. It is
not a hardware integral or evidence of charge gained while asleep. The initial
full-battery baseline is expected to be non-discriminating about sleep charging;
later partial-discharge runs must retain that distinction.

## Offline checks

Eleven focused tests cover constant/ramping integration and units; unplugging,
bad/low telemetry and discharge; changes to display or charger settings;
sleep during reads and between samples; slow/missing/duplicate/new-boot samples;
whole-duration drift; retained rejected observations; a zero-current full-battery
plateau; composed remote-source execution outside the checkout; invalid duration
before connection; and interrupted execution producing failure rather than a
partial pass.

`task check` passes 13 runtime and 616 tooling tests, with one existing optional
skip, plus the compiled selector/Mac mount guard, Bash syntax and ShellCheck.
Logs are `.local/neo121-tests.log` and `.local/neo121-check.log`.

## Awake hardware baseline

The 120-second task completed on diagnostic.20, kernel
`6.18.54-gameshellneo19`, boot `34483a13-9373-4ee3-8984-fd81a99bc5de`, with
the owner away and USB connected throughout all observations:

| Observation | Result |
| --- | --- |
| Samples / elapsed | 13 / 120.020630 seconds |
| Reported battery status / percentage | Charging / 100% throughout |
| Instantaneous current samples | 1–2 mA |
| Voltage samples | 4.1558–4.1569 V |
| Sampled awake charge estimate | 62.510581 µAh (approximately 0.0625 mAh), uncalibrated |
| Largest complete sample read bracket | 63.225991 ms |
| Maximum sampled thermal-zone temperature | 46.008°C |
| PM counters | 11 successful, 0 failed, unchanged |
| USB and AC input observations | Present/online throughout |
| Display and charger/input-limit readbacks | Unchanged throughout |

The summary was independently recomputed from all original samples, and both
captured helper hashes match the tracked source. The following independent USB
status and PM-health inspections pass on the same boot: no failed units or
kernel taint, SDIO active/forbidden at usage 2, brightness 1/backlight power 0.

Evidence beneath `.local/diagnostics/`:

| Capture | SHA-256 |
| --- | --- |
| Baseline `20261006T103340.186104Z/charge-baseline.jsonl` | `d2c3e920fd29fe919b1e51d704eefba14cd3bccc99d716851c6a77df121a1c59` |
| Final PM `20261006T103607.280647Z/inspection.json` | `fcefbb80eb4b3bc9a44df7e52d842598cec888d1b6f2dbeda6e03b935b7062ed` |

Source provenance is beside the original trace; independent USB status is in
`20261006T103608.566264Z/status.txt`. Host logs are
`.local/neo121-charge-baseline.log`, `.local/neo121-final-pm.log` and
`.local/neo121-final-usb-status.log`.

This completes NEO-121's tool and initial awake full-battery baseline. The
GameShell remains connected with its original charging configuration. No
discharge, screen blanking, reboot or sleep was initiated. The 100% plateau
does not establish available capacity, charge gained while asleep, or charger
termination accuracy. NEO-117 remains open: arrange controlled partial discharge
and a corresponding awake baseline when the owner returns, then choose the
attended sleep comparison using report 180's measurement limits. Resolving the
remaining-charge register contract and battery calibration is separate from
the already-passed stay-asleep-on-USB behavior.
