# First 60-second battery RTC trial and collection limitation

9 October 2026. NEO-182. Follows the first
[60-second USB trial](243-first-60-second-usb-rtc-trial.md) using the same
[bounded-duration helpers](242-bounded-rtc-duration-protocol.md).

The first attended **60-second battery-only sleep succeeds on the device**.
The recovered original passes independent RTC, all-CPU s2idle, timekeeping,
battery-endpoint and restoration validation. The owner confirms the long
warning and untouched return to the dim console. A separate later Wi-Fi health
check passes while USB remains unplugged.

**The host workflow does not pass cleanly.** Its collection step stops on a JSON
decode error before receiving the completed result. Read-only collection later
recovers that same attempt; no sleep is resubmitted. The original is preserved
without adding missing host route-proof flags. This establishes a successful
device trial with separately observed recovery, not a clean automatic result
or an accepted continuation chain. Recorder follow-up and clean repeatability
remain open before extending the duration.

## Preparation and physical confirmation

Both routes initially pass health checks on unchanged image
`0.1.0-diagnostic.25`, kernel `6.18.54-gameshellneo24`, boot
`2170b296-d964-4d16-bdb1-c135b0e7b812`. The full installed manifest and helper
hashes match the preceding accepted session. Initial PM is 39 successes/zero
failures, brightness 1/backlight power 0, and fresh battery telemetry reports
100%/Charging at 4.1624 V.

