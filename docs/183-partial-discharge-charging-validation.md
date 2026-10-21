# Partial discharge and awake charging validation

7 October 2026. NEO-117 follow-up using the existing saved measurement tasks.
This session prepares a charging observation below the full-battery plateau;
it does not measure charge gained during sleep or qualify battery capacity.

## Starting state and protocol

The owner returned with diagnostic.20 / `6.18.54-gameshellneo19` running on
boot `d49e0999-5edd-4fe1-9c6e-1c8e17cadfa9`. Independent USB and Wi-Fi status
checks succeeded. The saved PM inspection passed the locked-source and health
validator, with the battery guard valid, reported charge 100%, normal dim
display, and no failed services. Wi-Fi was reachable at a sampled −84 dBm;
the owner remained available during the bounded battery-only observation.

The new boot does not inherit the previous boot's sleep qualification. No
sleep, reboot, screen blanking or charging-setting change is part of this
awake discharge/charge session. Any subsequent sleep needs its own current
prerequisites and observer readiness.

The owner confirmed physical USB removal and that the GameShell remained
powered on. The saved command is:

```sh
task device:idle-sample ROUTE=wifi SECONDS=600 BACKLIGHT=keep
```

It first observes one minute of settling, then records a ten-minute awake
sample at ten-second intervals. The existing battery guard remains active.
The helper requires absent external power, discharging battery telemetry above
20%, valid recent guard readings, Wi-Fi carrier, no kernel taint and temperature
below its threshold. It preserves brightness and the CPU governor, rejecting
observed changes. A temporary systemd service bounds execution independently
of host collection. No other device diagnostics run concurrently.

The first observation after unplugging reported 99%/Discharging, −326 mA,
3.8665 V, both external inputs offline, valid guard readings, brightness 1 and
backlight power 0. Percentage and instantaneous voltage/current remain
uncalibrated software observations; a change on unplugging does not itself
measure usable capacity or establish battery wear.

After the discharge observation finished, the owner confirmed USB reconnection
and the normal dim console. The saved charging command is:

```sh
task device:charge-baseline SECONDS=120
```

That task records an awake, USB-connected trace with boot/PM/clock brackets,
read-only charger inventory and unchanged-setting checks. Its sampled charge
estimate must not be attributed to sleep. The existing full-battery trace in
[report 182](182-awake-charging-baseline.md) provides context, not a controlled
same-state comparison or calibrated reference.

## Partial-discharge result

The saved discharge task completed successfully after its settling minute.
All 61 samples passed the helper's checks; the final summary independently
recomputed from the original samples matches exactly.

| Observation | Result |
| --- | --- |
| Sampled duration | 599.999113 seconds |
| Reported percentage | 97% → 77% during the measured window; initial settling observation 99% |
| Reported current magnitude | 248–263 mA; time-weighted average 254.891682 mA |
| Voltage | 3.8467–3.9094 V |
| Sampled charge / energy estimate | 42.481884 mAh / 164.707265 mWh, uncalibrated |
| Time-weighted power estimate | 988.245051 mW, uncalibrated |
| Maximum sampled thermal-zone temperature | 36.288°C |
| Largest sample lateness | 6.470 ms |
| Adjacent sample spacing | 9.997341–10.002818 seconds |
| Wi-Fi signal at task start / finish | −82 / −83 dBm |
| Display, governor, boot and guard | Required state checks passed throughout the recorded samples |

This is awake operation with the dim display, associated Wi-Fi, active battery
guard and an open SSH collection channel. It is not a standby measurement or a
controlled comparison against earlier images. The percentage fell by twenty
points while the sampled current estimate accounts for about 42.5 mAh. These
uncalibrated quantities must not be converted into an inferred full capacity;
percentage calibration, usable capacity and actual endurance need separate
qualification.

A separate awake Wi-Fi connection inspection after sampling confirmed the
original boot, UDC `not attached`, USB carrier 0, both extcon roles clear and
both supply objects absent/offline. The ACIN and VBUS removal counters each
read 1, insertion counters 0. This evidence was saved before requesting USB
reconnection.

## Interrupted first charging attempt

The first charging command lost its SSH transport with `Connection reset by
peer` after the inventory and sample zero. It returned a nonzero task status
without a completed record. Preserve this attempt as **incomplete**; it is not
a passing two-minute baseline. The one preserved sample reported 76%/Charging,
228 mA and 4.2581 V. It cannot support an integrated-charge estimate.

Both routes subsequently reconnected. Process inspection found only the
production battery guard among Python/timeout processes, establishing that the
original sampler was no longer running before another command was considered.
A fresh PM snapshot passed the source/health validator on the original boot:
PM success/failure counters remained 0/0, normal display settings and charger
readbacks were unchanged, and there were no new kernel log entries relative to
the initial inspection. The Mac's saved sleep/wake history ends with its wake
at 13:30:45 NZDT, before the 13:50 charging attempt; it records no intervening
sleep. These observations do not identify which connection hop reset or its
cause. No cable action, reboot or interface reset was requested as recovery.

After reviewing this state, a distinct second two-minute charging command was
started. It does not replace or retroactively pass the original attempt.

