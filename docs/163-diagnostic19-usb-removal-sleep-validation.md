# Diagnostic.19: USB removal during sleep

5 October 2026, Pacific/Auckland; capture timestamps are UTC. NEO-112 / NEO-110.

Diagnostic.19 passed the attended USB-removal RTC sleep case. The owner unplugged
once during darkness as instructed and confirmed normal dim-console return.
The original result, collected over Wi-Fi before reconnection, reports absent
AC/USB power, absent PHY cable, a not-attached gadget and carrier 0. A separate
read-only inspection confirmed that state persisted.

This directly addresses the stale configured/carrier-1 state from diagnostic.18
in [report 153](153-usb-removal-sleep-state-failure.md). That original remains
failed and unchanged. This is one qualified removal case; attachment during
sleep, wider repetition and energy still need separate evidence.

## Admission and execution

[Report 162](162-diagnostic19-long-cue-debug-qualification.md) records seven
fresh debug cycles, owner-confirmed long warnings and normal display returns,
plus the current-source awake removal rehearsal. The old consumed sleep chain
was not reused after changing the audio helper.

After fresh readiness for exactly one removal during darkness, the task was
submitted once:

```sh
task device:sleep-cable-remove \
  QUALIFICATION=.local/neo112-long-cue-debug-history.json \
  REHEARSAL=0758d0c21a3143e8a6e540123e798da4 \
  CABLE_ACTION=1 ATTENDED=1
```

| Identity | Value |
| --- | --- |
| Source commit at submission | `adae92f` (helpers unchanged from `749ef9d`) |
| Image / kernel | `0.1.0-diagnostic.19` / `6.18.54-gameshellneo19` |
| Boot | `2fa86697-ead3-4e6f-a295-44e6ad203983` |
| Run | `bf84895bff984025b9bb44221b8eecc0` |
| Capture | `.local/diagnostics/20261004T232512.831679Z/` |
| Original `result.json` SHA-256 | `3c94831415986734e918d0138246a4b6b646011f214c7ede0923b3964fd35275` |

The owner was instructed to wait ten seconds after darkness, unplug once from
the GameShell and leave it disconnected. If the display returned before the
action, the cable was to remain untouched. After collection the owner answered
**“Unplugged during darkness; normal dim console returned.”** The separate
observer report is bound to the original result:

```sh
task report:sleep-cable \
  RESULT=.local/diagnostics/20261004T232512.831679Z/result.json \
  OBSERVATION=during-dark DISPLAY=normal
```

`result-cable-observation.json` reports `attended_case_passed=true`; SHA-256
`82558c3e653fe06f8f19e5b7b91e5ec18ebb6712d69be8ba48f93a7d8c573f2a`.
Human darkness observation does not precisely timestamp electrical contact
separation inside the kernel's s2idle interval.

## Original result

| Check | Observation |
| --- | --- |
| RTC | One event, flags `0xa0`; IRQ 31 count 5 → 6; recorded wake IRQ 31 |
| Alarm interval | 32.444 seconds including entry/return overhead |
| Submitted state interval | 31.737 seconds BOOTTIME |
| Traced s2idle interval | 29.139 seconds MONOTONIC |
| PM counters | Success 15 → 16; all failure counters zero |
| External power afterward | AC and USB both `present=0`, `online=0` |
| PHY afterward | `USB=0`, `USB-HOST=0` |
| Gadget afterward | `not attached`, carrier `0` |
| Network proof | Independent Wi-Fi SSH to the same boot; USB proof intentionally false for the absent profile |
| Input/memory | Original keypad handle retained, no held keys or input errors; process-memory check passed |
| SDIO | Usage 2, active/forbidden, control `on` |
| Battery telemetry | Valid/discharging, 100%, 4.0436 V at the recorded final sample |
| Final health | Kernel taint 0, no failed services |
| Restoration | Original policy, RTC, PM controls, console and audio restored; no retained ownership or drop-in |
| Trace integrity | Complete keypad/Wi-Fi/USB traces, no recorded loss, settings restored |

The warning was a level-5 one-second tone, with idle audio restored before RTC
arming. No gadget service restart, forced carrier write, driver reload, reboot,
charging change or recovery reconnect was used to obtain this result.