Power-policy inspection finds no retained diagnostic owner/drop-in. The RTC
alarm is inactive and nonpending; a fresh ten-second awake alarm smoke passes
delivery and restoration. With explicit owner readiness, the existing tasks
run once each, with each result reviewed before the next:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
# Invoke separately five times and inspect each result:
task device:pm-platform
```

All seven pass. PM advances 39/0 → 46/0, both network routes recover, the
original keypad connection is retained, and SDIO usage stays at 2. Warning and
restoration records pass. Transient SSH collection errors remain in the driver
and several platform logs; their tasks eventually complete with both route
proofs. No PM test is resubmitted, and no SSH-stall investigation is performed.

The owner confirms normal warnings/display and physically removes USB.
`task device:sleep-connection-inspect ROUTE=wifi` verifies both supplies
absent/offline, UDC unattached, carrier zero and PHY USB/host state zero.

## Awake battery rehearsal

```sh
task device:sleep-battery-rehearse ALARM_SECONDS=60 QUALIFICATION=.local/neo182-debug-history.json UNPLUGGED=1
```

Run `7406893d24194f6b8f845dac0c274e31` passes. The screen remains on, alarm
delivery takes 60.161 seconds, no CPU s2idle counter increments and PM remains
46/0. Direct endpoint checks, policy restoration and independent Wi-Fi proof
pass. USB proof is explicitly false in this battery profile. The battery gauge
endpoints are 97% → 95%, voltage 3.9160 → 3.9589 V; these are coarse awake
observations, not a sleep-energy measurement.

## Single actual attempt and collection outcome

After separate readiness to watch and listen, one attempt is submitted:

```sh
task device:sleep-battery ALARM_SECONDS=60 QUALIFICATION=.local/neo182-debug-history.json REHEARSAL=7406893d24194f6b8f845dac0c274e31 UNPLUGGED=1 ATTENDED=1
```

The original run is `82035365fb14437a9730012d57447ba1`. It claims its predecessor
once and submits one sleep. The host initially saves a `started` record, then
stops in `collect()` → `json.loads()` with:

```text
JSONDecodeError: Unterminated string starting at: line 1 column 230252 (char 230251)
```

The task exits with status 201. This shows that the collection reply could not
be parsed; it does not establish why it was incomplete, whether an SSH defect
caused it, or that the device's saved JSON was corrupt. The incomplete reply
itself is not saved, so its cause cannot be reconstructed from this exception
alone. The source and timing logs remain unchanged.

Only the existing read-only collection task is then used:

```sh
task device:sleep-collect RUN=82035365fb14437a9730012d57447ba1 ROUTE=wifi
```

The first retrieval times out opening the forwarded channel. The second
retrieves the original `started` record and a live recovery snapshot while
diagnostic power-policy ownership is still present. The third retrieves
`event=complete, passed=true` with all owned controls restored. These are three
retrievals of one attempt, not three sleeps. The owner independently reports
hearing the warning and seeing the normal dim console return untouched.

The recovered original passes `sleep_rtc.completed_result()` against unchanged
helpers and lock. Its host-added `wifi_ssh_verified` and `usb_ssh_verified`
fields are absent and remain absent; no receipt or result is rewritten to
retroactively qualify the interrupted host workflow. A fresh independent
Wi-Fi PM inspection subsequently passes on the original boot while unplugged.

## Recovered device evidence

| Observation | Result |
| --- | --- |
| Programmed RTC interval | 60 seconds |
| Last checked entry margin | 59 seconds |
| Alarm-start → return BOOTTIME | 61.766252 seconds |
| Submission-clock → return BOOTTIME | 61.045499 seconds |
| MONOTONIC advancement across that interval | 2.453074 seconds |
| BOOTTIME–MONOTONIC gap | 58.592426 seconds |
| Clock sampling uncertainty | 17.813 µs |
| Supported time inside s2idle trace | 58.592537 seconds |
| Timekeeping-freeze trace | One complete pair |
| Per-CPU s2idle callback change | +1 on each of CPU0–CPU3 |
| RTC event | IRQ 31, count 22 → 23; one notification, flags `0xa0` |
| PM success/failure | 46/0 → 47/0 |
| Policy, RTC and PM controls | Restored; no retained diagnostic owner/drop-in |
| Final display | Brightness 1, backlight power 0 |

The intervals have different boundaries; MONOTONIC advancement includes awake
entry and return work and is not a measured resume latency. CPU callbacks and
frozen timekeeping do not prove CPU/DRAM power-off or establish energy savings.
Late/noirq and RSB traces, process memory, original input handle, audio/display
restoration and SDIO reference checks pass. The final battery guard is fresh
at approximately 0.712 seconds old.

Cable observations before entry, immediately before submission and after
recovery all show absent USB/AC and unchanged cable IRQ counts. This agrees
with the owner's physical confirmation; sampled state and IRQ counts are not
continuous electrical instrumentation.

| Battery endpoint | Before submission | Immediately after return |
| --- | ---: | ---: |
| Gauge | 93% | 91% |
| Voltage | 3.9380 V | 3.9611 V |
| Instantaneous awake current | −289 mA | −250 mA |
| Status | Discharging | Discharging |
| SoC temperature | 47.304°C | 45.684°C |

Direct endpoint reads pass the reserve and timing bounds. Entry sampling begins
0.231 seconds before the submission clock; post-return reads end 0.0095 seconds
after return. Their span is 61.286 seconds. The nonblocking RTC event check
precedes the post-return battery read.

The two-percentage-point gauge change is **not** a measured two-percent-per-minute
standby drain. Capacity is uncalibrated, voltage rises across this interval,
and both current readings are instantaneous awake measurements. No current
integral spans sleep; no sleep power or endurance estimate is derived.

## Recovery and completion

After the recovered result and unplugged health evidence are saved, the owner
separately reconnects USB and confirms a normal console. USB PM inspection then
passes on the same boot/image, with PM still 47/0, both external supplies online,
normal brightness and 90%/Charging telemetry. This is recovery following an
explicit reconnect, not USB recovery during a battery-only sleep.

The hardware attempt and evidence collection are complete. No further sleep
is running. Full host-workflow qualification remains open: first address the
malformed-response handling in a separate, offline recorder slice, then obtain
fresh readiness and qualification for any repeat. Preserve the failed host
run and original device result, retain the one-submission rule, and do not use
this result as an automatic continuation anchor. Do not reopen the abandoned
SSH-stall investigation. Keep the 60-second cap; repeatability, longer sleep,
sleeping battery protection and energy/endurance remain separate work.

## Evidence inventory

All captures are private under `.local/diagnostics/`; no credentials or raw
journals are committed. Debug records reside in `cycle-1/result.json`:

| Stage | Capture |
| --- | --- |
| Freezer | `20261009T094248.299160Z` |
| Driver | `20261009T094411.403166Z` |
| Late/noirq 1–5 | `20261009T094524.630830Z`, `20261009T094636.084286Z`, `20261009T094753.865391Z`, `20261009T094906.733948Z`, `20261009T095014.368192Z` |
| USB / Wi-Fi admission | `20261009T094015.874493Z`, `20261009T094038.280392Z` |
| Policy / RTC / awake smoke | `20261009T094101.422603Z`, `20261009T094117.271276Z`, `20261009T094143.584050Z` |
| Unplugged connection | `20261009T095209.829229Z` |
| Awake battery rehearsal | `20261009T095240.260089Z` |
| Original interrupted host attempt | `20261009T095452.919455Z` |
| Read-only collection 1–3 | `20261009T095554.621912Z`, `20261009T095624.543947Z`, `20261009T095711.475674Z` |
| Independent unplugged Wi-Fi health | `20261009T095751.637237Z` |
| Reconnected USB health | `20261009T095854.928550Z` |

| Evidence file | SHA-256 |
| --- | --- |
| Rehearsal `20261009T095240.260089Z/result.json` | `4165d4ed411982d2aa9744c4f736241992913683273e8a59100de778fbc55d56` |
| Recovered original `20261009T095711.475674Z/result.json` | `71ad7b506b1b0dd912fa54614b529e9dc39bf104941e1281317f5f8b188c9543` |
| `.local/neo182-admission.json` | `8d5a27a8a1c4b1e30d56d205460f86e6d142a9a5de9c1eb957090408adb45995` |
| `.local/neo182-debug-history.json` | `62b06c0470a24c19adb8a7e7f2da959336244dc0cc192b1b52e1d8222b633651` |
| `.local/neo182-debug-review.json` | `660ec816ab463fb746f602f18e7822521df471a69ceb0b44093f1f428cd7edf0` |
| `.local/neo182-rehearsal-review.json` | `0c30a067fc3aaedcdbeff8575de04ae64ee37dc87fd57d038c96d6dee7b836e6` |
| `.local/neo182-sleep-review.json` | `4042386428cce19121997e35c366e89806f4992a1f2597e505089a02086ee153` |

The existing offline assessment also passes:

```sh
task report:sleep-evidence RESULT=.local/diagnostics/20261009T095711.475674Z/result.json
```

Its separate output is `20261009T095752.653632Z/sleep-evidence.json`, explicitly
without overall requalification. Logs are `.local/neo182-*.log`. This slice
changes documentation only; it does not alter helpers, drivers or the image.
