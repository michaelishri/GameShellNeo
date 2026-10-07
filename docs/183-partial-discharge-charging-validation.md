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

Once the discharge observation finishes, the owner is asked to reconnect USB
separately. The next planned saved command is:

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
reconnection. The awake charging baseline remains pending that physical action.

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

Discharge trace SHA-256:
`4a109af30a07bbc4acd65b841070b8ed44144077a9c220fc8cc27c3c006a8abc`.

The partial-discharge collection uses the existing awake-idle helper's
MONOTONIC timing. It is not valid evidence for a trace spanning sleep and must
not be reused as such when timekeeping-freeze support is introduced. The
charging helper separately rejects detected sleep with BOOTTIME/MONOTONIC and
PM-counter checks. See [report 180](180-sleep-charge-measurement-design.md) for
the unresolved accumulated-charge register and sleep-attribution limits.
