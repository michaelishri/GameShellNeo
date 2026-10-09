# Diagnostic.25 battery-only RTC qualification

9 October 2026; evidence timestamps are UTC. NEO-175 is complete under
NEO-108. All seven fresh USB-connected debug checks pass, with the owner
confirming clear warnings and normal dim-console returns. The owner has
physically unplugged USB; battery admission, the awake RTC rehearsal and one
separately attended actual battery-only sleep pass over Wi-Fi. The owner
confirms the warning and normal untouched dim-console return. The absent-state
evidence is saved before a separate USB reattachment, which also passes both
network routes and final health. PM is 20/0. No further sleep test is running.

## Scope and admission

[Reports 234](234-diagnostic25-pm-qualification.md) and
[235](235-diagnostic25-connected-sleep-repeatability.md) record seven debug
checks and five actual USB-connected sleeps. [Report 236](236-diagnostic25-post-sleep-usb-reconnects.md)
records four subsequent awake USB reconnects. The original boot remains
`2170b296-d964-4d16-bdb1-c135b0e7b812`, diagnostic.25/kernel
`6.18.54-gameshellneo24`, with PM12/0 and all four s2idle counts at 5 before
this preparation. Source checkpoint is `6829459`.

The existing sleep controller binds each actual-sleep history to its connection
profile. The USB sleep chain cannot become a battery-only chain. This slice
therefore needs seven fresh debug results, followed by physically verified USB
absence, a battery-profile awake RTC rehearsal and separately attended actual
sleep. The original consumed USB history and successor claims remain unchanged.
Battery-only results must use Wi-Fi for collection and cannot claim USB
recovery; physical reattachment is a separate later check. These requirements
are implemented by the saved [battery-profile tooling](150-battery-rtc-qualification.md).

## Initial health and Wi-Fi

Initial PM inspection `20261009T062412.209096Z` passes full health, with fresh
battery readings and unchanged PM12/0. Independent Wi-Fi SSH succeeds, but a
separate signal read reports −89 dBm and a 1 Mb/s link. The owner cannot move
closer to the home router. A nearby 2.4 GHz hotspot is offered; no network
configuration is changed by the agent.

At the owner's request, two further Wi-Fi SSH connections succeed and report
−85/−84 dBm with a 26 Mb/s link on 2412 MHz. The parallel USB inspection
`20261009T063148.828809Z` passes full health on the same boot, PM12/0, normal dim
backlight and a connected SSID matching `.env`. Credentials stay private.
These are reported link rates and successful samples, not measured throughput
or sustained reliability. Signal remains weak.

After those findings, the owner explicitly requests starting the test. Only
the USB-connected preparation begins, with long warnings before dark intervals,
controls untouched and per-result review. Wi-Fi will be reassessed before
physical USB removal; battery-only sleep has separate readiness and admission.

| Read-only health capture | Inspection SHA-256 |
| --- | --- |
| `20261009T062412.209096Z` | `d4af13743fbb5cade0ef276170738632d5900624a9731afe919fad9685e1b9ec` |
| `20261009T063148.828809Z` | `461d71c9e62a8e6484de61a8c88c2dce636b0ccae9f78b93a0dc48235523b4f2` |

Private logs are `.local/neo175-before-{pm,wifi}.log`,
`.local/neo175-wifi-signal.log` and
`.local/neo175-wifi-recheck-{signal,signal2,pm}.log`. Offline health checks are
`.local/neo175-preflight-validation.json` and
`.local/neo175-wifi-recheck-validation.json`. No PM/RTC or display operation
ran during those connection checks.

## Debug workflow

Saved tasks run sequentially, reviewing each original result before the next
submission and stopping on failure:

```sh
task device:pm-test STAGE=freezer CYCLES=1 SOCKET_STATE=0
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1 SOCKET_STATE=0
task device:pm-platform WIFI_TRACE=1 SOCKET_STATE=0
```

The platform task ran five times, once per reviewed result.
The freezer leaves the screen on; other stages use the one-second level-5
warning and restore the dim console. These stages return after the bounded
debug delay and do not enter real sleep. The abandoned SSH-stall investigation
is not resumed. All original collection errors, if any, remain in their saved
captures; no PM operation is resubmitted to hide a transport failure.

## Seven debug results

All seven original results pass offline revalidation and independent USB/Wi-Fi
route proofs. PM successes advance from 12 to 19 with zero failures; all four
CPU s2idle counts stay at 5, with unchanged s2idle residency. SDIO usage stays
at 2. The six driver/platform checks retain the original keypad handle, USB
device number and input path, with no keypad disconnect or supply-disable
event. Their traces and power-key ownership are restored, and the warning
playback restores mixer state. The owner confirms clear long warnings and
normal display returns throughout.

Capture directories are relative to `.local/diagnostics/`; each result is
`cycle-1/result.json`.

