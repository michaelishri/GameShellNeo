# Diagnostic.13 attended qualification (NEO-76)

2 October 2026. The owner returned for the guided PM, input and USB session
prepared in [report 91](91-diagnostic13-preparation.md), following the passing
[unattended workflow](95-awake-qualification-workflow.md).

The attended sequence passed: one freezer check, six driver debug cycles
including the physical input test, and four USB reconnects. The owner confirmed
normal screen return, button input and speaker cues. Final checks verified both
SSH routes, restored settings and no remaining diagnostic services or recovery
records. Actual low-power sleep remains unqualified and disabled.

## Initial preflight and retained evidence

The first two connection attempts stopped locally with `Operation not
permitted` under a restricted host network profile. No device test was
submitted. After the owner restored access, USB and independent Wi-Fi SSH
reached diagnostic.13 on boot `eafb7717-0cbc-46e8-9cc4-7666ab7ec086`.

The saved current-boot check correctly refused this baseline because its
kernel journal lacked the expected firmware identification. This did **not**
demonstrate a firmware crash: live `dmesg` retained the correct single
BCM43430/0 identification and no tracked radio faults. Kernel taint, failed
units and PM counters were zero; the battery monitor reported valid 100%
with external supplies online. The journal contained kernel entries only
from about 81 seconds onward, when journald had restarted and relinquished
its persistent storage. The journald configuration matched the repository
and Armbian ramlog remained masked. The owner reported no maintenance, with
USB disconnected most of the day and reconnected about three hours earlier.
The cause of journal loss remains open in `FOLLOW-UP.md`.

Evidence was saved before requesting a clean power cycle:

- `.local/diagnostics/20261002T083159.467690Z/`: refused boot preflight.
- `.local/diagnostics/20261002T083249.051588Z/`: read-only PM baseline.
- `.local/diagnostics/20261002T083344.736461Z/`: diagnostic archive.
- `.local/neo76-dmesg.log` and `.local/neo76-journal-*.log`: live ring buffer,
  journal configuration, service state, boot list and storage metadata.

An inspection attempted during the physical power cycle encountered an SSH
banner failure; it submitted no PM test. The owner then confirmed the normal
login screen had returned.

## Fresh baseline

The fresh boot is `fd480513-371b-4f00-8a69-db14bd7727d4`, running image
`0.1.0-diagnostic.13`, kernel `6.18.54-gameshellneo13`. The saved current-boot
check passed, including both SSH routes and the expected single firmware
identity. Read-only PM validation passed at about 78 seconds and again at
182 seconds; the complete earlier kernel journal remained intact beyond the
previous boot's restart point. All six integration groups passed, and keypad
and idle-audio baselines were saved. Configured NZ and accepted active AU
country policy were unchanged.

Private baseline captures under `.local/diagnostics/`:

| Check | Capture |
| --- | --- |
| Boot/routes | `20261002T084041.753110Z/` |
| Initial PM | `20261002T084041.771796Z/` |
| Settled PM | `20261002T084227.306708Z/` |
| Keypad | `20261002T084151.032579Z/` |
| Audio | `20261002T084151.045852Z/` |
| Integration | `20261002T084152.831080Z/` |

## Guided sequence

The saved tasks are run sequentially, checking each result before continuing:

```sh
task device:pm-test STAGE=freezer CYCLES=1
task device:pm-test STAGE=devices CYCLES=1 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:pm-test STAGE=devices CYCLES=4 KEYPAD_TRACE=1 WIFI_TRACE=1
task device:keypad-input AUDIO=1
task device:usb-reconnects CYCLES=4
```

The freezer check passed with both SSH routes verified; its capture is
`.local/diagnostics/20261002T084321.355471Z/`, run
`1e9b8366b485489f94c298e16ffc9601`. The owner then confirmed readiness to watch
the single driver cycle and four repeats, with USB connected and controls
untouched. This is one explicitly described observed batch; button and cable
instructions follow separately after recorder preparation.

The initial traced driver cycle passed in capture
`.local/diagnostics/20261002T084447.379018Z/`, run
`ddef003a79e24836a5b1e43f472b4a93`. Both SSH routes recovered; the original input
handle, USB device number and input sysfs path survived, with no keypad supply
disable or disconnect. Wi-Fi tracing was complete and restored, with two
EAPOL transmit and two receive events. The recorded stage interval was
7.552 seconds, including the deliberate five-second debug wait; the separate
post-stage keypad readiness check took 0.209 seconds.

All four repeats passed in
`.local/diagnostics/20261002T084640.118494Z/`. Each retained the original keypad
handle/device/path with zero disconnects or supply-disable events, recovered
both network routes, and recorded complete/restored Wi-Fi tracing with two
EAPOL transmit and two receive events. PM success rose from two to six, with
all failure counters unchanged at zero.

