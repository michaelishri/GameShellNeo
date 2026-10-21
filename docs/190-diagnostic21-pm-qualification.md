# Diagnostic.21 suspend/resume qualification

7 October 2026; capture timestamps are UTC. NEO-128 complete for seven attended
debug checks, the awake RTC rehearsal and one connected-USB actual sleep/wake.
The owner confirmed the warning and normal dim console return without touching
the cable or controls. Repeatability and the other power/cable profiles remain
separate qualification work.

[Report 189](189-diagnostic21-installation-and-gauge-validation.md) records the
installation and awake validation. This slice requalifies the changed kernel
before claiming its sleep behavior. It does not change charger/gauge settings
or establish physical voltage, usable capacity, charging during sleep or energy
savings.

## Identity and admission

Image `0.1.0-diagnostic.21`, kernel `6.18.54-gameshellneo20`, boot
`50dc8224-95e2-4f92-b35e-e35ca5566340`; source checkpoint `200cf51` on
`work/power-insertion-wake`. Fresh USB/Wi-Fi status passed. The saved PM
inspection `20261007T024506.150993Z/inspection.json` passes the existing
image/health validator with PM0/0 and normal dim console settings.

The owner answered “Ready—I'm watching and listening” for one freezer check
followed by a driver cycle, leaving USB connected, the headphone socket empty
and the controls untouched. The freezer result was reviewed before the driver
command was submitted; neither command was resubmitted.

```sh
task device:pm-power-key STAGE=freezer CYCLES=1
task device:pm-power-key STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
# After fresh owner readiness, run the first late/noirq check.
task device:pm-platform
# After its confirmation/readiness, repeat the last command four times,
# reviewing each original result before submitting the next.
```

| Stage | Capture beneath `.local/diagnostics/` | Run ID | Stage seconds | PM successes afterward |
| --- | --- | --- | ---: | ---: |
| Freezer | `20261007T024530.388585Z` | `bca52715c31f429992e33b79368a9b3a` | 5.525 | 1 |
| Driver | `20261007T024647.709870Z` | `85f4a8accfef4b0c95cacabd10c11bc3` | 7.761 | 2 |
| Late/noirq 1 | `20261007T024854.138857Z` | `5ea0927caf2a42aeb0dd85bd888f0d69` | 7.871 | 3 |
| Late/noirq repeat 1 | `20261007T025112.807318Z` | `fa63ddd2b88249f79d963f155d41832b` | 7.873 | 4 |
| Late/noirq repeat 2 | `20261007T025246.230148Z` | `e4cdadf64b8846e58298d344c330933a` | 7.856 | 5 |
| Late/noirq repeat 3 | `20261007T025405.499013Z` | `546fbedc6b214411a0f15b0f1aeea11f` | 7.929 | 6 |
| Late/noirq repeat 4 | `20261007T025524.403296Z` | `1dee94d60af0439bb68c266e25d60f94` | 7.876 | 7 |

The originals are `cycle-1/result.json` beneath each capture. All seven report
completion, pass and independent USB/Wi-Fi SSH recovery on the original boot.
The POWER input ownership was handed back. PM failure counters remain zero,
SDIO usage remains 2, and brightness/backlight power return to 1/0.
The driver trace retains the original keypad handle, USB device number and
input path, with zero disconnect or supply-disable events.

The driver warning records one level-5, 1,000 ms `screen-blank` cue with
successful playback and control restoration; speaker/headphone amplifiers
are off afterward. The freezer does not blank the display and needs no cue.
The driver collector logged one temporary `No route to host` SSH channel
failure before recovery. Its cause is unassigned; the original test result
was collected successfully without repeating PM.

The owner confirmed the driver's clear warning/normal console and gave fresh
readiness for late/noirq. `task device:pm-platform` then passed, retaining the
keypad and both SSH routes at PM3/0, SDIO usage 2 and restored audio controls.
Its collector also retained one temporary `No route to host` channel failure
before successful recovery of the original run.

