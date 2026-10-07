# Diagnostic.21 suspend/resume qualification

7 October 2026; capture timestamps are UTC. NEO-128, in progress.

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

The owner has been asked for separate readiness for one actual connected-USB
RTC sleep/wake test. No actual sleep has run in this slice yet.