| Repeat | Run ID | Stage interval (s) | Post-stage keypad readiness check (s) |
| --- | --- | --- | --- |
| 1 | `d7749e3bd0f2454b8f8fd69bf952ded4` | 7.720 | 0.225 |
| 2 | `11bf59170fd14142a7a94b6634963d19` | 7.576 | 0.238 |
| 3 | `369dbb228ef24768b3880c7b8af28cc6` | 7.666 | 0.226 |
| 4 | `10bdc4c0ced644c7bc24e55d51a1aaca` | 7.722 | 0.227 |

One intermediate USB collection attempt during repeat two reported
`No route to host`; collection continued for the same already-submitted run,
and both routes subsequently verified. No PM stage was resubmitted. These
intervals include diagnostic overhead and are not real sleep/wake latency.
Retention summaries sit beside each `result.json`; the condensed four-cycle
summary is `.local/neo76-four-summary.json`.

The owner confirmed that the dim console returned normally after all five
observed driver cycles, and then confirmed readiness for the on-screen button
test.

The physical test passed in
`.local/diagnostics/20261002T085323.939272Z/`, run
`86ea2ffd2425448a99e9226699af022c`. Requested A/B/X/Y taps before and after the
debug interval passed on the original input handle. The held-A observation
again used the **cleared** resume mode: Linux cleared the key during the
suspend path; the recorder did not claim a continuously asserted logical key
or an observed physical-release event. Keypad device/path/handle identity
survived, with no supply-disable or disconnect events. Console ownership and
the input grab were released afterward.

All nine confirmation cues completed, both amplifiers were idle before PM,
and the original mixer controls were restored. The owner confirmed correct
buttons, tones and final dim console. PM success reached seven with zero
failures; both SSH routes verified.

## USB reconnects

The recorder was armed and its ready event verified before asking the owner
to perform four cycles of unplugging for three seconds and reconnecting for
30 seconds, leaving USB connected at the end. The owner confirmed completion.
All four cycles passed on the same boot, with USB SSH verified after each
reconnection. The recorder stopped and cleaned up without a pending recovery
record.

Evidence is `.local/diagnostics/20261002T085657.582019Z/` and
`.local/neo76-usb.log`; the run lasted 08:56:57–09:00:04 UTC. Its saved summary
reports four requested and four verified cycles. This uses the standard 250 ms
sampler and manually timed cable actions; it does not measure electrical-edge
latency or qualify exact physical timing.

## Final state and restoration

The following saved tasks completed after the physical sequence:

```sh
task device:boot-cycles CYCLES=0
task device:pm-inspect
task device:keypad-inspect
task device:audio-inspect
task device:check ROUTE=usb ACTIVE_COUNTRY=AU
```

The read-only `qualify-awake.py --guard` check also confirmed the same boot,
no active diagnostic service and no recovery record. It did not rerun the
awake qualification suite.

- The boot remained `fd480513-371b-4f00-8a69-db14bd7727d4`, with the expected
  firmware identity and both SSH routes passing. All six integration groups
  passed; kernel taint was zero and there were no failed services.
- PM success reached seven; every failure counter remained zero. `pm_test`
  returned to `none`, asynchronous PM remained enabled and normal sleep
  remained masked.
- CPU, charging, backlight, USB experimental flags, Wi-Fi configuration and
  power-save policy matched the settled baseline. Firmware/NVRAM hashes,
  SDIO power retention and keypad supply retention were unchanged.
- The original keypad USB identity, input paths, regulator state and port
  quirks matched the baseline. Audio controls were restored, both PCMs were
  closed and both amplifiers were off.
- The final battery monitor reported valid 100%, charging, with both external
  supplies present/online. Its 4.1932 V software reading does not establish
  calibrated physical cell voltage or resolve NEO-10.
- The earlier kernel journal remained intact through the final PM inspection
  at about 21.5 minutes uptime. The previous boot's journal loss did not recur
  during this session, but its cause is still unresolved.

Private final captures under `.local/diagnostics/`:

| Check | Capture |
| --- | --- |
| Boot/routes | `20261002T090102.441761Z/` |
| PM | `20261002T090102.356948Z/` |
| Keypad | `20261002T090102.357255Z/` |
| Audio | `20261002T090102.436659Z/` |
| Integration | `20261002T090139.769362Z/` |
| Idle/recovery guard | `neo76-final-guard/20261002T090234.421467Z/` |

`.local/neo76-final-summary.json` records the comparisons with the settled
baseline. No further physical test is running; USB remains connected.

## Limits

These are bounded freezer/devices PM debug stages with the deliberate
five-second debug wait, not actual low-power sleep or wake-latency measurements.
Normal sleep remains masked. Tracing and diagnostic sampling add overhead.
This pass does not establish physical voltage, battery endurance,
energy savings, fault-injection recovery, NEO-55's original cause or the cause
of the earlier journal loss. The speaker-confirmation delay remains deferred
at the owner's request.