The owner confirmed the first late/noirq warning/display and gave readiness
for four repeats. Every repeat passed with the same retained keypad, restored
long warning, both SSH proofs and stable SDIO usage. Each platform trace has
the four ordered late/noirq phases and successful RSB noirq suspend/resume
callbacks. These durations include the five-second debug wait and do not
measure normal wake latency.

The first repeat retained an SSH banner timeout / `No existing session`;
the other three retained one channel connection failure each. In every case
the collector recovered the original completed result, without resubmitting PM
or requesting a cable action. The existing transport-timing investigation
remains applicable; the captures do not identify a driver or Mac cause.

`task check:sdio-ref-history -- --require-stable`, supplied exactly the seven
result paths above, passes stable usage 2 and unchanged runtime policy.
Its saved output is `.local/neo128-debug-history.json`, SHA-256
`785f2fd3b20b8f33dd8c6fb2a8f1c4dbea58561597caa99039e59aae9380a439`.
Original result SHA-256 values, in table order:

```text
75f0baa83064a10e364bc239e8313b86126412382e45d40b6e21f4cedc542021
8262ce56c8395ed3b44765e689f7595cba10a7f63474ecf42ed7b5acccb247f3
558f1fb872a926fd386fde863e55a140b29561305ac353d0ee1b772c348d7cfb
77fc40b42293c419b3efd7ad89d8ea7699dd08d85b3a4d1865a0f3bbf5b14af2
22b9c62ec684f433060ed5ed8d4676635155cd5373968c9727f603b79f564d1f
93a61c5df209174b7f05ac7a4bdc06a1fd24668ac2692bcfe8ce19c634572494
aa8949802f26b6a0cd7642744f07c11466c0e808d63a47c005fd56b4a6564f03
```

The owner confirmed “Yes—warnings clear and all returns normal” for the
four-repeat batch. No cable or control action was requested during the checks.

## Awake RTC rehearsal

After that confirmation, the saved task ran without blanking the display:

```sh
task device:sleep-rehearse QUALIFICATION=.local/neo128-debug-history.json
```

Capture `20261007T025809.820022Z/result.json`, run
`b5fb1d15febe4f8c9a888f74662dd2b1`, passes with both independent SSH proofs.
Its SHA-256 is
`9cd6dfca77916b0b728f83c7dc1a62fc225e989299d963e6ebf16e712aaa28fc`.
One RTC event arrived with flags `0xa0`; IRQ31 count advanced 1 to 2, with
the original alarm restored. Original power policy and input ownership were
restored. PM remains 7/0. This is alarm delivery while awake, not wake from sleep.

## Actual connected-USB RTC wake

The owner replied “ready for the next thing” to the pending actual-sleep
readiness request. Fresh read-only inspection
`20261007T031608.093239Z/inspection.json` passed on the same boot, at PM7/0 with
normal dim console settings. Source checkpoint at submission was `36644c3`;
only the preceding documentation checkpoint changed after the debug sequence.

The following historical command was submitted exactly once:

```sh
task device:sleep-rtc QUALIFICATION=.local/neo128-debug-history.json \
  REHEARSAL=b5fb1d15febe4f8c9a888f74662dd2b1 ATTENDED=1
```

The original result is
`20261007T031630.769742Z/result.json`, run
`41462052473d43a0b91b481c9815a630`, SHA-256
`29feef331628c442cb7fc821c8465f76cad0ab9b3e3631b92aac6f389ac6b063`.
The controller verifies functional RTC wake, restored policy and independent
USB/Wi-Fi SSH recovery on the original boot.