The collector retained one SSH channel timeout and two connection failures while
the cable was absent. It recovered the exact original result over Wi-Fi, with
no resubmission. The log records these transport failures separately from the
passing device recovery result; they do not establish a driver or radio cause.

## Evidence for logical session retirement

The USB trace places three endpoint-disable events (`ep1in`, `ep1out`, `ep2in`)
inside the MUSB bus suspend callback beginning at monotonic 10817.470147.
At 10817.470434, the gadget state event records speed 0/state 0; the callback
finishes at 10817.470527. The s2idle boundary begins later, at 10817.500955.
The controller resumes at 10846.717667–10846.717753. Final independent state
reads confirm `not attached`/carrier 0 with no host cable present.

These events support the intended retirement before sleep described in
[report 154](154-usb-sleep-session-retirement.md). Endpoint trace return text is
not used as an independent success oracle. The ECM journal has one deferred
`ecm deactivated` message at 10848.276253, after resume; that deferred log time
must not be mistaken for the disconnect callback's execution time.

| After removal and RTC wake | Diagnostic.18 original | Diagnostic.19 comparison |
| --- | --- | --- |
| External power / PHY | Absent | Absent |
| Gadget state / carrier | Configured / 1, stale | Not attached / 0, correct |
| Owner-observed display | Normal | Normal |
| Overall case | Failed | Passed |

All four AC/VBUS handler counters stayed unchanged. Diagnostic.19's prospective,
image-bound `masked-removal-v1` policy permits zero or one removal dispatch per
handler; no insertion, regression or extra dispatch is accepted. The source
explanation in report 154 is that removal is masked during suspend and may be
acknowledged before dispatch. No interrupt was invented, and all physical
endpoint checks remained mandatory. This observation does not prove that cable
removal caused wake; the RTC event and wake IRQ agree instead.

## Preserved disconnected state and limits

Before requesting reconnection, the saved read-only task ran over Wi-Fi:

```sh
task device:sleep-connection-inspect ROUTE=wifi
```

Capture `20261004T232757.220607Z/connection-inspection.json` passes the strict
absent-state validator on the same boot: absent AC/USB, PHY absent,
not-attached UDC and carrier 0, with unchanged cable-handler counts. SHA-256:
`9eced01dd40f4925a7c95d54e9df387c2af4f97f78ad17871d7034933c5ecf1d`.

The offline `report:sleep-evidence` assessment also passed RTC/trace/clock
checks, preserving the original. Its capture is `20261004T232829.593414Z`,
`sleep-evidence.json` SHA-256
`608b1bc5000e8ff99a1df4e23516fbc525271ced81d05f0f06e79d3a5e3ed0ad`.

CPU-idle driver remains `none` with no states; no timekeeping-freeze pair was
observed. The BOOTTIME/MONOTONIC gap is below sampling uncertainty. Neither this
pass nor its duration establishes CPU/DRAM retention, battery savings, precise
physical edge timing or sub-second whole-device wake latency. Normal sleep
policy remains disabled.

## Separate awake reconnection

Reconnection was requested only after the original and disconnected-state
evidence were saved. The owner confirmed one reconnect, a 30-second wait and
normal console. Two read-only tasks then passed on the original boot:

| Route / evidence | Capture | SHA-256 |
| --- | --- | --- |
| USB PM/health inspection | `20261004T233126.306953Z/inspection.json` | `1a9668818cfd44bb46201ff97865ce2e6dcfbef725fcb27dca8b5eacda6b8302` |
| Independent Wi-Fi connection inspection | `20261004T233126.307866Z/connection-inspection.json` | `635f963255116aa5c544db241e09ed889548b3ffa1c670b25d0c61dbfc2d4b0a` |

The strict present-state and PM health validators pass: UDC configured,
carrier 1, PHY present, both AC/USB present and online, healthy services, taint 0,
SDIO usage 2 and PM 16/0 unchanged. Relative to the saved absent-state snapshot,
AC and VBUS each gain exactly one insertion dispatch and no removal dispatch.
Battery telemetry is 98%, charging. The original sleep result hash is unchanged.

The bounded comparison and requested reconnection complete NEO-112's immediate
stale-session correction. NEO-110 retains attachment-during-sleep and broader
cable coverage; the removed-cable case does not qualify those conditions or
Mac-host sleep. No further sleep test is running. Leave USB connected for the
next separately prepared case.