| Stage | Capture | Run ID | PM successes | Stage seconds |
| --- | --- | --- | --- | --- |
| Freezer | `20261009T063501.438086Z` | `5d861651602545b2ad5145652d3b7fcf` | 12 → 13 | 5.242 |
| Devices | `20261009T063614.619908Z` | `490d10856ab94283b2622aaa71a43e6a` | 13 → 14 | 7.765 |
| Late/noirq 1 | `20261009T063737.585395Z` | `18a725692f2e483ea9cd66cd5a9f07a7` | 14 → 15 | 7.816 |
| Late/noirq 2 | `20261009T063903.898368Z` | `d05adb34cee14f2eba769175854051ad` | 15 → 16 | 7.859 |
| Late/noirq 3 | `20261009T064022.341424Z` | `87d2b0afe28f47b097089dd27bb8e5a8` | 16 → 17 | 7.842 |
| Late/noirq 4 | `20261009T064136.265759Z` | `962175bac59847749c0edb0d27e56fae` | 17 → 18 | 7.929 |
| Late/noirq 5 | `20261009T064301.358284Z` | `24ef4b6f77db455782129aba6883ba7a` | 18 → 19 | 7.898 |

| Original result | SHA-256 |
| --- | --- |
| Freezer | `b93699d890777473d468dbb35e9669c436b3bec23fe5245786e1f9a062a84e06` |
| Devices | `135cf9660846343e8a4e160dc6fec7e80270af6ca3607d5ac06e5b24ffe987c5` |
| Late/noirq 1 | `ce90f4147b75898f9f6a681c1c9ded48dea1472b5e1434377cc28ed005f3bc6a` |
| Late/noirq 2 | `fdc7a459a66cf71645f7ad00c7fa36d03170a6544739a957581f348b8f8d3c8f` |
| Late/noirq 3 | `85010f21ac49107c7de2101fe99fecfbaf21d959d132958a4dd0fe7d78ff726b` |
| Late/noirq 4 | `278fbdf27c2e93777948f7d091aa32b9c9929ce6dce3379ddd9275cf4ad16f82` |
| Late/noirq 5 | `742019740019f1d2fcd95abbf49b2f87bf5a6e615076669897277f73c5e7cf91` |

The driver and first three platform captures each retain one original
collection error (three channel-connect failures and one channel-open timeout
in total). Subsequent collection of the same run succeeds. The freezer and
final two platform captures have no collection error. No cause is inferred,
and no transport-investigation work is performed.

The saved `check:sdio-ref-history -- --require-stable` task builds
`.local/neo175-reference-history.json` from all seven explicit result paths.
Offline review is `.local/neo175-debug-summary.json`; task logs are
`.local/neo175-freezer.log`, `.local/neo175-driver.log` and
`.local/neo175-platform{1,2,3,4,5}.log`.

## Battery admission

After owner confirmation of physical removal, the saved `device:pm-inspect
ROUTE=wifi` and `device:sleep-connection-inspect ROUTE=wifi` tasks pass on the
same boot. PM remains 19/0, battery monitoring is valid/discharging and reports
100% at 4.0414 V. This is an uncalibrated gauge reading, not a measured usable
capacity. Both external inputs are absent/offline, UDC is `not attached`,
carrier is 0, and PHY state is `USB=0` / `USB-HOST=0`. AC/VBUS plug counters
remain 4 and removal counters are 5. Fresh qualification accepts all seven
debug records for the battery profile.

| Capture | SHA-256 |
| --- | --- |
| `20261009T064710.541568Z/inspection.json` | `bfad0b73cb84dfba54565625249c28ac4b50ffd358fee791556661da6933d778` |
| `20261009T064732.700827Z/connection-inspection.json` | `ac4a0f002880f85ee26e46de17c52385025f0bb8473f12f1dabd528e38c209ea` |

Validation is saved in `.local/neo175-battery-admission.json`. The awake
rehearsal uses the existing task, without entering sleep or blanking the screen:

```sh
task device:sleep-battery-rehearse QUALIFICATION=.local/neo175-reference-history.json UNPLUGGED=1 SOCKET_STATE=0
```

## Awake battery rehearsal

Run `b11e64c2a91c4948ae840e950cf540fe` passes, with original result at
`.local/diagnostics/20261009T064817.482344Z/result.json`, SHA-256
`08a17b510c0857e43040716b2320f3b3c4d361fbab761c39819abdb57077d866`.
Offline revalidation also passes, saved in
`.local/neo175-rehearsal-validation.json`; the task log is
`.local/neo175-battery-rehearse.log`. There are no recorded collection errors.

Exactly one RTC alarm arrives after 30.889 seconds; IRQ 31 advances from 7 to
8 and original RTC state is restored. PM remains 19/0 and all four CPU s2idle
counts remain 5, with no timekeeping freeze. Cable state and counters remain
unchanged across before/entry/after observations. Battery monitoring is valid
and discharging, reporting 98% before and 97% afterward. The original keypad,
memory, audio, traces and power policy pass restoration checks. Independent
Wi-Fi access verifies the original boot; `usb_ssh_verified=false` explicitly
records that absent USB recovery was not tested. This is an awake alarm and
cleanup rehearsal, not a sleep or energy result.

## One actual battery-only sleep

After fresh owner readiness to watch and listen, the saved task submits one
actual sleep with USB physically absent and controls untouched:

