# Diagnostic.22 connected-USB sleep repeatability

7 October 2026; capture timestamps are UTC. NEO-134 is complete. The owner
approved four actual connected-USB RTC sleep/wake cycles, keeping the cable and
controls untouched and observing the long warning/display return each time.
All four automated results pass, and the owner confirms clear warnings and
normal dim-console returns without touching the cable or controls.

[Report 195](195-diagnostic22-pm-qualification.md) records the seven debug
checks, awake RTC rehearsal and two actual sleep attempts. The first warning
was missed; the second has the owner's clear warning and untouched normal
console return. Preserve that distinction.

## Saved bounded workflow

Source checkpoint: `d736651`. The batch uses the second successful sleep's
continuation and the original awake rehearsal:

```sh
task device:sleep-batch \
  QUALIFICATION=.local/diagnostics/20261007T082435.420412Z/qualification-next.json \
  REHEARSAL=b1fef2d2d5cf4a149c39e496ee9c38ba CYCLES=4 ATTENDED=1
```

The task admits each successor only after the preceding original result passes
and both independent SSH routes are verified. It stops on failure and preserves
the failed/incomplete attempt; no automatic PM resubmission occurs. The
20-second awake gap between accepted cycles is an observation interval, not
resume-latency evidence. Each actual wake also includes the existing 30-second
post-wake recovery observation.

The original task output is `.local/neo134-sleep-batch.log`. The completed
batch is `.local/diagnostics/20261007T082950.896020Z/batch.json`, SHA-256
`bac17b124ab221bfaf989e69ed35f0957c1e7b532d80b8e671e531781872adb8`.
It records all four accepted runs. Each original is `cycle-N/result.json`
beneath that directory:

| Cycle | Run ID | Alarm-to-return seconds | Traced s2idle seconds | PM successes afterward | Result SHA-256 |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | `abdb4fbd317341219ce0126a10d29b9d` | 31.890 | 28.661 | 10 | `4b821a8537f7e377d7e08837c648d3d1d1717387de2a152a9ca36b7d02d23f8d` |
| 2 | `d9ad014e08614b65b791ed9ece0904d0` | 31.903 | 28.631 | 11 | `30a26f8cf24986d157809681743f503741e22eeb19e53db3ebea17ea5b822ace` |
| 3 | `a6ed3847aa324e928913287aa8042ea5` | 31.657 | 28.401 | 12 | `055a06df825e1fe7c2892d255f58a15320521f56b70e76aa7135e7acbd8e4e42` |
| 4 | `65cc6d057ee8423bb2eb14e6dd3cec3e` | 32.119 | 28.572 | 13 | `8b7f1fd4dbd0a4bb6fc4699e129dc0d8b973d4b7c2b8a8f2b9459b0956b3ec75` |

## Automated results

All four pass on boot `7884d229-2309-47df-9af0-b6fe500ad9ac`, diagnostic.22,
kernel `6.18.54-gameshellneo21`. Each original result verifies both USB and
independent Wi-Fi SSH, functional RTC wake, process memory, the original keypad
connection and loss-free USB/Wi-Fi trace restoration. The long-warning playback
and audio restoration checks pass each time. Original POWER/logind policy is
restored, with no retained policy, RTC, PM or console diagnostic owner.

Final PM success/fail is 13/0 with every failure counter zero. This boot has
seven debug cycles and six actual sleeps, including the two in report 195.
All adjacent PM snapshots match. SDIO usage remains 2 with its active/on/forbidden
runtime policy, and brightness/backlight power returns to 1/0 each time.
USB and both power-supply system-wake controls remain disabled by the unchanged
image policy. The batch does not change charger/gauge settings.

Each trace includes s2idle entry/exit and the four late/noirq phases with RSB
noirq suspend/resume. No timekeeping freeze pair was observed, and neither CPU
retention nor energy is qualified. The timing columns describe the alarm and
trace intervals, not ordinary wake latency or electrical sleep residency.

The collector retained temporary SSH failures while recovering original results.
Cycle 1 includes a channel failure and an SSH banner exception; cycle 2 includes
one channel failure; cycle 3 logs neither; cycle 4 includes two channel failures.
All four ultimately satisfy both independent route proofs. No cable action or
PM resubmission was requested. The errors lack sufficient timing to separate
expected sleep disconnection from late post-wake recovery; the existing transport
instrumentation follow-up remains open.

## Observer and continuation

The owner confirmed “Yes—warnings clear and all four returned normally,
untouched.” This supplies the separate audibility/display observation alongside
the four automated results.
No further sleep test is running.

The sole current continuation is
`.local/diagnostics/20261007T082950.896020Z/cycle-4/qualification-next.json`.
It contains seven debug references and six accepted sleep references. All earlier
continuations in this chain are consumed. The original awake rehearsal remains
`b1fef2d2d5cf4a149c39e496ee9c38ba`. Any further bounded sleep batch requires fresh
owner readiness and admission against this current continuation.

## Limits

This is a bounded connected-USB functional check. CPU retention, standby energy,
normal wake latency, other power/cable/POWER wake profiles, physical battery
accuracy and direct charging during sleep remain separately qualified work.
No charger/gauge settings or audio volume/duration changes are part of this batch.
