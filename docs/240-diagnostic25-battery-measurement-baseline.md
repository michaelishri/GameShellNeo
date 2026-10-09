# Diagnostic.25 battery measurement baseline and sleep protocol

9 October 2026. NEO-178, following the completed
[MUSB integration review](239-musb-restart-integration-review.md).

This slice uses the existing screen-on battery sampler to establish the awake
reference for later efficiency comparisons. It changes no driver, governor,
charger, gauge, Wi-Fi policy or installed image. A passing awake measurement
does not measure sleep consumption or establish a gain from the WFI driver.

## Measurement boundary

Diagnostic.25 exposes instantaneous battery voltage/current and the processed
percentage gauge. It has no qualified accumulated-charge property. The awake
sampler integrates frequent current/voltage readings only while its clock and
PM checks establish the recorded awake interval. The result is an uncalibrated
sampled estimate, including the battery guard, Wi-Fi association, collection
channel and sampling overhead.

That calculation must not bridge a sleep gap. Current sampled after wake
describes awake operation; it cannot reconstruct the intervening asleep
current. A percentage change across a timed sleep is a gauge observation,
not a calibrated charge or energy integral. Multiplying a percentage drop by
the replacement battery's advertised 1,020 mAh would add an unsupported
capacity assumption. The earlier [measurement audit](180-sleep-charge-measurement-design.md)
and [partial-discharge observation](183-partial-discharge-charging-validation.md)
explain these limits.

Patch 0035 makes the AXP223 B8 calibration-status register volatile. It does
not resolve the undocumented E2/E3 remaining-charge contract, coherent reads,
gauge corrections or reset behavior. No raw-bus access, cache bypass, gauge
programming or new power-supply property is part of this measurement.

## Admission and saved task

The installed image remains `0.1.0-diagnostic.25`, kernel
`6.18.54-gameshellneo24`, on boot
`2170b296-d964-4d16-bdb1-c135b0e7b812`. Fresh independent USB and Wi-Fi PM
inspections match the exact installed image manifest and pass the existing
source/health validator. PM remains 31 successes and zero failures, with
valid schema-2 BOOTTIME battery readings, reported charge 100%, brightness 1,
backlight power 0 and no failed services.

The initial general integration check used the default NZ active-country
expectation and rejected the home access point's AU announcement. The owner
had already accepted that announcement. A separate check with
`ACTIVE_COUNTRY=AU` passes; no Wi-Fi country or router setting was changed.
The original rejected check remains saved.

The owner confirmed USB removal and that the GameShell remained running.
The repeatable command is:

```sh
task device:idle-sample ROUTE=wifi SECONDS=600 BACKLIGHT=keep
```

Use the matching `work/musb-restart-integration` checkout and its shared `.env`.
Keep the Mac awake on the same Wi-Fi, the device stationary, USB disconnected
and controls untouched. This command needs no screen-observation step because
it leaves the display on. It waits one minute, then collects 61 samples over
ten minutes. No other device diagnostic runs concurrently.

The existing sampler requires a discharging, present battery above 20%, both
external supplies offline, valid recent battery-guard data, Wi-Fi carrier,
no kernel taint and temperature below 80°C. It rejects changes to boot,
brightness, backlight power or governor, observed system PM/clock disruption,
and sample gaps over twenty seconds. Its transient service has a 720-second
runtime bound. The battery guard stays active. This is a bounded awake test,
not qualification of battery protection during sleep.

The first post-unplug observation reported 99%, −324 mA, 3.9809 V and 47.628°C;
Wi-Fi signal was −48 dBm. This initial value precedes the settling minute and
is excluded from the measured-window integral. A full-charge/charging reading
changing after unplugging does not by itself establish battery health.

Private admission record: `.local/neo178-baseline-admission.json`. Original
USB/Wi-Fi inspections: `20261009T075136.744883Z` and
`20261009T075208.329183Z`. General integration captures:
`20261009T075056.801901Z` (default-country rejection) and
`20261009T075133.787138Z` (accepted AU announcement).

