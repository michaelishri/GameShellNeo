# First 60-second USB RTC-wake trial

9 October 2026. NEO-181. Hardware qualification of the
[bounded-duration recorder](242-bounded-rtc-duration-protocol.md), helper
commit `9cff343`.

The first attended **60-second USB-connected RTC trial passes**. The RTC woke
the GameShell, all four CPUs recorded s2idle callbacks, timekeeping freeze was
observed, both network routes recovered and the owner confirmed the long
warning and untouched return to the normal dim console. This is one successful
functional trial. Battery-only operation at this duration, longer intervals,
repeatability, sleep energy and endurance remain separate qualifications.

## Admission and preparation

Independent USB and Wi-Fi inspections pass on the unchanged installed image
`0.1.0-diagnostic.25`, kernel `6.18.54-gameshellneo24`, boot
`2170b296-d964-4d16-bdb1-c135b0e7b812`. The complete installed manifest matches
the preceding accepted session. The new recorder is uploaded as diagnostic
helpers with its own source hashes; it does not replace the installed image.
Initial PM counters are 31 successes and zero failures, with brightness 1,
backlight power 0 and valid 100%/Charging telemetry at approximately 4.167 V.

Read-only power-policy inspection finds no retained diagnostic owner or
drop-in. RTC inspection finds an inactive, nonpending alarm. A fresh ten-second
awake RTC smoke test passes delivery and restoration. No screen change or
sleep occurs during these admission checks.