| Check | Observation |
| --- | --- |
| Actual sleep | One s2idle boundary; `freeze`, `pm_test=none` |
| Submitted interval | 31.063 seconds BOOTTIME |
| In-loop s2idle trace | 28.438 seconds MONOTONIC |
| Alarm interval | 31.711 seconds from arming to userspace return; entry margin 29 seconds |
| Wake source | IRQ31, count 2 → 3; one RTC event with flags `0xa0` |
| PM counters | Success 7 → 8; fail and all stage-failure counters zero |
| USB / Wi-Fi | Independent SSH recovery to the original boot |
| Wi-Fi SDIO | Usage 2, active/forbidden with control `on`, unchanged |
| Keypad | Original handle connected; no hangup, poll/ioctl error or held key |
| Trace integrity | Keypad, Wi-Fi and USB complete, no recorded loss, settings restored |
| Wake policy | MUSB, USB supply and AC supply remain disabled |
| Cleanup | Original alarm/power policy restored; no retained policy, drop-in, control, RTC or console owner |
| Console | Brightness 1, backlight power 0 |

The warning was one level-5, 1,000 ms `screen-blank` cue, with successful
playback and mixer restoration before entry; both amplifiers were off. The
owner confirmed “Yes—warning clear; dim console returned untouched.” No
gadget restart, network repair or cable action was used to obtain recovery.

The collector retained three transient errors: a channel connection failure,
a channel-opening timeout and `No existing session` (with the SSH banner
traceback in the controller log). These delayed result collection, which
ultimately recovered the same original and independently verified both routes.
They do not establish a driver/host cause or measure device wake latency.
The test was not resubmitted.

## Post-resume checks and continuation

`task device:pm-inspect` capture `20261007T031835.364247Z/inspection.json`
passes the existing image/health validator and the saved continuation validator
against all seven debug originals plus this actual sleep. PM remains 8/0 and
SDIO usage 2; normal dim console settings and disabled wake controls remain.

The saved read-only `task device:charge-inspect` capture
`20261007T031843.369920Z/inventory.json` still admits schema 3's
`axp223-volatile-b8` profile. B8 returns fresh `c0` after PM, with calibration
disabled/not in progress. REG33/34, B8, E0/E1 and E6 match the initial
diagnostic.21 inventory, as do reported 4.2 V/1.2 A charger and 900 mA input
limits. Nonvolatile controls retain their possible-cache limitation.

This later awake sample reports 100%, Charging, 2 mA and 4.158 V (`ec/04`).
It does not resolve the earlier 4.2559 V discrepancy, prove calibrated voltage
or demonstrate charging during sleep. No charger/gauge programming or forced
calibration occurred. Final saved status checks pass on both routes:
`20261007T031930.559700Z` (USB), `20261007T031931.714732Z` (Wi-Fi).

The original first-sleep baseline is consumed. The saved continuation is
`20261007T031630.769742Z/qualification-next.json`; use its admitted history for
later connected-USB cycles, not the already-consumed baseline/rehearsal.
Other cable profiles need their own qualifying sequence.

The saved offline assessment also passes:

```sh
task report:sleep-evidence RESULT=.local/diagnostics/20261007T031630.769742Z/result.json
```

| Evidence | SHA-256 |
| --- | --- |
| Continuation | `2c8fb67805783b0ceca619de1f09ccf3abff7d44d39a6c551b98b0bcddfd4ddf` |
| Final PM inspection | `a0b3abe635e41cb21f6f590b294e991a11f09c7c24ffb20d780ca7d0117a9882` |
| Post-PM gauge inventory | `8a969868ea76f90f88913a35f07a569ef5bc6f5a22a92fc07a0624094608601c` |
| `20261007T031835.389756Z/sleep-evidence.json` | `3ec931a67c7dc77259ebade090c5dd9c03601c49e1da9f83cd5f7c51a2a6b37a` |

There are no observed timekeeping-freeze pairs, and the BOOTTIME/MONOTONIC gap
is below sampling uncertainty. This qualifies functional s2idle/RTC wake for
this one connected-USB attempt, not CPU retention, standby energy, product
resume latency or repeatability. Normal button/automatic sleep remains
disabled. NEO-10/NEO-117 retain the measurement and direct sleep-charge gaps.
The GameShell is awake, USB remains connected and no test is running.