## Accepted awake result

The saved task exited successfully. All 61 measured samples and the complete
settling/measurement clock proof pass. Recomputing the summary with the
repository's `sample-idle.py:summarize()` exactly reproduces every stored
summary field. `awake_clock.checked_proof()` separately accepts the complete
run, and the recorded helper hashes still match the unchanged source.

| Observation | Result |
| --- | --- |
| Measured duration | 600.013 seconds |
| Samples | 61, after the separate 60-second settling phase |
| Current magnitude | 256–277 mA; time-weighted estimate 263.775 mA |
| Voltage range | 3.9512–3.9974 V |
| Time-weighted power estimate | 1,046.645 mW |
| Sampled charge / energy estimate | 43.963 mAh / 174.445 mWh, uncalibrated |
| Gauge at measured endpoints | 97% → 91%; initial pre-settling observation 99% |
| Temperature at measured endpoints | 46.332°C → 44.064°C; peak 46.494°C |
| Wi-Fi signal at ready/completion | −48 / −52 dBm |
| Sample spacing | 9.991144–10.006137 seconds |
| Maximum sample lateness | 26.231 ms |
| PM counters | 31 successes, zero failures, unchanged |
| Display/governor | Brightness 1, backlight power 0 and original governor retained |

All 122 sample-window clock observations share a consistent offset; the
widest bracket is 237.919 µs, below the existing 1 ms limit. The separate run
proof has 70 observations and unchanged PM counters. Its nonzero clock offset
reflects earlier qualified sleeps; this baseline adds no observed sleep or
timekeeping discontinuity. These bounded observations retain the documented
short-interruption/pending-counter limitation in
[report 135](135-awake-measurement-clock-guards.md). The long ordinary run
passes, but a deliberately interrupted live measurement has not been tested.

The measured window cooled by about 2.3°C. That context matters to subsequent
comparisons; this single run is not a controlled before/after result for WFI,
the USB fix or any earlier image. It includes the ordinary diagnostic software
and measurement overhead. No calibrated usable-capacity estimate is inferred
from the six percentage points or advertised battery capacity.

The original raw capture is
`.local/diagnostics/20261009T075325.893767Z/idle-sample.jsonl`, SHA-256
`3f42c80ef276dbf1d421046a2a66cc58b99cf8aeb8ee5bd7fa234ec37cdd939e`.
Its private task log is `.local/neo178-awake-baseline.log`; independent
recomputation is `.local/neo178-awake-review.json`.

After completion and before requesting reconnection, Wi-Fi inspection
`20261009T080509.790349Z/inspection.json` passes the battery-profile health
validator on the same boot, with the exact manifest and PM31/0. Both external
supplies are absent/offline, the battery reports 91%/Discharging, and the normal
dim display is unchanged. Its SHA-256 is
`6b709137694f44b2696a1334a1ce1ced681274cf4cef3865e68134efae36a366`.
The owner then confirmed the separately requested USB reconnect and normal
dim console.

Final independent USB and Wi-Fi PM inspections both pass on the original boot,
with the exact image manifest, normal dim display, both external supplies
online and valid 91%/Charging battery telemetry. PM remains 31/0. No further
measurement, screen change or sleep is running.

| Final private evidence | SHA-256 |
| --- | --- |
| USB `20261009T080635.781495Z/inspection.json` | `23047a412af61ae18fb085d9e779f2944479c4be0c4c87fc20394b92bd2a929f` |
| Wi-Fi `20261009T080639.220498Z/inspection.json` | `9ef56a08f3adb72e82ff460de4a37bdda06d69da1cc7aed3f1d699790ad0c31f` |
| `.local/neo178-baseline-admission.json` | `f291b58a9bc124d6a4360baf0c4754cb9fdc9d191c14190e5e9068dac542c719` |
| `.local/neo178-awake-review.json` | `8de4e8e76c312318682c6fe9a95d7b6a9af061edbf885bc073993b9d3a0e6d30` |