```sh
task device:sleep-battery QUALIFICATION=.local/neo175-reference-history.json REHEARSAL=b11e64c2a91c4948ae840e950cf540fe UNPLUGGED=1 ATTENDED=1 SOCKET_STATE=0
```

Run `14aecc31023341879b671cbca694c420` passes, with original result at
`.local/diagnostics/20261009T065007.506109Z/result.json`, SHA-256
`a8e5b3dde5d8e660ba1222e596048aed5a65c07df02d03b336b8178991973c93`.
Full offline revalidation, cable consistency and Wi-Fi proof pass; no USB
recovery is claimed while the cable is absent. There are no recorded collection
or submission errors. The owner confirms the clear warning and normal dim
console returned without touching either the cable or controls.

| Observation | Result |
| --- | --- |
| PM success / fail | 19 → 20 / zero failures |
| RTC IRQ 31 | 8 → 9, exactly one delivery, original RTC state restored |
| Alarm-to-return interval | 32.584 seconds |
| State-write-to-return BOOTTIME interval | 31.940 seconds, including entry, wait and resume |
| BOOTTIME–MONOTONIC gap | 29.489 seconds; paired sampling uncertainty 17.52 microseconds |
| CPU sleep callbacks | All four advance once, from 5 to 6 |
| Trace evidence | Actual s2idle boundary, one timekeeping-freeze pair, late/noirq and RSB phases |
| Cable observations | Absent before, immediately before entry and after recovery; IRQ counters unchanged |
| Battery monitoring | Valid/discharging, reported 96% before and 95% after |
| SDIO / keypad / memory | Existing result validator passes unchanged SDIO policy, original keypad and process memory |
| Cleanup | Audio, trace, power-key, RTC, console and PM policy ownership restored |
| Route proof | Independent Wi-Fi succeeds on original boot; USB explicitly untested |

The saved offline assessment also passes:

```sh
task report:sleep-evidence RESULT=.local/diagnostics/20261009T065007.506109Z/result.json
```

Assessment: `.local/diagnostics/20261009T065202.235264Z/sleep-evidence.json`.
It preserves `overall_requalified=false` and does not rewrite the original
result. Logs and derived review are `.local/neo175-battery-sleep.log`,
`.local/neo175-battery-sleep-evidence.log` and
`.local/neo175-battery-sleep-validation.json`.

A subsequent read-only Wi-Fi PM inspection, still physically unplugged, passes
full battery health and continuation admission on the original boot at PM20/0,
all four CPU s2idle counts 6 and reported charge 95%. Capture:
`.local/diagnostics/20261009T065216.396566Z/inspection.json`, SHA-256
`4cd68f3f7ec84272cf991c051f3ba5d1a27d52a00b4379703e6b4f715b26f8f8`.
Validation is `.local/neo175-battery-after-validation.json`.

The unused battery-profile continuation is
`.local/diagnostics/20261009T065007.506109Z/qualification-next.json`, SHA-256
`3f791963549074de07c51a888961a50d1ea1172bc549270e22c1a01ac5176e17`.
It does not authorize an unattended successor or a change of cable profile.
Physical reconnection is requested only after saving this absent-state evidence
and obtaining the owner's normal-return confirmation.

This qualifies one functional battery-only s2idle/RTC cycle. Callback counts
and timekeeping suspension do not establish CPU/DRAM power-off, wake latency,
energy savings or long-duration standby reliability. Short gauge changes are
not a power measurement. Cable changes during sleep remain a separate profile
and qualification under NEO-108.

## Separate USB reattachment and final state

After the explicit reconnect instruction, the owner confirms one reattachment,
30 seconds connected and the normal dim console. The saved USB PM inspection
and an independent Wi-Fi boot read both reach the original boot. Full USB-profile
health passes: PM remains 20/0, all four CPU s2idle counts remain 6, brightness
is 1 with backlight power 0, and fresh battery monitoring reports 95% and
charging. No driver, charger, network or ordinary sleep-policy setting changes.

The passive connection inspection separately verifies configured UDC, carrier
1, PHY `USB=1` / `USB-HOST=0` and both external inputs present/online. Plug
counters advance from 4 to 5; removal counters remain 5. These separate proofs
qualify reattachment after the battery sleep. They do not alter the original
battery result's explicit lack of USB recovery proof while unplugged.

| Final capture | SHA-256 |
| --- | --- |
| `20261009T065310.153763Z/inspection.json` | `92e3913b718831ec53bd4a80a8750e0b31a83b5325e53add75f9ea4e3e3d17ef` |
| `20261009T065356.769536Z/connection-inspection.json` | `4d4482e7883ef07b5290fd374b2bb9ec22f75cbcd26404628cca813ceebf2f56` |

Logs are `.local/neo175-reattached-{pm,wifi,connection}.log`; validation is in
`.local/neo175-reattached-validation.json` and
`.local/neo175-reattached-connection-validation.json`. USB remains connected
and no diagnostic sleep or screen test is running. NEO-175's bounded battery
and reattachment qualification is complete. NEO-108 remains open for its
current-image cable-during-sleep profiles; broader stability, race reproduction,
power-button wake and energy measurements remain separate.