## Completed awake charging baseline

The second command completed successfully with 13 accepted samples. Independent
summary recomputation matches the saved result; both helper hashes and the
source-lock hash match the checkout.

| Observation | Result |
| --- | --- |
| Elapsed sampled time | 120.019754 seconds |
| Reported percentage / status | 82% → 86% / Charging throughout |
| Reported current | 182–195 mA; sampled time-weighted average 188.375592 mA |
| Sampled net-charge estimate | 6,280.220051 µAh, approximately 6.28 mAh, uncalibrated |
| Voltage telemetry | 4.2559 V in all 13 samples |
| Configured charge voltage / current | 4.2 V / 1.2 A, unchanged readbacks |
| Largest complete sample read bracket | 54.527851 ms |
| Maximum sampled thermal-zone temperature | 42.606°C |
| PM success/failure counters | 0/0 throughout |
| External power, display and charging settings | Required unchanged-state checks passed |

Unlike the earlier full-battery trace's 1–2 mA readings, this trace reports
substantial positive current below 100%. That supports an operational awake
charging path. The sampled 6.28 mAh is neither a calibrated hardware integral
nor a sleep-charge measurement. Charging also occurred between reconnection
and this accepted window; do not attribute the entire percentage recovery to
the two-minute trace.

The 4.2559 V telemetry exceeds the configured 4.2 V target and repeats the
existing **NEO-10** discrepancy. Passing the recording protocol does not qualify
electrical voltage/current accuracy, charge termination or this unbranded
pack's limits. The control-register inventory is possibly cached, as documented
in [report 181](181-charge-inventory-validation.md). No guessed offset, charger
change or gauge calibration was applied. Keep the discrepancy open and defer
extended charging/termination experiments under NEO-10's existing criteria.

Final USB PM inspection and independent Wi-Fi status both succeeded on the
original boot. The PM source/health validator passed, with counters still 0/0,
valid battery monitoring at 87%/Charging, both external inputs present/online,
unchanged brightness 1/backlight power 0 and unchanged charger readbacks. No new
kernel log entries appeared relative to the initial PM inspection. The helper
has exited, USB remains connected, and no diagnostic test remains running.

This completes the bounded partial-discharge/awake-charge session. NEO-117's
stay-asleep behavior retains its earlier qualification; **direct charge gained
during sleep remains unqualified**. The gauge/voltage investigation and the
measurement limitations in report 180 remain relevant before claiming that
criterion or choosing a longer charging comparison.

## Evidence

Private evidence beneath `.local/diagnostics/`:

- `20261007T003200.959255Z/status.txt`: initial USB status.
- `20261007T003200.981370Z/status.txt`: independent Wi-Fi status.
- `20261007T003401.591331Z/inspection.json`: validated initial PM snapshot.
- `20261007T003528.956284Z/idle-sample.jsonl`: original discharge trace.
- `20261007T003528.956284Z/session-provenance.json`: command, source hashes,
  checkout commit, owner unplug confirmation and preflight reference.
- `20261007T004656.536121Z/connection-inspection.json`: separate final
  disconnected-state inspection over Wi-Fi.
- `20261007T005018.870396Z/charge-baseline.jsonl`: incomplete first charging
  attempt, with its own source/payload provenance beside it.
- `20261007T005122.316532Z/status.txt` and
  `20261007T005122.424495Z/status.txt`: USB and Wi-Fi recovery reads.
- `20261007T005156.089039Z/inspection.json`: validated PM health after the
  transport failure; process inspection is in the host log
  `.local/neo117-charge-processes-20261007.log`.
- `20261007T005229.574288Z/`: saved Mac USB/network and sleep/wake inspection.
- `20261007T005302.169072Z/charge-baseline.jsonl`: distinct completed charging
  trace, with its own source/payload provenance beside it.
- `20261007T005529.182219Z/inspection.json` and
  `20261007T005530.278257Z/status.txt`: final USB PM and Wi-Fi health checks.

Discharge trace SHA-256:
`4a109af30a07bbc4acd65b841070b8ed44144077a9c220fc8cc27c3c006a8abc`.

| Charging evidence | SHA-256 |
| --- | --- |
| Incomplete original trace | `ce7b63f193c3eeeb1ce3939c392c79c080bfc6a894c6758291f70ca5d23994bc` |
| Completed trace | `f8e74eee97495eb30c5c185de991491225726087eb4e463844746bef850b9471` |
| Completed trace provenance | `6ec543f2ce03866e557154ba5aa5d058d704c6e5b9db26445b3fc50640a60206` |
| Final PM inspection | `f0c388da036074d8a4203a8573a5c47930c13437b81b92585ff5718bc2697000` |

The partial-discharge collection uses the existing awake-idle helper's
MONOTONIC timing. It is not valid evidence for a trace spanning sleep and must
not be reused as such when timekeeping-freeze support is introduced. The
charging helper separately rejects detected sleep with BOOTTIME/MONOTONIC and
PM-counter checks. See [report 180](180-sleep-charge-measurement-design.md) for
the unresolved accumulated-charge register and sleep-attribution limits.