The owner explicitly confirms readiness for the freezer/driver/five-late-noirq
sequence, keeping USB connected, the headphone socket empty and controls
untouched. Each existing task runs once, with its original result checked
before the next starts:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
# Invoke separately five times, reviewing each result before continuing:
task device:pm-platform
```

All seven pass, with independent USB/Wi-Fi recovery, no PM failures, the
original keypad connection retained and SDIO usage remaining at 2. PM success
advances from 31 to 38. The owner confirms the long warnings and normal dim
console after every dark interval. The existing one-second, level-5 warning
and restoration path are used before each screen-darkening test.

## Matching awake rehearsal

```sh
task device:sleep-rehearse ALARM_SECONDS=60 QUALIFICATION=.local/neo181-debug-history.json
```

Run `3653a8c2aec44457abc777fbdba177ac` passes while the screen remains on.
Alarm-start-to-return BOOTTIME is **60.483 seconds**. The gauge endpoints are
100% → 100%, voltage 4.1635 V → 4.1635 V, with all reserve/freshness rules
accepted. No CPU s2idle counter increments and no PM success increment occur;
PM remains 38/0. Both network routes and original policy restoration pass.

The recorder independently revalidates this same-source, same-boot,
same-duration rehearsal before actual sleep. It does not reuse a 30-second
rehearsal or a consumed predecessor.

## Actual sleep result

After separate explicit readiness to watch and listen for roughly a minute of
darkness, the existing task submits one attempt:

```sh
task device:sleep-rtc ALARM_SECONDS=60 QUALIFICATION=.local/neo181-debug-history.json REHEARSAL=3653a8c2aec44457abc777fbdba177ac ATTENDED=1
```

Run `216161bb2aa34459862209374ed0d9d3` succeeds. It claims the final debug
predecessor once, records the requested 60-second alarm, plays the long warning
and makes one sleep submission. The owner confirms the warning and normal dim
console return without touching the cable or controls.

| Observation | Accepted result |
| --- | --- |
| Programmed RTC interval | 60 seconds |
| Last checked entry margin | 59 seconds |
| Alarm-start → return BOOTTIME | 62.119850 seconds |
| Submission-clock → return BOOTTIME | 61.459501 seconds |
| MONOTONIC advancement across that interval | 2.602867 seconds |
| BOOTTIME–MONOTONIC gap | 58.856635 seconds |
| Clock sampling uncertainty | 22.501 µs |
| Supported time inside the s2idle trace | 58.856860 seconds |
| Paired in-loop timekeeping-freeze trace | One complete pair |
| Per-CPU s2idle callback count change | +1 on each of CPU0–CPU3 |
| RTC IRQ | IRQ 31; count 19 → 20 |
| RTC event | Exactly one notification, flags `0xa0` |
| PM success/failure | 38/0 → 39/0 |
| Recovery | USB and Wi-Fi independently verified on the original boot |

The alarm interval begins before entry work, and return includes driver resume.
The table preserves those distinct intervals. In particular, the 2.603 seconds
of MONOTONIC advancement is **not** a measured resume latency: it includes
awake work on both sides. The clock gap and CPU callbacks do not establish
CPU/DRAM power-off or measure energy.

The nonblocking RTC-event check runs before post-return battery reads, so their
overhead cannot wait out an early wake. Complete late/noirq/RSB traces, original
input handle, process memory, audio/display restoration, SDIO ownership and
unchanged image/boot all pass. Alarm and PM controls restore, original logind
policy returns and no diagnostic power-key, drop-in, PM-control or RTC owner
remains. Final brightness is 1/backlight power 0. The later battery guard is
fresh at about 7.9 seconds old.

## Immediate battery endpoints

| Observation | Before submission | Just after return |
| --- | ---: | ---: |
| Gauge | 100% | 100% |
| Voltage | 4.1635 V | 4.1635 V |
| Instantaneous battery current | +2 mA | +1 mA |
| Status | Charging | Charging |
| SoC temperature | 49.410°C | 46.494°C |

Both external supply objects remain present/online. The entry reading begins
0.235 seconds before the immediate submission clock; post-return reads finish
0.012 seconds after the recorded return. Their overall endpoint span is
61.706 seconds. The direct readings satisfy the configured reserve and timing
bounds; cached guard data is not substituted for the immediate return readings.

These current values are **awake battery charge-current observations with USB
power connected**, not total device consumption or asleep current. The flat
gauge/voltage readings cannot establish zero consumption. No current integration,
calibrated sleep power, discharge endurance or week-long projection is derived.

## Original evidence and validation

All paths below are private captures under `.local/diagnostics/`. Originals
remain unchanged. The debug results each reside in `cycle-1/result.json`:

| Stage | Capture |
| --- | --- |
| Freezer | `20261009T091700.961605Z` |
| Driver | `20261009T091808.902108Z` |
| Late/noirq 1 | `20261009T091932.905441Z` |
| Late/noirq 2 | `20261009T092051.219518Z` |
| Late/noirq 3 | `20261009T092208.451583Z` |
| Late/noirq 4 | `20261009T092321.585526Z` |
| Late/noirq 5 | `20261009T092443.297249Z` |

Preflight captures are `20261009T091428.255335Z` (USB),
`20261009T091451.269176Z` (Wi-Fi), `20261009T091536.629131Z` (policy) and
`20261009T091540.832667Z` (RTC). Awake RTC smoke is
`20261009T091636.529458Z`.

| Original `result.json` | SHA-256 |
| --- | --- |
| Rehearsal `20261009T092612.627927Z` | `5297730941aadff8d9becb8b9726ef5fd7863ef285ec2e4687285d2a43f14594` |
| Sleep `20261009T092909.877954Z` | `e135c22b06806fece4c594aa60bf6044446a48993f466e2cdaf7a3543e512fb9` |

Both completed originals pass `sleep_rtc.completed_result()` against the
unchanged helper sources and lock, including recomputed RTC, trace and battery
assessments. The separate offline task also passes:

```sh
task report:sleep-evidence RESULT=.local/diagnostics/20261009T092909.877954Z/result.json
```

Its separate assessment is `20261009T093204.931062Z/sleep-evidence.json`; it
does not rewrite or retroactively requalify the original. Local task logs are
`.local/neo181-*.log`. Derived summaries bind the private originals and owner
observations:

| Local summary | SHA-256 |
| --- | --- |
| `neo181-admission.json` | `5999041a0134770906b6e1303aab77818fe9b0def61422e1f948e6a9a1f41e20` |
| `neo181-debug-history.json` | `da115ced37442e869e5e1bdd057c531cafac95837dfe8003897bbcd21443fb03` |
| `neo181-debug-review.json` | `eca00c6692ef8ad5a56391e3a6aff2b47df16f5c5d7de329312ff79016a3dfc1` |
| `neo181-rehearsal-review.json` | `672c005abee09006ba6c5e4af1814ef8ce9ca8fd7de1e30447f5cfcb4fd85204` |
| `neo181-sleep-review.json` | `575129ed2a110eda375b4478da8bd99c21a0087cf604584c9956a39a2aff3646` |

There is no source change or new image in this hardware slice. Existing live
validators, independent route proofs, original-evidence recomputation and
document/hash checks provide its validation; the preceding offline suite does
not need repeating against unchanged code.

## Completion and next step

NEO-181's first observed USB trial is complete. The GameShell remains connected
to USB at its normal dim console; no further sleep is running. The next slice
is a separately qualified **60-second battery-only trial**, including fresh
preparation, explicit unplug/readiness, matching awake rehearsal and a separate
reconnect after the original unplugged result is saved. No card swap is needed.

Keep the 60-second cap. Longer intervals, repeated trials, sleeping low-battery
protection, calibrated charge measurement and standby endurance remain open.