Inspection paths are relative to `.local/diagnostics/`. Final task logs are
`.local/neo178-pm-connected-after.log` and `.local/neo178-pm-wifi-final.log`.
All 344 image-input hashes remain unchanged. No new source tests were needed
for this documentation/measurement slice; validation uses the completed live
window, existing validators, raw recomputation, artifact hashes and document
checks. This completes NEO-178's awake baseline and comparison protocol, not
the future backlight or sleep-energy experiments.

The previously tracked host sandbox temporary-mount quota error recurred on
two local inspection launches. Approved local host reads succeeded and the
already-running device sampler continued without interruption. A separate
local summary-formatting attempt assumed the USB inventory was a dictionary
rather than its stored list; correcting that display-only code left the
original snapshot and passing health validation unchanged.

## Next comparison sequence

1. Keep this screen-on window as the initial reference. Recompute its summary
   from the original samples, validate the raw awake proof and check the
   post-run device state before accepting it.
2. Measure a matched **awake, backlight-off** window using the existing
   `BACKLIGHT=off` task, then repeat `BACKLIGHT=keep` to expose drift. Obtain
   fresh readiness before blanking and use the existing long speaker warning
   and restoration path. Keep all other policies unchanged. Compare both
   surrounding lit windows separately; do not hide thermal, radio or battery
   drift in one average. This isolates the backlight change, not system sleep.
3. Extend the existing RTC recorder deliberately before longer sleep trials.
   Its current alarm and validators are fixed at 30 seconds; changing an
   environment variable cannot turn it into a longer energy test. A duration
   extension needs matching awake rehearsal, deadline/entry-margin checks,
   durable original-result ownership, all-CPU/timekeeping evidence and complete
   restoration. Admission must retain the actual new duration rather than
   accepting a differently timed predecessor as equivalent. Audit the host's
   collection deadlines and the transient service's timeout/restoration rules
   alongside the device alarm; a userspace timeout is not an asleep wake source.
4. Start with a short extension, then a longer bounded interval only after
   normal RTC wake and recovery. Select the permitted duration from fresh
   battery/voltage observations and the measured awake discharge envelope,
   preserving a conservative reserve; do not depend on the awake userspace
   guard to protect the battery while frozen. Keep physical observation and
   long warnings. Record battery/gauge endpoints next to the sleep operation,
   independent of later SSH collection, and preserve early wakes as failures
   of the intended interval rather than successful long-sleep measurements.
5. Report what the data supports. Without a qualified charge accumulator,
   endpoint percentage/voltage changes are a coarse timed-discharge observation.
   They can guide duration and further experiments, but do not yield precise
   asleep milliwatts or a reliable week-long projection. A defensible energy
   claim requires separately established gauge/error bounds or independent
   power measurement. Retain small repeatable improvements in supported awake
   measurements even when sleep-energy resolution remains insufficient.

This sequence avoids attributing display savings to CPU sleep and avoids
counting resume, speaker or collection overhead as time asleep. Longer-term
endurance, sleeping low-battery protection and product power-key sleep retain
their own acceptance work.

For scale only, the replacement battery's advertised 1,020 mAh divided by
168 hours is about **6.1 mA** average for a week. At the advertised nominal
3.7 V that is about **22.5 mW**. Actual usable capacity, reserve and conversion
losses are unqualified, so these are optimistic label-based budgets, not a
standby prediction. The awake baseline and the existing WFI functional tests
cannot establish whether that target is reachable.

## Tool follow-up

The charger inventory's explicit image allowlist currently ends at
diagnostic.23. It intentionally rejects diagnostic.24/.25 before register
access. Before reusing `device:charge-inspect` or `device:charge-baseline`,
re-audit and add the exact installed image/kernel profiles with their cache
and ADC-width contract. Do not weaken the allowlist or substitute an older
image identity. This does not affect the sysfs-based idle sampler used here;
the separate work is recorded in [FOLLOW-UP.md](../FOLLOW-UP.md).
