# Diagnostic.20: USB attachment during sleep

5 October 2026; capture timestamps are UTC. NEO-117 and NEO-110.

One attended USB-attachment-during-sleep case passes on diagnostic.20. The owner
connected USB after ten seconds of darkness and confirmed that the screen
stayed dark after insertion, then returned normally later. The recorded wake
was RTC IRQ31, with USB/Wi-Fi recovery and the original keypad connection
intact. The device reported Charging after resume. No further sleep test is
running; USB remains connected.

This corrects the observed early-wake behavior of diagnostic.19 for this one
case. The original failure in [report 165](165-diagnostic19-usb-attachment-early-wake.md)
remains failed. Repetition, removal under the new policy and charge acceptance
during the sleep interval remain open; NEO-117 is still in progress.

## Admission and original result

[Report 170](170-diagnostic20-usb-attachment-preparation.md) records the fresh
seven-stage debug baseline, owner-confirmed warnings/display, verified physical
unplug and passing awake attachment rehearsal. The connected-USB sleep in
[report 169](169-diagnostic20-first-rtc-wake.md) used a different baseline.

The owner gave fresh readiness for one actual attempt: hear the long warning,
count ten seconds after darkness, connect USB once and leave it connected,
keeping the Mac awake and all buttons untouched. If the screen returned before
attachment, the instruction was to leave the cable unplugged. The saved command
was submitted once, with no automatic retry:

```sh
task device:sleep-cable-attach \
  QUALIFICATION=.local/neo117-attach-debug-history.json \
  REHEARSAL=c548a689188f4c1983b57d4febbf80a9 \
  CABLE_ACTION=1 UNPLUGGED=1 ATTENDED=1
```

| Identity | Value |
| --- | --- |
| Host source checkpoint | `d58fa84`, `work/power-insertion-wake` |
| Image / kernel | `0.1.0-diagnostic.20` / `6.18.54-gameshellneo19` |
| Boot | `86a43151-7d9b-44bd-83b3-cc1b9fcff215` |
| Run | `8e77967471fa46f2b233373110dd12d5` |
| Original capture beneath this worktree | `.local/diagnostics/20261005T055302.118712Z/result.json` |
| Original result SHA-256 | `13c123565c355725f174c1d8af3ff7386ba481597b205293d3288d8792996ee2` |

The controller validated the original source/boot/image/RTC history before
submission and consumed this independent baseline. Neither this baseline nor
the prior connected-USB baseline may be replayed.

## Automated outcome

| Check | Observation |
| --- | --- |
| Actual sleep | One s2idle boundary, `pm_test=none`; four ordered late/noirq phases and RSB callbacks |
| Submitted interval | 30.927 seconds BOOTTIME |
| In-loop s2idle trace | 28.378 seconds MONOTONIC |
| Alarm interval | 31.629 seconds from arming to userspace return |
| Wake source | IRQ31; RTC count 4 → 5; one event with flags `0xa0` |
| Starting/entry cable state | UDC not attached, carrier 0, PHY USB/HOST 0, both supplies absent/offline |
| Ending cable state | UDC configured, carrier 1, PHY USB 1/HOST 0, both supplies present/online |
| Wake policy | MUSB and both supply wake controls remain disabled before/after |
| PM counters | Success 15 → 16, fail and every failure counter zero |
| USB / Wi-Fi | Both independent SSH proofs reach the original boot |
| Keypad / memory | Original input handle retained without disconnect, errors or held keys; memory check passes |
| SDIO runtime policy | Active/forbidden, control `on`, usage 2 unchanged |
| Trace integrity | Keypad/Wi-Fi/USB traces complete and restored |
| POWER / cleanup | No POWER activity; checked handback and original policy restored; no retained diagnostic owners |
| Warning / display | One level-5, 1,000 ms cue before entry; mixer/amplifiers restored; console restored |

The original result was collected over Wi-Fi before the independent USB proof.
No gadget restart, network repair, reconnect request or PM retry was used.
Two `SSHException: Timeout opening channel.` collection errors remain preserved;
the collector recovered this exact original run and verified both routes. Their
cause remains unassigned under the existing transport-timing follow-up.

Both ACIN/VBUS plugin handler counts remain 0; both removal counts remain 1.
This passes the prospective `masked-cable-v2` criteria selected by the image:
the requested insertion dispatch may be zero or one while masked, and opposite
events must stay unchanged. The trace's RTC event/wake IRQ and the correctly
reconciled endpoints are still required. Zero insertion callbacks do not mean
the cable was never connected; masked status can be acknowledged by regmap
before its nested handler runs. No exact electrical-edge timestamp is claimed.

## Separate owner observation

The owner answered **"Yes—stayed dark after USB; then console returned"** to
the explicit question about hearing the warning, connecting once after ten
seconds of darkness and seeing the normal dim console return later. This was
recorded separately without modifying the device's original result:

```sh
task report:sleep-cable \
  RESULT=.local/diagnostics/20261005T055302.118712Z/result.json \
  OBSERVATION=during-dark DISPLAY=normal
```

`result-cable-observation.json` reports `attended_case_passed=true`; SHA-256
`8305f39afdf60138670f0c354d4e67d7de374b133740221339b23a3d855e14a6`.
The observer evidence and the software trace agree on staying dark through
insertion and later RTC recovery. Darkness and handler counters still do not
timestamp the physical electrical edge precisely inside s2idle.

## Postflight and practical limits

Fresh `task device:pm-inspect` capture
`20261005T055548.123219Z/inspection.json` passes health validation at PM16/0;
SHA-256 `c022e745d4ff7bfa9851b076b6ede3078d7b0f9f459661804365c70234ff0c21`.
The separate saved `report:sleep-evidence` assessment passes RTC/trace/clock
checks at `20261005T055548.132655Z/sleep-evidence.json`, SHA-256
`d4054ad568f84c5a9873b317378af8996d6e6d62726441291cea3a606f40071e`.
That assessment never rewrites or requalifies the original result.

Battery monitoring reports 92%/Discharging before sleep and 94%/Charging after
resume, followed by 96%/Charging at postflight. These rapid gauge changes are
not a measured charge gain. The postflight 4.2559 V repeats the existing
uncalibrated charging-voltage finding under NEO-10; charging settings were not
changed. Charging status after resume does not establish current flow during
the sleep interval.

The clock gap remains below sampling uncertainty and no timekeeping-freeze
pairs were observed. This establishes one functional stay-asleep-on-attachment
and RTC recovery case, not deep CPU retention, standby energy, broad reliability
or production wake latency. Ordinary automatic/button sleep remains disabled.
Next qualification should cover USB removal with these supply wake policies,
repeat cable cases and separate evidence for charging through sleep. Original
results and consumed baselines must remain intact.
